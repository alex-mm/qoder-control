# Qoder Control

Codex skill for sending tasks to a local, logged-in Qoder CLI and collecting profile-based mailbox artifacts: concise summaries, structured findings, and raw output fallbacks.

- Agent rules: `SKILL.md`
- Human usage guide: `USAGE.md`
- Bridge script: `scripts/qoder_bridge.py`

By default, completed long runs are read from `summary.md` and `findings.json`; `raw_output.txt` is kept for verification and log-heavy debugging. The bridge chooses `minimal`, `review`, `test`, or `full` artifact profiles so Qoder writes only what the task needs.

The skill discovers `qodercli` from `--qodercli`, `QODERCLI` / `QODERCLI_PATH`, or `PATH`; it does not depend on a user-specific local path.
