# GiPH/PRISM Migration Bug Scanner
## Python 2 → Python 3 Migration Bug Detection Tool

### What This Does
Detects Python 2 to Python 3 migration bugs using a three-stage data flow 
methodology. Finds bugs that survive migration undetected and are invisible 
to mypy, pyright, and 2to3.

### Requirements
- Python 3.8+
- git (for codebase extraction)
- Two codebases: py2_codebase (last Python 2 commit) and py3_codebase (current)

### Project Structure

### Step 1 — Clone the target project
```bash
git clone https://github.com/<org>/<project>.git py3_codebase
```

### Step 2 — Find the Python 2 last commit
```bash
cd py3_codebase
git log --oneline | grep -i "python 2\|py2\|drop python\|python3 only"
```
Identify the last commit before Python 3 only support. Then:
```bash
git clone py3_codebase ../py2_codebase
cd ../py2_codebase
git checkout <migration_commit>^
```

### Step 3 — Run the Stage 1 binary origin scan
```bash
cd py3_codebase
grep -rn "open.*['\"]rb['\"]" <project>/ --include="*.py" | grep -v test
grep -rn "\.recv(" <project>/ --include="*.py" | grep -v test
grep -rn "struct\.unpack" <project>/ --include="*.py" | grep -v test
```

### Step 4 — Run the Stage 2 pattern scan (all 40 patterns)

GROUP 1 — Bytes/str separation:
```bash
grep -rn "ord(" <project>/ --include="*.py" | grep -v test
grep -rn "chr(" <project>/ --include="*.py" | grep -v test
grep -rn "return \"\"" <project>/ --include="*.py" | grep -v test
grep -rn "encode.*latin\|decode.*latin\|latin1\|latin-1" <project>/ --include="*.py" | grep -v test
```

GROUP 2 — Removed builtins:
```bash
grep -rn "has_key\|basestring\|unicode(\|xrange\|raw_input\|reduce(" <project>/ --include="*.py" | grep -v test
grep -rn "map(\|filter(\|zip(" <project>/ --include="*.py" | grep -v test | head -20
grep -rn "\.keys()\|\.values()\|\.items()" <project>/ --include="*.py" | grep -v test | head -20
```

GROUP 3 — Integer arithmetic:
```bash
grep -rn "sys\.maxint" <project>/ --include="*.py" | grep -v test
```

GROUP 4 — Exception handling:
```bash
grep -rn "raise Exception.*," <project>/ --include="*.py" | grep -v test
grep -rn "except.*," <project>/ --include="*.py" | grep -v test | head -10
```

GROUP 5 — Import renames:
```bash
grep -rn "import urllib2\|import httplib\|import cookielib\|import StringIO\|import cPickle" <project>/ --include="*.py" | grep -v test
```

GROUP 6 — String encoding:
```bash
grep -rn "\.decode()" <project>/ --include="*.py" | grep -v test
grep -rn "encode.*latin\|decode.*latin" <project>/ --include="*.py" | grep -v test
```

GROUP 7 — Silent comparisons:
```bash
grep -rn "== \"" <project>/ --include="*.py" | grep -v test | head -20
```

### Step 5 — Stage 3: Trace each hit

For each hit from Stage 2:
1. Find the binary origin that feeds the variable (from Stage 1 output)
2. Trace every assignment from origin to the hit line by line
3. Confirm type at hit is bytes not str
4. Run grep on py2_codebase to compare

### Step 6 — Write the crash test
Save test script to analysis\test_bugN.py
Run from inside py3_codebase:
```bash
cd py3_codebase
py -3 "..\analysis\test_bugN.py" 2>&1 | tee "..\analysis\bugN_proof.txt"
```

### Step 7 — Document the finding
Required fields for every confirmed bug:
- File and line number
- ORIGIN → FLOW → SINK chain
- Test script path
- Live crash traceback
- py2 vs py3 behavioral difference

### Results So Far (10 projects)
| Project | Bugs | Key finding |
|---------|------|-------------|
| mitmproxy | 0 | Negative control — two-layer architecture |
| sqlmap | 4 | str.__iter__, map() iterator, int(bytes), str.decode() removed |
| OCRmyPDF | 1 | bytes(str) without encoding |
| scrapy | 0 | Negative control — systematic migration |
| numpy | 1 | asbytes() latin-1 residue |
| pandas | 1 | _decode() latin-1 fallback |
| DRF | 1 | Basic Auth latin-1 — security vulnerability |
| celery | 0 | Negative control — minimal shims |
| paramiko | 0 | Negative control — SSH binary surface, clean |
| requests | 0 | Negative control — RFC-compliant encoding |
