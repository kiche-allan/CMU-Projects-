Migration Bug Detection Methodology
May 2026

1. Research Motivation
The Python 2 to Python 3 migration produced a class of bugs that no existing static analysis tool detects. These bugs share three properties: they are syntactically valid Python 3 and raise no SyntaxError; they produce crashes or silently wrong results at runtime; and they are invisible to mypy, pyright, pylint, and 2to3. They exist because Python 3 changed the semantics of several core language constructs without changing their syntax, meaning that Python 2 code using those constructs can be imported and run without error right up to the moment a specific code path is exercised.

The canonical example from this study is ord(c) applied to bytes data in QEMU's analyze-migration.py. In Python 2, iterating a string gave single characters, and ord('A') = 65 was correct. In Python 3, iterating bytes gives integers directly, and ord(65) crashes with TypeError. The line is syntactically identical in both versions. Four levels of function calls and class boundaries separate the open('rb') origin from the crash site. No existing tool traces this connection. The methodology was designed specifically to find bugs of this class at scale across multiple open-source projects.

2. Methodology Overview
The methodology applies a three-stage data flow analysis pipeline to each target project. Two codebase snapshots are extracted from the project's git history: the last commit before Python 3 only support was declared (py2_codebase) and the current Python 3 master (py3_codebase). The pipeline runs against py3_codebase and uses py2_codebase as a behavioral baseline for comparison.

Stage	Name	Purpose
1	Binary origin identification	Locate all entry points where binary data enters the codebase — open("rb"), socket.recv(), struct.unpack(), ssl.read(), channel.recv(). These are the ORIGIN nodes in the data flow model.
2	40-pattern scan	Run 40 grep patterns derived from Python 3 semantic changes across py3_codebase. Each hit is classified as CONFIRMED (new in py3), CANDIDATE (needs tracing), or FALSE POSITIVE (context proves safety).
3	Data flow trace	For every CONFIRMED or CANDIDATE hit, trace the data from its binary ORIGIN through every FLOW step (assignments, function calls, returns) to the SINK (the crashing or silently wrong operation). Compare with py2_codebase behavior. Produce a live crash proof.

The three-stage structure exists because pattern scanning alone produces too many false positives. A call to ord() is only a bug if the argument is an integer arriving from a bytes iteration, not a character arriving from a string. The data flow trace in Stage 3 is what distinguishes real bugs from coincidental pattern matches, and it is the step that makes the methodology genuinely novel compared to existing approaches.

3. Codebase Selection Criteria
Each project in the study must satisfy four criteria. First, it must have a confirmed Python 2 history visible in git log, demonstrating that a real migration occurred rather than the project being Python 3 native. Second, it must be actively maintained on Python 3, ensuring the py3_codebase is a current production codebase rather than an abandoned snapshot. Third, it must handle binary data at some level, whether through network I/O, file reads, protocol parsing, or binary serialization, since binary data is the primary source of bytes/str type confusion bugs. Fourth, the codebase must be large enough for non-trivial analysis, with a minimum of 50 Python source files, since smaller projects rarely have the function call depth needed for multi-level data flow bugs.

Negative controls are selected deliberately. The study includes projects expected to be clean alongside projects expected to have bugs, so that the false positive rate of the methodology can be validated. A methodology that only returns true positives cannot be trusted in isolation.

4. Derivation of the 40 Patterns
The 40 patterns were derived systematically by examining every semantic change Python 3 introduced and asking a single question: does any code pattern that was correct under Python 2 semantics become incorrect under Python 3 semantics without being a syntax error? Every yes answer produces a pattern. The source documents examined were PEP 3100 (miscellaneous Python 3 changes), PEP 3107 (function annotations), the Python 3 What's New document, and the official Python 2 to 3 porting guide. The resulting 40 patterns are grouped into seven categories based on the type of language change that produced them.

Group 1 — Bytes/str Separation (8 patterns)
Python 3's most significant change was making bytes and str distinct non-interchangeable types. In Python 2, str was simultaneously a byte sequence and a character sequence. Any operation that expected str in Python 2 but now receives bytes from a binary data origin is a candidate pattern. The eight patterns cover the full set of such operations: ord() on bytes iteration, chr() returning str instead of a byte, inconsistent return types mixing str and bytes, and the string methods find, split, startswith, endswith when called on bytes with a str argument. The most dangerous member of this group is bytes == str, which returns False silently in Python 3 with no error — logic that depends on this comparison silently takes the wrong branch on every execution.

Group 2 — Removed or Changed Builtins (12 patterns)
Python 3 removed several built-in names that existed in Python 2 and changed the return types of several built-in functions. The removed names — has_key(), basestring, unicode(), xrange(), raw_input(), and reduce() — raise NameError or AttributeError when called in Python 3, but only at runtime when the code path containing them is reached. They can survive in rarely-exercised branches for years undetected. The return type changes are subtler: filter(), map(), and zip() now return lazy iterators rather than lists. Code that stores the result and later calls len(), indexes it, or iterates it twice silently fails or crashes. The three dict view methods — keys(), values(), items() — also return views rather than lists, which are not subscriptable.

