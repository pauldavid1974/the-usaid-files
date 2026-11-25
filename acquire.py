"""Acquire mirror copies and import the intact official bundle when available."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
NAME = re.compile(r"[a-z0-9][a-z0-9-]*-([0-9a-f]{12})\.(pdf|xlsx|mp4)\Z")
OFFICIAL = "https://www.usaid.gov/downloads/usaid-files.zip?v=69a7f85d2acb"
MIRROR = "https://usaid-files.vercel.app"


def digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def describe(path, url):
    stat = path.stat()
    return {"path": path.relative_to(ROOT).as_posix(), "url": url,
            "bytes": stat.st_size, "sha256": digest(path),
            "local_mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def write_json(path, data):
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    part.replace(path)


def download(filename):
    match = NAME.fullmatch(filename)
    if not match:
        return {"filename": filename, "error": "unexpected filename"}
    folder = ROOT / "mirrors" / "files"
    path = folder / filename
    url = MIRROR + "/originals/" + quote(filename) + "/?download=1"
    try:
        if not path.exists():
            part = path.with_suffix(path.suffix + ".part")
            options = ["curl.exe", "--fail", "--silent", "--show-error", "--location",
                       "--proto", "=https", "--retry", "2", "--max-time", "600",
                       "--output", str(part), url]
            subprocess.run(options, check=True, capture_output=True)
            if not digest(part).startswith(match[1]):
                raise ValueError("bytes differ from filename digest prefix")
            part.replace(path)
        item = describe(path, url)
        if not item["sha256"].startswith(match[1]):
            raise ValueError("local checksum differs from filename digest prefix")
        return item
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        message = error.stderr.decode(errors="replace").strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        return {"filename": filename, "url": url, "error": message}


def mirror():
    text = (ROOT / "mirrors/llms-full.txt").read_text(encoding="utf-8")
    names = re.findall(r"(?m)^- Original filename: ([^\n]+)$", text)
    if len(set(names)) != len(names) or not all(NAME.fullmatch(name) for name in names):
        raise ValueError("unexpected or duplicate filenames in mirror export")
    (ROOT / "mirrors/files").mkdir(exist_ok=True)
    if shutil.disk_usage(ROOT).free < 3_000_000_000:
        raise OSError("less than 3 GB available")
    with ThreadPoolExecutor(max_workers=6) as pool:
        result = list(pool.map(download, names))
    write_json(ROOT / "manifests/mirror-files.json", result)
    print(f"{sum('sha256' in item for item in result)}/{len(names)} mirror binaries verified against filename prefixes")


def official(archive):
    if shutil.disk_usage(ROOT).free < 3_000_000_000:
        raise OSError("less than 3 GB available")
    preserved = ROOT / "government-archives/usaid-files.zip"
    if archive.resolve() != preserved.resolve():
        with ZipFile(archive) as source:
            if source.testzip() is not None:
                raise ValueError("archive CRC check failed")
        if preserved.exists():
            raise FileExistsError(preserved)
        pending = preserved.with_suffix(".zip.part")
        with archive.open("rb") as source, pending.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        if digest(pending) != digest(archive):
            raise ValueError("copied ZIP checksum differs")
        pending.replace(preserved)
    write_json(ROOT / "manifests/government-zip.json", describe(preserved, OFFICIAL))
    catalog = json.loads((ROOT / "manifests/official-catalog.json").read_text(encoding="utf-8"))
    expected = {row["filename"] for row in catalog}
    with ZipFile(preserved) as source:
        members = [item for item in source.infolist() if not item.is_dir()]
        names = [Path(item.filename).name for item in members]
        if len(set(names)) != len(names) or set(names) != expected:
            raise ValueError("ZIP filenames differ from official catalog. Review before extraction.")
        if sum(item.file_size for item in members) > shutil.disk_usage(ROOT).free:
            raise OSError("insufficient space for extraction")
        if source.testzip() is not None:
            raise ValueError("archive CRC check failed")
        result = []
        for member, name in zip(members, names):
            match = NAME.fullmatch(name)
            if not match:
                raise ValueError(f"unexpected ZIP member {name!r}")
            destination = ROOT / "originals" / name
            part = destination.with_suffix(destination.suffix + ".part")
            other = ROOT / "mirrors/files" / name
            with source.open(member) as input_file:
                member_hash = file_digest(input_file, "sha256").hexdigest()
            identical = other.is_file() and digest(other) == member_hash
            if destination.exists() and digest(destination) != member_hash:
                raise ValueError(f"existing original differs for {name}")
            if not destination.exists():
                if identical:
                    try:
                        os.link(other, destination)
                    except OSError:
                        pass
                if not destination.exists():
                    with source.open(member) as input_file, part.open("wb") as output_file:
                        shutil.copyfileobj(input_file, output_file)
                    if digest(part) != member_hash:
                        raise ValueError(f"extracted bytes differ for {name}")
                    part.replace(destination)
            record = describe(destination, "https://www.usaid.gov/files/" + quote(name))
            if not record["sha256"].startswith(match[1]):
                raise ValueError(f"official filename digest mismatch for {name}")
            record.update(path=destination.relative_to(ROOT).as_posix(), zip_member=member.filename,
                          zip_timestamp=member.date_time)
            record["mirror_comparison"] = ("identical" if identical else "different") if other.is_file() else "unavailable"
            result.append(record)
    write_json(ROOT / "manifests/official-files.json", result)
    print(f"{len(result)} official ZIP members verified and extracted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["mirror", "official"])
    parser.add_argument("zip", nargs="?", type=Path)
    args = parser.parse_args()
    if args.source == "mirror":
        mirror()
    else:
        official(args.zip or ROOT / "government-archives/usaid-files.zip")
