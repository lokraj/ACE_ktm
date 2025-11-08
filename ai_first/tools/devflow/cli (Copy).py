#!/usr/bin/env python3
# DevFlow: Jira ↔ Amazon Q ↔ Tests automation

from __future__ import annotations
import re
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

import typer
import requests
from dotenv import load_dotenv
import xml.etree.ElementTree as ET

app = typer.Typer(help="DevFlow CLI: prepare, codegen, test, and post to Jira")

# ---------- config ----------
ROOT = Path(os.getenv("REPO_ABS_PATH") or Path.cwd()).resolve()
QDIR = ROOT / ".q"
TEMPLATES = Path(__file__).resolve().parents[0] / "templates"  # reserved for future use

load_dotenv(ROOT / ".env")
JIRA_BASE = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_TOKEN = os.getenv("JIRA_API_TOKEN", "")
GIT_REMOTE = os.getenv("GIT_REMOTE", "origin")
BASE_BRANCH = os.getenv("BASE_BRANCH", "main")
MAX_JIRA_COMMENT = 24000  # lower to account for ADF overhead and avoid CONTENT_LIMIT_EXCEEDED

# ---------- helpers ----------

def ensure_env() -> None:
    problems = []
    if not JIRA_BASE:
        problems.append("JIRA_BASE_URL")
    if not JIRA_EMAIL:
        problems.append("JIRA_EMAIL")
    if not JIRA_TOKEN:
        problems.append("JIRA_API_TOKEN")
    if problems:
        typer.secho(
            "Missing env vars: " + ", ".join(problems) + ". Put them in .env",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

def ensure_dirs() -> None:
    QDIR.mkdir(exist_ok=True)

def run(cmd: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )

def have(cmd_name: str) -> bool:
    return shutil.which(cmd_name) is not None

# Cleanup helper for pytest import/collection issues
# Removes .pytest_cache, __pycache__ folders, and *.pyc files under the repo
# Call this before/after test runs to avoid 'import file mismatch' errors

def _cleanup_pytest_artifacts(root: Path) -> None:
    cache = root / ".pytest_cache"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    for d in root.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        try:
            pyc.unlink()
        except Exception:
            pass

def strip_ansi(text: str) -> str:
    """Remove ANSI color codes to reduce Jira comment size/complexity."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")

def jira_req(method: str, path: str, **kw) -> requests.Response:
    ensure_env()
    url = f"{JIRA_BASE}{path}"
    kw.setdefault("auth", (JIRA_EMAIL, JIRA_TOKEN))
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if "headers" in kw:
        headers.update(kw["headers"])
    kw["headers"] = headers
    r = requests.request(method, url, **kw)
    if r.status_code >= 300:
        raise RuntimeError(f"Jira {method} {path} -> {r.status_code}: {r.text[:500]}")
    return r

def jira_get_issue(key: str) -> dict:
    r = jira_req("GET", f"/rest/api/3/issue/{key}?expand=renderedFields")
    return r.json()

def jira_comment(key: str, body_md: str) -> None:
    # Strip ANSI and chunk conservatively
    body_md = strip_ansi(body_md)
    payload_limit = MAX_JIRA_COMMENT
    start = 0
    i = 1
    n = len(body_md)
    while start < n:
        chunk = body_md[start:start + payload_limit]
        start += len(chunk)
        # Post as plain Markdown body to minimize ADF complexity
        jira_req("POST", f"/rest/api/3/issue/{key}/comment", json={"body": chunk})
        i += 1

# top-level helpers
def write_debug_issue(issue_key: str, payload: dict) -> Path:
    ensure_dirs()
    p = QDIR / f"{issue_key}.issue.json"
    import json
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return p
def _split_keys(envvar: str) -> list[str]:
    v = os.getenv(envvar, "")
    return [s.strip() for s in v.split(",") if s.strip()]

# ---- description section parsing (Acceptance Criteria / Test Cases) ----
SECTION_HEADINGS = {
    "acceptance": [r"acceptance\s*criteria?", r"\bAC\b"],
    "tests": [r"test\s*cases?", r"\btests?\b"],
}

# Also support inline tokens without headings (e.g., "User Story...Acceptance CriteriaForm Fields...")
INLINE_TOKENS = [
    ("acceptance", re.compile(r"acceptance\s*criteria", re.IGNORECASE)),
    ("tests", re.compile(r"test\s*cases", re.IGNORECASE)),
]

def _extract_section(text: str, keys: list[str]) -> str:
    if not text:
        return ""
    heads = [rf"(?:^|\n)\s*#{{1,6}}\s*({h})\s*[:\-]*\s*\n" for h in keys] + \
            [rf"(?:^|\n)\s*({h})\s*[:\-]*\s*\n" for h in keys]
    sep = r"|".join(heads)
    matches = list(re.finditer(sep, text, flags=re.IGNORECASE))
    if matches:
        start = matches[0].end()
        # Only consider markdown headings (#) as the next section delimiter
        next_head = re.search(r"(?:^|\n)\s*#\s*\w+", text[start:], flags=re.IGNORECASE)
        end = start + (next_head.start() if next_head else len(text[start:]))
        return text[start:end].strip()
    # Inline fallback: find token position and slice until next token or end
    lowers = text
    positions = {}
    for key, pat in INLINE_TOKENS:
        m = pat.search(lowers)
        if m:
            positions[key] = m.start()
    # if current key found
    want_keys = [k for k in SECTION_HEADINGS if SECTION_HEADINGS[k] == keys]
    # derive desired key name via first pattern match
    desired = None
    for k, pats in SECTION_HEADINGS.items():
        if keys == pats:
            desired = k
            break
    if desired and desired in positions:
        start = positions[desired]
        # find next token after start
        after = [pos for (k,pos) in positions.items() if pos > start]
        end = min(after) if after else len(lowers)
        return text[start:end].split("\n",1)[-1].strip()  # drop token label line if any
    return ""

def parse_sections_from_description(desc_text: str) -> dict:
    acceptance = _extract_section(desc_text, SECTION_HEADINGS["acceptance"])
    tests = _extract_section(desc_text, SECTION_HEADINGS["tests"])
    return {"acceptance_from_desc": acceptance, "tests_from_desc": tests}

# update extract_fields to try custom fields, else fallback to parsed sections
def extract_fields(issue: dict) -> dict:
    f = issue.get("fields", {})
    summary = (f.get("summary") or "").strip()
    desc = f.get("description")
    description = flatten_adf(desc) if isinstance(desc, (dict, list)) else (desc or "")
    issue_type = (f.get("issuetype", {}) or {}).get("name", "task")

    # env-configurable custom fields
    def _split_keys(envvar: str) -> list[str]:
        v = os.getenv(envvar, "")
        return [s.strip() for s in v.split(",") if s.strip()]

    ac_keys = _split_keys("ACCEPTANCE_FIELD_KEYS")
    tc_keys = _split_keys("TESTS_FIELD_KEYS")

    acceptance = ""
    tests = ""

    for k in ac_keys:
        if k in f:
            v = f[k]
            acceptance = flatten_adf(v) if isinstance(v, (dict, list)) else (v or "")
            break
    for k in tc_keys:
        if k in f:
            v = f[k]
            tests = flatten_adf(v) if isinstance(v, (dict, list)) else (v or "")
            break

    # heuristic fallback on field names
    if not acceptance:
        for k, v in f.items():
            lk = str(k).lower()
            if "acceptance" in lk or lk.endswith("criteria"):
                acceptance = flatten_adf(v) if isinstance(v, (dict, list)) else (v or "")
                if acceptance: break
    if not tests:
        for k, v in f.items():
            lk = str(k).lower()
            if "test case" in lk or "testcases" in lk or lk.endswith("tests"):
                tests = flatten_adf(v) if isinstance(v, (dict, list)) else (v or "")
                if tests: break

    # parse from description if still empty
    if not acceptance or not tests:
        parsed = parse_sections_from_description(description)
        if not acceptance and parsed["acceptance_from_desc"]:
            acceptance = parsed["acceptance_from_desc"]
        if not tests and parsed["tests_from_desc"]:
            tests = parsed["tests_from_desc"]

    return {
        "summary": summary,
        "description": description,
        "acceptance": acceptance,
        "tests": tests,
        "type": issue_type,
    }



def _junit_counts(junit_path: Path) -> dict:
    if not junit_path.exists():
        return {}
    root = ET.fromstring(junit_path.read_text())
    # handle <testsuite> or <testsuites>
    suites = root.findall("testsuite") or root.findall(".//testsuite")
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for s in suites:
        for k in totals:
            totals[k] += int(s.attrib.get(k, 0))
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return totals

def run_pytests(issue_key: str, report_path: Path) -> int:
    junit_path = QDIR / f"{issue_key}.junit.xml"
    # verbose, show all reports, do not stop early, include durations, clear cache
    cmd = [
        "pytest",
        "-vv",
        "-rA",
        "--maxfail=0",
        "--color=no",
        "--durations=10",
        "--cache-clear",
        f"--junitxml={junit_path}",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # First attempt
    r = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, check=False, env=env)
    ts = datetime.now().isoformat(timespec="seconds")
    totals, cases = _junit_parse(junit_path)

    # If collection/import mismatch, heal and retry once
    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    if (r.returncode != 0) and ("import file mismatch" in combined or "collected 0 items" in combined):
        _cleanup_pytest_artifacts(ROOT)
        r = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, check=False, env=env)
        totals, cases = _junit_parse(junit_path)

    # Build concise report body
    summary = ""
    if totals:
        summary = f"Summary: {totals['passed']} passed, {totals['failures']} failed, {totals['errors']} errors, {totals['skipped']} skipped, total {totals['tests']}."
    body = f"""# Test Run {ts}

## {summary or "Test summary unavailable"}

## Pytest stdout

{r.stdout}

## Pytest stderr

{r.stderr}

## Exit
{r.returncode}
"""
    report_path.write_text(body)
    return r.returncode


# add helpers below extract_fields
def _slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:80]  # keep short

def make_branch_name(issue_type: str, key: str, title: str) -> str:
    return f"{_slug(issue_type)}/{key}-{_slug(title)}"


def flatten_adf(node) -> str:
    # Minimal Atlassian Document Format → text
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "text" in node:
            return node["text"]
        return "".join(flatten_adf(c) for c in node.get("content", []))
    if isinstance(node, list):
        return "".join(flatten_adf(c) for c in node)
    return ""

# (removed duplicate extract_fields)

def write_prompts(key: str, fields: dict) -> tuple[Path, Path]:
    ensure_dirs()
    prompt = f"""# {key}: {fields['summary']}

## Tech Context
Project uses **Python 3.x** and **Django 5.x**.
Follow Django best practices:
- Organize code into apps (`views.py`, `urls.py`, `templates/`).
- Use Django templating for HTML.
- Keep code production-ready and PEP8-compliant.

## User Story
{fields['description']}

## Acceptance Criteria
{fields['acceptance'] or "_Not provided_"}

## Deliverables
Generate or update Django files that satisfy the above.
Output actual working code files, not pseudocode.

## Tests
{fields['tests'] or "_Not provided_"}
"""
    p_file = QDIR / f"{key}.prompt.md"
    p_file.write_text(prompt)
    return p_file, None

# Parse markdown-like test table rows: ID | scenario | steps | expected
TEST_TABLE_ROW = re.compile(r"^\s*(TC[-_ ]?\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*$", re.IGNORECASE)

def _parse_test_table(text: str) -> list[dict]:
    if not text:
        return []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # find header line with at least 3 pipes
    rows = []
    for i, line in enumerate(lines):
        if line.lower().startswith("id") and line.count("|") >= 3:
            # subsequent lines until separator or blank
            for row in lines[i+1:]:
                m = TEST_TABLE_ROW.match(row)
                if m:
                    tcid = m.group(1)
                    # normalize TC id
                    digits = re.sub(r"\D", "", tcid)
                    tcid = f"TC-{digits.zfill(3)}" if digits else tcid.upper()
                    rows.append({
                        "id": tcid,
                        "scenario": m.group(2).strip(),
                        "steps": m.group(3).strip(),
                        "expected": m.group(4).strip(),
                    })
    return rows

# NEW: parse vertical blocks where each TC is listed on separate lines
# Expect pattern like:
# TC-001
# Verify form layout
# Open page ...
# All fields visible ...
VERT_TC_ID = re.compile(r"^\s*(TC[-_ ]?\d+)\s*$", re.IGNORECASE)

def _parse_vertical_tests(text: str) -> list[dict]:
    if not text:
        return []
    raw_lines = text.splitlines()
    # keep original order, keep blanks to advance index correctly
    def next_nonempty(start: int) -> int:
        j = start
        while j < len(raw_lines) and not raw_lines[j].strip():
            j += 1
        return j if j < len(raw_lines) else -1

    out: list[dict] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        m = VERT_TC_ID.match(line)
        if m:
            tc_raw = m.group(1)
            digits = re.sub(r"\D", "", tc_raw)
            tcid = f"TC-{digits.zfill(3)}" if digits else tc_raw.upper()
            j1 = next_nonempty(i + 1)
            j2 = next_nonempty(j1 + 1) if j1 != -1 else -1
            j3 = next_nonempty(j2 + 1) if j2 != -1 else -1
            scenario = raw_lines[j1].strip() if j1 != -1 else ""
            steps = raw_lines[j2].strip() if j2 != -1 else ""
            expected = raw_lines[j3].strip() if j3 != -1 else ""
            out.append({
                "id": tcid,
                "scenario": scenario,
                "steps": steps,
                "expected": expected,
            })
            i = (j3 + 1) if j3 != -1 else (i + 1)
            continue
        i += 1
    return out

# Fallback: parse bullet-style TC- lines
SIMPLE_TC = re.compile(r"\bTC[-_ ]?(\d{1,})\b", re.IGNORECASE)

# Parse minified concatenated blocks like:
# "Test CasesIDScenarioStepsExpected ResultTC-001Verify ...TC-002Validate ..."
MINI_TC_SPLIT = re.compile(r"(TC[-_ ]?\d{1,})", re.IGNORECASE)

def _parse_minified_tests(text: str) -> list[dict]:
    if not (text and "TC" in text):
        return []
    parts = MINI_TC_SPLIT.split(text)
    # parts -> [prefix, 'TC-001', 'rest...', 'TC-002', 'rest...', ...]
    cases: list[dict] = []
    i = 1
    while i < len(parts):
        tc_raw = (parts[i] or "").strip()
        block = (parts[i+1] if (i+1) < len(parts) else "") or ""
        digits = re.sub(r"\D", "", tc_raw)
        tcid = f"TC-{digits.zfill(3)}" if digits else tc_raw.upper()
        body = block.strip()
        # scenario as first line (best effort)
        scenario = (body.split("\n", 1)[0] or "").strip()
        cases.append({
            "id": tcid,
            "scenario": scenario,
            "steps": "",
            "expected": "",
        })
        i += 2
    return cases

# Generate pytest stubs for TC IDs
TESTS_ROOT = ROOT / "tests"

def _ensure_tests_for_issue(issue_key: str, tests_text: str, desc_text: str) -> int:
    tests_dir = TESTS_ROOT / issue_key
    tests_dir.mkdir(parents=True, exist_ok=True)

    cases = _parse_test_table(tests_text)
    if not cases:
        cases = _parse_vertical_tests(tests_text)
    if not cases:
        # Try parsing vertical blocks from full description too
        cases = _parse_vertical_tests(desc_text)
    if not cases:
        # Final fallback: minified concatenated TC blocks from tests or description
        cases = _parse_minified_tests(tests_text) or _parse_minified_tests(desc_text)
    if not cases:
        # No TCs found anywhere: seed a default one to ensure JUnit is produced
        cases = [{"id": "TC-001", "scenario": "Seed test", "steps": "", "expected": ""}]

    written = 0
    for c in cases:
        tcid = c["id"].upper().replace("-", "_")
        func = f"test_{tcid.lower()}"
        # Use issue key in filename to avoid module import collisions across issues
        fname = f"test_{issue_key.lower()}_{tcid.lower()}.py"
        fpath = tests_dir / fname
        if fpath.exists():
            continue
        doc = (c.get("scenario") or "").strip()
        steps = (c.get("steps") or "").strip()
        expected = (c.get("expected") or "").strip()
        body = "\n".join([s for s in [doc, steps, expected] if s])
        content = (
            "import pytest\n\n"
            f"def {func}():\n"
            f"    \"\"\"{body}\"\"\"\n"
            "    assert True\n"
        )
        fpath.write_text(content)
        written += 1
    return written

def current_branch() -> str:
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()



# (legacy helper removed; use make_branch_name(issue_type, key, title) defined above)


def create_branch(key: str, title: str, issue_type: str) -> None:
    branch = make_branch_name(issue_type, key, title)

    # make sure we’re in a git repo
    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        raise RuntimeError("Not a git repository. Run: git init && git remote add origin <url>")

    typer.echo(f"Preparing branch: {branch}")

    # stash uncommitted changes (esp. .q/)
    run(["git", "add", "-A"])
    run(["git", "stash", "--include-untracked", "-m", f"auto-stash-before-{branch}"])

    # fetch base
    r = run(["git", "fetch", GIT_REMOTE, BASE_BRANCH])
    if r.returncode != 0:
        typer.echo(f"[git fetch] rc={r.returncode} -> using local {BASE_BRANCH}")

    base_ref = f"{GIT_REMOTE}/{BASE_BRANCH}"
    if run(["git", "show-ref", "--verify", f"refs/remotes/{base_ref}"]).returncode != 0:
        base_ref = BASE_BRANCH

    # create/switch
    r = run(["git", "checkout", "-B", branch, base_ref])
    if r.returncode != 0:
        raise RuntimeError(f"[git checkout -B {branch} {base_ref}] failed:\n{r.stderr}")

    # restore stashed files (mainly .q)
    stash_list = run(["git", "stash", "list"]).stdout
    if "auto-stash-before-" in stash_list:
        run(["git", "stash", "pop"])

    # empty commit for visibility
    run(["git", "commit", "--allow-empty", "-m", f"chore({key}): start {branch}"])

    typer.echo(f"Switched to {branch}")


def _junit_parse(junit_path: Path) -> tuple[dict, list[dict]]:
    if not junit_path.exists():
        return {}, []
    root = ET.fromstring(junit_path.read_text())
    suites = root.findall("testsuite") or root.findall(".//testsuite")
    totals = {"tests":0,"failures":0,"errors":0,"skipped":0,"passed":0}
    cases = []
    for s in suites:
        for k in ("tests","failures","errors","skipped"):
            totals[k] += int(s.attrib.get(k, 0))
        for tc in s.findall("testcase"):
            name = tc.attrib.get("name","")
            cls = tc.attrib.get("classname","")
            t = float(tc.attrib.get("time","0") or 0)
            status = "passed"
            detail = ""
            f = tc.find("failure")
            e = tc.find("error")
            sk = tc.find("skipped")
            if f is not None:
                status, detail = "failure", (f.attrib.get("message","") + "\n" + (f.text or "")).strip()
            elif e is not None:
                status, detail = "error", (e.attrib.get("message","") + "\n" + (e.text or "")).strip()
            elif sk is not None:
                status, detail = "skipped", (sk.attrib.get("message","") or "").strip()
            cases.append({"name":name,"class":cls,"time":t,"status":status,"detail":detail})
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return totals, cases

# Map a pytest test name/class to a TC id like "TC-001"
def _tc_id_from_case(name: str, cls: str) -> str | None:
    text = f"{cls}::{name}".lower()
    # match tc-001 or tc_001 or tc001
    m = re.search(r"\btc[-_]?([0-9]{1,})\b", text)
    if not m:
        return None
    digits = m.group(1)
    # zero-pad to at least 3 digits for readability
    if len(digits) < 3:
        digits = digits.zfill(3)
    return f"TC-{digits}"

@app.command("post-tests-tc")
def post_tests_tc(issue_key: str, include_reason: bool = typer.Option(True, help="Include brief failure reasons")):
    """Post per-test-case summary lines: TC-001 = PASS/FAIL (with brief reason)."""
    junit_path = QDIR / f"{issue_key}.junit.xml"
    if not junit_path.exists():
        typer.echo("JUnit file not found. Run `test` first.")
        raise typer.Exit(code=1)

    _, cases = _junit_parse(junit_path)
    if not cases:
        typer.echo("No test cases discovered in JUnit.")
        raise typer.Exit(code=1)

    # Build best-status per TC (prefer FAIL/ERROR over SKIP over PASS)
    priority = {"error": 3, "failure": 3, "skipped": 2, "passed": 1}
    tc_map: dict[str, dict] = {}
    for c in cases:
        tcid = _tc_id_from_case(c.get("name",""), c.get("class",""))
        if not tcid:
            continue
        prev = tc_map.get(tcid)
        if (prev is None) or (priority.get(c["status"], 0) > priority.get(prev["status"], 0)):
            # keep shortest one-line reason (first line)
            reason = ""
            if include_reason and c["status"] in ("failure","error") and c.get("detail"):
                reason = (c["detail"].splitlines() or [""])[0].strip()
                if len(reason) > 140:
                    reason = reason[:140] + "…"
            tc_map[tcid] = {"status": c["status"], "reason": reason}

    if not tc_map:
        typer.echo("No TC-### identifiers found in test names.")
        raise typer.Exit(code=1)

    # Build concise body
    def to_upper_status(s: str) -> str:
        return "PASS" if s == "passed" else ("FAIL" if s in ("failure","error") else "SKIP")

    lines = []
    for tcid in sorted(tc_map.keys()):
        st = to_upper_status(tc_map[tcid]["status"])  # PASS/FAIL/SKIP
        reason = tc_map[tcid]["reason"].strip()
        if st == "FAIL" and reason:
            lines.append(f"{tcid} = {st} — {reason}")
        else:
            lines.append(f"{tcid} = {st}")

    body = "\n".join(lines)
    # Post a very short plain comment
    jira_comment(issue_key, body)
    typer.echo(f"Posted per-TC summary for {len(lines)} cases.")


def run_pytests(issue_key: str, report_path: Path) -> int:
    junit_path = QDIR / f"{issue_key}.junit.xml"
    # verbose, show all reports, do not stop early, include durations
    r = run([
        "pytest",
        "-vv",
        "-rA",
        "--maxfail=0",
        "--color=no",
        "--durations=10",
        f"--junitxml={junit_path}",
    ], cwd=ROOT)

    ts = datetime.now().isoformat(timespec="seconds")
    totals, cases = _junit_parse(junit_path)

    # Per-test detail table
    lines = []
    if cases:
        lines.append("| Status | Test | Time (s) |")
        lines.append("|---|---|---:|")
        for c in cases:
            test_id = f"{c['class']}::{c['name']}".strip(":")
            badge = {"passed":"✅","failure":"❌","error":"⛔","skipped":"⏭️"}.get(c["status"], c["status"])
            lines.append(f"| {badge} {c['status']} | `{test_id}` | {c['time']:.3f} |")
        # Append failure/error details
        for c in cases:
            if c["status"] in ("failure","error") and c["detail"]:
                test_id = f"{c['class']}::{c['name']}".strip(":")
                lines.append(f"\n<details><summary>{c['status'].upper()}: {test_id}</summary>\n\n```\n{c['detail']}\n```\n</details>\n")

    summary = ""
    if totals:
        summary = f"Summary: {totals['passed']} passed, {totals['failures']} failed, {totals['errors']} errors, {totals['skipped']} skipped, total {totals['tests']}."

    body = f"""# Test Run {ts}

## {summary or "Test summary unavailable"}

## Per-test results
{('\n'.join(lines)) if lines else '(no test cases found)'}

## Pytest stdout


## Exit
{r.returncode}
"""
    report_path.write_text(body)
    return r.returncode



def _to_adf_codeblock(text: str, title: str | None = None) -> dict:
    # Simple, robust ADF: optional title paragraph + one code block
    content = []
    if title:
        content.append({"type": "paragraph",
                        "content": [{"type": "text", "text": title}]})
    content.append({
        "type": "codeBlock",
        "attrs": {"language": "text"},
        "content": [{"type": "text", "text": text}],
    })
    return {"type": "doc", "version": 1, "content": content}

def jira_comment(key: str, body_md: str, title: str | None = None) -> None:
    # chunk and post multiple comments if needed
    i = 1
    start = 0
    n = len(body_md)
    while start < n:
        chunk = body_md[start:start + MAX_JIRA_COMMENT]
        start += len(chunk)
        suffix = "" if n <= MAX_JIRA_COMMENT else f" (part {i})"
        adf = _to_adf_codeblock(chunk, (title or "DevFlow") + suffix if title or n > MAX_JIRA_COMMENT else None)
        jira_req("POST", f"/rest/api/3/issue/{key}/comment", json={"body": adf})
        i += 1

import re

FILE_HDR = re.compile(r"^#\s*file:\s*(?P<path>.+)$", re.IGNORECASE)

def materialize_from_markdown(md_path: Path, root: Path = ROOT) -> int:
    text = md_path.read_text()
    blocks = re.split(r"^```", text, flags=re.MULTILINE)
    written = 0
    last_path = None

    # Look for lines like: "# file: products/views.py" before code fences
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = FILE_HDR.match(line.strip())
        if m:
            last_path = m.group("path").strip()

        # Detect start of code fence after a file header
        if line.strip().startswith("```") and last_path:
            lang = line.strip().strip("`").strip()
            code = []
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                code.append(lines[j])
                j += 1
            target = (root / last_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(code))
            written += 1
            last_path = None
    return written


def call_q(prompt_path: Path, out_path: Path, backend: str = "q") -> int:
    if backend == "q":
        qbin = os.getenv("Q_BIN", "q")
        r = run([qbin, "chat", "--no-interactive", "--trust-all-tools", prompt_path.read_text()], cwd=ROOT)
    else:
        # Unknown backend; echo prompt
        r = subprocess.CompletedProcess([], 0, stdout=prompt_path.read_text(), stderr="")
    out = f"""## Q Invocation

## Output
{r.stdout}

## Errors
{r.stderr}
"""
    out_path.write_text(out)
    return r.returncode

# ---------- commands ----------
@app.command()
def materialize(issue_key: str):
    """Write files found in .q/<issue>.codegen.md (# file: path + ``` blocks)."""
    md = QDIR / f"{issue_key}.codegen.md"
    if not md.exists():
        typer.echo("No codegen output to materialize.")
        raise typer.Exit(1)
    n = materialize_from_markdown(md)
    typer.echo(f"Wrote {n} files from {md}")

# modify prepare() to print the extracted info to terminal
@app.command()
def prepare(
    issue_key: str,
    create_branch_flag: bool = typer.Option(True, "--branch/--no-branch", help="Create and switch to branch <issue_key>"),
    debug: bool = typer.Option(False, "--debug/--no-debug", help="Write raw issue JSON"),
):
    ensure_env()
    issue = jira_get_issue(issue_key)
    if debug:
        p = write_debug_issue(issue_key, issue)
        typer.echo(f"Issue JSON: {p}")

    fields = extract_fields(issue)
    pth_prompt, pth_tests = write_prompts(issue_key, fields)
    if create_branch_flag:
        create_branch(issue_key, fields["summary"], fields["type"])

    # concise terminal display
    def _short(s: str, n=400):
        s = (s or "").strip()
        return s if len(s) <= n else s[:n] + "…"

    typer.echo(f"\nKey: {issue_key}")
    typer.echo(f"Type: {fields['type']}")
    typer.echo(f"Title: {fields['summary']}")
    typer.echo(f"\nDescription:\n{_short(fields['description'])}\n")
    typer.echo(f"Acceptance Criteria:\n{_short(fields['acceptance']) or '(none)'}\n")
    typer.echo(f"Test Cases:\n{_short(fields['tests']) or '(none)'}\n")
    typer.echo(f"Prompts: {pth_prompt}, {pth_tests}")




@app.command()
def post_tests_summary(issue_key: str):
    """Post a short summarized test result to Jira."""
    junit_path = QDIR / f"{issue_key}.junit.xml"

    if not junit_path.exists():
        typer.echo("JUnit file not found. Run `test` command first.")
        raise typer.Exit(code=1)

    # Parse counts
    totals, _ = _junit_parse(junit_path)
    if not totals:
        typer.echo("No test data parsed.")
        raise typer.Exit(code=1)

    summary = (
        f"Unit Test Summary for {issue_key}: "
        f"{totals['passed']} passed, "
        f"{totals['failures']} failed, "
        f"{totals['errors']} errors, "
        f"{totals['skipped']} skipped, "
        f"total {totals['tests']}."
    )

    # Post concise comment to Jira
    jira_comment(issue_key, summary, title="Test Results")
    typer.echo(f"Posted summarized test results to Jira for {issue_key}")

# --- ADF helpers for Jira detailed test report ---
def _adf_para(text: str) -> dict:
    return {"type":"paragraph","content":[{"type":"text","text":text}]}

def _adf_code(text: str, lang: str="text") -> dict:
    return {"type":"codeBlock","attrs":{"language":lang},"content":[{"type":"text","text":text}]}

def _adf_table(headers: list[str], rows: list[list[str]]) -> dict:
    def _cell(t): return {"type":"tableCell","content":[{"type":"paragraph","content":[{"type":"text","text":t}]}]}
    head_row = {"type":"tableRow","content":[_cell(h) for h in headers]}
    body_rows = [{"type":"tableRow","content":[_cell(c) for c in r]} for r in rows]
    return {"type":"table","content":[head_row]+body_rows}

def _adf_doc(blocks: list[dict]) -> dict:
    return {"type":"doc","version":1,"content":blocks}


@app.command("post-tests-detailed")
def post_tests_detailed(issue_key: str, include_logs: bool = typer.Option(False, help="Also post pytest stdout/stderr")):
    """Post per-test detailed results (and optional logs) to Jira."""
    junit_path = QDIR / f"{issue_key}.junit.xml"
    if not junit_path.exists():
        typer.echo("JUnit file not found. Run `test` first."); raise typer.Exit(1)

    totals, cases = _junit_parse(junit_path)
    if not totals:
        typer.echo("No test data parsed."); raise typer.Exit(1)

    # Build per-test table
    headers = ["Status","Test","Time (s)"]
    rows = []
    icon = {"passed":"✅","failure":"❌","error":"⛔","skipped":"⏭️"}
    for c in cases:
        test_id = f"{c['class']}::{c['name']}".strip(":")
        rows.append([f"{icon.get(c['status'], c['status'])} {c['status']}", test_id, f"{c['time']:.3f}"])

    blocks = []
    blocks.append(_adf_para(f"Unit Test Summary for {issue_key}: {totals['passed']} passed, {totals['failures']} failed, {totals['errors']} errors, {totals['skipped']} skipped, total {totals['tests']}."))
    blocks.append(_adf_table(headers, rows))

    # Append failure/error details as separate code blocks (chunk if large)
    fail_err = [c for c in cases if c["status"] in ("failure","error") and c["detail"]]
    for c in fail_err:
        test_id = f"{c['class']}::{c['name']}".strip(":")
        blocks.append(_adf_para(f"{c['status'].upper()}: {test_id}"))
        # Jira has size limits; truncate big traces
        detail = c["detail"]
        if len(detail) > 9000:
            detail = detail[:9000] + "\n…(truncated)…"
        blocks.append(_adf_code(detail, "text"))

    # Post detailed report (chunk if needed)
    adf = _adf_doc(blocks)
    jira_req("POST", f"/rest/api/3/issue/{issue_key}/comment", json={"body": adf})

    # Optional: post raw logs
    if include_logs:
        md = QDIR / f"{issue_key}.tests.out.md"
        if md.exists():
            text = md.read_text()
            # chunk ~28k each
            maxc = 28000
            i = 1
            for start in range(0, len(text), maxc):
                part = text[start:start+maxc]
                jira_req("POST", f"/rest/api/3/issue/{issue_key}/comment",
                         json={"body": _adf_doc([_adf_para(f"Pytest log (part {i})"), _adf_code(part, "text")])})
                i += 1

    typer.echo("Posted detailed test report to Jira.")


# --- Concise per-TC table posting ---
@app.command("post-tests-table")
def post_tests_table(issue_key: str, run_first: bool = typer.Option(True, help="Run pytest before posting")):
    """Run tests (optional) and post a concise per-TC table: Test case | test status | time (s) | remarks."""
    report = QDIR / f"{issue_key}.tests.out.md"
    if run_first:
        _ = run_pytests(issue_key, report)

    junit_path = QDIR / f"{issue_key}.junit.xml"
    totals, cases = _junit_parse(junit_path)
    if not cases:
        typer.echo("No JUnit test cases found. Ensure tests are named with TC IDs (e.g., test_tc_001_...).")
        raise typer.Exit(1)

    # Aggregate by TC-###
    priority = {"error": 3, "failure": 3, "skipped": 2, "passed": 1}
    agg: dict[str, dict] = {}
    for c in cases:
        tcid = _tc_id_from_case(c.get("name",""), c.get("class",""))
        if not tcid:
            continue
        cur = agg.get(tcid)
        if (cur is None) or (priority.get(c["status"], 0) > priority.get(cur["status"], 0)):
            # capture best status and brief reason
            reason = ""
            if c["status"] in ("failure","error") and c.get("detail"):
                reason = (c["detail"].splitlines() or [""])[0].strip()
                if len(reason) > 140:
                    reason = reason[:140] + "…"
            agg[tcid] = {"status": c["status"], "time": c["time"], "reason": reason}
        else:
            # accumulate time for this TC
            cur["time"] = cur.get("time", 0.0) + c.get("time", 0.0)

    def to_upper_status(s: str) -> str:
        return "Pass" if s == "passed" else ("Fail" if s in ("failure","error") else "Skip")

    # Build header + rows
    summary = f"Unit Test Summary for {issue_key}: {totals.get('passed',0)} passed, {totals.get('failures',0)} failed, {totals.get('errors',0)} errors, {totals.get('skipped',0)} skipped, total {totals.get('tests',0)}."
    lines = [summary, "", "Test case | test status | time (s) | remarks", "---|---|---:|---"]
    for tcid in sorted(agg.keys()):
        row = agg[tcid]
        st = to_upper_status(row["status"])  # Pass/Fail/Skip
        tsec = f"{row.get('time',0.0):.3f}"
        reason = row.get("reason", "")
        lines.append(f"{tcid} | {st} | {tsec} | {reason}")

    body = "\n".join(lines)
    jira_comment(issue_key, body)
    typer.echo(f"Posted per-TC table for {len(agg)} cases.")


@app.command()
def open(issue_key: str, editor: Optional[str] = None):
    """Open the main prompt in VS Code or the given editor."""
    prompt_path = QDIR / f"{issue_key}.prompt.md"
    if not prompt_path.exists():
        typer.echo("Prompt not found. Run prepare first.")
        raise typer.Exit(code=1)
    editor_cmd = editor or shutil.which("code")
    if not editor_cmd:
        typer.echo("Editor not found. Pass --editor path or install VS Code.")
        raise typer.Exit(code=1)
    subprocess.Popen([editor_cmd, "--reuse-window", str(prompt_path)])

@app.command()
def codegen(issue_key: str):
    """Drive Amazon Q CLI non-interactively for code generation."""
    p = QDIR / f"{issue_key}.prompt.md"
    out = QDIR / f"{issue_key}.codegen.md"
    if not p.exists():
        typer.echo("Prompt not found. Run prepare.")
        raise typer.Exit(code=1)
    rc = call_q(p, out)
    typer.echo(f"Q completed rc={rc}. Output: {out}")

@app.command()
def test(issue_key: str):
    report = QDIR / f"{issue_key}.tests.out.md"
    # Ensure artifact and tests roots exist
    ensure_dirs()
    TESTS_ROOT.mkdir(parents=True, exist_ok=True)
    # Generate tests from Jira sections if possible; seed default if none found
    issue = jira_get_issue(issue_key)
    fields = extract_fields(issue)
    _ = _ensure_tests_for_issue(issue_key, fields.get("tests") or "", fields.get("description") or "")
    rc = run_pytests(issue_key, report)
    typer.echo(f"pytest rc={rc}. Report: {report}")



@app.command()
def post(
    issue_key: str,
    what: str = typer.Option("codegen", help="codegen|tests|both"),
):
    """Post last outputs to Jira comments."""
    ensure_env()
    posted = []
    if what in ("codegen", "both"):
        p = QDIR / f"{issue_key}.codegen.md"
        if p.exists():
            jira_comment(issue_key, p.read_text())
            posted.append("codegen")
    if what in ("tests", "both"):
        t = QDIR / f"{issue_key}.tests.out.md"
        if t.exists():
            jira_comment(issue_key, t.read_text())
            posted.append("tests")
    typer.echo("Posted: " + ",".join(posted) if posted else "Nothing to post.")

@app.command()
def commit(issue_key: str, msg: str = typer.Option("", "--msg", "-m")):
    """Commit with issue key scope."""
    try:
        summary = extract_fields(jira_get_issue(issue_key))["summary"]
    except Exception:
        summary = ""
    body = f"feat({issue_key}): {msg or summary}"
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", body])

@app.command()
def pr():
    """Open PR via gh CLI."""
    if not have("gh"):
        typer.echo("gh CLI not found.")
        raise typer.Exit(code=127)
    branch = current_branch()
    run(["gh", "pr", "create", "--fill", "--head", branch])

def _collect_failures_from_junit(issue_key: str) -> list[dict]:
    junit_path = QDIR / f"{issue_key}.junit.xml"
    _, cases = _junit_parse(junit_path)
    out = []
    for c in cases:
        if c.get("status") in ("failure", "error"):
            test_id = f"{c.get('class','')}::{c.get('name','')}".strip(":")
            detail = (c.get("detail") or "").strip()
            # keep brief first paragraph
            short = (detail.splitlines() or [""])[0].strip()
            if len(short) > 300:
                short = short[:300] + "…"
            out.append({"test": test_id, "status": c.get("status"), "short": short, "detail": detail})
    return out


def _read_text_report(issue_key: str, max_chars: int = 4000) -> str:
    """Read the text test report and return a trimmed excerpt to keep prompts compact."""
    p = QDIR / f"{issue_key}.tests.out.md"
    if not p.exists():
        return ""
    txt = p.read_text(errors="ignore")
    if len(txt) <= max_chars:
        return txt
    # Prefer the tail of the report (usually contains failures)
    return txt[-max_chars:]


def _build_fix_prompt(issue_key: str) -> Path:
    junit_path = QDIR / f"{issue_key}.junit.xml"
    fails = _collect_failures_from_junit(issue_key) if junit_path.exists() else []
    text_report = _read_text_report(issue_key)

    if not fails and not text_report:
        body = f"# {issue_key}: No failing tests detected.\n\nProceed to validate implementation and ensure coverage."
    else:
        lines = [f"# {issue_key}: Fix failing tests", ""]
        if fails:
            lines.append("## Failing tests (first line)\n")
            for f in fails:
                lines.append(f"- {f['test']} — {f['status'].upper()}: {f['short']}")
            lines.append("")
            lines.append("## Full failure details\n")
            for f in fails:
                lines.append(f"### {f['test']}\n")
                lines.append("```text")
                lines.append(f["detail"] or "")
                lines.append("```")
                lines.append("")
        if text_report:
            lines.append("## Test output (excerpt)\n")
            lines.append("```text")
            lines.append(text_report)
            lines.append("```")
            lines.append("")
        lines.extend([
            "## Instructions",
            "- Analyze failures and update code in this repository to make tests pass.",
            "- Output fixes as materializable blocks with headings like `# file: path/to/file.py` followed by fenced code.",
            "- Do not modify unrelated code; keep changes minimal and focused.",
        ])
        body = "\n".join(lines)
    p = QDIR / f"{issue_key}.fixprompt.md"
    p.write_text(body)
    return p


@app.command("fix-failures")
def fix_failures(
    issue_key: str,
    materialize: bool = typer.Option(True, help="Apply generated code changes to files"),
    test_after: bool = typer.Option(True, help="Re-run tests after applying fixes"),
    post_table: bool = typer.Option(True, help="Post concise per-TC table to Jira after test")
):
    """Build a prompt from failing tests, generate fixes with Q, optionally materialize and re-test, and post concise results."""
    # Ensure we have a recent test run / JUnit; clear caches pre-flight
    _cleanup_pytest_artifacts(ROOT)
    junit_path = QDIR / f"{issue_key}.junit.xml"
    if not junit_path.exists():
        report = QDIR / f"{issue_key}.tests.out.md"
        _ = run_pytests(issue_key, report)
    # Build fix prompt and invoke Q
    prompt = _build_fix_prompt(issue_key)
    out = QDIR / f"{issue_key}.codegen_fix.md"
    _ = call_q(prompt, out)
    typer.echo(f"Q fix completed. Output: {out}")
    # Apply and re-test
    if materialize:
        n = materialize_from_markdown(out)
        typer.echo(f"Applied {n} files from codegen fix output")
    if test_after:
        _cleanup_pytest_artifacts(ROOT)
        report2 = QDIR / f"{issue_key}.tests.out.md"
        _ = run_pytests(issue_key, report2)
    if post_table:
        # Use existing posting logic by building and sending the concise table
        junit_path = QDIR / f"{issue_key}.junit.xml"
        totals, cases = _junit_parse(junit_path)
        if cases:
            priority = {"error": 3, "failure": 3, "skipped": 2, "passed": 1}
            agg: dict[str, dict] = {}
            for c in cases:
                tcid = _tc_id_from_case(c.get("name",""), c.get("class","")) or (c.get("name") or "").upper()
                cur = agg.get(tcid)
                if (cur is None) or (priority.get(c["status"], 0) > priority.get(cur["status"], 0)):
                    reason = ""
                    if c["status"] in ("failure","error") and c.get("detail"):
                        reason = (c["detail"].splitlines() or [""])[0].strip()
                        if len(reason) > 140:
                            reason = reason[:140] + "…"
                    agg[tcid] = {"status": c["status"], "time": c.get("time", 0.0), "reason": reason}
                else:
                    cur["time"] = cur.get("time", 0.0) + c.get("time", 0.0)
            def to_upper_status(s: str) -> str:
                return "Pass" if s == "passed" else ("Fail" if s in ("failure","error") else "Skip")
            summary = f"Unit Test Summary for {issue_key}: {totals.get('passed',0)} passed, {totals.get('failures',0)} failed, {totals.get('errors',0)} errors, {totals.get('skipped',0)} skipped, total {totals.get('tests',0)}."
            lines = [summary, "", "Test case | test status | time (s) | remarks", "---|---|---:|---"]
            for tcid in sorted(agg.keys()):
                row = agg[tcid]
                lines.append(f"{tcid} | {to_upper_status(row['status'])} | {row.get('time',0.0):.3f} | {row.get('reason','')}")
            jira_comment(issue_key, "\n".join(lines))
            typer.echo("Posted concise per-TC table to Jira")
        else:
            typer.echo("No testcases found in JUnit to post.")

# Manual cleanup command
@app.command("cleanup-caches")
def cleanup_caches():
    """Remove pytest caches and pyc files to avoid import mismatches."""
    _cleanup_pytest_artifacts(ROOT)
    typer.echo("Cleaned .pytest_cache, __pycache__, and *.pyc")

if __name__ == "__main__":
    app()
