"""
QEMU Migration Bug Scanner
==================================
Python 2 -> Python 3 migration bug detection using three-stage data flow analysis.

Architecture:
  Stage 1 - Binary origin identification (AST walker)
  Stage 2 - 40-pattern scan (grep-based, all 7 groups)
  Stage 3 - Intra-file taint tracking (AST backward trace from hit to origin)
           + py2_codebase comparison (CONFIRMED / CANDIDATE / FALSE_POSITIVE)

Output: structured JSON report compatible with report.py

Usage:
  python scanner.py --py3 <path> --py2 <path> --project <name> [--output <file>]

Author: Allan Kiche, QEMU Research, Carnegie Mellon University
"""

import ast
import os
import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Origin:
    file: str
    line: int
    col: int
    origin_type: str          # open_rb | socket_recv | struct_unpack | ssl_read | channel_recv
    variable: str             # variable name assigned from this origin
    code_snippet: str

@dataclass
class PatternHit:
    file: str
    line: int
    pattern_id: int
    pattern_group: int
    group_name: str
    pattern_name: str
    code_snippet: str
    classification: str = "CANDIDATE"   # CONFIRMED | CANDIDATE | FALSE_POSITIVE
    confidence: str = "LOW"             # HIGH | MEDIUM | LOW
    taint_chain: list = field(default_factory=list)
    py2_present: bool = False
    py2_snippet: str = ""
    notes: str = ""

@dataclass
class ScanResult:
    project: str
    py3_path: str
    py2_path: str
    py3_commit: str
    py2_commit: str
    total_files_scanned: int
    origins: list = field(default_factory=list)
    hits: list = field(default_factory=list)
    confirmed_bugs: list = field(default_factory=list)
    false_positives: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# THE 40 PATTERNS — all 7 groups
# ─────────────────────────────────────────────────────────────────────────────

