---
name: qoder-control
description: Control the local Qoder desktop app from Codex by sending prompts through the `qoder chat` CLI and collecting Qoder's answer from a mailbox directory. Use when the user asks Codex to ask Qoder, delegate work to Qoder, compare Qoder's answer with Codex, send a command or prompt to local Qoder, or retrieve Qoder's response from a local file.
---

# Qoder Control

Use `scripts/qoder_bridge.py` for all Qoder interaction. Prefer the logged-in headless `qodercli -p` transport. Do not hardcode a qodercli versioned path in this skill; discover it from explicit `--qodercli`, `QODERCLI` / `QODERCLI_PATH`, or `PATH`. Default to async sends and bounded checks. Do not read Qoder's internal databases or logs unless debugging the bridge itself.

Human-facing usage docs live in `USAGE.md`; keep `SKILL.md` focused on agent execution rules.

## First-Run Setup

Before sending a Qoder task in a fresh session, run:

```bash
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE" status
```

Proceed with headless mode only when `preferred_qodercli` is non-null and logged in. If it is missing:

1. Ask the user to install or expose `qodercli` on `PATH`, or provide an explicit absolute path with `--qodercli`.
2. Ask the user to run `qodercli login` for that executable.
3. Re-run `status`.

Accepted discovery mechanisms:

```bash
export QODERCLI=/absolute/path/to/qodercli
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE" --qodercli /absolute/path/to/qodercli status
command -v qodercli
```

Use desktop `qoder chat` only when the user explicitly wants that route and pass `--transport app-chat`.

## Protocol

The bridge creates one run directory under:

```text
~/.codex/qoder-bridge/runs/<run-id>/
```

Each run contains:

- `prompt.md`: the protocol prompt sent to Qoder
- `response.md`: Qoder's final answer file
- `status.json`: Qoder's completion signal
- `metadata.json`: bridge metadata
- `stdout.txt` / `stderr.txt`: `qoder chat` process output

The bridge tells Qoder to write `response.md.tmp`, rename it to `response.md`, then write `status.json.tmp` and rename it to `status.json`. Treat `status.json` plus an existing `response.md` as the completion signal. Do not treat a partial `response.md.tmp` as complete.

## Send A Task

Use `agent` mode by default. With the default `--transport auto`, the bridge requires a logged-in `qodercli` discovered from `--qodercli`, `QODERCLI` / `QODERCLI_PATH`, or `PATH`; it uses `qodercli -p` with the raw user prompt, then captures stdout and writes `response.md` / `status.json` from Codex. If no logged-in qodercli exists, stop and ask the user to fix setup instead of silently switching transports.

For long tasks such as repository/PR code review, use real detached mode so Codex can return immediately and check later:

```bash
python3 "$QODER_BRIDGE" send \
  --detach \
  --transport qodercli \
  --yolo \
  --cwd "$PWD" \
  "Review this repository and write findings."
```

Detached mode starts a background worker, returns `run_id` immediately, and later writes `response.md` / `status.json`. Use `check`, `show`, or `wait` to inspect it.

After a successful detached send, report the `run_id`, run directory, and exact check/show commands, then stop the current turn. Do not immediately poll, wait, or say "I will keep waiting" unless the user explicitly asks to monitor, wait for completion, or check again later in the same request.

### YOLO Selection Guidance

Choose `--yolo` deliberately; do not treat it as part of `--detach`.

Use `--yolo` automatically when all of these are true:

- The user explicitly asks Qoder to perform engineering automation such as repository/PR code review, running tests, inspecting project files, or posting routine PR review comments.
- The task will run through non-interactive `qodercli` (`--wait` or `--detach`) and is likely to need tool/file/command access.
- The scope is bounded to the requested repository, working directory, PR, or routine engineering destination.
- The requested action is not destructive, credential-related, sensitive-data related, or high-impact communication.

Do not use `--yolo` for pure Q&A, conceptual explanations, small read-only prompts, `terminal-input`, or `app-chat`.

Ask the user before using `--yolo`, or run without it, when the request involves deletion, credential/auth changes, security settings, broad filesystem access, sensitive/private data transmission, paid/financial/legal actions, or reputationally sensitive external communication.

Default patterns:

