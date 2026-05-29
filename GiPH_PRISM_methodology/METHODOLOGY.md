# Migration Bug Detection Methodology
## GiPH/PRISM Research — Carnegie Mellon University

### 1. Overview
The methodology detects Python 2 to Python 3 migration bugs through a 
three-stage data flow analysis applied to open-source Python codebases.
Each stage builds on the previous:

Stage 1 — Origin identification: locate binary data entry points
Stage 2 — Pattern scan: 40 patterns derived from Python 3 semantic changes
Stage 3 — Flow tracing: follow data from origin through assignments to sink

### 2. Derivation of the 40 Patterns

The 40 patterns were not collected ad hoc. They were derived systematically 
from the complete set of semantic changes Python 3 introduced that:
(a) preserve syntactic validity — the code runs without SyntaxError
(b) change runtime behavior — the code produces a different result or crash
(c) are invisible to existing tools — mypy, pyright, and 2to3 do not flag them

The derivation process examined every section of PEP 3100, PEP 3107, 
the Python 3 What's New document, and the Python 2 to 3 porting guide, 
then extracted patterns in seven groups:

**Group 1 — Bytes/str separation (8 patterns)**
Python 3 made bytes and str distinct non-interchangeable types. In Python 2
they were unified as str. Any operation that took str in Python 2 but now
receives bytes from open("rb"), socket.recv(), or struct.unpack() is a 
candidate pattern. Patterns derived:
- ord(c) — bytes[i] is int in Python 3, ord(int) crashes
- chr(c) — chr() returns str in Python 3, breaks binary writes
- return "" — inconsistent return type when function also returns bytes
- .find(str) on bytes — always -1, no error
- .split(str) on bytes — TypeError
- .startswith(str) on bytes — always False
- .endswith(str) on bytes — always False
- bytes == str — always False, silent logic error

**Group 2 — Removed or changed builtins (12 patterns)**
Systematic enumeration from the Python 3 changelog of names removed 
from builtins or changed semantically:
- has_key() — removed from dict
- basestring — type removed
- unicode() — function removed
- xrange() — replaced by range()
- raw_input() — replaced by input()
- reduce() — moved to functools
- filter() — now returns iterator not list
- map() — now returns iterator not list
- zip() — now returns iterator not list
- dict.keys() — now returns view not list
- dict.values() — now returns view not list
- dict.items() — now returns view not list

**Group 3 — Integer arithmetic (2 patterns)**
- / operator between integers — returns float in Python 3
- sys.maxint — removed, replaced by sys.maxsize

**Group 4 — Exception handling (4 patterns)**
- raise Exception(fmt, arg) — tuple not string
- except X, e: — syntax removed in Python 3
- raise exc.with_traceback(tb) — changed idiom
- sys.exc_info() three-argument reraise — changed idiom

**Group 5 — Import renames (8 patterns)**
Systematic enumeration of Python 3 stdlib reorganization:
- urllib2 → urllib.request / urllib.error
- httplib → http.client
- cookielib → http.cookiejar
- StringIO → io
- cPickle → pickle
- ConfigParser → configparser
- HTMLParser → html.parser
- from __future__ — signals dual-version awareness (informational)

**Group 6 — String encoding (4 patterns)**
- .encode() without explicit encoding argument
- .decode() without error handler
- str() on bytes — produces "b'...'" not the content
- % formatting on bytes — TypeError in Python 3

**Group 7 — Silent comparison failures (2 patterns)**
- bytes == "string" — always False
- bytes != "string" — always True
Both produce no error in Python 3 — the most dangerous class.

### 3. The Three-Stage Data Flow Pipeline

Stage 1: Binary Origin Identification
Search for these entry points — each returns bytes in Python 3:
  open(f, "rb")        → file object, all reads return bytes
  socket.recv(n)       → bytes
  struct.unpack(fmt,d) → tuple of bytes/int
  ssl.read(n)          → bytes
  channel.recv(n)      → bytes

Stage 2: Pattern Scan
Run the 40 patterns across the codebase.
For each hit: record filename, line number, code, context.
Classify each hit as:
  CONFIRMED — hit exists in py3, absent or different in py2
  CANDIDATE — hit exists in both, behavioral difference needs tracing
  FALSE POSITIVE — hit exists but context proves safety

Stage 3: Data Flow Trace
For each CONFIRMED or CANDIDATE hit:
  Step 1: Find the binary origin (Stage 1) that feeds this variable
  Step 2: Trace every assignment from origin to the hit
  Step 3: Confirm the type at the hit is bytes not str
  Step 4: Compare py2_codebase behavior at the same line
  Step 5: Write the ORIGIN → FLOW → SINK chain
  Step 6: Produce a test script and confirm live crash

### 4. Codebase Selection Criteria
Each project must satisfy:
- Confirmed Python 2 history (git log shows Python 2 era commits)
- Active Python 3 migration (not abandoned, maintained)
- Binary data handling (network, file I/O, or protocol parsing)
- Sufficient size (>50 Python files) for non-trivial analysis

### 5. Negative Controls
Clean projects are as important as buggy ones. A methodology that only
produces true positives is useless without true negatives to validate the
false positive rate. For each clean project document:
- All patterns searched
- All hits investigated
- Why each hit is safe
- What migration approach made the codebase clean

### 6. Documentation Standard
Every confirmed bug requires:
- Exact file and line number
- Test script saved to analysis\ folder
- Live crash output with full traceback
- py2_codebase grep showing the origin of the bug
- ORIGIN → FLOW → SINK data flow chain
- Before/after comparison showing Python 2 vs Python 3 behavior