PATTERNS = [
    # Group 1 — Bytes/str separation (8 patterns)
    {"id": 1,  "group": 1, "group_name": "Bytes/str separation",    "name": "ord() on bytes",          "regex": r"\bord\s*\("},
    {"id": 2,  "group": 1, "group_name": "Bytes/str separation",    "name": "chr() returning str",     "regex": r"\bchr\s*\("},
    {"id": 3,  "group": 1, "group_name": "Bytes/str separation",    "name": "return empty string",     "regex": r'return\s+""'},
    {"id": 4,  "group": 1, "group_name": "Bytes/str separation",    "name": "latin-1 encoding",        "regex": r"latin.?1|iso.?8859|iso8859"},
    {"id": 5,  "group": 1, "group_name": "Bytes/str separation",    "name": ".find(str) on bytes",     "regex": r'\.find\s*\(\s*["\']'},
    {"id": 6,  "group": 1, "group_name": "Bytes/str separation",    "name": ".split(str) on bytes",    "regex": r'\.split\s*\(\s*["\']'},
    {"id": 7,  "group": 1, "group_name": "Bytes/str separation",    "name": ".startswith(str)",        "regex": r'\.startswith\s*\(\s*["\']'},
    {"id": 8,  "group": 1, "group_name": "Bytes/str separation",    "name": ".endswith(str)",          "regex": r'\.endswith\s*\(\s*["\']'},

    # Group 2 — Removed or changed builtins (12 patterns)
    {"id": 9,  "group": 2, "group_name": "Removed/changed builtins","name": "has_key()",               "regex": r"\.has_key\s*\("},
    {"id": 10, "group": 2, "group_name": "Removed/changed builtins","name": "basestring",              "regex": r"\bbasestring\b"},
    {"id": 11, "group": 2, "group_name": "Removed/changed builtins","name": "unicode()",               "regex": r"\bunicode\s*\("},
    {"id": 12, "group": 2, "group_name": "Removed/changed builtins","name": "xrange()",                "regex": r"\bxrange\s*\("},
    {"id": 13, "group": 2, "group_name": "Removed/changed builtins","name": "raw_input()",             "regex": r"\braw_input\s*\("},
    {"id": 14, "group": 2, "group_name": "Removed/changed builtins","name": "reduce() builtin",        "regex": r"\breduce\s*\("},
    {"id": 15, "group": 2, "group_name": "Removed/changed builtins","name": "filter() as list",        "regex": r"\bfilter\s*\("},
    {"id": 16, "group": 2, "group_name": "Removed/changed builtins","name": "map() as list",           "regex": r"\bmap\s*\("},
    {"id": 17, "group": 2, "group_name": "Removed/changed builtins","name": "zip() as list",           "regex": r"\bzip\s*\("},
    {"id": 18, "group": 2, "group_name": "Removed/changed builtins","name": "dict.keys() as list",     "regex": r"\.keys\s*\(\s*\)"},
    {"id": 19, "group": 2, "group_name": "Removed/changed builtins","name": "dict.values() as list",   "regex": r"\.values\s*\(\s*\)"},
    {"id": 20, "group": 2, "group_name": "Removed/changed builtins","name": "dict.items() as list",    "regex": r"\.items\s*\(\s*\)"},

    # Group 3 — Integer arithmetic (2 patterns)
    {"id": 21, "group": 3, "group_name": "Integer arithmetic",       "name": "sys.maxint removed",     "regex": r"\bsys\.maxint\b"},
    {"id": 22, "group": 3, "group_name": "Integer arithmetic",       "name": "integer division /",     "regex": r"(?<![/*])/(?![/*=])"},

    # Group 4 — Exception handling (4 patterns)
    {"id": 23, "group": 4, "group_name": "Exception handling",       "name": "raise tuple",            "regex": r"\braise\s+\w+\s*\(.*,"},
    {"id": 24, "group": 4, "group_name": "Exception handling",       "name": "except X, e syntax",     "regex": r"\bexcept\s+\w+\s*,\s*\w+\s*:"},
    {"id": 25, "group": 4, "group_name": "Exception handling",       "name": "bare except",            "regex": r"except\s*:"},
    {"id": 26, "group": 4, "group_name": "Exception handling",       "name": "except Exception broad", "regex": r"except\s+Exception\s*:"},

    # Group 5 — Import renames (8 patterns)
    {"id": 27, "group": 5, "group_name": "Import renames",           "name": "import urllib2",         "regex": r"\bimport\s+urllib2\b"},
    {"id": 28, "group": 5, "group_name": "Import renames",           "name": "import httplib",         "regex": r"\bimport\s+httplib\b"},
    {"id": 29, "group": 5, "group_name": "Import renames",           "name": "import cookielib",       "regex": r"\bimport\s+cookielib\b"},
    {"id": 30, "group": 5, "group_name": "Import renames",           "name": "import StringIO",        "regex": r"\bimport\s+StringIO\b"},
    {"id": 31, "group": 5, "group_name": "Import renames",           "name": "import cPickle",         "regex": r"\bimport\s+cPickle\b"},
    {"id": 32, "group": 5, "group_name": "Import renames",           "name": "import ConfigParser",    "regex": r"\bimport\s+ConfigParser\b"},
    {"id": 33, "group": 5, "group_name": "Import renames",           "name": "import HTMLParser",      "regex": r"\bimport\s+HTMLParser\b"},
    {"id": 34, "group": 5, "group_name": "Import renames",           "name": "from __future__",        "regex": r"from\s+__future__\s+import"},

    # Group 6 — String encoding (4 patterns)
    {"id": 35, "group": 6, "group_name": "String encoding",          "name": ".decode() bare",         "regex": r"\.decode\s*\(\s*\)"},
    {"id": 36, "group": 6, "group_name": "String encoding",          "name": ".encode() bare",         "regex": r"\.encode\s*\(\s*\)"},
    {"id": 37, "group": 6, "group_name": "String encoding",          "name": "str() on bytes",         "regex": r"\bstr\s*\(\s*b['\"]"},
    {"id": 38, "group": 6, "group_name": "String encoding",          "name": "bytes() without encoding","regex": r"\bbytes\s*\(\s*['\"]"},

    # Group 7 — Silent comparison failures (2 patterns) — most dangerous
    {"id": 39, "group": 7, "group_name": "Silent comparisons",       "name": "bytes == str literal",   "regex": r'==\s*["\'][^"\']*["\']'},
    {"id": 40, "group": 7, "group_name": "Silent comparisons",       "name": "bytes != str literal",   "regex": r'!=\s*["\'][^"\']*["\']'},
]

# ─────────────────────────────────────────────────────────────────────────────
# BINARY ORIGIN SIGNATURES
# ─────────────────────────────────────────────────────────────────────────────

