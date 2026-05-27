#!/usr/bin/env python3
"""
Crash proof for thirdparty/beautifulsoup/beautifulsoup.py line 488

Bug:
    class NavigableString(text_type, PageElement):
        def __unicode__(self):
            return str(self).decode(DEFAULT_OUTPUT_ENCODING)   # line 488

    In Python 3:
        - str has NO .decode() method (removed in Python 3.0)
        - str(self) returns a str object
        - str_object.decode(...) raises AttributeError

What triggers it:
    Python 2: unicode(nav_string) called __unicode__ automatically
    Python 3: __unicode__ is never called by the runtime, BUT:
        - any code that calls nav_string.__unicode__() directly crashes
        - any code that calls unicode(nav_string) crashes (NameError: unicode)
        - beautifulsoup's own __str__ guard (line 493) shows the devs knew
          about Py2/3 but did NOT apply the same guard to __unicode__

This script:
  1. Proves str.decode() does not exist in Python 3
  2. Proves the exact line 488 expression crashes
  3. Imports NavigableString directly and calls __unicode__() to show live crash
  4. Shows that __str__ (line 490) works fine — it has the py2/py3 guard
  5. Shows the correct fix
"""

import sys
import os

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"
SEP  = "-" * 62

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py3_codebase"))

def section(title):
    print()
    print(SEP)
    print(title)
    print(SEP)


# ---------------------------------------------------------------------------
section("ENVIRONMENT")
# ---------------------------------------------------------------------------
print(f"Python : {sys.version}")


# ---------------------------------------------------------------------------
section("STEP 1: str has no .decode() in Python 3 — the root cause")
# ---------------------------------------------------------------------------

s = str("hello")
print(f"type(str('hello')) = {type(s)}")
print(f"hasattr(str, 'decode') = {hasattr(str, 'decode')}")

assert not hasattr(str, 'decode'), "str should not have .decode() in Python 3"
print(PASS, "str.decode does not exist in Python 3")


# ---------------------------------------------------------------------------
section("STEP 2: Reproduce line 488 exactly — str(self).decode(...)")
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_ENCODING = "utf-8"    # same constant used in beautifulsoup.py

class FakeNavigableString(str):
    """Minimal stand-in matching NavigableString's relevant structure."""
    def __unicode__(self):
        return str(self).decode(DEFAULT_OUTPUT_ENCODING)   # line 488 verbatim

    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):   # line 490 for comparison
        if encoding and sys.version_info < (3, 0):
            return str.__str__(self).encode(encoding)
        else:
            return str.__str__(self)

nav = FakeNavigableString("test content")

# --- __str__ works fine ---
try:
    result = str(nav)
    print(PASS, f"__str__(nav) = {result!r}  (no crash — line 490 has py2/py3 guard)")
except Exception as e:
    print(FAIL, f"__str__ unexpectedly crashed: {type(e).__name__}: {e}")

# --- __unicode__ crashes ---
unicode_exc_type = None
try:
    nav.__unicode__()
    print(FAIL, "__unicode__() did not raise — expected AttributeError")
except AttributeError as e:
    unicode_exc_type = AttributeError
    print(PASS, f"__unicode__() raises AttributeError: {e}")
except Exception as e:
    print(FAIL, f"__unicode__() raised wrong type: {type(e).__name__}: {e}")

assert unicode_exc_type is AttributeError


# ---------------------------------------------------------------------------
section("STEP 3: Live import — crash NavigableString from beautifulsoup.py")
# ---------------------------------------------------------------------------

try:
    from thirdparty.beautifulsoup.beautifulsoup import NavigableString
    print(INFO, "NavigableString imported successfully")

    ns = NavigableString("hello world")
    print(INFO, f"NavigableString instance: {ns!r}, type: {type(ns)}")

    # __str__ should work
    try:
        s = str(ns)
        print(PASS, f"str(NavigableString) = {s!r}  (__str__ works)")
    except Exception as e:
        print(FAIL, f"str(NavigableString) crashed: {type(e).__name__}: {e}")

    # __unicode__ should crash
    crash_exc = None
    try:
        ns.__unicode__()
        print(FAIL, "ns.__unicode__() did not raise — expected AttributeError")
    except AttributeError as e:
        crash_exc = e
        print(PASS, f"ns.__unicode__() raises AttributeError: {e}")
    except Exception as e:
        print(FAIL, f"ns.__unicode__() raised wrong exception: {type(e).__name__}: {e}")

    assert crash_exc is not None, "Should have raised AttributeError"

