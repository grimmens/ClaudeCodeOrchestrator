import subprocess
from ..config import Config


def run_claude(prompt: str, working_dir: str, config: Config) -> tuple[int, str, str]:
    """Spawn the claude CLI, pass the prompt via stdin, return (exit_code, stdout, stderr)."""
    cmd = [config.claude_cli_path, "-p", "-"]
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
