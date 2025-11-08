Git flow guide – clean start and per‑issue workflow (VS Code)

This guide documents the exact commands to clean your workspace and run a new end‑to‑end demo per Jira issue.

## Prerequisites
- Git remote configured (default: `origin`)
- .env configured for Jira (see README)
- Dependencies installed:

```bash
pip install -r tools/devflow/requirements.txt
```

## One‑time VS Code tooling (optional)
For Wayland auto‑typing into VS Code Amazon Q chat:

```bash
sudo apt install ydotool   # preferred
# or
sudo apt install wtype
```

## Clean workspace before a new demo
The following cleans local/remote branches and resets the local main to a known state.

1) Fetch and prune

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch --all --prune
```

2) Inspect branches (optional)

```bash
git -C /home/lokraj/PythonProjects/AI_first branch --merged origin/main
git -C /home/lokraj/PythonProjects/AI_first branch -r --merged origin/main
```

3) Delete a merged feature branch (local and remote)

Replace the branch name as needed.

```bash
git -C /home/lokraj/PythonProjects/AI_first branch -d feature/SCRUM-1-create-product-information-form-with-frontend-vali
git -C /home/lokraj/PythonProjects/AI_first push origin --delete feature/SCRUM-1-create-product-information-form-with-frontend-vali
```

4) Reset local main to remote and clean untracked files

```bash
git -C /home/lokraj/PythonProjects/AI_first checkout main
git -C /home/lokraj/PythonProjects/AI_first reset --hard origin/main
git -C /home/lokraj/PythonProjects/AI_first clean -fd
```

You now have a clean baseline.

## Start a new issue – standard flow (recommended)
Branches from a fresh `origin/main`.

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY>
```

This will:
- Sync base branch and create `feature/<ISSUE>-<slug>` from `origin/main`
- Generate `.q/<ISSUE>.prompt.md`
- Commit/push the prompt and comment on the Jira ticket

## Start a new issue – stacked flow (when building on unmerged work)
Branches from the current `HEAD` or an explicit base.

```bash
# Stack on current HEAD
python tools/devflow/cli.py prepare <ISSUE-KEY> --stack

# Or branch from an explicit base ref (another feature branch or commit)
python tools/devflow/cli.py prepare <ISSUE-KEY> --base feature/PREV-ISSUE-some-slug
```

## Working the issue (VS Code)
Open the prompt in VS Code:

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
```

Optionally auto‑type the prompt into VS Code Q chat (Wayland):

```bash
# Ensure the chat input is focused first
python tools/devflow/cli.py inject <ISSUE-KEY>
```

Generate unit test stubs from Jira TC‑IDs and run tests:

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

Post results back to Jira (per Test Case summary if JUnit is available):

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

## Keeping a feature branch up‑to‑date (optional)
Rebase on top of the latest main while developing:

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch origin
git -C /home/lokraj/PythonProjects/AI_first rebase origin/main
```

## Wrap up
Create a PR and merge (or squash‑merge) to main. Then repeat the “Clean workspace” section for the next demo.

## Quick script (optional)
Run all clean steps at once (edit branch name as needed):

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch --all --prune && \
git -C /home/lokraj/PythonProjects/AI_first branch -d feature/SCRUM-1-create-product-information-form-with-frontend-vali || true && \
git -C /home/lokraj/PythonProjects/AI_first push origin --delete feature/SCRUM-1-create-product-information-form-with-frontend-vali || true && \
git -C /home/lokraj/PythonProjects/AI_first checkout main && \
git -C /home/lokraj/PythonProjects/AI_first reset --hard origin/main && \
git -C /home/lokraj/PythonProjects/AI_first clean -fd
```

Git flow guide – clean start and per‑issue workflow

This guide documents the exact commands to clean your workspace and run a new end‑to‑end demo per Jira issue.

## Prerequisites
- Git remote configured (default: `origin`)
- .env configured for Jira (see README)
- Dependencies installed:

```bash
pip install -r tools/devflow/requirements.txt
```

## One‑time VS Code tooling (optional)
For Wayland auto‑typing into VS Code Amazon Q chat:

```bash
sudo apt install ydotool   # preferred
# or
sudo apt install wtype
```

## Clean workspace before a new demo
The following cleans local/remote branches and resets the local main to a known state.

1) Fetch and prune

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch --all --prune
```

2) Inspect branches (optional)

```bash
git -C /home/lokraj/PythonProjects/AI_first branch --merged origin/main
git -C /home/lokraj/PythonProjects/AI_first branch -r --merged origin/main
```

3) Delete a merged feature branch (local and remote)

Replace the branch name as needed.

```bash
git -C /home/lokraj/PythonProjects/AI_first branch -d feature/SCRUM-1-create-product-information-form-with-frontend-vali
git -C /home/lokraj/PythonProjects/AI_first push origin --delete feature/SCRUM-1-create-product-information-form-with-frontend-vali
```

4) Reset local main to remote and clean untracked files

```bash
git -C /home/lokraj/PythonProjects/AI_first checkout main
git -C /home/lokraj/PythonProjects/AI_first reset --hard origin/main
git -C /home/lokraj/PythonProjects/AI_first clean -fd
```

You now have a clean baseline.

## Start a new issue – standard flow (recommended)
Branches from a fresh `origin/main`.

```bash
python tools/devflow/cli.py prepare <ISSUE-KEY>
```

This will:
- Sync base branch and create `feature/<ISSUE>-<slug>` from `origin/main`
- Generate `.q/<ISSUE>.prompt.md`
- Commit/push the prompt and comment on the Jira ticket

## Start a new issue – stacked flow (when building on unmerged work)
Branches from the current `HEAD` or an explicit base.

```bash
# Stack on current HEAD
python tools/devflow/cli.py prepare <ISSUE-KEY> --stack

# Or branch from an explicit base ref (another feature branch or commit)
python tools/devflow/cli.py prepare <ISSUE-KEY> --base feature/PREV-ISSUE-some-slug
```

## Working the issue (VS Code)
Open the prompt in VS Code:

```bash
python tools/devflow/cli.py open <ISSUE-KEY> --editor code
```

Optionally auto‑type the prompt into VS Code Q chat (Wayland):

```bash
# Ensure the chat input is focused first
python tools/devflow/cli.py inject <ISSUE-KEY>
```

Generate unit test stubs from Jira TC‑IDs and run tests:

```bash
python tools/devflow/cli.py test <ISSUE-KEY>
```

Post results back to Jira (per Test Case summary if JUnit is available):

```bash
python tools/devflow/cli.py post <ISSUE-KEY>
```

## Keeping a feature branch up‑to‑date (optional)
Rebase on top of the latest main while developing:

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch origin
git -C /home/lokraj/PythonProjects/AI_first rebase origin/main
```

## Wrap up
Create a PR and merge (or squash‑merge) to main. Then repeat the “Clean workspace” section for the next demo.

## Quick script (optional)
Run all clean steps at once (edit branch name as needed):

```bash
git -C /home/lokraj/PythonProjects/AI_first fetch --all --prune && \
git -C /home/lokraj/PythonProjects/AI_first branch -d feature/SCRUM-1-create-product-information-form-with-frontend-vali || true && \
git -C /home/lokraj/PythonProjects/AI_first push origin --delete feature/SCRUM-1-create-product-information-form-with-frontend-vali || true && \
git -C /home/lokraj/PythonProjects/AI_first checkout main && \
git -C /home/lokraj/PythonProjects/AI_first reset --hard origin/main && \
git -C /home/lokraj/PythonProjects/AI_first clean -fd
```



