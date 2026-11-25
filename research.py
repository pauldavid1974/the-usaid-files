"""Build and query the local USAID Files research index."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from acquire import ROOT, digest, write_json
from catalog import catalog, mirror_records

DB = ROOT / "index/usaid.sqlite"
TIMESTAMP = re.compile(r"(?m)^\[(\d+:\d{2}:\d{2})\]\s*(.+)$")
HEADERS = re.compile(r"(?im)^\s*(From|To|Cc|Bcc|Date|Sent|Subject|Attachments?):\s*([^\n]+)")
FINANCE = 'funding OR expenditure OR disbursement OR grant OR budget OR invoice OR contract OR payment'


def seconds(stamp):
    hours, minutes, secs = map(int, stamp.split(":"))
    return hours * 3600 + minutes * 60 + secs


def segment(locator, body, method, **metadata):
    return {"locator": locator, "body": body, "method": method, **metadata}


def mirror_segments(body, filetype):
    if filetype == "mp4":
        return [segment(f"time {match[1]}", match[2], "mirror supplied caption",
                        start=seconds(match[1])) for match in TIMESTAMP.finditer(body)]
    headings = list(re.finditer(r"(?m)^### (.+)$", body))
    items = []
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        content = body[heading.end():end].strip()
        method = "mirror extraction"
        if content.startswith("*OCR"):
            method = "mirror OCR"
        items.append(segment(heading[1], content, method))
    return items


def physical_segments(path, row, allow_ocr):
    if row["format"] == "xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, keep_links=False, data_only=False)
        cached = load_workbook(path, read_only=True, keep_links=False, data_only=True)
        output = []
        try:
            for sheet in workbook.worksheets:
                for number, (cells, values) in enumerate(zip(sheet.iter_rows(), cached[sheet.title].iter_rows()), 1):
                    entries = {}
                    for cell, cached_cell in zip(cells, values):
                        if cell.value is None:
                            continue
                        entry = {"value": cell_value(cell.value), "format": cell.number_format}
                        if cell.data_type == "f":
                            entry["cached_value"] = cell_value(cached_cell.value)
                        entries[cell.coordinate] = entry
                    if entries:
                        text = " | ".join(f"{coordinate} {entry['value']}" for coordinate, entry in entries.items())
                        output.append(segment(f"{sheet.title} row {number}", text, "spreadsheet cells", cells=entries))
            return output
        finally:
            workbook.close()
            cached.close()
    if row["format"] != "pdf":
        return []
    import pymupdf
    with pymupdf.open(path) as pdf:
        output = []
        for index, page in enumerate(pdf, 1):
            native = page.get_text(sort=True).strip()
            word_count = len(re.findall(r"\b[A-Za-z]{3,}\b", native))
            image_area = sum((pymupdf.Rect(image["bbox"]) & page.rect).get_area() for image in page.get_image_info())
            needs_ocr = (word_count < 12 and image_area > page.rect.get_area() * .15
                         or "\ufffd" in native or bool(re.search(r"\w[\[\\\]\^]\w", native))
                         or (row["id"] == "publication-004" and index == 1))
            method, text = "PDF text layer", native
            extra = {}
            if needs_ocr:
                if allow_ocr:
                    try:
                        extracted = ocr_page(page)
                        extra["native_text"] = native
                        if extracted:
                            method, text = "local OCR, review against page", extracted
                        else:
                            method = "OCR returned no text, review page"
                    except (ImportError, OSError, RuntimeError, ValueError) as error:
                        method = "OCR failed, review page"
                        extra["ocr_error"] = str(error)
                else:
                    method = "OCR candidate, review page"
            if row["kind"] == "Email":
                headers = list(HEADERS.finditer(text))
                extra["visible_email_headers"] = [{"field": m[1], "value": m[2]} for m in headers]
            output.append(segment(f"Page {index}", text, method, **extra))
        return output


def cell_value(value):
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return {"seconds": value.total_seconds()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__iter__"):
        return dict(value)
    return str(value)


def ocr_page(page):
    if not hasattr(ocr_page, "engine"):
        from rapidocr import RapidOCR
        ocr_page.engine = RapidOCR(params={
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.intra_op_num_threads": 3,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": True,
        })
    pix = page.get_pixmap(dpi=170, alpha=False)
    result = ocr_page.engine(pix.tobytes("png"))
    return "\n".join(result.txts or [])


def comparison(local, mirror, filetype):
    from rapidfuzz.fuzz import ratio, token_sort_ratio
    if filetype == "xlsx":
        cells = {(row["locator"].rsplit(" row ", 1)[0], coordinate): entry["value"]
                 for row in local for coordinate, entry in row["cells"].items()}
        compared = set()
        flags = []
        for section in mirror:
            sheet = re.sub(r", rows \d+ to \d+$", "", section["locator"])
            for match in re.finditer(r"(?:^| \| )([A-Z]+\d+) (.+?)(?= \| [A-Z]+\d+ |$)",
                                     section["body"], flags=re.M):
                coordinate, published = match.groups()
                key = (sheet, coordinate)
                compared.add(key)
                value = cells.get(key)
                if value is None:
                    flags.append({"locator": f"{sheet}!{coordinate}", "reason": "mirror cell missing from local rows"})
                elif not equal_cell(value, published):
                    flags.append({"locator": f"{sheet}!{coordinate}", "reason": "cell text differs"})
        for sheet, coordinate in sorted(cells.keys() - compared):
            flags.append({"locator": f"{sheet}!{coordinate}", "reason": "cell missing from mirror export"})
        return flags
    if filetype == "mp4":
        differences = []
        for index, item in enumerate(local):
            start, end = item["start"], item["end"]
            aligned = " ".join(cue["body"] for cue in mirror if start <= cue["start"] < end)
            if aligned:
                score = round(ratio(normalize(item["body"]), normalize(aligned)), 1)
                if score < 70:
                    differences.append({"locator": item["locator"], "score": score})
        return differences
    if filetype != "pdf":
        return []
    pixels = {item["locator"]: item for item in mirror}
    differences = []
    for page in local:
        peer = pixels.get(page["locator"])
        if peer is None:
            differences.append({"locator": page["locator"], "reason": "mirror page not found"})
            continue
        left = normalize(page["body"])
        right = normalize(re.sub(r"(?m)^\*OCR text[^\n]*\n", "", peer["body"]))
        score = round(token_sort_ratio(left, right), 1)
        if score < 70:
            differences.append({"locator": page["locator"], "score": score})
    return differences


def equal_cell(value, other):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return Decimal(str(value)) == Decimal(other)
        except InvalidOperation:
            return False
    return normalize(str(value)) == normalize(other)


def normalize(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


def read_manifest(name):
    path = ROOT / "manifests" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def attachments(path, source):
    import pymupdf
    output = []
    with pymupdf.open(path) as pdf:
        objects = [(None, pdf.embfile_info(name), pdf.embfile_get(name)) for name in pdf.embfile_names()]
        for page in pdf:
            for annotation in page.annots(types=(pymupdf.PDF_ANNOT_FILE_ATTACHMENT,)):
                objects.append((page.number + 1, annotation.file_info, annotation.get_file()))
        for page, metadata, body in objects:
            checksum = hashlib.sha256(body).hexdigest()
            folder = "mirrors" if source == "mirror" else "originals"
            target = ROOT / folder / "attachments" / (checksum + ".bin")
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                with target.open("xb") as output_file:
                    output_file.write(body)
            output.append({"page": page, "metadata": metadata,
                           "relative_path": target.relative_to(ROOT).as_posix(), "sha256": checksum, "bytes": len(body)})
        return pdf.metadata, output


def document_date(row, physical):
    if row["format"] == "pdf" and physical:
        first_page = physical[0]["body"]
        match = re.search(r"(?im)^\s*Date:\s*([A-Za-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})\b", first_page)
        if match:
            for pattern in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
                try:
                    value = datetime.strptime(match[1], pattern).date()
                    return value.isoformat(), f"PDF page 1 Date field ({physical[0]['method']})"
                except ValueError:
                    continue
    return row["mirror_date"], row["mirror_date_claim"]


def additions():
    for row in read_manifest("additions.json"):
        filename = row["filename"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*\.(?:pdf|xlsx|mp4)", filename, re.I):
            raise ValueError(f"unsupported additional filename: {filename!r}")
        if not re.fullmatch(r"additional-[a-z0-9-]+", row["id"]):
            raise ValueError("addition IDs must start with additional-")
        if not row["url"].startswith(("https://", "http://")):
            raise ValueError("provide a source URL for each addition")
        path = ROOT / "originals/additions" / filename
        record = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
        yield {**row, "format": path.suffix[1:].lower(), "mirror_title": row["title"],
               "mirror_url": None, "mirror_kind": row["kind"], "mirror_date": row.get("date"),
               "mirror_date_claim": "addition manifest", "mirror_entity_hints": ""}, record


def build(allow_ocr, reuse):
    added = list(additions())
    catalog_rows = catalog() + [record for record, _ in added]
    mirrors = {m[2]["Original filename"]: m for m in mirror_records()}
    reviewed_pages = read_manifest("page-review.json") or {}
    files = {}
    for name, source in (("mirror-files.json", "mirror"), ("official-files.json", "official")):
        for item in read_manifest(name):
            if "sha256" in item:
                files[Path(item["path"]).name] = (item, source)
    for record, item in added:
        if record["filename"] in files:
            raise ValueError("additional filename duplicates an existing file")
        files[record["filename"]] = (item, "additional")
    temporary = DB.with_suffix(".building")
    inventory = []
    discrepancies = []
    with sqlite3.connect(temporary) as db:
        db.executescript("""
        DROP TABLE IF EXISTS docs;
        DROP TABLE IF EXISTS passages;
        CREATE TABLE docs (id TEXT PRIMARY KEY, filename TEXT, title TEXT, kind TEXT,
          format TEXT, date TEXT, date_claim TEXT, url TEXT, mirror_url TEXT,
          path TEXT, sha256 TEXT, byte_source TEXT, entity_hints TEXT);
        CREATE VIRTUAL TABLE passages USING fts5(
          doc_id UNINDEXED, locator UNINDEXED, source UNINDEXED, method UNINDEXED,
          title, body, hints, tokenize='unicode61');
        """)
        for row in catalog_rows:
            name, filetype = row["filename"], row["format"]
            raw = mirrors.get(name)
            peer = mirror_segments(raw[3], filetype) if raw else []
            item, byte_source = files.get(name, ({}, "missing"))
            path = ROOT / item["path"] if item else None
            local = []
            error = None
            if path:
                try:
                    if filetype == "mp4":
                        transcript = ROOT / "transcripts" / (path.stem + ".asr.json")
                        if transcript.exists():
                            data = json.loads(transcript.read_text(encoding="utf-8"))
                            if data["sha256"] != item["sha256"]:
                                raise ValueError("ASR input hash differs")
                            local = [segment(f"time {cue['start']:.3f}s", cue["text"], "local ASR, review against recording",
                                             start=cue["start"], end=cue["end"]) for cue in data["segments"]]
                    else:
                        output = ROOT / "text" / (path.stem + ".json")
                        cached = json.loads(output.read_text(encoding="utf-8")) if reuse and output.exists() else {}
                        if cached.get("sha256") == item["sha256"]:
                            local = cached["segments"]
                        else:
                            local = physical_segments(path, row, allow_ocr)
                        for entry in local:
                            if not entry["body"]:
                                entry.update(reviewed_pages.get(row["id"], {}).get(entry["locator"], {}))
                        metadata, embedded = attachments(path, byte_source) if filetype == "pdf" else (None, [])
                        write_json(output, {"id": row["id"], "input": item["path"], "sha256": item["sha256"],
                                            "segments": local, "file_metadata": metadata, "attachments": embedded})
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            if filetype == "mp4" and raw:
                write_json(ROOT / "transcripts" / (Path(name).stem + ".mirror.json"),
                           {"id": row["id"], "url": row["mirror_url"], "export_line": raw[4], "captions": peer})
            record_date, date_claim = document_date(row, local)
            db.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (row["id"], name, row["mirror_title"], row["kind"], filetype, record_date,
                        date_claim, row["url"], row["mirror_url"], item.get("path"),
                        item.get("sha256"), byte_source, row["mirror_entity_hints"]))
            def insert_passage(locator, source, method, body, hints=""):
                db.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?)",
                           (row["id"], locator, source, method, row["mirror_title"], body, hints))
            insert_passage("Catalog", "catalog", "official kind and mirror metadata", "", row["mirror_entity_hints"])
            for source, entries in ((byte_source, local), ("supplement", peer)):
                for entry in entries:
                    insert_passage(entry["locator"], source, entry["method"], entry["body"])
            flags = comparison(local, peer, filetype) if raw else []
            date_difference = record_date != row["mirror_date"] and bool(row["mirror_date"])
            if flags or row["kind"] != row["mirror_kind"] or date_difference:
                discrepancies.append({"id": row["id"], "filename": name, "catalog_kind": row["kind"],
                                      "mirror_kind": row["mirror_kind"], "text_review_flags": flags,
                                      "indexed_date": record_date, "mirror_date": row["mirror_date"]})
            inventory.append({"id": row["id"], "format": filetype, "byte_source": byte_source,
                              "local_methods": dict(Counter(entry["method"] for entry in local)),
                              "mirror_segments": len(peer), "error": error})
        assert db.execute("SELECT count(*) FROM docs").fetchone()[0] == len(catalog_rows)
        assert db.execute("SELECT count(*) FROM passages WHERE passages MATCH ?", ('"information integrity"',)).fetchone()[0] > 0
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.close()
    temporary.replace(DB)
    write_json(ROOT / "manifests/processing.json", inventory)
    write_json(ROOT / "manifests/discrepancies.json", discrepancies)
    print(json.dumps({"documents": len(inventory), "byte_sources": dict(Counter(row["byte_source"] for row in inventory)),
                      "extraction_errors": [row for row in inventory if row["error"]]}, indent=2))


def connect():
    db = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def emit(rows):
    for row in rows:
        print(json.dumps(dict(row)))


def search(db, args):
    expression = args.query or FINANCE
    if args.phrase:
        expression = '"' + expression.replace('"', '""') + '"'
    source = args.source
    if source == "evidence":
        filter_sql = "(p.source IN ('official','mirror','catalog','additional') OR (p.source='supplement' AND NOT EXISTS (SELECT 1 FROM passages x WHERE x.doc_id=d.id AND x.source IN ('official','mirror'))))"
    elif source == "all":
        filter_sql = "1=1"
    else:
        filter_sql = "p.source=?"
    params = [expression] + ([source] if source not in ("all", "evidence") else [])
    for sql, value in (("d.id != ?", args.exclude), ("d.kind = ? COLLATE NOCASE", args.kind), ("d.format = ? COLLATE NOCASE", args.format),
                       ("d.date >= ?", args.since), ("d.date <= ?", args.until)):
        if value:
            filter_sql += " AND " + sql
            params.append(value)
    emit(db.execute(f"""SELECT d.id, d.filename, d.kind, d.date, d.url, d.path,
        p.locator, p.source, p.method, snippet(passages,-1,'[',']',' … ',28) AS snippet
        FROM passages p JOIN docs d ON d.id=p.doc_id
        WHERE passages MATCH ? AND {filter_sql} ORDER BY rank LIMIT ?""", [*params, args.limit]))


def show(db, args):
    doc = db.execute("SELECT * FROM docs WHERE id=? OR filename=?", (args.id, args.id)).fetchone()
    if doc is None:
        raise SystemExit("Unknown document ID or filename")
    emit([doc])
    if args.verify and doc["path"]:
        sha = digest(ROOT / doc["path"])
        emit([{"sha256": sha, "matches_inventory": sha == doc["sha256"]}])
        if sha != doc["sha256"]:
            raise SystemExit(1)
    if args.locator:
        emit(db.execute("""SELECT locator, source, method, body FROM passages
                        WHERE doc_id=? AND locator=? COLLATE NOCASE""", (doc["id"], args.locator)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--ocr", action="store_true")
    build_parser.add_argument("--reuse-extraction", action="store_true")
    for command in ("search", "funding", "related"):
        query = commands.add_parser(command)
        if command == "related":
            query.add_argument("exclude", help="document ID to omit")
        else:
            query.set_defaults(exclude=None)
        query.add_argument("query", nargs="?" if command == "funding" else None)
        query.add_argument("--phrase", action="store_true")
        query.add_argument("--source", choices=["evidence", "official", "mirror", "supplement", "catalog", "additional", "all"], default="evidence")
        for name in ("kind", "format", "since", "until"):
            query.add_argument("--" + name)
        query.add_argument("--limit", type=int, choices=range(1, 101), metavar="1-100", default=12)
    view = commands.add_parser("show")
    view.add_argument("id")
    view.add_argument("locator", nargs="?")
    view.add_argument("--verify", action="store_true")
    commands.add_parser("stats")
    args = parser.parse_args()
    if args.command == "build":
        build(args.ocr, args.reuse_extraction)
    else:
        with connect() as db:
            if args.command == "show":
                show(db, args)
            elif args.command == "stats":
                emit(db.execute("SELECT format, byte_source, count(*) AS documents FROM docs GROUP BY format, byte_source"))
                emit(db.execute("SELECT source, method, count(*) AS passages FROM passages GROUP BY source, method"))
            else:
                search(db, args)


if __name__ == "__main__":
    main()