```bash
# Long engineering automation: detached + yolo
python3 "$QODER_BRIDGE" send --detach --transport qodercli --yolo --cwd "$PWD" "Review this PR."

# Short read-only question: wait, no yolo
python3 "$QODER_BRIDGE" send --wait --cwd "$PWD" "Summarize this file."
```

```bash
python3 "$QODER_BRIDGE" send \
  --mode agent \
  --cwd "$PWD" \
  "Analyze this repository and write a concise risk list."
```

Return the `run_id` to the user if the result is not needed immediately.

For a prompt stored in a file:

```bash
python3 "$QODER_BRIDGE" send \
  --mode agent \
  --cwd "$PWD" \
  --prompt-file /absolute/path/to/prompt.md
```

Add file context with repeated `--add-file` arguments when Qoder should inspect specific files:

```bash
python3 "$QODER_BRIDGE" send \
  --mode agent \
  --cwd "$PWD" \
  --add-file /absolute/path/to/file.ts \
  "Review this file and write findings."
```

For short tasks where the user expects an immediate answer, use a bounded wait:

```bash
python3 "$QODER_BRIDGE" send \
  --wait \
  --timeout 60 \
  --mode agent \
  --cwd "$PWD" \
  "Answer briefly."
```

Never wait unboundedly.

For fully authorized local automation, such as a user explicitly asking Qoder to run commands and post a routine PR review comment, use YOLO mode. This fully bypasses qodercli permission checks in headless mode:

```bash
python3 "$QODER_BRIDGE" send \
  --wait \
  --transport qodercli \
  --yolo \
  --cwd "$PWD" \
  "Review this PR and comment directly."
```

`--dangerously-skip-permissions` is kept as a compatibility alias, but prefer `--yolo` in this skill.

If the user wants to watch Qoder answer in their already-open Terminal, and the selected Terminal tab is already running interactive `qodercli`, use `terminal-input`. This types the prompt into that tab and presses return. Codex only records that the prompt was sent; Qoder's output remains in Terminal and is not captured:

```bash
python3 "$QODER_BRIDGE" send \
  --transport terminal-input \
  --cwd "$PWD" \
  "你好"
```

## Read Existing Runs

Show a run's current state:

```bash
python3 "$QODER_BRIDGE" show <run-id>
```

Use `check` for heartbeat or automation checks. Exit code `0` means complete or blocked with a readable response, `1` means pending, and `2` means Qoder reported an error:

```bash
python3 "$QODER_BRIDGE" check <run-id>
```

Wait briefly for a run:

```bash
python3 "$QODER_BRIDGE" wait <run-id> --timeout 60
```

List recent runs:

```bash
python3 "$QODER_BRIDGE" list
```

Generate a prompt suitable for a Codex heartbeat:

```bash
python3 "$QODER_BRIDGE" heartbeat-prompt <run-id>
```

## Monitoring

Use a Codex heartbeat when the user asks to monitor a Qoder run or continue this same task later. The heartbeat prompt should call `check <run-id>`, report `response.md` when complete, and stop monitoring after completion.

Use cron automation only for broad recurring scans, such as checking all pending Qoder bridge runs every day. Do not create a long-running shell watcher.

## Safety Rules

- Prefer this mailbox protocol over scraping Qoder UI state, SQLite tables, or logs.
- Tell Qoder to write only `response.md` and `status.json` unless the user's request explicitly asks Qoder to modify project files.
- Use absolute paths for `--cwd`, `--prompt-file`, and `--add-file` when possible.
- If the bridge times out or `check` returns pending, report the run directory and use `check` or `show` later. Do not assume Qoder failed; it may still be running in the app.
- If `qoder chat` is missing, run `qoder --help` and report the installed CLI capability instead of inventing another interface.
- Run `status` at the start of a fresh session and when debugging local setup; it checks the desktop app CLI, known native Qoder status endpoint, and qodercli candidates from explicit path/env/PATH.
- If no logged-in qodercli exists, ask the user to run `qodercli login`, set `QODERCLI`, add qodercli to `PATH`, or pass `--qodercli`.
- Do not hardcode user-home, versioned, or application-bundle qodercli paths in this skill. Use discovery or user-provided paths.
- Use `terminal-input` only when the selected Terminal tab is intended to receive the text. If the tab is at a shell prompt instead of interactive `qodercli`, the prompt will be executed by the shell.
- Use `--yolo` only when the user has clearly authorized full local automation for this task. It maps to qodercli's full permission bypass and can run tools without interactive confirmations.
