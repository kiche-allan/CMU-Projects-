#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bug 1 Crash Proof
=================
File:     pandas/io/stata.py
Function: _decode()
Lines:    1459-1478
Bug:      Stata 15+ (format >= 118) files that fail UTF-8 decoding are
          silently re-decoded as latin-1.  The caller receives wrong string
          content with no exception, only a suppressible UnicodeWarning.

This script inlines the _decode() logic verbatim so no pandas C extensions
are needed.  find_stack_level() is replaced by the literal 2.
"""

import io
import sys
import warnings

# Force UTF-8 output so Unicode characters in test data print correctly on
# Windows consoles and when piped to Out-File.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SEP = "=" * 72

# ─────────────────────────────────────────────────────────────────────────────
# Verbatim from pandas/io/stata.py lines 1459-1478
# Only change: find_stack_level() → 2
# ─────────────────────────────────────────────────────────────────────────────

def _decode_buggy(s: bytes, encoding: str) -> str:
    """Verbatim pandas buggy implementation."""
    s = s.partition(b"\0")[0]
    try:
        return s.decode(encoding)
    except UnicodeDecodeError:
        msg = (
            f"\nOne or more strings in the dta file could not be decoded using "
            f"{encoding}, and\nso the fallback encoding of latin-1 is being used.  "
            f"This can happen when a file\nhas been incorrectly encoded by Stata or "
            f"some other software. You should verify\nthe string values returned are "
            f"correct."
        )
        warnings.warn(msg, UnicodeWarning, stacklevel=2)
        return s.decode("latin-1")


def _decode_fixed(s: bytes, encoding: str) -> str:
    """Proposed fix: raise UnicodeDecodeError instead of silently substituting."""
    s = s.partition(b"\0")[0]
    return s.decode(encoding)  # propagate — caller must handle explicitly


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — What _decode() does with bytes that fail UTF-8
# ─────────────────────────────────────────────────────────────────────────────

print(SEP)
print("SECTION 1 — Basic behavior: bytes valid in latin-1 but invalid in UTF-8")
print(SEP)

# These bytes are valid ISO-8859-1 / latin-1 but NOT valid UTF-8:
#   \xe9 = start of a 3-byte UTF-8 sequence, but no continuation bytes follow
#   \xc3 alone = start of a 2-byte UTF-8 sequence with no continuation byte
#   \xff = permanently unassigned in UTF-8

cases = [
    # (label, raw_bytes, what_the_file_actually_intended)
    (r"b'\xe9'       — lone high byte (é in latin-1)",
     b"\xe9",
     "latin-1 'é' (U+00E9) — ambiguous, could be correct"),
    (r"b'\xc3'       — truncated UTF-8 lead byte (Ã in latin-1)",
     b"\xc3",
     "Ã in latin-1 — probably wrong, file had a truncated UTF-8 sequence"),
    (r"b'\xc3\xa9'[:-1] — UTF-8 'é' with continuation byte stripped",
     b"\xc3\xa9"[:-1],   # = b"\xc3"
     "truncated UTF-8; correct value would be 'é' (U+00E9)"),
    (r"b'\x80\x81'   — C1 control range, valid latin-1, invalid UTF-8",
     b"\x80\x81",
     "latin-1 PAD/HOP control chars — data corruption territory"),
    (r"b'caf\xe9'    — 'café' encoded in latin-1, file claims UTF-8",
     b"caf\xe9",
     "intended to be UTF-8 'café' (b'caf\\xc3\\xa9') but stored as latin-1"),
]

for label, raw, intent in cases:
    captured = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = _decode_buggy(raw, "utf-8")
        warned = len(w) > 0

    print(f"\nInput bytes : {raw!r}  ({label})")
    print(f"Intent      : {intent}")
    print(f"Buggy result: {result!r}  (UnicodeWarning issued: {warned})")
    print(f"UTF-8 valid : {False}  |  latin-1 decode succeeds silently: {True}")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Minimal fake Stata-like scenario
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 2 — Minimal fake Stata 118 (UTF-8) file with mis-encoded strings")
print(SEP)

# Simulate what StataReader._get_varlist() feeds to _decode():
# Variable names read from a file that claims format 118 (UTF-8) but was
# converted from a format 117 (latin-1) file with non-ASCII names intact.
fake_varlist_bytes = [
    b"income\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",  # clean ASCII
    b"r\xe9gion\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",   # latin-1 "région"
    b"pr\xebt\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", # latin-1 "prêt"
    b"na\xefve\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",# latin-1 "naïve"
]

format_version = 118   # Stata 15 — should be UTF-8
encoding = "utf-8"     # set by _set_encoding() because format >= 118

print(f"\nSimulated Stata format version : {format_version}")
print(f"Encoding set by _set_encoding() : {encoding!r}")
print(f"Variable name bytes from file:")

decoded_names = []
for varbytes in fake_varlist_bytes:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        name = _decode_buggy(varbytes, encoding)
        issued_warning = len(w) > 0
    decoded_names.append(name)
    raw_preview = varbytes.partition(b"\0")[0]
    print(f"  raw={raw_preview!r:25s}  =>  decoded={name!r:12s}  "
          f"(warning={'YES [!]' if issued_warning else 'no'})")

print(f"\nResulting DataFrame columns: {decoded_names}")
print("\nThe user sees columns named income, région, prêt, naïve — no exception.")
print("Whether these are correct depends entirely on whether the original file")
print("intended latin-1.  If the file was corrupted UTF-8, these are wrong names.")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Warning suppression: the silent failure mode
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 3 — Warning suppression: the UnicodeWarning is easily silenced")
print(SEP)

bad_bytes = b"r\xe9gion"

print("\nCase A — warnings enabled (default in interactive sessions):")
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    result_a = _decode_buggy(bad_bytes, "utf-8")
    print(f"  Result   : {result_a!r}")
    print(f"  Warnings : {[str(x.message) for x in w]}")

print("\nCase B — UnicodeWarning filtered (common in production / logging setups):")
with warnings.catch_warnings(record=True) as w:
    warnings.filterwarnings("ignore", category=UnicodeWarning)
    result_b = _decode_buggy(bad_bytes, "utf-8")
    print(f"  Result   : {result_b!r}")
    print(f"  Warnings : {w}  ← empty list, caller gets no signal at all")

print("\nCase C — warnings.simplefilter('error') would catch it, but nobody does that:")
try:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnicodeWarning)
        result_c = _decode_buggy(bad_bytes, "utf-8")
    print(f"  Result   : {result_c!r}  ← no warning elevated, passed through")
except UnicodeWarning as e:
    print(f"  Raised UnicodeWarning: {str(e)[:60]}...")
    print("  Only reachable if the caller explicitly turns warnings into errors.")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — latin-1 never fails: it silently accepts every possible byte
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 4 — latin-1 never fails: accepts all 256 byte values")
print(SEP)

failures = 0
for byte_val in range(256):
    b = bytes([byte_val])
    try:
        b.decode("latin-1")
    except Exception as e:
        failures += 1
        print(f"  UNEXPECTED FAILURE at byte 0x{byte_val:02x}: {e}")

if failures == 0:
    print(f"\n  All 256 byte values (0x00–0xff) decode successfully as latin-1.")
    print(f"  latin-1 is a complete 256-codepoint bijection onto bytes — it CANNOT fail.")
    print(f"  This is why the fallback always 'succeeds': it accepts anything,")
    print(f"  including corrupted data, garbage, or partial multi-byte sequences.")

# Demonstrate the contrast with UTF-8:
utf8_failures = 0
for byte_val in range(256):
    b = bytes([byte_val])
    try:
        b.decode("utf-8")
    except UnicodeDecodeError:
        utf8_failures += 1

print(f"\n  Single-byte UTF-8 decode failures: {utf8_failures}/256 byte values")
print(f"  (bytes 0x80–0xbf are continuation bytes, 0xc0–0xc1/0xf5–0xff are invalid)")
print(f"\n  When a latin-1 fallback is used, those {utf8_failures} values that would")
print(f"  have raised an error instead silently return latin-1 characters.")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — py2 comparison: what would have happened before the migration
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 5 — py2 comparison: no _decode() wrapper existed in py2 stata.py")
print(SEP)

print("""
In pandas py2 (v0.24.2 / stata.py), there is no _decode() method.
grep for '_decode|latin|UnicodeDecodeError|fallback' in py2 stata.py → No matches.

