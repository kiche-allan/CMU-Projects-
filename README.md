# CMU Projects — Python 2→3 Migration Bug Detection Research

Research repository for the GiPH/PRISM methodology: a three-stage data flow analysis pipeline that detects Python 2 to Python 3 migration bugs invisible to all existing static analysis tools.

## What This Repository Contains

| Folder | Contents |
|---|---|
| `methodology/` | Full methodology documentation, 40-pattern definitions, and research framework |
| `celery_analysis/` | Celery — negative control (clean migration) |
| `drf_analysis/` | Django REST Framework — Bug: Basic Auth latin-1 fallback (security) |
| `mitmproxy_analysis/` | mitmproxy — negative control (two-layer bytes/str architecture) |
| `numpy_analysis/` | NumPy — Bug: asbytes() hardcoded latin-1, silent UTF-8 corruption |
| `ocrmypdf_analysis/` | OCRmyPDF — Bug: bytes(str) without encoding, silent NUL-stripping |
| `pandas_analysis/` | pandas — Bug: _decode() latin-1 fallback, wrong Stata column names |
| `paramiko_analysis/` | paramiko — negative control (deepest binary surface, cleanest migration) |
| `requests_analysis/` | requests — negative control (RFC-compliant iso-8859-1 encoding) |
| `scrapy_analysis/` | scrapy — negative control (systematic six-library removal) |
| `sqlmap_analysis/` | sqlmap — 4 bugs: str.__iter__, map() iterator, int(bytes), str.decode() |

## Key Finding

**7 confirmed bugs across 5 projects.** The dominant pattern is the **latin-1 fallback anti-pattern** — independently present in numpy, pandas, and Django REST Framework — with escalating severity from silent data corruption to a security vulnerability allowing two different credentials to authenticate as the same user.

## Methodology Summary

Three stages:
1. **Binary origin identification** — locate all `open("rb")`, `socket.recv()`, `struct.unpack()` entry points
2. **40-pattern scan** — classify hits as CONFIRMED, CANDIDATE, or FALSE POSITIVE
3. **Data flow trace** — trace ORIGIN → FLOW → SINK across class/module boundaries; confirm with live crash proof

See [`methodology/METHODOLOGY.md`](methodology/METHODOLOGY.md) for the full methodology.

## Projects Analysed

| Project | Bugs | Verdict |
|---|---|---|
| mitmproxy | 0 | Negative control — two-layer bytes/str architecture |
| sqlmap | 4 | str.__iter__, map() iterator, int(bytes) TypeError, str.decode() removed |
| OCRmyPDF | 1 | bytes(str) without encoding — silent NUL-stripping failure |
| scrapy | 0 | Negative control — systematic six-library removal |
| numpy | 1 | asbytes() hardcoded latin-1 — silent UTF-8 corruption |
| pandas | 1 | _decode() latin-1 fallback — wrong Stata column names |
| DRF | 1 | Basic Auth latin-1 fallback — wrong credentials authenticate as same user |
| celery | 0 | Negative control — minimal shims, clean migration |
| paramiko | 0 | Negative control — deepest binary surface in study, cleanest migration |
| requests | 0 | Negative control — RFC-compliant encoding, iso-8859-1 is HTTP spec mandated |
