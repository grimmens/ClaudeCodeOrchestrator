import subprocess
import threading
import time
from queue import Empty, Queue
from threading import Event
from typing import Callable, Optional

from ..config import Config


_EOF = object()


def _build_cmd(config: Config) -> list[str]:
    cmd = [config.claude_cli_path, "-p", "-"]
    cmd += ["--max-turns", str(config.max_turns)]
    if config.max_budget_usd > 0:
        cmd += ["--max-budget-usd", str(config.max_budget_usd)]
    if config.permission_mode == "override":
        cmd += ["--dangerously-skip-permissions"]
    else:
        tools = [t.strip() for t in config.allowed_tools.split() if t.strip()]
        if tools:
            cmd += ["--allowedTools"] + tools
    return cmd


def run_claude_streaming(
    prompt: str,
    working_dir: str,
    config: Config,
    on_output: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[Event] = None,
    inactivity_timeout: float = 0,
) -> tuple[int, str, str]:
    """Spawn the claude CLI, stream stdout/stderr line-by-line.

    - on_output(line) is invoked for each line as it arrives (newline kept).
    - If cancel_event is set, the subprocess is terminated.
    - If no output is seen for inactivity_timeout seconds (0 = disabled),
      the subprocess is terminated.

    Returns (exit_code, stdout, stderr) collected across the full run.
    """
    proc = subprocess.Popen(
        _build_cmd(config),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=working_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    try:
        if proc.stdin is not None:
            proc.stdin.write(prompt)
            proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    q: Queue = Queue()

    def _reader(stream, tag: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                q.put((tag, line))
        finally:
            q.put((tag, _EOF))
            try:
                stream.close()
            except Exception:
                pass

    t_out = threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []
    last_activity = time.monotonic()
    eof_count = 0
    terminated = False

    while eof_count < 2:
        try:
            tag, payload = q.get(timeout=0.5)
        except Empty:
            if cancel_event is not None and cancel_event.is_set():
                terminated = True
                if on_output:
                    on_output("\n[Cancelled — terminating subprocess]\n")
                break
            if inactivity_timeout > 0 and (time.monotonic() - last_activity) > inactivity_timeout:
                terminated = True
                if on_output:
                    on_output(
                        f"\n[Watchdog: no output for {inactivity_timeout:.0f}s — terminating]\n"
                    )
                break
            continue

        if payload is _EOF:
            eof_count += 1
            continue

        last_activity = time.monotonic()
        if tag == "stdout":
            stdout_buf.append(payload)
            if on_output:
                on_output(payload)
        else:
            stderr_buf.append(payload)
            if on_output:
                on_output(f"[stderr] {payload}" if not payload.startswith("[stderr]") else payload)

    if terminated:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        except Exception:
            pass
    else:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # Drain any straggler lines that arrived after we decided to stop
    while True:
        try:
            tag, payload = q.get_nowait()
        except Empty:
            break
        if payload is _EOF:
            continue
        if tag == "stdout":
            stdout_buf.append(payload)
        else:
            stderr_buf.append(payload)

    exit_code = proc.returncode if proc.returncode is not None else -1
    return exit_code, "".join(stdout_buf), "".join(stderr_buf)


def run_claude(prompt: str, working_dir: str, config: Config) -> tuple[int, str, str]:
    """Non-streaming convenience wrapper for callers that just want the final output."""
    return run_claude_streaming(prompt, working_dir, config)
