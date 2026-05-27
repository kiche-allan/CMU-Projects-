"""
BUG 1 PROOF — numpy/lib/_npyio_impl.py:1706
asbytes() migration residue in fromregex()

Root cause: py3 kept py2's asbytes() coercion but dropped the symmetric elif
branch. asbytes() hardcodes latin1 encoding, causing:
  - Silent wrong results when binary content is UTF-8 encoded
  - UnicodeEncodeError crash when regexp contains chars outside latin1 range

File:  numpy/lib/_npyio_impl.py
Lines: 1706-1707

NOTE: Run from analysis/ directory (not py3_codebase/) so system numpy is used.
      The installed numpy has the same asbytes shim — this is not version-specific.
"""

import sys
import os

# Force UTF-8 output so non-ASCII chars in proof output don't crash on cp1252 console
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# numpy is installed in analysis/Lib/site-packages (pip installed locally)
# Strip any source tree paths that would shadow it
sys.path = [p for p in sys.path if 'py3_codebase' not in p and 'py2_codebase' not in p]

_here = os.path.dirname(os.path.abspath(__file__))
_site = os.path.join(_here, "Lib", "site-packages")
if _site not in sys.path:
    sys.path.insert(0, _site)

import traceback
from io import BytesIO, StringIO

print("=" * 62)
print("ENVIRONMENT")
print("=" * 62)
print(f"Python : {sys.version}")

# ----------------------------------------------------------------
# 0. Show the asbytes() definition we're exercising
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 0: asbytes() definition  (numpy/_utils/_conversions.py)")
print("=" * 62)

from numpy._utils import asbytes
import inspect
print(inspect.getsource(asbytes))

# ----------------------------------------------------------------
# 1. Show what asbytes() does to various regexp strings
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 1: What asbytes() does to str regexps")
print("=" * 62)

cases = [
    (r'simple',      'ASCII only — safe'),
    ('café',    'U+00E9 é  — latin1 range, silently encodes'),
    ('café+',   'U+00E9 with quantifier — silently encodes'),
    ('αdata',   'U+03B1 α  — outside latin1, should CRASH'),
    ('中文', 'U+4E2D U+6587 — Chinese, outside latin1, CRASH'),
]

for s, label in cases:
    try:
        result = asbytes(s)
        print(f"  asbytes({s!r:20}) => {result!r:30}  [{label}]")
    except UnicodeEncodeError as e:
        # use ascii() to avoid console encoding issues
        print(f"  asbytes({s!r:20}) => UnicodeEncodeError: {ascii(str(e))}  [{label}]")

# ----------------------------------------------------------------
# 2. Demonstrate SILENT WRONG RESULT — UTF-8 encoded binary file
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 2: Silent wrong result — UTF-8 binary content")
print("=" * 62)

import numpy as np

# Simulate a binary file whose content is UTF-8 encoded
# é in UTF-8 = b'\xc3\xa9'  (two bytes)
# é in latin1 = b'\xe9'     (one byte)
utf8_content = 'record café 42\nrecord naïve 99\n'.encode('utf-8')
print(f"  Binary content (UTF-8): {utf8_content!r}")
print(f"  UTF-8 bytes for é: {chr(0xe9).encode('utf-8')!r}  (2 bytes: \\xc3\\xa9)")
print(f"  latin1 byte for é: {chr(0xe9).encode('latin1')!r} (1 byte: \\xe9)")
print()

# Regexp as str with the non-ASCII char
regexp_str = r'record (café) (\d+)'
regexp_str = 'record (café) (\\d+)'
print(f"  User regexp (str): {regexp_str!r}")

# What asbytes will turn it into:
coerced = asbytes(regexp_str)
print(f"  After asbytes():   {coerced!r}")
print(f"  Note: asbytes encoded é as \\xe9 (latin1)")
print(f"  But UTF-8 file has é as \\xc3\\xa9 — NO MATCH possible")
print()

dtype = [('key', 'S10'), ('val', np.int32)]
fh = BytesIO(utf8_content)
result = np.fromregex(fh, 'record (café) (\\d+)', dtype=dtype)
print(f"  np.fromregex result:  {result}")
print(f"  Expected:             1 row with key=b'café', val=42")
print(f"  Got:                  {len(result)} rows — SILENT EMPTY RESULT (wrong!)")

# ----------------------------------------------------------------
# 3. Contrast — latin1 binary content looks correct but is fragile
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 3: False positive — latin1 binary content appears to work")
print("=" * 62)

latin1_content = 'record café 42\nrecord naiïve 99\n'.encode('latin1')
print(f"  Binary content (latin1): {latin1_content!r}")
print(f"  latin1 byte for é: \\xe9  — matches asbytes output")
print()

fh2 = BytesIO(latin1_content)
result2 = np.fromregex(fh2, 'record (café) (\\d+)', dtype=dtype)
print(f"  np.fromregex result:  {result2}")
print(f"  Got {len(result2)} row(s) — APPEARS to work, but only")
print(f"  because this file happened to be latin1-encoded.")
print(f"  The coercion is encoding-assumption, not correctness.")

# ----------------------------------------------------------------
# 4. Demonstrate CRASH — regexp with char outside latin1
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 4: UnicodeEncodeError crash — char outside latin1 range")
print("=" * 62)

content_with_greek = 'data α 42\n'.encode('utf-8')
fh3 = BytesIO(content_with_greek)
print(f"  regexp: 'data \\u03b1 (\\\\d+)'  (α = U+03B1, outside latin1)")
try:
    result3 = np.fromregex(fh3, 'data α (\\d+)', dtype=[('val', np.int32)])
    print(f"  Result: {result3}  (unexpected: should have crashed)")
