import subprocess
from ..config import Config


def run_claude(prompt: str, working_dir: str, config: Config) -> tuple[int, str, str]:
    """Spawn the claude CLI, pass the prompt via stdin, return (exit_code, stdout, stderr)."""
    cmd = [config.claude_cli_path, "-p", "-"]

    # Max turns
    cmd += ["--max-turns", str(config.max_turns)]

    # Budget (0 = unlimited)
    if config.max_budget_usd > 0:
        cmd += ["--max-budget-usd", str(config.max_budget_usd)]

    # Permission mode: override grants all, otherwise use allowedTools
    if config.permission_mode == "override":
        cmd += ["--dangerously-skip-permissions"]
    else:
        tools = [t.strip() for t in config.allowed_tools.split() if t.strip()]
        if tools:
            cmd += ["--allowedTools"] + tools

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=working_dir,
        text=True,
    )
    stdout, stderr = proc.communicate(input=prompt)
    return (proc.returncode, stdout, stderr)
