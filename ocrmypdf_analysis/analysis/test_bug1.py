"""
Bug 1 Proof: src/ocrmypdf/_metadata.py lines 88-89

  for k, v in pdf.docinfo.items():
      if isinstance(v, str) and b'\\x00' in bytes(v):       # line 88
          pdf.docinfo[k] = bytes(v).replace(b'\\x00', b'')  # line 89

TWO Python 3 defects on these two lines:

  (A) bytes(str_value) in Python 3 requires an encoding argument;
      it raises TypeError: string argument without an encoding.
      The except TypeError on line 91 silently swallows this crash
      and the function returns False — NUL is never removed.

  (B) With pikepdf >= ~8, pdf.docinfo.items() yields pikepdf.Object,
      not Python str, so isinstance(v, str) is False and the body
      is never entered at all.  Both defects cause silent data loss.

We inline repair_docinfo_nuls verbatim so the test has no dependency
on ocrmypdf's heavyweight import chain.
"""
import sys
import os
import logging

# pikepdf installed in the sqlmap venv's site-packages
_SQLMAP_SITE = os.path.normpath(
    os.path.join(
        os.path.abspath(__file__),
        '..', '..', '..',
        'sqlmap_analysis', 'py3_codebase', 'Lib', 'site-packages',
    )
)
if os.path.isdir(_SQLMAP_SITE) and _SQLMAP_SITE not in sys.path:
    sys.path.insert(0, _SQLMAP_SITE)

import pikepdf
from pikepdf import Dictionary, Pdf, String

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='  [%(levelname)s] %(message)s')


# ── verbatim copy of repair_docinfo_nuls from _metadata.py lines 78-94 ──
def repair_docinfo_nuls(pdf):
    """If the DocumentInfo block contains NUL characters, remove them."""
    modified = False
    try:
        if not isinstance(pdf.docinfo, Dictionary):
            raise TypeError("DocumentInfo is not a dictionary")
        for k, v in pdf.docinfo.items():
            if isinstance(v, str) and b'\x00' in bytes(v):        # line 88
                pdf.docinfo[k] = bytes(v).replace(b'\x00', b'')   # line 89
                modified = True
    except TypeError:
        log.error("File contains a malformed DocumentInfo block - continuing anyway.")
    return modified
# ─────────────────────────────────────────────────────────────────────────


print("=" * 60)
print("Bug 1: _metadata.py lines 88-89")
print("  bytes(v) on str raises TypeError in Python 3")
print("=" * 60)
print()

# ── Step 1: show bytes(str) crashes in Python 3 ──────────────────────────
v_str = "Hello\x00World"
print(f"Step 1 — bytes(str_value) in Python 3:")
print(f"  value = {v_str!r}")
try:
    result = bytes(v_str)
    print(f"  UNEXPECTED SUCCESS: {result!r}")
except TypeError as exc:
    print(f"  CRASH (TypeError): {exc}")
print()

# ── Step 2: build an in-memory PDF with a NUL in docinfo ─────────────────
pdf = Pdf.new()
pdf.docinfo['/Title'] = String("Hello\x00World")
pdf.docinfo['/Author'] = String("Clean Author")

raw = pdf.docinfo.get('/Title')
print(f"Step 2 — pdf.docinfo['/Title']:")
print(f"  value        = {str(raw)!r}")
print(f"  Python type  = {type(raw)}")
print(f"  isinstance(v, str) = {isinstance(raw, str)}")
print()

# ── Step 3: call repair_docinfo_nuls — expect False ──────────────────────
print("Step 3 — calling repair_docinfo_nuls(pdf):")
result = repair_docinfo_nuls(pdf)
print()
print(f"  Return value: {result!r}")
after = str(pdf.docinfo.get('/Title', ''))
print(f"  pdf.docinfo['/Title'] after call: {after!r}")
nul_still_present = '\x00' in after
print(f"  NUL byte still present: {nul_still_present}")
print()

if result is False:
    print("RESULT: BUG CONFIRMED")
    print("  repair_docinfo_nuls returned False — NUL was NOT removed.")
    if not isinstance(raw, str):
        print("  Defect B: isinstance(v, str) is False for pikepdf.Object,")
        print("    so the body is never entered.")
    else:
        print("  Defect A: bytes(v) raised TypeError, caught silently.")
else:
    print("RESULT: function returned True — NUL removed (bug not present).")
print()

# ── Step 4: show Defect A in isolation with a plain Python str ───────────
print("Step 4 — demonstrate Defect A with a plain Python str value:")
print("  (simulates older pikepdf that returned str from docinfo.items())")
print()

pdf2 = Pdf.new()
# Bypass pikepdf by patching: iterate items as plain Python str pairs
class PatchedDocinfo:
    """Mimics pdf.docinfo.items() returning plain Python str values."""
    def __init__(self, real):
        self._real = real
    def __instancecheck__(self, instance):
        return True
    def items(self):
        for k, v in self._real.items():
            yield k, str(v)           # coerce to plain str — as older pikepdf did

pdf2.docinfo['/Title'] = String("NUL\x00Here")

# Inline the logic manually with str values to trigger bytes(str)
v_plain = str(pdf2.docinfo.get('/Title'))
print(f"  v_plain = {v_plain!r}  type={type(v_plain)}")
print(f"  isinstance(v_plain, str) = {isinstance(v_plain, str)}")
print(f"  Calling: bytes(v_plain)...")
try:
    b = bytes(v_plain)
    print(f"  UNEXPECTED SUCCESS: {b!r}")
except TypeError as exc:
    print(f"  CRASH (TypeError): {exc}")
    print()
    print("  This TypeError is caught by except TypeError at line 91,")
    print("  so repair_docinfo_nuls logs an error and returns False.")
print()

# ── Step 5: show the fix ─────────────────────────────────────────────────
print("Root cause (lines 88-89):")
print("  bytes(v)  — Python 3 requires an encoding; bytes(str) raises TypeError")
print()
print("Expected fix:")
print("  if isinstance(v, (str, pikepdf.String)):")
print("      s = str(v)")
print("      if '\\x00' in s:")
print("          pdf.docinfo[k] = s.replace('\\x00', '')")
print("          modified = True")
print()
print("Done.")
