Devflow CLI – Jira‑driven local developer workflow (VS Code)

## Overview
Devflow streamlines a ticket‑centric workflow in VS Code:
- Fetch a Jira issue and prepare your repo (refresh base, create/switch branch)
- Generate a rich prompt for the AI coding assistant (VS Code Amazon Q)
- Open the prompt in VS Code and optionally auto‑type it into Q chat (Wayland‑safe)
- Auto‑generate unit test stubs per Jira Test Case (TC‑001, TC‑002, …)
- Run tests and post per‑test‑case results back to the Jira ticket

## Requirements
- Python 3.9+
- Linux (tested on Ubuntu). Windows/macOS may work for basic commands; injection is Wayland‑focused
- Git repository with a configured remote
- Jira Cloud credentials for API access

## Install dependencies

```bash
pip install -r tools/devflow/requirements.txt
```

## Configure environment (.env at repo root)
Create or update `/home/lokraj/PythonProjects/AI_first/.env`:

```ini
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your_api_token

# Optional (defaults shown)
GIT_REMOTE=origin
BASE_BRANCH=main

# Default editor for `open` (overridable by --editor)
DEVFLOW_EDITOR=code
```

## Command reference
Run commands from the repo root unless using absolute paths.

### 1) Prepare workspace from a Jira issue

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY> [--stack|--from-current|--base <ref>]
```

Actions:
- Fetch issue title/description from Jira
- Detect/ensure local environment (basic Python/Django bootstrap supported)
- Create/switch to `feature/<ISSUE>-<slug>` from the chosen base
- Generate `.q/<ISSUE>.prompt.md`
- Commit/push the prompt; post a Jira comment with branch/prompt info

Branch base options:
- Default (no flag): sync `origin/main` locally and branch from it
- `--stack` or `--from-current`: branch from current `HEAD` (stacking on unmerged work)
- `--base <ref>`: branch from an explicit ref (e.g., another feature branch or commit)

### 2) Open the prompt in VS Code

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
# or set once
export DEVFLOW_EDITOR=code
python tools/devflow/cli.py open <ISSUE-KEY>
```

### 3) Inject the prompt into VS Code Q chat (Wayland‑safe)
Types the entire `.q/<ISSUE>.prompt.md` into the currently focused VS Code window and presses Enter.

Install one of:
```bash
sudo apt install ydotool   # preferred
# or
sudo apt install wtype
```

Run:
```bash
python tools/devflow/cli.py inject <ISSUE-KEY>
```

Notes:
- ydotool typically requires sudo; to avoid prompts you may allow NOPASSWD for `/usr/bin/ydotool` in sudoers
- Ensure the VS Code Amazon Q chat input is focused before running

### 4) Generate and run tests per Jira Test Case

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

What it does:
- Parses Jira description for blocks starting with `TC-###: Title` (e.g., `TC-001: successful login`)
- Writes pytest stubs under `tests/<ISSUE-KEY>/`, one file per TC (skipped by default)
- Runs pytest for that directory and stores logs + JUnit XML under `.devflow_artifacts/<ISSUE-KEY>/`

Naming & mapping:
- Test function is `test_tc_###()` derived from the TC ID (e.g., `TC-001` -> `test_tc_001`)
- Jira results posting maps by this convention; keep it stable if you customize

### 5) Post test results to Jira

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

Behavior:
- If a JUnit XML exists for the issue (created by the test step), Devflow summarizes per Test Case ID
- Posts a comment like:

```
Local unit test status: FAIL

Per test case (from Jira):
TC-001: PASS
TC-002: FAIL
TC-003: SKIP
```

- If no JUnit is available, Devflow posts the first 120 lines of the latest test output

## Standard vs stacked workflows

Standard (recommended):
1. Merge previous feature into main
2. Sync main locally (`prepare` does this for you)
3. `prepare <ISSUE>` (branches from fresh `origin/main`)

Stacked (when you must build on unmerged work):
1. Commit/push current branch
2. `prepare <ISSUE> --stack` (branches from current `HEAD`)
   - Or: `prepare <ISSUE> --base feature/PREV-ISSUE-…`
3. Continue; tests run per issue; merge to main later when ready

Tip: Avoid stacking unless necessary; it complicates reviews and merges.

## Safety notes
- `prepare` (default mode) resets the local base branch to `origin/<BASE_BRANCH>` and runs `git clean -fd`
  - Ensure work is committed/stashed; this is destructive to untracked/dirty files
- Jira API token grants access to your data; keep `.env` private
- ydotool types low‑level keystrokes; only allow passwordless sudo if you trust your environment

## Test runners and artifacts
- Auto‑detection for: pytest, npm/yarn/pnpm test, vitest, jest, mocha, mvn, gradle, go test, cargo test, dotnet test, make test
- Per‑issue artifacts: `.devflow_artifacts/<ISSUE-KEY>/`
  - `last.log`, `last.status`, time‑stamped logs, optional `junit.xml`