ORIGIN_SIGNATURES = [
    {"type": "open_rb",       "regex": r'open\s*\([^)]*["\']rb["\']'},
    {"type": "socket_recv",   "regex": r'\.recv\s*\('},
    {"type": "struct_unpack", "regex": r'\bstruct\.unpack\s*\('},
    {"type": "ssl_read",      "regex": r'ssl\b.*\.read\s*\('},
    {"type": "channel_recv",  "regex": r'channel\b.*\.recv\s*\('},
    {"type": "recvfrom",      "regex": r'\.recvfrom\s*\('},
    {"type": "read_binary",   "regex": r'\.read\s*\([^)]*\)'},
]


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — BINARY ORIGIN IDENTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def stage1_find_origins(codebase_path: str, exclude_tests: bool = True) -> list[Origin]:
    """
    Walk all Python files in codebase_path.
    Find every binary data origin — open("rb"), recv(), struct.unpack(), etc.
    Extract the variable name assigned from the origin for taint tracking.
    Returns list of Origin objects.
    """
    origins = []
    path = Path(codebase_path)

    for py_file in path.rglob("*.py"):
        if exclude_tests and ("test" in py_file.parts or "test" in py_file.name.lower()):
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
        except Exception:
            continue

        rel_path = str(py_file.relative_to(path))

        for line_num, line in enumerate(lines, 1):
            for sig in ORIGIN_SIGNATURES:
                if re.search(sig["regex"], line, re.IGNORECASE):
                    # Extract variable name from assignment if present
                    var_name = _extract_assigned_variable(line)
                    origins.append(Origin(
                        file=rel_path,
                        line=line_num,
                        col=0,
                        origin_type=sig["type"],
                        variable=var_name,
                        code_snippet=line.strip()
                    ))
                    break  # one origin type per line

    return origins


def _extract_assigned_variable(line: str) -> str:
    """
    Extract variable name from assignment lines like:
      data = socket.recv(1024)    -> 'data'
      self.content = f.read()     -> 'self.content'
      x, y = struct.unpack(...)   -> 'x'
    """
    line = line.strip()
    # simple assignment: var = ...
    m = re.match(r'^([\w\.]+)\s*=\s*', line)
    if m:
        return m.group(1)
    # tuple unpacking: a, b = ...
    m = re.match(r'^([\w]+)\s*,', line)
    if m:
        return m.group(1)
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — 40-PATTERN SCAN
# ─────────────────────────────────────────────────────────────────────────────

def stage2_pattern_scan(codebase_path: str, exclude_tests: bool = True) -> list[PatternHit]:
    """
    Run all 40 patterns against every Python file in codebase_path.
    Returns list of PatternHit objects (unclassified at this stage).
    """
    hits = []
    path = Path(codebase_path)
    compiled = [(p, re.compile(p["regex"])) for p in PATTERNS]

    for py_file in path.rglob("*.py"):
        if exclude_tests and ("test" in py_file.parts or "test" in py_file.name.lower()):
            continue

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
        except Exception:
            continue

        rel_path = str(py_file.relative_to(path))

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # skip comment lines

            for pattern, compiled_re in compiled:
                if compiled_re.search(line):
                    hits.append(PatternHit(
                        file=rel_path,
                        line=line_num,
                        pattern_id=pattern["id"],
                        pattern_group=pattern["group"],
                        group_name=pattern["group_name"],
                        pattern_name=pattern["name"],
                        code_snippet=stripped,
                    ))

    return hits


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3A — INTRA-FILE TAINT TRACKING
# ─────────────────────────────────────────────────────────────────────────────