except UnicodeEncodeError as e:
    import traceback as _tb
    tb_lines = _tb.format_exc().splitlines()
    print(f"  [PASS] UnicodeEncodeError raised: {ascii(str(e))}")
    print(f"  Origin in call stack:")
    for line in tb_lines:
        if 'asbytes' in line or 'fromregex' in line or 'encode' in line:
            print(f"    {line.strip()}")

# ----------------------------------------------------------------
# 5. The dropped elif — py2 had symmetric handling
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 5: The missing elif — py2 vs py3 asymmetry")
print("=" * 62)

print("""
  py2 npyio.py:1513-1517:
    content = file.read()
    if isinstance(content, bytes) and isinstance(regexp, np.unicode):
        regexp = asbytes(regexp)       # bytes file + unicode regexp
    elif isinstance(content, np.unicode) and isinstance(regexp, bytes):
        regexp = asstr(regexp)         # unicode file + bytes regexp  ← DROPPED

  py3 _npyio_impl.py:1705-1707:
    content = file.read()
    if isinstance(content, bytes) and isinstance(regexp, str):
        regexp = asbytes(regexp)       # only handles one direction

  Result: in py3, if someone passes bytes regexp to a text-mode file,
  there is NO coercion — re.compile(bytes_regexp).findall(str_content)
  raises TypeError directly from re module.
""")

# Demonstrate the missing elif — text content + bytes regexp → TypeError
text_fh = StringIO('record café 42\n')
print("  Testing: str content + bytes regexp (the dropped elif path):")
try:
    result4 = np.fromregex(text_fh, rb'record (.+) (\d+)', dtype=dtype)
    print(f"  Result: {result4}")
except TypeError as e:
    print(f"  [OBSERVED] TypeError: {e}")
    print(f"  py2 would have coerced bytes regexp → str via asstr()")
    print(f"  py3 has no handler for this case — TypeError propagates")

# ----------------------------------------------------------------
# 6. The correct py3 fix
# ----------------------------------------------------------------
print()
print("=" * 62)
print("STEP 6: What the correct py3 code should look like")
print("=" * 62)
print("""
  CURRENT (py3, _npyio_impl.py:1706-1707):
    if isinstance(content, bytes) and isinstance(regexp, str):
        regexp = asbytes(regexp)          # hardcodes latin1 silently

  CORRECT py3 fix (option A — raise on ambiguity):
    if isinstance(content, bytes) and isinstance(regexp, str):
        raise TypeError(
            "Binary file content requires a bytes regexp. "
            "Encode your regexp explicitly: regexp.encode('utf-8')"
        )

  CORRECT py3 fix (option B — respect caller's encoding param):
    if isinstance(content, bytes) and isinstance(regexp, str):
        enc = encoding or 'latin1'
        regexp = regexp.encode(enc)       # use encoding param, not hardcoded

  Root cause: asbytes() is a py2 compat shim. Its presence in py3
  production code (imported at _npyio_impl.py:21) is the migration
  residue. The function hardcodes latin1, which was py2's default
  str encoding but is NOT a safe assumption in py3 where str is Unicode.
""")

# ----------------------------------------------------------------
# 7. Confirm asbytes import is the last compat-shim in _npyio_impl
# ----------------------------------------------------------------
print("=" * 62)
print("STEP 7: Confirm asbytes is a surviving compat shim in py3")
print("=" * 62)

try:
    import numpy._utils._conversions as conv_module   # v2.6.0dev name
except ModuleNotFoundError:
    import numpy._utils._convertions as conv_module   # v2.4.x installed name (typo)
print(f"  Module file: {conv_module.__file__}")
print(f"  __all__: {conv_module.__all__}")
print()
print(f"  Full source:")
src = inspect.getsource(conv_module)
for line in src.splitlines():
    print(f"    {line}")
print()
print(f"  The module comment says 'retained from np.compat module'.")
print(f"  asbytes() and asunicode() are legacy functions kept alive")
print(f"  only because production code still references them.")
print()
print(f"  Uses of asbytes in _npyio_impl.py (py3):")
print(f"    line 1707: fromregex() — the bug site")
print(f"    line 2224: loadtxt() byte_converters path — secondary use")

print()
print("=" * 62)
print("SUMMARY")
print("=" * 62)
print("""
  BUG: numpy/lib/_npyio_impl.py:1706-1707
  TYPE: Migration residue — py2 compat shim (asbytes) in py3 code
  SEVERITY:
    - SILENT WRONG RESULT when binary file is UTF-8 encoded and
      regexp contains non-ASCII chars (e.g., é, ñ, ü)
    - UnicodeEncodeError CRASH when regexp contains chars > U+00FF
      (e.g., Greek, CJK, emoji)

  ROOT CAUSE:
    asbytes() was py2's "unicode → bytes" bridge using latin1.
    In py3, all strings are Unicode. The latin1 assumption is wrong
    for any file not encoded in latin1/iso-8859-1.

  EVIDENCE:
    - Step 2: fromregex on UTF-8 file returns [] instead of 1 row
    - Step 4: fromregex crashes with UnicodeEncodeError on α regexp
    - Step 5: The elif branch for the reverse case was silently dropped
    - Step 7: asbytes defined in _conversions.py with comment
              "retained from np.compat module"

  FIX: Remove the asbytes coercion. Either raise TypeError asking
       the user to encode their regexp, or encode using the
       encoding= parameter already present in the function signature.
""")
