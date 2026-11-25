# USAID Files acquisition report

## Release inventory

The government listing enumerates 248 records. It lists 242 PDFs covering 2,160 pages, three XLSX workbooks, and three MP4 recordings. The page advertises a 1.1 GB ZIP. The first ZIP member carries a November 24, 2026 timestamp without a timezone. Contemporaneous reporting also attributes the release to November 24. [USAID release listing](https://www.usaid.gov/) · [Official ZIP](https://www.usaid.gov/downloads/usaid-files.zip?v=69a7f85d2acb) · [The Boston Report](https://thebostonreport.com/2026/11/24/usaid-files-disinformation-meta-youtube-google/)

The independent Apple Lamps collection supplied a binary copy for every official catalog filename. Total payload is 1,142,469,329 bytes. Each full SHA-256 starts with the 12-hex digest in that filename. All 248 hashes are distinct. The archive also preserves the bulk text, text index, methodology, and one per-record Markdown sample. The mirror has its own browser search tool. Searches located the publisher's GitHub profile. The source repository and any other independent binary mirror of this exact release remain unlocated. [Mirror home](https://usaid-files.vercel.app/) · [Bulk text](https://usaid-files.vercel.app/llms-full.txt) · [Text index](https://usaid-files.vercel.app/llms.txt) · [Methodology](https://usaid-files.vercel.app/about/) · [Sample Markdown](https://usaid-files.vercel.app/archive/text/usaid-disinformation-primer-3-5-21-final-public-18db212f9db2.md) · [Search tool](https://usaid-files.vercel.app/files/) · [GitHub profile](https://github.com/AppleLamps)

## Government acquisition

Direct requests to the government ZIP and a sample PDF received HTTP 403 Cloudflare challenges. The in-app browser displayed the official catalog and began the download. The Chrome and Edge integrations were unavailable. Active monitoring ended at Paul's request while the transfer was still incomplete. The local index is available immediately using the 248 independently hosted files. The partial comparison manifest records how many bytes of the first ZIP member matched the independently hosted video. USAID's online copy of the four-page GDI concept note supplied a representative content check. The ZIP importer is ready to measure the intact ZIP, check its CRCs and compare full SHA-256 values against the independently acquired copies. [Partial comparison](../manifests/government-partial-comparison.json) · [Official GDI concept note](https://www.usaid.gov/files/gdi-usaid-concept-note-august-2022-293a61098fd0.pdf)

## Processing and verification

Open [verification.json](../manifests/verification.json) for measured storage, file counts, searchable passages by source and method, and review flags. The manifests give acquisition URLs, local timestamps, byte lengths and full SHA-256 values. [processing.json](../manifests/processing.json) records extraction by document. [discrepancies.json](../manifests/discrepancies.json) lists catalog type differences and low-similarity PDF and transcript comparisons. Local ASR, OCR and spreadsheet extracts have their own locators and link to the recorded input hash.

OCR ran on 521 pages. It returned text on 518. The remaining three were checked visually. One had no visible text, one contained only redactions, and one had a visible attachment label that was transcribed. The three workbooks contain 741 extracted cells across 229 populated rows. The recording index includes 331 locally generated transcript segments and 2,167 independently supplied caption cues.

One example is publication-004, a memo whose filename and mirror date field indicate July 12, 2022. The rendered first page says July 11, 2022. The mirror's first-page extract contains visibly garbled words. Local OCR recovered readable text in the reviewed passage. The USAID catalog labels the Primer a Report, while the independent site labels it a Document. These examples illustrate why catalog metadata, dates, and automated extraction need source review.

Mirror captions and locally generated transcripts are machine-readable aids. Caption alignment and automated text similarity can produce false flags, and similarity is no substitute for reviewing the exact source page or recording. The index searches financial terms and provides cell coordinates where available. It does not establish whether a named amount was proposed, authorized, or transferred. Dates and entity hints are sparse and partly mirror-supplied. PDF text preserves page boundaries but may flatten layouts or omit text in mixed image/text areas. Email fields are recovered only when visible and recognizable in the released files. Supplied redactions remain in the source.

## Start research

Open [START-HERE.md](../START-HERE.md) for commands, source labels and citation examples. Use [AGENTS.md](../AGENTS.md) for handling, maintenance and adding records. The archive and research tools run locally.
