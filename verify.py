"""Read back the local archive, verify its bytes and exercise the search index."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
from zipfile import ZipFile

from acquire import ROOT, MIRROR, OFFICIAL, describe, digest, write_json
from research import connect, read_manifest


def compare_partial(path):
    """Compare only the observable stored member prefix in an incomplete official ZIP."""
    with path.open("rb") as partial:
        header = partial.read(30)
        signature, _, flags, method, dos_time, dos_date, _, size, _, name_len, extra_len = struct.unpack("<4s5H3I2H", header)
        if signature != b"PK\x03\x04" or flags & 0x9 or method != 0:
            raise ValueError("partial ZIP first member is not an unencrypted stored file")
        filename = partial.read(name_len).decode("ascii")
        known = next((row for row in read_manifest("official-catalog.json") if row["filename"] == filename), None)
        if known is None:
            raise ValueError("first ZIP member is absent from official catalog")
        partial.read(extra_len)
        verified = 0
        with (ROOT / "mirrors/files" / filename).open("rb") as mirror:
            while verified < size and (block := partial.read(min(1_048_576, size - verified))):
                if block != mirror.read(len(block)):
                    raise ValueError(f"government ZIP payload differs at or after byte {verified}")
                verified += len(block)
        stamp = datetime(1980 + (dos_date >> 9), (dos_date >> 5) & 15, dos_date & 31,
                         dos_time >> 11, (dos_time >> 5) & 63, (dos_time & 31) * 2)
    result = {"url": OFFICIAL, "first_member": filename, "first_member_expected_bytes": size,
              "matching_prefix_bytes": verified, "member_zip_timestamp_without_timezone": stamp.isoformat(),
              "verified_utc": datetime.now(timezone.utc).isoformat()}
    write_json(ROOT / "manifests/government-partial-comparison.json", result)
    print(result)


def verify():
    catalog = read_manifest("official-catalog.json")
    mirror = read_manifest("mirror-files.json")
    original = read_manifest("official-files.json")
    processing = [row for row in read_manifest("processing.json") if row["id"].startswith("publication-")]
    assert len(catalog) == len(mirror) == 248
    expected = {row["filename"]: row["sha256_prefix"] for row in catalog}
    seen = set()
    checks = []
    for item in [*mirror, *original]:
        path = ROOT / item["path"]
        assert item["sha256"].startswith(expected[path.name])
        assert path.stat().st_size == item["bytes"], path
        assert digest(path) == item["sha256"], path
        checks.append(item)
        seen.add(path.name)
    assert seen == set(expected)
    zipped = ROOT / "government-archives/usaid-files.zip"
    if zipped.exists():
        with ZipFile(zipped) as archive:
            assert archive.testzip() is None
            assert {Path(item.filename).name for item in archive.infolist() if not item.is_dir()} == set(expected)
        assert len(original) == len(catalog)
        checks.append(describe(zipped, OFFICIAL))
    assets = []
    for name, route in (("mirror.html", "/"), ("about.html", "/about/"),
                        ("llms.txt", "/llms.txt"), ("llms-full.txt", "/llms-full.txt"),
                        ("sample-mirror.md", "/archive/text/usaid-disinformation-primer-3-5-21-final-public-18db212f9db2.md")):
        path = ROOT / "mirrors" / name
        if path.exists():
            assets.append(describe(path, MIRROR + route))
    write_json(ROOT / "manifests/source-assets.json", assets)
    checks.extend(assets)
    (ROOT / "manifests/SHA256SUMS.txt").write_text("".join(
        f"{row['sha256']}  {row['path']}\n" for row in checks), encoding="utf-8")
    with connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT count(*) FROM docs WHERE id LIKE 'publication-%'").fetchone()[0] == 248
        for format_, query in (("pdf", '"information integrity"'), ("xlsx", '"Sri Lanka"'), ("mp4", "democracy")):
            count = db.execute("""SELECT count(*) FROM passages p JOIN docs d ON d.id=p.doc_id
              WHERE passages MATCH ? AND d.format=? AND p.locator != 'Catalog'""", (query, format_)).fetchone()[0]
            assert count > 0, format_
        stats = [dict(row) for row in db.execute("SELECT source, method, count(*) AS passages FROM passages GROUP BY source, method")]
    media = [row for row in processing if row["format"] == "mp4"]
    differences = read_manifest("discrepancies.json")
    pdf_count = sum(sum(row["local_methods"].values()) for row in processing if row["format"] == "pdf")
    assert pdf_count == 2160, f"{pdf_count} local pages vs 2160 in official catalog"
    assert all(row["local_methods"] for row in media)
    assert sum(row["mirror_segments"] for row in media) == 2167
    assert all(not row["error"] for row in processing), [row for row in processing if row["error"]]
    workbook_rows = workbook_cells = 0
    for row in catalog:
        if row["format"] != "xlsx":
            continue
        file = ROOT / "text" / (Path(row["filename"]).stem + ".json")
        sheet = json.loads(file.read_text(encoding="utf-8"))
        workbook_rows += len(sheet["segments"])
        workbook_cells += sum(len(entry["cells"]) for entry in sheet["segments"])
    assert workbook_cells == 741
    bytes_by_folder = Counter()
    for path in ROOT.rglob("*"):
        if path.is_file():
            bytes_by_folder[path.relative_to(ROOT).parts[0]] += path.stat().st_size
    report = dict(verified_utc=datetime.now(timezone.utc).isoformat(), government_files=len(original),
                  mirror_files=len(mirror), mirror_bytes=sum(item["bytes"] for item in mirror),
                  repeated_mirror_hashes={key: value for key, value in Counter(item["sha256"] for item in mirror).items() if value > 1},
                  official_zip_bytes=zipped.stat().st_size if zipped.exists() else None,
                  pdf_pages=pdf_count, workbook_rows=workbook_rows, workbook_cells=workbook_cells,
                  media=media, passages=stats, differing_records=len(differences),
                  differing_types=sum(item["catalog_kind"] != item["mirror_kind"] for item in differences),
                  text_flags=sum(len(item["text_review_flags"]) for item in differences),
                  workspace_logical_bytes=sum(bytes_by_folder.values()), bytes_by_top_level=dict(bytes_by_folder))
    write_json(ROOT / "manifests/verification.json", report)
    print(f"Read-back verified {len(seen)} distinct release filenames and {len(checks)} checksums")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial-zip", type=Path)
    arguments = parser.parse_args()
    if arguments.partial_zip:
        compare_partial(arguments.partial_zip)
    else:
        verify()
