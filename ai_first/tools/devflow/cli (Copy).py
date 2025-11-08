import os, re, json, base64, subprocess, shlex, pathlib, sys, time, shutil, tempfile
from typing import Optional, Tuple
import requests
from dotenv import load_dotenv

WORKSPACE = pathlib.Path(os.getenv("REPO_ABS_PATH") or pathlib.Path.cwd()).resolve()
ENV_PATH = WORKSPACE / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

JIRA_BASE = os.environ["JIRA_BASE_URL"].rstrip("/")
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_API_TOKEN"]
GIT_REMOTE = os.environ.get("GIT_REMOTE", "origin")
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")

AUTH = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
JHDRS = {"Authorization": f"Basic {AUTH}", "Accept": "application/json", "Content-Type": "application/json"}

PROMPT_DIR = WORKSPACE / ".q"
ARTIFACT_DIR = WORKSPACE / ".devflow_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def run(cmd: str, cwd: Optional[pathlib.Path] = None, check: bool = True) -> str:
    shell = os.name == "nt"
    p = subprocess.run(cmd if shell else shlex.split(cmd),
                       cwd=str(cwd) if cwd else None,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, shell=shell)
    if check and p.returncode != 0:
        raise RuntimeError(p.stdout)
    return p.stdout

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]

def jira_get_issue(issue_key: str) -> dict:
    url = f"{JIRA_BASE}/rest/api/3/issue/{issue_key}?fields=summary,description"
    r = requests.get(url, headers=JHDRS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Jira fetch failed: {r.status_code} {r.text}")
    f = r.json()["fields"]
    # Atlassian Document Format → plain text (best effort)
    desc = f.get("description")
    description = ""
    if isinstance(desc, dict) and "content" in desc:
        chunks = []
        for blk in desc.get("content", []):
            for c in blk.get("content", []) or []:
                t = c.get("text")
                if t: chunks.append(t)
        description = "\n".join(chunks).strip()
    elif isinstance(desc, str):
        description = desc
    return {"summary": f.get("summary", ""), "description": description}

def ensure_base():
    run("git fetch --all", cwd=WORKSPACE)
    run(f"git checkout {BASE_BRANCH}", cwd=WORKSPACE)
    run(f"git reset --hard {GIT_REMOTE}/{BASE_BRANCH}", cwd=WORKSPACE)
    run("git clean -fd", cwd=WORKSPACE)

def ensure_branch(issue_key: str, summary: str) -> str:
    name = f"feature/{issue_key}-{slug(summary)}"
    out = run(f"git branch --list {name}", cwd=WORKSPACE, check=False)
    if name not in out:
        run(f"git checkout -b {name} {GIT_REMOTE}/{BASE_BRANCH}", cwd=WORKSPACE)
    else:
        run(f"git checkout {name}", cwd=WORKSPACE)
    run(f"git push -u {GIT_REMOTE} {name}", cwd=WORKSPACE, check=False)
    return name

def write_prompt(issue_key: str, summary: str, description: str) -> pathlib.Path:
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    p = PROMPT_DIR / f"{issue_key}.prompt.md"
    body = [
        f"# {issue_key}: {summary}",
        "",
        "## Context",
        description or "No description.",
        "",
        "## Deliverables",
        f"- Implement the feature.",
        f"- Add unit tests under `tests/{issue_key}/`.",
        "- Do not change unrelated files.",
        "",
        "## Constraints",
        "- Idempotent changes. Commit small, coherent diffs.",
        "- Keep style consistent with repo.",
        "",
        "## Notes for Amazon Q inside VS Code",
        "- Use full project context.",
        "- Generate runnable code and tests.",
      ]
    p.write_text("\n".join(body), encoding="utf-8")
    return p

def commit_push(message: str):
    run("git add -A", cwd=WORKSPACE)
    run(f'git commit -m "{message}" || true', cwd=WORKSPACE, check=False)
    run("git push", cwd=WORKSPACE, check=False)

def jira_comment(issue_key: str, text: str):
    url = f"{JIRA_BASE}/rest/api/3/issue/{issue_key}/comment"
    body = {"body": {"type": "doc", "version": 1,
                     "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}}
    r = requests.post(url, headers=JHDRS, data=json.dumps(body), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Jira comment failed: {r.status_code} {r.text}")

def detect_test_command() -> Tuple[str, str]:
    """
    Return (command, label) for the detected ecosystem.
    The command must exit non-zero on failure.
    """
    w = WORKSPACE
    # Python
    if (w / "pytest.ini").exists() or (w / "pyproject.toml").exists() or (w / "requirements.txt").exists():
        return ("pytest -q --maxfail=1 --disable-warnings", "pytest")
    # Node / JS / TS
    if (w / "package.json").exists():
        # prefer npm test if defined, else try common test runners
        try:
            pkg = json.loads((w / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return ("npm test --silent --if-present || yarn test || pnpm test", "npm/yarn/pnpm test")
        except Exception:
            pass
        return ("npx --yes vitest run || npx --yes jest --ci || npx --yes mocha", "npx test runner")
    # Java
    if (w / "pom.xml").exists():
        return ("mvn -q -DskipTests=false test", "maven")
    if (w / "build.gradle").exists() or (w / "gradlew").exists():
        return ("./gradlew test || gradle test", "gradle")
    # Go
    if (w / "go.mod").exists():
        return ("go test ./...", "go test")
    # Rust
    if (w / "Cargo.toml").exists():
        return ("cargo test --quiet", "cargo")
    # .NET
    slns = list(w.glob("*.sln"))
    if slns or list(w.rglob("*.csproj")):
        return ("dotnet test -v minimal", "dotnet")
    # Fallback
    if (w / "Makefile").exists():
        return ("make test", "make test")
    return ("echo 'No test runner detected' && exit 0", "none")

def run_tests(issue_key: str) -> Tuple[int, str, str]:
    cmd, label = detect_test_command()
    shell = True  # cross-platform convenience for chained commands
    print(f"[devflow] Running tests via: {label}\n$ {cmd}")
    p = subprocess.run(cmd, cwd=str(WORKSPACE), shell=shell,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = p.stdout
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = ARTIFACT_DIR / issue_key
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"test-{stamp}.log").write_text(out, encoding="utf-8")
    (out_dir / "last.log").write_text(out, encoding="utf-8")
    (out_dir / "last.status").write_text(str(p.returncode), encoding="utf-8")
    return p.returncode, out, str(out_dir)

# --- add near other imports ---
import platform
import json

# --- constants (put near PROMPT_DIR/ARTIFACT_DIR) ---
REPO_STACK_FILE = WORKSPACE / ".devflow.tech.json"   # repo-wide defaults
# schema: {"default":{"lang":"python","framework":"django"},
#          "issues":{"SCRUM-1":{"lang":"node","framework":"next"}}}

# --- utils ---
def _venv_paths(venv_dir: pathlib.Path) -> Tuple[pathlib.Path, pathlib.Path]:
    if platform.system().lower().startswith("win"):
        return venv_dir / "Scripts" / "python.exe", venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "python", venv_dir / "bin" / "pip"

def _read_repo_defaults() -> dict:
    if REPO_STACK_FILE.exists():
        try:
            return json.loads(REPO_STACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _read_issue_cache(issue_key: str) -> dict:
    f = ARTIFACT_DIR / issue_key / "stack.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _write_issue_cache(issue_key: str, stack: dict) -> None:
    d = ARTIFACT_DIR / issue_key
    d.mkdir(parents=True, exist_ok=True)
    (d / "stack.json").write_text(json.dumps(stack, indent=2), encoding="utf-8")

def _parse_env_stack() -> dict:
    # Example: DEVFLOW_TECH="python/django" or "node:next"
    raw = os.environ.get("DEVFLOW_TECH", "").strip().lower()
    if not raw:
        return {}
    for sep in ("/", ":", ","):
        if sep in raw:
            lang, framework = [s.strip() for s in raw.split(sep, 1)]
            return {"lang": lang, "framework": framework}
    return {"lang": raw, "framework": ""}

def detect_tech_stack(summary: str, description: str) -> dict:
    text = f"{summary}\n{description}".lower()
    w = WORKSPACE

    # Heuristics
    # Python+Django
    if (w / "manage.py").exists() or any(
        "django" in (p.read_text(encoding="utf-8", errors="ignore").lower() if p.exists() else "")
        for p in [w / "requirements.txt", w / "pyproject.toml"]
    ) or "django" in text:
        return {"lang": "python", "framework": "django"}

    # Node+Next
    if (w / "package.json").exists():
        try:
            pkg = json.loads((w / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                return {"lang": "node", "framework": "next"}
        except Exception:
            pass
        if "next" in text:
            return {"lang": "node", "framework": "next"}
        return {"lang": "node", "framework": ""}

    return {}

def resolve_stack(issue_key: str, summary: str, description: str) -> dict:
    """
    Priority: per-issue cache > DEVFLOW_TECH env var > repo config (issue override > default) > auto-detect.
    Persist chosen value to per-issue cache for reuse.
    """
    # 1) issue cache
    cached = _read_issue_cache(issue_key)
    if cached:
        return cached

    # 2) env
    envs = _parse_env_stack()
    if envs:
        _write_issue_cache(issue_key, envs)
        return envs

    # 3) repo config
    cfg = _read_repo_defaults()
    if cfg.get("issues", {}).get(issue_key):
        picked = cfg["issues"][issue_key]
        _write_issue_cache(issue_key, picked)
        return picked
    if cfg.get("default"):
        picked = cfg["default"]
        _write_issue_cache(issue_key, picked)
        return picked

    # 4) detect
    guessed = detect_tech_stack(summary, description)
    if guessed:
        _write_issue_cache(issue_key, guessed)
    return guessed

# --- environment setup ---
def _detect_node_pm() -> Tuple[str, str]:
    """Return (install_cmd, add_cmd_prefix) for package manager."""
    w = WORKSPACE
    if (w / "yarn.lock").exists():
        return ("yarn install --silent", "yarn add -D")
    if (w / "pnpm-lock.yaml").exists():
        return ("pnpm install --reporter=silent", "pnpm add -D")
    if (w / "package-lock.json").exists():
        return ("npm ci --silent", "npm install -D --silent")
    return ("npm install --silent", "npm install -D --silent")

# --- add below imports ---
import platform

# --- add helpers near top ---
def _venv_paths(venv_dir: pathlib.Path) -> Tuple[pathlib.Path, pathlib.Path]:
    """Return (python_path, pip_path) inside venv."""
    if platform.system().lower().startswith("win"):
        py = venv_dir / "Scripts" / "python.exe"
        pip = venv_dir / "Scripts" / "pip.exe"
    else:
        py = venv_dir / "bin" / "python"
        pip = venv_dir / "bin" / "pip"
    return py, pip

def detect_tech_stack(summary: str, description: str) -> dict:
    """
    Heuristics: returns {"lang": "...", "framework": "..."} or {}.
    Detects Django from repo and Jira text.
    """
    text = f"{summary}\n{description}".lower()
    w = WORKSPACE

    # File-based Django signals
    if (w / "manage.py").exists() or any(
        "django" in (p.read_text(encoding="utf-8", errors="ignore").lower() if p.exists() else "")
        for p in [w / "requirements.txt", w / "pyproject.toml"]
    ):
        return {"lang": "python", "framework": "django"}

    # Keyword-based
    if "django" in text:
        return {"lang": "python", "framework": "django"}

    # Extend here for other stacks as needed (node, spring, etc.)
    return {}

def ensure_environment(stack: dict) -> None:
    """
    Ensure local runtime for the detected stack.
    Implements Python+Django. No-ops if already satisfied.
    """
    if not stack:
        print("[env] No tech stack detected. Skipping environment setup.")
        return

    if stack.get("lang") == "python" and stack.get("framework") == "django":
        venv_dir = WORKSPACE / ".venv"
        if not venv_dir.exists():
            print(f"[env] Creating virtualenv at {venv_dir}")
            run(f'"{sys.executable}" -m venv "{venv_dir}"', cwd=WORKSPACE)

        py, pip = _venv_paths(venv_dir)
        if not pip.exists():
            # Repair venv if partial
            run(f'"{sys.executable}" -m venv "{venv_dir}"', cwd=WORKSPACE)
            py, pip = _venv_paths(venv_dir)

        print("[env] Upgrading pip/setuptools/wheel")
        run(f'"{pip}" install -U pip setuptools wheel', cwd=WORKSPACE)

        req = WORKSPACE / "requirements.txt"
        if req.exists():
            print("[env] Installing requirements.txt")
            run(f'"{pip}" install -r "{req}"', cwd=WORKSPACE)
        else:
            # Minimal bootstrap to ensure django present
            print("[env] requirements.txt not found. Installing django")
            run(f'"{pip}" install "django>=4"', cwd=WORKSPACE)

        # Sanity check: django import
        code = 'import django,sys; print("Django", django.get_version())'
        run(f'"{py}" -c "{code}"', cwd=WORKSPACE)
        print(f"[env] Python venv ready at {venv_dir}")
        return

    # Placeholder for future stacks
    print(f"[env] Stack not implemented: {stack}. Skipping.")

# --- modify cmd_prepare to call env setup before branching ---
def cmd_prepare(issue_key: str):
    info = jira_get_issue(issue_key)
    ensure_base()

    # NEW: detect and ensure environment before branch creation
    stack = detect_tech_stack(info["summary"], info["description"])
    ensure_environment(stack)

    branch = ensure_branch(issue_key, info["summary"])
    pf = write_prompt(issue_key, info["summary"], info["description"])
    commit_push(f"devflow: add Q prompt for {issue_key}")
    jira_comment(
        issue_key,
        f"Branch ready: {branch}\nPrompt: {pf}\n"
        f"Environment: {stack or 'none detected'}\n"
        "Open in VS Code and use Amazon Q to generate code. Push when done.",
    )
    print(f"[OK] Branch {branch}\nPrompt {pf}")


# --- modify prepare to resolve + persist stack before branch ---
def cmd_prepare(issue_key: str):
    info = jira_get_issue(issue_key)
    ensure_base()

    stack = resolve_stack(issue_key, info["summary"], info["description"])
    ensure_environment(stack)

    branch = ensure_branch(issue_key, info["summary"])
    pf = write_prompt(issue_key, info["summary"], info["description"])
    commit_push(f"devflow: add Q prompt for {issue_key}")
    jira_comment(
        issue_key,
        f"Branch ready: {branch}\nPrompt: {pf}\nEnvironment: {stack or 'none'}\n"
        "Open in VS Code and use Amazon Q to generate code. Push when done.",
    )
    print(f"[OK] Branch {branch}\nPrompt {pf}")


def cmd_open(issue_key: str):
    pf = PROMPT_DIR / f"{issue_key}.prompt.md"
    if not pf.exists():
        print("Prompt not found. Run 'prepare' first."); sys.exit(1)
    # Try to open prompt in the editor.
    run(f'code -g "{pf}"', check=False)
    print(f"Open {pf} in VS Code and use Amazon Q.")

def cmd_inject(issue_key: str):
    pf = PROMPT_DIR / f"{issue_key}.prompt.md"
    if not pf.exists():
        print("Run 'prepare' first."); sys.exit(1)
    text = pf.read_text(encoding="utf-8")
    # Prefer X11 path: xdotool + clipboard, to drive VS Code and paste
    if shutil.which("xdotool"):
        # Copy to clipboard
        if shutil.which("xclip"):
            subprocess.run(f'xclip -selection clipboard < "{pf}"', shell=True)
        elif shutil.which("wl-copy"):
            subprocess.run(f'wl-copy < "{pf}"', shell=True)
        else:
            print("Clipboard tool not found. Install xclip or wl-clipboard."); sys.exit(1)
        # Focus VS Code and send keys
        subprocess.run('xdotool search --onlyvisible --name "Visual Studio Code" windowactivate --sync', shell=True)
        for s in ['key ctrl+shift+p', 'type Amazon Q: Open Chat', 'sleep 0.2', 'key Return', 'sleep 0.2', 'key ctrl+v', 'sleep 0.2', 'key Return']:
            subprocess.run(f"xdotool {s}", shell=True)
        print(f"Injected into VS Code via xdotool: {pf}")
        return
    # Wayland fallbacks: try to bring VS Code forward, then type into focused window
    run(f'code -g "{pf}"', check=False)
    if shutil.which("ydotool"):
        cmd = f"sudo ydotool type {shlex.quote(text)} && sudo ydotool key 28"
        subprocess.run(cmd, shell=True)
        print(f"Injected via ydotool: {pf}")
        return
    if shutil.which("wtype"):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            subprocess.run(f'wtype < "{tmp_path}" && wtype -k Return', shell=True)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        print(f"Injected via wtype: {pf}")
        return
    print("Install xdotool (X11) or ydotool/wtype (Wayland) to inject into Q chat."); sys.exit(1)

def cmd_inject(issue_key: str):
    pf = PROMPT_DIR / f"{issue_key}.prompt.md"
    if not pf.exists():
        print("Run 'prepare' first."); sys.exit(1)
    text = pf.read_text(encoding="utf-8")
    # Prefer ydotool (Wayland-friendly)
    if shutil.which("ydotool"):
        cmd = f"sudo ydotool type {shlex.quote(text)} && sudo ydotool key 28"
        subprocess.run(cmd, shell=True)
        print(f"Injected via ydotool: {pf}")
        return
    # Fallback: wtype
    if shutil.which("wtype"):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        try:
            subprocess.run(f'wtype < "{tmp_path}" && wtype -k Return', shell=True)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        print(f"Injected via wtype: {pf}")
        return
    print("Install ydotool (preferred) or wtype."); sys.exit(1)

def cmd_test(issue_key: str):
    code, out, path = run_tests(issue_key)
    status = "PASS" if code == 0 else "FAIL"
    print(f"[{status}] Artifacts: {path}")

def cmd_post(issue_key: str):
    out_file = ARTIFACT_DIR / issue_key / "last.log"
    status_file = ARTIFACT_DIR / issue_key / "last.status"
    if not out_file.exists() or not status_file.exists():
        print("No local test artifacts. Run 'test' first."); sys.exit(1)
    out = out_file.read_text(encoding="utf-8")
    code = int(status_file.read_text(encoding="utf-8").strip() or "1")
    status = "PASS" if code == 0 else "FAIL"
    snippet = "\n".join(out.splitlines()[:120])
    jira_comment(issue_key, f"Local unit test status: {status}\n\nOutput (first 120 lines):\n{snippet}")
    print(f"[{status}] Posted to Jira {issue_key}")

def cmd_stack(issue_key: str, lang: str, framework: Optional[str] = None):
    stack = {"lang": lang.lower(), "framework": (framework or "").lower()}
    _write_issue_cache(issue_key, stack)
    print(f"[stack] {issue_key} -> {stack}")

def help():
    print("Usage:")
    print("  python tools/devflow/cli.py prepare <ISSUE-KEY>")
    print("  python tools/devflow/cli.py open    <ISSUE-KEY>")
    print("  python tools/devflow/cli.py inject  <ISSUE-KEY>")
    print("  python tools/devflow/cli.py test    <ISSUE-KEY>")
    print("  python tools/devflow/cli.py post    <ISSUE-KEY>")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        help()
        sys.exit(1)

    cmd, key = sys.argv[1].lower(), sys.argv[2]

    if cmd == "prepare":
        cmd_prepare(key)
    elif cmd == "open":
        cmd_open(key)
    elif cmd == "test":
        cmd_test(key)
    elif cmd == "post":
        cmd_post(key)
    elif cmd == "inject":
        cmd_inject(key)
    elif cmd == "stack":
        if len(sys.argv) < 4:
            print("Usage: python tools/devflow/cli.py stack <ISSUE-KEY> <lang> [framework]")
            sys.exit(1)
        lang = sys.argv[3]
        framework = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_stack(key, lang, framework)
    else:
        help()
        sys.exit(1)

