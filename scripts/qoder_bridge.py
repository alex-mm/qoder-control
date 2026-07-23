#!/usr/bin/env python3
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BRIDGE_DIR = Path.home() / ".codex" / "qoder-bridge"
SKILL_NAME = "qoder-control"
DONE_STATUSES = {"done", "blocked", "error"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def make_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def bridge_dir(value: str | None) -> Path:
    return Path(value).expanduser() if value else DEFAULT_BRIDGE_DIR


def runs_dir(base: Path) -> Path:
    return base / "runs"


def run_dir(base: Path, run_id: str) -> Path:
    return runs_dir(base) / run_id


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json_atomic(path: Path, data: dict) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def display_path(path: Path | str) -> str:
    text = str(path)
    home = str(Path.home())
    if text == home:
        return "$HOME"
    if text.startswith(home + os.sep):
        return "$HOME" + text[len(home):]
    return text


def display_command(command: list[str]) -> list[str]:
    return [display_path(part) for part in command]


def display_text(text: str) -> str:
    return text.replace(str(Path.home()), "$HOME")


def qoder_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("qoder")
    if not found:
        raise SystemExit("qoder CLI not found on PATH")
    return found


def qodercli_candidates(explicit: str | None = None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    candidates: list[Path] = []
    for env_name in ["QODERCLI", "QODERCLI_PATH"]:
        env_path = os.environ.get(env_name)
        if env_path:
            candidates.append(Path(env_path).expanduser())
    path_qodercli = shutil.which("qodercli")
    if path_qodercli:
        candidates.append(Path(path_qodercli))
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def qodercli_status(qodercli: Path) -> str:
    try:
        proc = subprocess.run([str(qodercli), "status"], text=True, capture_output=True, timeout=15)
    except Exception as exc:
        return f"error: {exc}"
    output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    return output or f"exit={proc.returncode}"


def qodercli_logged_in(status_text: str) -> bool:
    return bool(status_text.strip()) and "not logged in" not in status_text.lower()


def redact_status_text(status_text: str) -> str:
    redacted_prefixes = ("username:", "email:", "avatar:")
    lines = []
    for line in status_text.splitlines():
        if line.lower().startswith(redacted_prefixes):
            key = line.split(":", 1)[0]
            lines.append(f"{key}: <redacted>")
        else:
            lines.append(line)
    return "\n".join(lines)


def qodercli_path(explicit: str | None = None) -> Path | None:
    for candidate in qodercli_candidates(explicit):
        if not candidate.exists() or not os.access(candidate, os.X_OK):
            continue
        if qodercli_logged_in(qodercli_status(candidate)):
            return candidate
    return None


def qodercli_setup_error(explicit: str | None = None) -> str:
    candidates = qodercli_candidates(explicit)
    if not candidates:
        return (
            "logged-in qodercli not found. Put qodercli on PATH, set QODERCLI=/absolute/path/to/qodercli, "
            "or pass --qodercli /absolute/path/to/qodercli; then run `qodercli login`."
        )
    lines = [
        "logged-in qodercli not found.",
        "Checked candidates:",
    ]
    for candidate in candidates:
        if not candidate.exists():
            lines.append(f"- {display_path(candidate)}: missing")
        elif not os.access(candidate, os.X_OK):
            lines.append(f"- {display_path(candidate)}: not executable")
        else:
            status_text = redact_status_text(qodercli_status(candidate)).replace("\n", " | ")
            lines.append(f"- {display_path(candidate)}: {status_text}")
    lines.append("Run `<path>/qodercli login`, set QODERCLI, or pass --qodercli with a logged-in executable.")
    return "\n".join(lines)


def terminal_input_command(prompt: str) -> list[str]:
    script = """
on run argv
  set promptText to item 1 of argv
  tell application "Terminal"
    activate
    if (count of windows) = 0 then error "No Terminal window is open"
    do script promptText in selected tab of front window
  end tell
end run
"""
    return ["osascript", "-e", script, prompt]


def qoder_version(qoder: str) -> str:
    try:
        proc = subprocess.run([qoder, "--version"], text=True, capture_output=True, timeout=15)
    except Exception as exc:
        return f"unknown: {exc}"
    output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    return output or f"exit={proc.returncode}"


def native_qoder_status() -> str:
    candidates = [
        Path("/Applications/Qoder.app/Contents/Resources/app/resources/bin/aarch64_darwin/Qoder"),
        Path("/Applications/QoderWork.app/Contents/Resources/app/resources/bin/aarch64_darwin/Qoder"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                proc = subprocess.run([str(candidate), "status"], text=True, capture_output=True, timeout=10)
            except Exception as exc:
                return f"{candidate}: {exc}"
            output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
            return output or f"{candidate}: exit={proc.returncode}"
    return "native Qoder status binary not found"


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return read_text_file(Path(args.prompt_file).expanduser())
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    raise SystemExit("provide a prompt argument, --prompt-file, or stdin")


def build_protocol_prompt(user_prompt: str, cwd: Path, response_path: Path, status_path: Path) -> str:
    response_tmp = response_path.with_suffix(response_path.suffix + ".tmp")
    status_tmp = status_path.with_suffix(status_path.suffix + ".tmp")
    return f"""You are Qoder, invoked by Codex through a local mailbox protocol.

Working directory:
{cwd}

Task from Codex:
{user_prompt}

Return protocol:
1. Write your final answer in Markdown to this temporary file:
{response_tmp}
2. Atomically rename it to this exact file:
{response_path}
3. Write valid JSON to this temporary file:
{status_tmp}
4. Atomically rename it to this exact file:
{status_path}
5. The JSON must include:
   {{"status":"done"|"blocked"|"error","summary":"one short sentence","wrote_at":"ISO-8601 timestamp"}}

Constraints:
- Unless the task explicitly asks you to modify project files, write only the two files above.
- If you need to report a blocker, still write response.md and status.json with status "blocked".
- Do not ask Codex to copy content from the Qoder UI. The file response is the interface.
- Write status.json only after response.md is complete and renamed into place.
"""


def read_completion(base: Path, rid: str) -> tuple[bool, dict, str]:
    rdir = run_dir(base, rid)
    status_path = rdir / "status.json"
    response_path = rdir / "response.md"
    metadata_path = rdir / "metadata.json"
    result = {
        "run_id": rid,
        "run_dir": display_path(rdir),
        "status_path": display_path(status_path),
        "response_path": display_path(response_path),
        "state": "pending",
    }
    if not rdir.exists():
        result["state"] = "missing"
        return False, result, ""
    if not status_path.exists():
        if metadata_path.exists():
            try:
                metadata = json.loads(read_text_file(metadata_path))
                result.update({
                    "detached": metadata.get("detached"),
                    "worker_pid": metadata.get("worker_pid"),
                    "worker_state": metadata.get("worker_state"),
                    "qoder_kind": metadata.get("qoder_kind"),
                })
            except Exception:
                pass
        return False, result, ""
    try:
        status = json.loads(read_text_file(status_path))
    except Exception as exc:
        result.update({"state": "invalid_status", "error": str(exc)})
        return False, result, ""
    response_text = read_text_file(response_path) if response_path.exists() else ""
    status_value = str(status.get("status", "")).strip().lower()
    complete = bool(response_path.exists() and status_value in DONE_STATUSES)
    result.update({
        "state": "complete" if complete else "invalid_completion",
        "status": status,
        "has_response": response_path.exists(),
        "response_bytes": len(response_text.encode("utf-8")),
    })
    return complete, result, response_text


def print_completion(result: dict, response_text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("STATUS:")
    status = result.get("status", result)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if response_text:
        print("\nRESPONSE:")
        print(response_text.rstrip())


def build_run(args: argparse.Namespace, rid: str, rdir: Path) -> tuple[Path, Path, Path, str, list[str], dict, bool]:
    cwd = Path(args.cwd or os.getcwd()).expanduser().resolve()
    prompt = load_prompt(args)
    response_path = rdir / "response.md"
    status_path = rdir / "status.json"
    protocol_prompt = build_protocol_prompt(prompt, cwd, response_path, status_path)

    transport = args.transport
    qodercli = qodercli_path(args.qodercli) if transport in {"auto", "qodercli"} else None
    if transport in {"auto", "qodercli"} and not qodercli:
        raise SystemExit(qodercli_setup_error(args.qodercli))
    use_qodercli = bool(qodercli and transport != "app-chat")

    if transport == "terminal-input":
        command = terminal_input_command(prompt)
        qoder = "Terminal.app"
        qoder_kind = "terminal-input"
    elif use_qodercli:
        command = [str(qodercli), "-w", str(cwd), "--max-turns", str(args.max_turns), "--max-output-tokens", args.max_output_tokens]
        if args.dangerously_skip_permissions or args.yolo:
            command.append("--dangerously-skip-permissions")
        for add_file in args.add_file or []:
            command.extend(["--attachment", str(Path(add_file).expanduser())])
        command.extend(["-p", prompt])
        qoder = str(qodercli)
        qoder_kind = "qodercli-print"
    else:
        qoder = qoder_path(args.qoder)
        command = [qoder, "chat", "--mode", args.mode, "--reuse-window"]
        for add_file in args.add_file or []:
            command.extend(["--add-file", str(Path(add_file).expanduser())])
        command.append(protocol_prompt)
        qoder_kind = "qoder-app-chat"

    (rdir / "user-prompt.md").write_text(prompt, encoding="utf-8")
    (rdir / "prompt.md").write_text(protocol_prompt if qoder_kind == "qoder-app-chat" else prompt, encoding="utf-8")

    metadata = {
        "skill": SKILL_NAME,
        "run_id": rid,
        "created_at": now_iso(),
        "cwd": display_path(cwd),
        "mode": args.mode,
        "transport": transport,
        "qoder": display_path(qoder),
        "qoder_kind": qoder_kind,
        "qoder_version": qoder_version(qoder),
        "response_path": display_path(response_path),
        "status_path": display_path(status_path),
        "command": display_command(command[:-1]) + ["<prompt>"],
    }
    return cwd, response_path, status_path, qoder_kind, command, metadata, use_qodercli


def finalize_run(
    rdir: Path,
    metadata: dict,
    stdout: str,
    stderr: str,
    returncode: int,
    qoder_kind: str,
    use_qodercli: bool,
    response_path: Path,
    status_path: Path,
) -> None:
    (rdir / "stdout.txt").write_text(stdout or "", encoding="utf-8")
    (rdir / "stderr.txt").write_text(stderr or "", encoding="utf-8")
    metadata["qoder_chat_exit_code"] = returncode
    metadata["finished_at"] = now_iso()
    metadata["worker_state"] = "finished"

    if qoder_kind == "terminal-input" and not status_path.exists():
        write_text_atomic(
            response_path,
            "Sent prompt to the selected Terminal tab. Output is visible in Terminal and is not captured by Codex.\n",
        )
        write_json_atomic(status_path, {
            "status": "done" if returncode == 0 else "error",
            "summary": "prompt sent to Terminal" if returncode == 0 else "failed to send prompt to Terminal",
            "wrote_at": now_iso(),
        })
    elif use_qodercli and not status_path.exists():
        output = (stdout or "").strip()
        if returncode != 0:
            output = "\n".join(part for part in [output, (stderr or "").strip()] if part)
        write_text_atomic(response_path, (output or "(qodercli returned no output)") + "\n")
        write_json_atomic(status_path, {
            "status": "done" if returncode == 0 else "error",
            "summary": "qodercli completed" if returncode == 0 else "qodercli failed",
            "wrote_at": now_iso(),
        })
    elif qoder_kind == "qoder-app-chat" and not status_path.exists():
        write_text_atomic(
            response_path,
            "Desktop qoder chat was launched, but no mailbox response was written. Use headless qodercli for reliable async results.\n",
        )
        write_json_atomic(status_path, {
            "status": "blocked",
            "summary": "desktop app-chat did not produce a mailbox response",
            "wrote_at": now_iso(),
        })

    write_json(rdir / "metadata.json", metadata)


def send(args: argparse.Namespace) -> int:
    base = bridge_dir(args.bridge_dir)
    rid = args.run_id or make_run_id()
    rdir = run_dir(base, rid)
    rdir.mkdir(parents=True, exist_ok=False)

    cwd, response_path, status_path, qoder_kind, command, metadata, use_qodercli = build_run(args, rid, rdir)
    write_json(rdir / "metadata.json", metadata)

    if args.detach:
        worker_config = {
            "cwd": str(cwd),
            "command": command,
            "qoder_kind": qoder_kind,
            "use_qodercli": use_qodercli,
            "response_path": str(response_path),
            "status_path": str(status_path),
        }
        write_json(rdir / "worker_config.json", worker_config)
        worker_out = open(rdir / "worker.stdout.txt", "ab")
        worker_err = open(rdir / "worker.stderr.txt", "ab")
        worker_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--bridge-dir",
            str(base),
            "run-worker",
            rid,
        ]
        proc = subprocess.Popen(
            worker_command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=worker_out,
            stderr=worker_err,
            start_new_session=True,
            close_fds=True,
        )
        worker_out.close()
        worker_err.close()
        metadata.update({
            "detached": True,
            "worker_pid": proc.pid,
            "worker_state": "running",
            "worker_started_at": now_iso(),
            "worker_command": display_command(worker_command),
        })
        write_json(rdir / "metadata.json", metadata)
        print(json.dumps({
            "run_id": rid,
            "run_dir": display_path(rdir),
            "status_path": display_path(status_path),
            "response_path": display_path(response_path),
            "detached": True,
            "worker_pid": proc.pid,
            "state": "pending",
        }, ensure_ascii=False, indent=2))
        return 0

    proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)
    finalize_run(
        rdir,
        metadata,
        proc.stdout or "",
        proc.stderr or "",
        proc.returncode,
        qoder_kind,
        use_qodercli,
        response_path,
        status_path,
    )

    print(json.dumps({
        "run_id": rid,
        "run_dir": display_path(rdir),
        "status_path": display_path(status_path),
        "response_path": display_path(response_path),
        "qoder_chat_exit_code": proc.returncode,
    }, ensure_ascii=False, indent=2))

    if not args.wait or args.no_wait:
        return proc.returncode
    return wait_for_run(base, rid, args.timeout, args.poll_interval)


def run_worker(args: argparse.Namespace) -> int:
    base = bridge_dir(args.bridge_dir)
    rdir = run_dir(base, args.run_id)
    config_path = rdir / "worker_config.json"
    metadata_path = rdir / "metadata.json"
    try:
        config = json.loads(read_text_file(config_path))
        metadata = json.loads(read_text_file(metadata_path)) if metadata_path.exists() else {}
        metadata["worker_state"] = "running"
        metadata["worker_started_at"] = metadata.get("worker_started_at") or now_iso()
        write_json(metadata_path, metadata)

        proc = subprocess.run(
            config["command"],
            cwd=config["cwd"],
            text=True,
            capture_output=True,
        )
        metadata = json.loads(read_text_file(metadata_path)) if metadata_path.exists() else metadata
        finalize_run(
            rdir,
            metadata,
            proc.stdout or "",
            proc.stderr or "",
            proc.returncode,
            config["qoder_kind"],
            bool(config.get("use_qodercli")),
            Path(config["response_path"]),
            Path(config["status_path"]),
        )
        return proc.returncode
    except Exception as exc:
        response_path = rdir / "response.md"
        status_path = rdir / "status.json"
        write_text_atomic(response_path, f"Qoder bridge worker failed: {exc}\n")
        write_json_atomic(status_path, {
            "status": "error",
            "summary": "qoder bridge worker failed",
            "wrote_at": now_iso(),
        })
        metadata = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(read_text_file(metadata_path))
            except Exception:
                metadata = {}
        metadata.update({
            "worker_state": "error",
            "worker_error": str(exc),
            "finished_at": now_iso(),
        })
        write_json(metadata_path, metadata)
        return 2


def wait_for_run(base: Path, rid: str, timeout: int, poll_interval: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        complete, result, response_text = read_completion(base, rid)
        if complete:
            print_completion(result, response_text, as_json=False)
            return 0
        time.sleep(poll_interval)
    print(f"Timed out waiting for Qoder run {rid}", file=sys.stderr)
    print(f"Run directory: {display_path(run_dir(base, rid))}", file=sys.stderr)
    return 124


def wait_cmd(args: argparse.Namespace) -> int:
    return wait_for_run(bridge_dir(args.bridge_dir), args.run_id, args.timeout, args.poll_interval)


def check(args: argparse.Namespace) -> int:
    complete, result, response_text = read_completion(bridge_dir(args.bridge_dir), args.run_id)
    print_completion(result, response_text if complete else "", as_json=args.json)
    if complete:
        status_value = str(result.get("status", {}).get("status", "")).lower()
        return 2 if status_value == "error" else 0
    return 1


def show(args: argparse.Namespace) -> int:
    rdir = run_dir(bridge_dir(args.bridge_dir), args.run_id)
    if not rdir.exists():
        print(f"run not found: {display_path(rdir)}", file=sys.stderr)
        return 2
    for name in ["metadata.json", "status.json", "response.md", "stderr.txt", "stdout.txt", "prompt.md"]:
        path = rdir / name
        if path.exists():
            print(f"\n== {name} ==")
            print(display_text(read_text_file(path)).rstrip())
    return 0


def run_state(rdir: Path) -> str:
    if not (rdir / "status.json").exists():
        return "pending"
    try:
        status = json.loads(read_text_file(rdir / "status.json")).get("status", "done")
    except Exception:
        return "invalid_status"
    return str(status)


def list_runs(args: argparse.Namespace) -> int:
    root = runs_dir(bridge_dir(args.bridge_dir))
    if not root.exists():
        return 0
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for rdir in dirs[: args.limit]:
        status = run_state(rdir)
        if args.state != "all":
            is_pending = status == "pending"
            if args.state == "pending" and not is_pending:
                continue
            if args.state == "complete" and is_pending:
                continue
        print(f"{rdir.name}\t{status}\t{display_path(rdir)}")
    return 0


def status(args: argparse.Namespace) -> int:
    qoder = None
    qoder_error = None
    try:
        qoder = qoder_path(args.qoder)
    except SystemExit as exc:
        qoder_error = str(exc)
    chat_help_ok = False
    if qoder:
        try:
            proc = subprocess.run([qoder, "chat", "--help"], text=True, capture_output=True, timeout=15)
            chat_help_ok = proc.returncode == 0 and "Usage: qoder chat" in proc.stdout
        except Exception:
            chat_help_ok = False
    qodercli_info = []
    for candidate in qodercli_candidates(args.qodercli):
        info = {
            "path": display_path(candidate),
            "exists": candidate.exists(),
            "executable": candidate.exists() and os.access(candidate, os.X_OK),
        }
        if info["executable"]:
            status_text = qodercli_status(candidate)
            info["logged_in"] = qodercli_logged_in(status_text)
            info["status"] = redact_status_text(status_text)
        qodercli_info.append(info)
    print(json.dumps({
        "qoder": display_path(qoder) if qoder else None,
        "qoder_error": qoder_error,
        "qoder_version": qoder_version(qoder) if qoder else None,
        "qoder_chat_help_ok": chat_help_ok,
        "preferred_qodercli": display_path(qodercli_path(args.qodercli)) if qodercli_path(args.qodercli) else None,
        "qodercli_candidates": qodercli_info,
        "native_qoder_status": native_qoder_status(),
        "bridge_dir": display_path(bridge_dir(args.bridge_dir)),
    }, ensure_ascii=False, indent=2))
    return 0


def heartbeat_prompt(args: argparse.Namespace) -> int:
    base = bridge_dir(args.bridge_dir)
    rdir = run_dir(base, args.run_id)
    script_path = display_path(Path(__file__).resolve())
    prompt = f"""Check Qoder bridge run `{args.run_id}`.

Run:
{display_path(rdir)}

Use:
QODER_BRIDGE="{script_path}"
python3 "$QODER_BRIDGE" check {args.run_id}

If complete, report Qoder's `response.md` content to the user and stop monitoring. If pending, say it is still pending and schedule/check again later only if the user requested continued monitoring.
"""
    print(prompt)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send prompts to local Qoder and collect file-based responses.")
    p.add_argument("--bridge-dir", help=f"Bridge directory. Default: {DEFAULT_BRIDGE_DIR}")
    p.add_argument("--qoder", help="Path to qoder app CLI. Default: first qoder on PATH.")
    p.add_argument("--qodercli", help="Path to headless qodercli. Default: first logged-in candidate.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("send")
    s.add_argument("prompt", nargs="?", help="Prompt to send to Qoder.")
    s.add_argument("--prompt-file", help="Read prompt from file.")
    s.add_argument("--cwd", help="Working directory for qoder chat. Default: current directory.")
    s.add_argument("--mode", default="agent", choices=["ask", "edit", "agent"], help="Qoder chat mode.")
    s.add_argument("--transport", choices=["auto", "qodercli", "app-chat", "terminal-input"], default="auto", help="Use logged-in qodercli when available; fall back to app chat. terminal-input types into the selected Terminal tab.")
    s.add_argument("--add-file", action="append", help="Add a file as Qoder context. Repeatable.")
    s.add_argument("--run-id", help="Optional caller-provided run id.")
    s.add_argument("--max-turns", type=int, default=25, help="Max qodercli agent turns for --transport qodercli.")
    s.add_argument("--max-output-tokens", default="16k", choices=["16k", "32k"], help="Max qodercli output tokens.")
    s.add_argument("--yolo", action="store_true", help="Alias for --dangerously-skip-permissions; fully bypass qodercli permission checks.")
    s.add_argument("--dangerously-skip-permissions", action="store_true", help="Pass through to qodercli for fully authorized local automation.")
    s.add_argument("--detach", action="store_true", help="Start Qoder in a background worker and return run_id immediately.")
    s.add_argument("--wait", action="store_true", help="Wait for status.json after sending. Default is async/no wait.")
    s.add_argument("--no-wait", action="store_true", help="Deprecated no-op; send is async by default.")
    s.add_argument("--timeout", type=int, default=900, help="Seconds to wait for status.json.")
    s.add_argument("--poll-interval", type=float, default=2.0)
    s.set_defaults(func=send)

    w = sub.add_parser("wait")
    w.add_argument("run_id")
    w.add_argument("--timeout", type=int, default=900)
    w.add_argument("--poll-interval", type=float, default=2.0)
    w.set_defaults(func=wait_cmd)

    c = sub.add_parser("check")
    c.add_argument("run_id")
    c.add_argument("--json", action="store_true", help="Print machine-readable check result.")
    c.set_defaults(func=check)

    sh = sub.add_parser("show")
    sh.add_argument("run_id")
    sh.set_defaults(func=show)

    ls = sub.add_parser("list")
    ls.add_argument("--limit", type=int, default=20)
    ls.add_argument("--state", choices=["all", "pending", "complete"], default="all")
    ls.set_defaults(func=list_runs)

    st = sub.add_parser("status")
    st.set_defaults(func=status)

    hp = sub.add_parser("heartbeat-prompt")
    hp.add_argument("run_id")
    hp.set_defaults(func=heartbeat_prompt)

    rw = sub.add_parser("run-worker", help=argparse.SUPPRESS)
    rw.add_argument("run_id")
    rw.set_defaults(func=run_worker)
    return p


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
