"""
Bug 2 Proof: beautifulsoup.py line 579
  self.attrs = map(convert, self.attrs)

In Python 3, map() returns a lazy iterator, not a list.
Any downstream code that calls len(self.attrs) or indexes self.attrs[i]
will raise TypeError: object of type 'map' has no len()

NOTE: A second Python 3 incompatibility (Tag.__nonzero__ vs __bool__)
prevents the high-level BeautifulSoup() API from building a parse tree,
so the bug is demonstrated by instantiating Tag directly — which is
exactly the code path that line 579 runs through for EVERY parsed tag.
"""
import sys
import os

# cwd must be py3_codebase when running this script
sys.path.insert(0, os.getcwd())

from thirdparty.beautifulsoup.beautifulsoup import Tag

print("=" * 60)
print("Bug 2: beautifulsoup.py line 579")
print("  self.attrs = map(convert, self.attrs)")
print("  Returns iterator in Python 3")
print("=" * 60)
print()

# Minimal fake parser — provides the four attributes Tag.__init__ reads
class FakeParser:
    convertHTMLEntities = False
    convertXMLEntities = False
    escapeUnrecognizedEntities = True
    def isSelfClosingTag(self, name):
        return False

parser = FakeParser()
raw_attrs = [('href', 'http://example.com'), ('class', 'link')]

print(f"Input attrs (before Tag.__init__):  {raw_attrs}")
print(f"Input attrs type:                   {type(raw_attrs)}")
print()

# Instantiate a Tag — this executes line 579 internally
tag = Tag(parser, 'a', raw_attrs)

print(f"tag.attrs after Tag.__init__:       {repr(tag.attrs)}")
print(f"tag.attrs type:                     {type(tag.attrs)}")
print()

# --- Crash 1: len() on the map iterator ----------------------------
print("Test 1 — len(tag.attrs):")
try:
    n = len(tag.attrs)
    print(f"  UNEXPECTED SUCCESS: len = {n}")
except TypeError as exc:
    print(f"  CRASH (TypeError): {exc}")
print()

# --- Crash 2: indexed access (used at line 654) --------------------
# Reconstruct a fresh tag so the iterator isn't exhausted
tag2 = Tag(parser, 'a', [('href', 'http://example.com'), ('class', 'link')])
print("Test 2 — tag.attrs[0]  (used at beautifulsoup.py:654):")
try:
    first = tag2.attrs[0]
    print(f"  UNEXPECTED SUCCESS: {first!r}")
except TypeError as exc:
    print(f"  CRASH (TypeError): {exc}")
print()

# --- Crash 3: exhausted iterator on second pass --------------------
tag3 = Tag(parser, 'a', [('href', 'http://example.com'), ('class', 'link')])
print("Test 3 — second iteration yields nothing (iterator exhausted):")
first_pass  = list(tag3.attrs)
second_pass = list(tag3.attrs)
print(f"  first  list(tag.attrs) = {first_pass!r}")
print(f"  second list(tag.attrs) = {second_pass!r}  <- silently empty")
print()

# --- Root cause summary --------------------------------------------
print("Root cause (line 579):")
print("  self.attrs = map(convert, self.attrs)   # Python 3: returns iterator")
print()
print("Expected fix:")
print("  self.attrs = list(map(convert, self.attrs))")
print()
print("Done.")