def stage3_taint_track(hit: PatternHit, origins: list[Origin], codebase_path: str) -> tuple[str, str, list]:
    """
    For a given pattern hit, search backward in the same file for a binary origin
    that feeds the variable being used at the hit site.

    Returns: (confidence, chain_description, chain_list)
      confidence: HIGH | MEDIUM | LOW
      chain: list of {level, file, line, description}
    """
    path = Path(codebase_path)
    hit_file = path / hit.file

    try:
        source = hit_file.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
    except Exception:
        return "LOW", "Could not read file", []

    hit_line_content = lines[hit.line - 1] if hit.line <= len(lines) else ""

    # Extract the variable being used at the hit site
    hit_var = _extract_hit_variable(hit_line_content, hit.pattern_name)
    if not hit_var:
        return "LOW", "Could not identify variable at hit site", []

    # Search backward from hit line for assignments to this variable
    chain = []
    found_origin = None
    search_limit = max(0, hit.line - 200)  # look back up to 200 lines

    for line_num in range(hit.line - 1, search_limit, -1):
        line_content = lines[line_num]
        stripped = line_content.strip()

        # Check if this line assigns to our variable
        if _line_assigns_to(line_content, hit_var):
            chain.append({
                "level": f"FLOW {len(chain) + 1}",
                "file": hit.file,
                "line": line_num + 1,
                "description": stripped
            })

            # Check if this assignment comes from a binary origin
            for sig in ORIGIN_SIGNATURES:
                if re.search(sig["regex"], line_content, re.IGNORECASE):
                    found_origin = {
                        "level": "ORIGIN",
                        "file": hit.file,
                        "line": line_num + 1,
                        "origin_type": sig["type"],
                        "description": stripped
                    }
                    break

            if found_origin:
                break

            # Follow the chain: get the RHS variable to continue tracing
            new_var = _extract_rhs_variable(line_content)
            if new_var and new_var != hit_var:
                hit_var = new_var

    # Also check file-level origins for the same file
    file_origins = [o for o in origins if o.file == hit.file]

    if found_origin:
        chain.insert(0, found_origin)
        chain.append({
            "level": "SINK",
            "file": hit.file,
            "line": hit.line,
            "description": hit.code_snippet
        })
        confidence = "HIGH" if len(chain) <= 4 else "MEDIUM"
        return confidence, f"Intra-file taint chain: {len(chain)} steps", chain

    elif file_origins:
        # Origins exist in the same file — medium confidence
        nearest = min(file_origins, key=lambda o: abs(o.line - hit.line))
        chain = [
            {"level": "ORIGIN (same file)", "file": nearest.file, "line": nearest.line,
             "origin_type": nearest.origin_type, "description": nearest.code_snippet},
            {"level": "SINK", "file": hit.file, "line": hit.line, "description": hit.code_snippet}
        ]
        return "MEDIUM", f"Origin in same file ({nearest.origin_type} at line {nearest.line}), direct chain not traced", chain

    else:
        chain = [{"level": "SINK", "file": hit.file, "line": hit.line, "description": hit.code_snippet}]
        return "LOW", "No binary origin found in same file", chain


def _extract_hit_variable(line: str, pattern_name: str) -> str:
    """Extract the variable name being used at a pattern hit site."""
    # ord(var)
    m = re.search(r'\bord\s*\(\s*([\w\[\]\.]+)', line)
    if m:
        return m.group(1).split("[")[0]
    # var.decode()
    m = re.search(r'([\w\[\]\.]+)\.decode\s*\(\s*\)', line)
    if m:
        return m.group(1).split("[")[0]
    # var.encode()
    m = re.search(r'([\w\[\]\.]+)\.encode\s*\(\s*\)', line)
    if m:
        return m.group(1).split("[")[0]
    # int(var)
    m = re.search(r'\bint\s*\(\s*([\w\[\]\.]+)', line)
    if m:
        return m.group(1).split("[")[0]
    # map(func, var)
    m = re.search(r'\bmap\s*\([^,]+,\s*([\w\.]+)', line)
    if m:
        return m.group(1)
    return ""


def _line_assigns_to(line: str, varname: str) -> bool:
    """Check if a line assigns to varname."""
    if not varname or varname == "unknown":
        return False
    escaped = re.escape(varname)
    return bool(re.search(rf'^\s*{escaped}\s*=(?!=)', line) or
                re.search(rf'^\s*self\.{escaped}\s*=(?!=)', line))


def _extract_rhs_variable(line: str) -> str:
    """Extract the variable on the right-hand side of an assignment."""
    m = re.match(r'^\s*[\w\.]+\s*=\s*([\w\.]+)', line.strip())
    if m:
        return m.group(1)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3B — PY2 CODEBASE COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

