"""
Bug 1 trigger: has_key() crash in BeautifulSoup 3.2.1b on Python 3.

has_key() was removed from dict in Python 3. BS3 calls it internally
at line 1016 of beautifulsoup.py when the matchAgainst argument to
_matches() has an .items() attribute (i.e., is dict-like), which is
exactly what happens when you use soup.findAll(attrs={...}).

Execution path:
  soup.findAll(attrs={'class': 'test'})
  -> Tag.findAll()
  -> SoupStrainer.searchTag()
  -> SoupStrainer._matches()
  -> markup.has_key(matchAgainst)   # line 1016 -- AttributeError on py3
"""

import sys
import os

# Add the py3_codebase root to sys.path so thirdparty imports resolve
CODEBASE = os.path.join(os.path.dirname(__file__), '..', 'py3_codebase')
sys.path.insert(0, os.path.abspath(CODEBASE))

from thirdparty.beautifulsoup.beautifulsoup import BeautifulSoup

HTML = """
<html>
  <body>
    <div class="test">Hello</div>
    <div class="other">World</div>
    <p class="test">Paragraph</p>
  </body>
</html>
"""

print(f"Python version: {sys.version}")
print(f"BeautifulSoup location: {BeautifulSoup.__module__}")
print()

print("Step 1: Parsing HTML...")
soup = BeautifulSoup(HTML)
print("  OK - soup created")
print()

print("Step 2: soup('a') - string tag search (safe path, no dict)...")
tags = soup('a')
print(f"  OK - found {len(tags)} <a> tags (expected 0)")
print()

print("Step 3: soup.findAll(attrs={'class': 'test'}) - dict attr filter (SHOULD CRASH)...")
try:
    results = soup.findAll(attrs={'class': 'test'})
    print(f"  UNEXPECTED SUCCESS - found {len(results)} results")
    for r in results:
        print(f"    {r}")
except AttributeError as e:
    print(f"  CRASH CONFIRMED: AttributeError: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"  UNEXPECTED EXCEPTION ({type(e).__name__}): {e}")
    import traceback
    traceback.print_exc()
