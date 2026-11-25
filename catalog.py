"""Reconcile the mirror export with the government catalog captured in the browser."""
from collections import Counter
from datetime import date
import re

from acquire import ROOT, NAME, write_json

OFFICIAL_FINGERPRINT = 0xa6d5f8fb053db86c
OFFICIAL_IDS = "2b2d2e2f2g0203042i08090a2k052606070b1p0c0d2l0e2m2n2o2r272829711j1k1l72732s2t0f2q2p0g0h0j0k0l1m0m1q2v0n2w2u0i2x2y0o0p0r0q2z313332740s0t30343c36351r0u370v38393a3b0w2a1s1t3d1n3e1u0x3f3h3i1v3l3k3j3m3n3o3p43243q44454647486c494c4a4d4b4e1w4f3r4g4h4i4l4j4k4q4r3s3t4s4o4p4n4m4t4u1x1y1z6d4v4x4y4w3u4z5051520z555356543y5957585a5b5c5d205e6e5f5h5g5i6g5j5k0y5l3w215m5n6h5q5s5r23225t3z5u5o6i5p5v5w6962635y5z5x1060656164666711126a6b3x6j6k136l40146m15196n701618171a6o6p6q1b6r6s6y1o1f1c1d6t6u756v011e6w6x1h1g251i6z"
OFFICIAL_KINDS = (
    "555553aa522a5a228555d5555557775"
    "777555555553285255555565f288855"
    "5552df2222222222222e515c5025552"
    "5555555222222222222222222222222"
    "2222222222222222222222222222222"
    "2222222222222222222222222222222"
    "2222222222252222222222255b55156"
    "355529255f05552224555502552c255"
)
KINDS = ("Video", "Concept note", "Email", "Briefing", "Report", "Document", "Program review",
         "Chat log", "Presentation", "Summary of conclusions", "Information memo", "Action memo",
         "Paper", "Fact sheet", "Call for partners", "Spreadsheet")
RECORD = re.compile(r"(?m)^# (.+)\n\n- Record page: (https://usaid-files\.vercel\.app/(?:files|videos)/[^\s]+)\n")


def mirror_records():
    raw = (ROOT / "mirrors/llms-full.txt").read_text(encoding="utf-8")
    matches = list(RECORD.finditer(raw))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        record = raw[match.end():end]
        metadata = dict(re.findall(r"(?m)^- ([A-Za-z ]+): (.+)$", record.split("\n## ", 1)[0]))
        source = re.search(r"(?m)^## Source text(?:: transcript)?\s*\n", record)
        if not source or not NAME.fullmatch(metadata.get("Original filename", "")):
            raise ValueError(f"unrecognized source format for {match[1]}")
        body = re.sub(r"\n---\s*$", "", record[source.end():]).strip()
        yield match[1], match[2], metadata, body, raw.count("\n", 0, source.end()) + 1


def catalog():
    records = sorted(mirror_records(), key=lambda item: item[2]["Original filename"])
    names = [item[2]["Original filename"] for item in records]
    fingerprint = 14695981039346656037
    for byte in "\n".join(names).encode("ascii"):
        fingerprint = ((fingerprint ^ byte) * 1099511628211) & (2**64 - 1)
    if (fingerprint != OFFICIAL_FINGERPRINT or len(set(names)) != 248
            or len(OFFICIAL_KINDS) != 248 or len(OFFICIAL_IDS) != 496):
        raise ValueError("mirror filenames do not match the captured official catalog")
    rows = []
    for index, (title, mirror_url, metadata, _, _) in enumerate(records):
        filename = metadata["Original filename"]
        record_id = int(OFFICIAL_IDS[2*index:2*index+2], 36)
        date_claim = metadata.get("Date", "")
        match = re.match(r"^\d{4}-\d{2}-\d{2}\b", date_claim)
        document_date = date.fromisoformat(match[0]).isoformat() if match else None
        entities = "; ".join(metadata[key] for key in ("People mentioned", "Companies mentioned", "Indexed topics") if key in metadata)
        rows.append({"id": f"publication-{record_id:03}", "filename": filename,
                     "kind": KINDS[int(OFFICIAL_KINDS[index], 16)], "format": NAME.fullmatch(filename)[2],
                     "url": "https://www.usaid.gov/files/" + filename, "sha256_prefix": NAME.fullmatch(filename)[1],
                     "mirror_title": title, "mirror_url": mirror_url, "mirror_kind": metadata.get("Type"),
                     "mirror_date": document_date, "mirror_date_claim": date_claim,
                     "mirror_entity_hints": entities})
    assert len({row["id"] for row in rows}) == 248
    assert Counter(row["format"] for row in rows) == {"pdf": 242, "xlsx": 3, "mp4": 3}
    return rows


if __name__ == "__main__":
    rows = catalog()
    write_json(ROOT / "manifests/official-catalog.json", rows)
    print("Matched all 248 filenames to the official catalog")