## Troubleshooting
- Jira 401/403: verify `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env`
- Git errors: ensure you are in a Git repo with correct remote and base branch
- Editor not found: install VS Code, or pass `--editor /path/to/editor`
- Inject not working: install `ydotool` (preferred) or `wtype`; ensure chat input is focused; grant NOPASSWD for ydotool if needed
- “No test runner detected”: add `Makefile test` or configure a supported runner

## Extending
- Stacks: Add more `detect_tech_stack` branches and `ensure_environment` steps
- Test generation: Adjust parsing in `parse_test_cases_from_description` and stub generation in `write_pytest_cases`
- Editors: Expand `open`/`inject` support for other editors or OSes as needed

## Typical end‑to‑end flow

```bash
# 1) Prepare from Jira
python tools/devflow/cli.py prepare SCRUM-1

# 2) Open the prompt and start coding with VS Code Amazon Q
python tools/devflow/cli.py open SCRUM-1 --editor code
# Or auto‑type the prompt into Q (Wayland)
python tools/devflow/cli.py inject SCRUM-1

# 3) Generate and run tests per Jira TC
python tools/devflow/cli.py test SCRUM-1

# 4) Post detailed results back to Jira
python tools/devflow/cli.py post SCRUM-1
```

## Cheat sheet: commands by action (VS Code)

- Prepare environment and branch (from clean main)

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY>
```

- Prepare environment and branch stacked on current work (no merge)

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY> --stack
# or specify an explicit base ref/branch
python tools/devflow/cli.py prepare <ISSUE-KEY> --base feature/PREV-ISSUE-some-slug
```

- Open the AI prompt in VS Code

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
# or set a default once
export DEVFLOW_EDITOR=code && python tools/devflow/cli.py open <ISSUE-KEY>
```

- Generate code automatically by injecting the prompt text into VS Code Q chat (Wayland)

```bash
# Ensure editor chat input is focused first
python tools/devflow/cli.py inject <ISSUE-KEY>
```

- Generate unit test stubs from Jira TC-IDs and run tests

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

- Post last test result summary (per TC) to Jira

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

- Override tech stack detection for an issue (persisted)

```bash
python tools/devflow/cli.py stack <ISSUE-KEY> python django
# or: node next
```

## License
MIT (adjust as needed)

Devflow CLI – Jira‑driven local developer workflow (VS Code)

## Overview
Devflow streamlines a ticket‑centric workflow in VS Code:
- Fetch a Jira issue and prepare your repo (refresh base, create/switch branch)
- Generate a rich prompt for the AI coding assistant (VS Code Amazon Q)
- Open the prompt in VS Code and optionally auto‑type it into Q chat (Wayland‑safe)
- Auto‑generate unit test stubs per Jira Test Case (TC‑001, TC‑002, …)
- Run tests and post per‑test‑case results back to the Jira ticket

## Requirements
- Python 3.9+
- Linux (tested on Ubuntu). Windows/macOS may work for basic commands; injection is Wayland‑focused
- Git repository with a configured remote
- Jira Cloud credentials for API access

## Install dependencies

```bash
pip install -r tools/devflow/requirements.txt
```

## Configure environment (.env at repo root)
Create or update `/home/lokraj/PythonProjects/AI_first/.env`:

```ini
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your_api_token

# Optional (defaults shown)
GIT_REMOTE=origin
BASE_BRANCH=main

# Default editor for `open` (overridable by --editor)
DEVFLOW_EDITOR=code
```

## Command reference
Run commands from the repo root unless using absolute paths.

### 1) Prepare workspace from a Jira issue

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY> [--stack|--from-current|--base <ref>]
```

Actions:
- Fetch issue title/description from Jira
- Detect/ensure local environment (basic Python/Django bootstrap supported)
- Create/switch to `feature/<ISSUE>-<slug>` from the chosen base
- Generate `.q/<ISSUE>.prompt.md`
- Commit/push the prompt; post a Jira comment with branch/prompt info

Branch base options:
- Default (no flag): sync `origin/main` locally and branch from it
- `--stack` or `--from-current`: branch from current `HEAD` (stacking on unmerged work)
- `--base <ref>`: branch from an explicit ref (e.g., another feature branch or commit)