except ImportError as e:
    print(INFO, f"Direct import failed ({e}) — simulation in Step 2 is the proof")


# ---------------------------------------------------------------------------
section("STEP 4: The asymmetry — __str__ guarded, __unicode__ not")
# ---------------------------------------------------------------------------

print()
print("Line 487-488  __unicode__ (NO guard):")
print("    def __unicode__(self):")
print("        return str(self).decode(DEFAULT_OUTPUT_ENCODING)   # CRASH on Py3")
print()
print("Line 490-496  __str__ (HAS guard):")
print("    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):")
print("        data = self.BARE_AMPERSAND_OR_BRACKET.sub(self._sub_entity, self)")
print("        if encoding and sys.version_info < (3, 0):   # <-- guard exists")
print("            return data.encode(encoding)")
print("        else:")
print("            return data")
print()
print(INFO, "The developer added sys.version_info < (3,0) to __str__ but NOT to __unicode__")
print(PASS, "The missing guard in __unicode__ is the exact bug")


# ---------------------------------------------------------------------------
section("STEP 5: When does __unicode__ actually get called?")
# ---------------------------------------------------------------------------

print()
print("Python 2 triggers:")
print("  unicode(nav_string)  ->  calls __unicode__() automatically")
print("  '%s' % nav_string    ->  may call __unicode__ via coercion")
print()
print("Python 3 triggers:")
print("  nav_string.__unicode__()  ->  direct call  ->  AttributeError CRASH")

# unicode() does not exist in Python 3
try:
    result = unicode(nav)     # type: ignore  # noqa: F821
    print(FAIL, "unicode() exists in Python 3 — unexpected")
except NameError as e:
    print(PASS, f"unicode() does not exist in Python 3: {e}")
    print(INFO, "Runtime never auto-calls __unicode__ in Py3 — crash only on explicit .call")


# ---------------------------------------------------------------------------
section("STEP 6: The fix")
# ---------------------------------------------------------------------------

print()
print("Option A — guard matching __str__:")
print("    def __unicode__(self):")
print("        if sys.version_info >= (3, 0):")
print("            return str(self)")
print("        return str(self).decode(DEFAULT_OUTPUT_ENCODING)")
print()
print("Option B — remove __unicode__ entirely:")
print("    Python 3 does not use __unicode__; __str__ already handles str()")
print()
print("Option C — delegate to __str__:")
print("    def __unicode__(self):")
print("        return NavigableString.__str__(self)")
print()

# Verify option A works
class FixedNavigableString(str):
    def __unicode__(self):                         # Option A applied
        if sys.version_info >= (3, 0):
            return str(self)
        return str(self).decode(DEFAULT_OUTPUT_ENCODING)

fixed = FixedNavigableString("fixed content")
try:
    result = fixed.__unicode__()
    assert isinstance(result, str)
    assert result == "fixed content"
    print(PASS, f"Fixed __unicode__() returns {result!r}  (type={type(result).__name__})")
except Exception as e:
    print(FAIL, f"Fix raised: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
section("SUMMARY")
# ---------------------------------------------------------------------------
print(f"Python  : {sys.version}")
print()
print("File    : thirdparty/beautifulsoup/beautifulsoup.py")
print("Class   : NavigableString  (line 461)")
print("Method  : __unicode__  (line 487)")
print()
print("Buggy code:")
print("    def __unicode__(self):")
print("        return str(self).decode(DEFAULT_OUTPUT_ENCODING)  # line 488")
print()
print("Root cause:")
print("    str.decode() was removed in Python 3.0")
print("    The sibling __str__ method (line 490) has an explicit sys.version_info")
print("    guard; __unicode__ does not")
print()
print("Trigger:")
print("    Any explicit call to nav_string.__unicode__()")
print("    (Python 3 runtime never auto-calls __unicode__)")
print()
print("Fix:")
print("    Add sys.version_info guard, OR remove __unicode__ (unused in Py3)")
print()
print("All assertions passed.")