Groups 3 through 7 — Remaining 20 Patterns
Group	Category	Count	Key change and risk
3	Integer arithmetic	2	/ between integers returns float in Python 3. sys.maxint removed. Silent wrong results in numeric code.
4	Exception handling	4	raise Exception(fmt, arg) stores a tuple not a formatted string. except X, e: syntax removed. Both invisible to syntax checkers.
5	Import renames	8	urllib2, httplib, cookielib, StringIO, cPickle, ConfigParser, HTMLParser all renamed. ImportError at runtime only.
6	String encoding	4	.encode()/.decode() without explicit arguments, str() on bytes producing "b'...'", % formatting on bytes raising TypeError.
7	Silent comparison failures	2	bytes == str and bytes != str produce no error but always return False and True respectively. The most dangerous class.


5. The Data Flow Trace in Detail
Stage 3 is the most technically demanding part of the methodology and the part that makes it novel. For each confirmed or candidate hit from Stage 2, a complete ORIGIN → FLOW → SINK chain is constructed by manual tracing through the codebase. The ORIGIN is the binary data entry point identified in Stage 1. The FLOW is every intermediate step — variable assignment, function return, parameter passing, class attribute assignment — through which the bytes value travels. The SINK is the operation where the bytes value is misused as if it were a str.

The chain frequently crosses class and module boundaries, which is why pattern scanning alone cannot find these bugs. In the QEMU case, the ORIGIN is open(filename, 'rb') in MigrationFile.__init__() at line 36. The bytes value flows through self.file.read(size) in MigrationFile.readvar() at line 56, crosses into RamSection.read() via a method call at line 234, and reaches the SINK ord(c) at line 255 — four levels deep, two class boundaries crossed. Looking at line 255 in isolation, the code appears to be valid Python 3. The bug is only visible when the full chain is traced from origin to sink.

Once the chain is established, a test script is written that exercises the exact code path without modifying any source files. The test is run from inside the py3_codebase directory, and the full traceback is captured as a proof file. This live crash confirmation is required for every bug — theoretical findings based on code reading alone are not accepted. The py2_codebase is then grepped to show that the same code path existed and functioned correctly under Python 2, confirming that the bug is a migration artifact rather than a pre-existing error.

6. Negative Controls and False Positive Validation
The study includes five projects that returned clean results: mitmproxy, scrapy, celery, paramiko, and requests. These negative controls are not failures of the methodology — they are essential validation evidence. A detection methodology with no validated true negatives cannot claim a reliable false positive rate, and research based on such a methodology cannot be trusted.

For each clean project, every hit from the 40-pattern scan is investigated and documented with an explanation of why it is safe. The documentation records the type of the variable at the hit site, the context that proves safety, and the migration approach the project used. Analysis of the five negative controls reveals four distinct migration patterns that consistently prevent bugs: an explicit two-layer bytes/str architecture (mitmproxy), systematic use and complete removal of a compatibility library (scrapy), a custom compatibility module dissolved systematically into production code (paramiko), and RFC-compliant encoding choices with full documentation of reasoning (requests). These patterns form a set of migration best practices that the research contributes alongside the bug findings.

The false positive classification in Stage 2 also contributes to this validation. Every hit initially flagged as a candidate that is later proved safe is documented as a false positive with a full explanation. Across 10 projects, the false positive investigation has revealed important distinctions: ord() called on a str loop variable annotated with type hints is not a bug; latin-1 encoding in HTTP Basic Auth is RFC 7617 compliant and not the anti-pattern; bare .decode() on PEM output is safe because PEM is structurally ASCII. These distinctions are part of what the research tool must encode as context-sensitive rules.

7. Results — 10 Projects
Project	Bugs	Bug class / verdict
mitmproxy	0	Negative control — two-layer bytes/str architecture
sqlmap	4	str.__iter__ addition, map() iterator, int(bytes) TypeError, str.decode() removed
OCRmyPDF	1	bytes(str) without encoding argument — silent NUL-stripping failure
scrapy	0	Negative control — systematic six library removal
numpy	1	asbytes() hardcoded latin-1 — silent corruption on UTF-8 content
pandas	1	_decode() latin-1 fallback — silent wrong column names in Stata files
DRF	1	Basic Auth latin-1 fallback — wrong credentials authenticate as same user
celery	0	Negative control — minimal shims, clean migration
paramiko	0	Negative control — deepest binary surface in study, cleanest migration
requests	0	Negative control — RFC-compliant encoding, iso-8859-1 is HTTP spec mandated

The dominant finding across the five buggy projects is the latin-1 fallback anti-pattern: try to decode bytes as UTF-8, catch UnicodeDecodeError, fall back to latin-1. This pattern appears independently in numpy, pandas, and Django REST Framework. In numpy it causes silent data corruption when reading UTF-8 content. In pandas it causes wrong column names in Stata file imports. In DRF it allows two different credentials to authenticate as the same user — a security vulnerability. The escalating severity across three independent occurrences of the same pattern is the strongest argument in the study for why a systematic detection tool is needed.