### 2) Open the prompt in VS Code

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
# or set once
export DEVFLOW_EDITOR=code
python tools/devflow/cli.py open <ISSUE-KEY>
```

### 3) Inject the prompt into VS Code Q chat (Wayland‑safe)
Types the entire `.q/<ISSUE>.prompt.md` into the currently focused VS Code window and presses Enter.

Install one of:
```bash
sudo apt install ydotool   # preferred
# or
sudo apt install wtype
```

Run:
```bash
python tools/devflow/cli.py inject <ISSUE-KEY>
```

Notes:
- ydotool typically requires sudo; to avoid prompts you may allow NOPASSWD for `/usr/bin/ydotool` in sudoers
- Ensure the VS Code Amazon Q chat input is focused before running

### 4) Generate and run tests per Jira Test Case

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

What it does:
- Parses Jira description for blocks starting with `TC-###: Title` (e.g., `TC-001: successful login`)
- Writes pytest stubs under `tests/<ISSUE-KEY>/`, one file per TC (skipped by default)
- Runs pytest for that directory and stores logs + JUnit XML under `.devflow_artifacts/<ISSUE-KEY>/`

Naming & mapping:
- Test function is `test_tc_###()` derived from the TC ID (e.g., `TC-001` -> `test_tc_001`)
- Jira results posting maps by this convention; keep it stable if you customize

### 5) Post test results to Jira

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

Behavior:
- If a JUnit XML exists for the issue (created by the test step), Devflow summarizes per Test Case ID
- Posts a comment like:

```
Local unit test status: FAIL

Per test case (from Jira):
TC-001: PASS
TC-002: FAIL
TC-003: SKIP
```

- If no JUnit is available, Devflow posts the first 120 lines of the latest test output

## Standard vs stacked workflows

Standard (recommended):
1. Merge previous feature into main
2. Sync main locally (`prepare` does this for you)
3. `prepare <ISSUE>` (branches from fresh `origin/main`)

Stacked (when you must build on unmerged work):
1. Commit/push current branch
2. `prepare <ISSUE> --stack` (branches from current `HEAD`)
   - Or: `prepare <ISSUE> --base feature/PREV-ISSUE-…`
3. Continue; tests run per issue; merge to main later when ready

Tip: Avoid stacking unless necessary; it complicates reviews and merges.

## Safety notes
- `prepare` (default mode) resets the local base branch to `origin/<BASE_BRANCH>` and runs `git clean -fd`
  - Ensure work is committed/stashed; this is destructive to untracked/dirty files
- Jira API token grants access to your data; keep `.env` private
- ydotool types low‑level keystrokes; only allow passwordless sudo if you trust your environment

## Test runners and artifacts
- Auto‑detection for: pytest, npm/yarn/pnpm test, vitest, jest, mocha, mvn, gradle, go test, cargo test, dotnet test, make test
- Per‑issue artifacts: `.devflow_artifacts/<ISSUE-KEY>/`
  - `last.log`, `last.status`, time‑stamped logs, optional `junit.xml`

## Troubleshooting
- Jira 401/403: verify `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env`
- Git errors: ensure you are in a Git repo with correct remote and base branch
- Editor not found: install Cursor or VS Code, or pass `--editor /path/to/editor`
- Inject not working: install `ydotool` (preferred) or `wtype`; ensure chat input is focused; grant NOPASSWD for ydotool if needed
- “No test runner detected”: add `Makefile test` or configure a supported runner

## Extending
- Stacks: Add more `detect_tech_stack` branches and `ensure_environment` steps
- Test generation: Adjust parsing in `parse_test_cases_from_description` and stub generation in `write_pytest_cases`
- Editors: Expand `open`/`inject` support for other editors or OSes as needed

## Typical end‑to‑end flow

```bash
# 1) Prepare from Jira
python tools/devflow/cli.py prepare SCRUM-1

# 2) Open the prompt and start coding with VS Code Amazon Q
python tools/devflow/cli.py open SCRUM-1 --editor code
# Or auto‑type the prompt into Q (Wayland)
python tools/devflow/cli.py inject SCRUM-1

# 3) Generate and run tests per Jira TC
python tools/devflow/cli.py test SCRUM-1

# 4) Post detailed results back to Jira
python tools/devflow/cli.py post SCRUM-1
```

## Cheat sheet: commands by action (VS Code)

- Prepare environment and branch (from clean main)

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY>
```

- Prepare environment and branch stacked on current work (no merge)

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY> --stack
# or specify an explicit base ref/branch
python tools/devflow/cli.py prepare <ISSUE-KEY> --base feature/PREV-ISSUE-some-slug
```

- Open the AI prompt in VS Code

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
# or set a default once
export DEVFLOW_EDITOR=code && python tools/devflow/cli.py open <ISSUE-KEY>
```

- Generate code automatically by injecting the prompt text into VS Code Q chat (Wayland)

```bash
# Ensure editor chat input is focused first
python tools/devflow/cli.py inject <ISSUE-KEY>
```

- Generate unit test stubs from Jira TC-IDs and run tests

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

- Post last test result summary (per TC) to Jira

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

- Override tech stack detection for an issue (persisted)

```bash
python tools/devflow/cli.py stack <ISSUE-KEY> python django
# or: node next
```

## License
MIT (adjust as needed)