def stage3_py2_compare(hit: PatternHit, py2_path: str) -> tuple[bool, str]:
    """
    Check if the same pattern hit exists in the py2_codebase.
    Returns (py2_present, py2_snippet).

    If the pattern is NOT in py2 but IS in py3 -> CONFIRMED migration bug.
    If the pattern IS in both -> CANDIDATE (behavioral difference needs manual check).
    """
    if not py2_path or not Path(py2_path).exists():
        return False, ""

    # Try the same file path in py2
    py2_file = Path(py2_path) / hit.file
    if not py2_file.exists():
        # Try stripping top-level directory differences
        parts = Path(hit.file).parts
        for i in range(len(parts)):
            candidate = Path(py2_path).joinpath(*parts[i:])
            if candidate.exists():
                py2_file = candidate
                break
        else:
            return False, ""

    try:
        lines = py2_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return False, ""

    compiled = re.compile(PATTERNS[hit.pattern_id - 1]["regex"])

    # Search ±5 lines around the same line number
    search_start = max(0, hit.line - 6)
    search_end = min(len(lines), hit.line + 5)

    for i in range(search_start, search_end):
        if compiled.search(lines[i]):
            return True, lines[i].strip()

    # Also search the whole file for the same pattern
    for i, line in enumerate(lines):
        if compiled.search(line):
            return True, f"(line {i+1}) {line.strip()}"

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFICATION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def classify_hit(hit: PatternHit, confidence: str, py2_present: bool) -> str:
    """
    Combine taint confidence and py2 comparison to produce a classification.

    CONFIRMED:      High confidence taint chain + pattern NOT in py2
    CANDIDATE:      Medium confidence OR pattern exists in both codebases
    FALSE_POSITIVE: Low confidence + no same-file origin + pattern in py2 too
    """
    # Group 5 (import renames) — if present in py3 and not in py2: always CONFIRMED
    if hit.pattern_group == 5 and not py2_present:
        return "CONFIRMED"

    # Group 7 (silent comparisons) with binary origin in same file: HIGH risk
    if hit.pattern_group == 7 and confidence in ("HIGH", "MEDIUM"):
        return "CONFIRMED" if not py2_present else "CANDIDATE"

    # High confidence taint chain traced to a binary origin
    if confidence == "HIGH":
        return "CONFIRMED" if not py2_present else "CANDIDATE"

    # Medium confidence — origin in same file but chain not fully traced
    if confidence == "MEDIUM":
        return "CANDIDATE"

    # Low confidence — no binary origin connection found
    if confidence == "LOW":
        if not py2_present and hit.pattern_group in (1, 6):
            return "CANDIDATE"   # encoding patterns without origin still worth checking
        return "FALSE_POSITIVE"

    return "CANDIDATE"


