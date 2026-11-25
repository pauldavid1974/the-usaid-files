# USAID Files research archive

This archive covers the 248 records listed in the November 2026 USAID Files release. Read [acquisition status](findings/ACQUISITION.md) for the current evidence and gaps. Read [AGENTS.md](AGENTS.md) before researching or adding material.

## Search

From this directory, use Python 3.13 or a Python build with SQLite FTS5. The existing index is readable with the standard library. Requests below return JSON lines for easy piping or agent use.

```powershell
python research.py stats
python research.py search 'information integrity' --phrase --limit 5
python research.py search 'Samantha Power' --phrase --kind Email --since 2022-01-01
python research.py search 'State Department' --phrase --format pdf
python research.py funding --limit 5
python research.py search 'Sri Lanka' --phrase --format xlsx
python research.py search 'democracy' --format mp4 --source all --limit 5
python research.py related publication-065 'Global Disinformation Index' --phrase
python research.py show publication-065 'Page 1' --verify
```

Search uses normal SQLite FTS5 syntax, including `AND`, `OR`, quoted phrases and a trailing `*` for prefix expansion. Use the result's `id` and exact `locator` with `show`. Search dates come from recognizable first-page PDF date fields or mirror metadata. `show` gives the date's origin. A date filter excludes undated records. People, organizations and agencies can be looked up by name through full text and mirror metadata hints. Related searches look for the same term in other documents.

## Read and verify

1. Start with a short search and read a few passages from distinct documents. In `show`, keep the source label next to each extract.
2. Follow the local `path` and inspect the original PDF page, spreadsheet sheet and row, or recording time. A PDF locator is the physical page position starting at 1.
3. Run `show ID --verify` to compare local bytes with the full SHA-256 recorded at ingestion. Check the official URL and the release inventory for provenance.
4. Cite the filename, physical page or sheet and cells or timestamp, relevant passage, and official URL. If available evidence comes from a mirror or automated extraction, say so. For videos, listen to the recording around a timestamp before quoting. For tables, read the column headers, units, neighboring rows and workbook context.

Source labels include `official` for ZIP-derived bytes after verified import, `mirror` for local extraction from separately hosted file bytes that match official filename digest prefixes, `catalog` for listing metadata, `supplement` for the independent publisher's extraction and captions, and `additional` for separately registered documents. Independent editorial opinion and AI summaries remain only in the preserved export. Searchable topic and name hints are leads provided by the mirror publisher.

## Layout

| Path | Contents |
| --- | --- |
| `government-archives/` | Intact official ZIP when acquired |
| `originals/` | Verified government ZIP members, opaque PDF attachments and separately registered additions |
| `mirrors/` | Independent binaries and machine-readable exports |
| `text/` | Page- and row-level local extraction JSON with source hashes |
| `transcripts/` | Independent timestamped captions and local speech recognition JSON |
| `manifests/` | Catalog, SHA-256 inventory, processing status, and comparison flags |
| `index/` | Rebuildable SQLite FTS5 index |
| `findings/` | Acquisition report and future evidence notes |
| `summaries/` | Optional researcher summaries with document references |
| `.venv/`, `.models/` | Local extraction environment and speech model cache |