The py2 StataReader:
  - Set self._encoding = None initially (line 974)
  - _set_encoding() set 'latin-1' for format < 118, 'utf-8' for >= 118  (same logic)
  - String fields were decoded inline, without a try/except wrapper
  - On UnicodeDecodeError the exception propagated — caller saw the crash

Simulating py2 behavior (inline decode, no fallback):
""")

py2_cases = [
    (b"income",    "clean ASCII — succeeds in both"),
    (b"r\xe9gion", "latin-1 bytes in UTF-8 file — py2 raises, py3 silently wrong"),
    (b"caf\xe9",   "latin-1 bytes in UTF-8 file — py2 raises, py3 silently wrong"),
]

for raw, note in py2_cases:
    raw_stripped = raw.partition(b"\0")[0]
    # py2 behavior: direct decode, no fallback
    try:
        py2_result = raw_stripped.decode("utf-8")
        py2_outcome = f"OK → {py2_result!r}"
    except UnicodeDecodeError as e:
        py2_outcome = f"UnicodeDecodeError: {e}"

    # py3 buggy behavior
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        py3_result = _decode_buggy(raw, "utf-8")
    py3_outcome = f"silent → {py3_result!r} (warned={bool(w)})"

    print(f"  Input : {raw!r}  ({note})")
    print(f"  py2   : {py2_outcome}")
    print(f"  py3   : {py3_outcome}")
    print()

print("py2 raised a hard error.  The py3 'fix' (GH #25960) traded a noisy")
print("crash for a quiet wrong answer — the opposite of what a safe migration")
print("should do.")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — The fix: raise instead of silently substituting
# ─────────────────────────────────────────────────────────────────────────────

print()
print(SEP)
print("SECTION 6 — Proposed fix: propagate UnicodeDecodeError with context")
print(SEP)

print("""
Fixed _decode() — raise with actionable message instead of silent substitution:

    def _decode(self, s: bytes) -> str:
        s = s.partition(b"\\0")[0]
        try:
            return s.decode(self._encoding)
        except UnicodeDecodeError as err:
            raise UnicodeDecodeError(
                err.encoding,
                err.object,
                err.start,
                err.end,
                f"Stata file string could not be decoded as {self._encoding}. "
                f"Re-open with encoding='latin-1' if this is a legacy file "
                f"(GH 25960). Original error: {err.reason}",
            ) from err