# ─────────────────────────────────────────────────────────────────────────────
# GIT UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def get_git_commit(path: str) -> str:
    """Get the current HEAD commit hash for a git repository."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=path, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def count_python_files(path: str, exclude_tests: bool = True) -> int:
    """Count Python files in a directory."""
    count = 0
    for f in Path(path).rglob("*.py"):
        if exclude_tests and ("test" in f.parts or "test" in f.name.lower()):
            continue
        count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCANNER
# ─────────────────────────────────────────────────────────────────────────────

def scan(py3_path: str, py2_path: str, project_name: str) -> ScanResult:
    """
    Run the full three-stage scan on a project.
    Returns a ScanResult with all findings.
    """
    print(f"\n{'='*60}")
    print(f"QEMU Scanner — {project_name}")
    print(f"{'='*60}")
    print(f"py3_codebase: {py3_path}")
    print(f"py2_codebase: {py2_path}")

    result = ScanResult(
        project=project_name,
        py3_path=py3_path,
        py2_path=py2_path,
        py3_commit=get_git_commit(py3_path),
        py2_commit=get_git_commit(py2_path),
        total_files_scanned=count_python_files(py3_path)
    )

    # ── Stage 1 ──────────────────────────────────────────────
    print(f"\n[Stage 1] Binary origin identification...")
    origins = stage1_find_origins(py3_path)
    result.origins = [asdict(o) for o in origins]
    print(f"  Found {len(origins)} binary origins across {len(set(o.file for o in origins))} files")

    # ── Stage 2 ──────────────────────────────────────────────
    print(f"\n[Stage 2] 40-pattern scan...")
    raw_hits = stage2_pattern_scan(py3_path)
    print(f"  Found {len(raw_hits)} raw pattern hits across all 40 patterns")

    # Group hit counts by pattern group
    group_counts = {}
    for h in raw_hits:
        group_counts[h.group_name] = group_counts.get(h.group_name, 0) + 1
    for group, count in sorted(group_counts.items()):
        print(f"    {group}: {count} hits")

    # ── Stage 3 ──────────────────────────────────────────────
    print(f"\n[Stage 3] Taint tracking + py2 comparison...")

    for hit in raw_hits:
        # 3a: intra-file taint tracking
        confidence, chain_desc, chain = stage3_taint_track(hit, origins, py3_path)
        hit.taint_chain = chain
        hit.confidence = confidence

        # 3b: py2 comparison
        py2_present, py2_snippet = stage3_py2_compare(hit, py2_path)
        hit.py2_present = py2_present
        hit.py2_snippet = py2_snippet

        # classify
        hit.classification = classify_hit(hit, confidence, py2_present)

    # ── Organise results ─────────────────────────────────────
    confirmed = [h for h in raw_hits if h.classification == "CONFIRMED"]
    candidates = [h for h in raw_hits if h.classification == "CANDIDATE"]
    false_pos  = [h for h in raw_hits if h.classification == "FALSE_POSITIVE"]

    result.hits            = [asdict(h) for h in raw_hits]
    result.confirmed_bugs  = [asdict(h) for h in confirmed]
    result.candidates      = [asdict(h) for h in candidates]
    result.false_positives = [asdict(h) for h in false_pos]

    result.stats = {
        "total_files":      result.total_files_scanned,
        "total_origins":    len(origins),
        "total_hits":       len(raw_hits),
        "confirmed":        len(confirmed),
        "candidates":       len(candidates),
        "false_positives":  len(false_pos),
        "false_positive_rate": round(len(false_pos) / max(len(raw_hits), 1) * 100, 1),
        "hit_rate_by_group": group_counts,
        "origins_by_type": _count_by_key(origins, "origin_type"),
        "confirmed_by_group": _count_by_key(confirmed, "group_name"),
    }

    # ── Summary ──────────────────────────────────────────────
    print(f"\n{'─'*40}")
    print(f"  CONFIRMED bugs:   {len(confirmed)}")
    print(f"  Candidates:       {len(candidates)}")
    print(f"  False positives:  {len(false_pos)}")
    print(f"  FP rate:          {result.stats['false_positive_rate']}%")
    print(f"{'─'*40}")

    if confirmed:
        print(f"\n  Confirmed bugs:")
        for b in confirmed:
            print(f"    [{b['group_name']}] {b['file']}:{b['line']} — {b['pattern_name']}")

    if candidates:
        print(f"\n  Candidates requiring manual investigation:")
        for c in candidates:
            print(f"    [{c['group_name']}] {c['file']}:{c['line']} — {c['pattern_name']}")

    return result


def _count_by_key(items, key: str) -> dict:
    counts = {}
    for item in items:
        val = item[key] if isinstance(item, dict) else getattr(item, key)
        counts[val] = counts.get(val, 0) + 1
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="QEMU Migration Bug Scanner — Python 2 to Python 3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scanner.py --py3 sqlmap_analysis/py3_codebase --py2 sqlmap_analysis/py2_codebase --project sqlmap
  python scanner.py --py3 pandas_analysis/py3_codebase --py2 pandas_analysis/py2_codebase --project pandas --output pandas_scan.json
        """
    )
    parser.add_argument("--py3",     required=True,  help="Path to Python 3 codebase")
    parser.add_argument("--py2",     required=True,  help="Path to Python 2 codebase")
    parser.add_argument("--project", required=True,  help="Project name")
    parser.add_argument("--output",  default=None,   help="Output JSON file (default: <project>_scan.json)")
    parser.add_argument("--include-tests", action="store_true", help="Include test files in scan")

    args = parser.parse_args()

    if not Path(args.py3).exists():
        print(f"ERROR: py3 path not found: {args.py3}", file=sys.stderr)
        sys.exit(1)

    result = scan(
        py3_path=str(Path(args.py3).resolve()),
        py2_path=str(Path(args.py2).resolve()) if Path(args.py2).exists() else "",
        project_name=args.project,
    )

    output_file = args.output or f"{args.project}_scan.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2, default=str)

    print(f"\n  Results written to: {output_file}")


if __name__ == "__main__":
    main()