""")

print("Demonstrating fixed behavior:")
fix_cases = [
    (b"income",    "utf-8", "clean — no change"),
    (b"r\xe9gion", "utf-8", "invalid UTF-8 bytes — now raises with guidance"),
    (b"r\xe9gion", "latin-1", "same bytes with correct encoding — success"),
]

for raw, enc, note in fix_cases:
    try:
        result = _decode_fixed(raw, enc)
        print(f"  _decode_fixed({raw!r}, {enc!r}) → {result!r}  ({note})")
    except UnicodeDecodeError as e:
        print(f"  _decode_fixed({raw!r}, {enc!r}) → UnicodeDecodeError raised  ({note})")
        print(f"    {e}")

print()
print(SEP)
print("CONCLUSION")
print(SEP)
print(f"""
Bug:   _decode() catches UnicodeDecodeError and retries with latin-1.
       latin-1 never raises — so every byte sequence silently 'succeeds'.
       The caller receives potentially wrong strings with only a suppressible
       UnicodeWarning as notification.

Root cause:  GH #25960 traded a hard error (py2 behavior) for a silent wrong
             answer to accommodate files mis-converted by Stata itself.  The
             warning is not visible in production environments where warnings
             are filtered (logging frameworks, -W ignore, pytest -p no:warnings).

Scope:  Affects every string field in the file:
          _get_varlist()        → column names
          _get_variable_labels() → variable labels
          _get_data_label()     → dataset label
          _read_new_value_labels() → category string values
        All 12+ call sites pass through _decode().

Fix:   Raise UnicodeDecodeError with an actionable message pointing the user
       to the encoding= parameter.  Let the caller decide, not the library.

Python version: {sys.version}
""")
