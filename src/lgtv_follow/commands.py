"""Running the command-line tools and hooks that change things on the Mac."""

import logging
import os
import shutil
import signal
import subprocess
import tempfile

log = logging.getLogger(__name__)
# Actions run one at a time, so a stuck command would hold up everything after it.
TOOL_TIMEOUT = 30  # betterdisplaycli can take ~10s to disconnect a TV that's turning off
HOOK_TIMEOUT = 60


def find_tool(name: str) -> str | None:
    # launchd starts agents with a minimal PATH, so also look in Homebrew's prefixes.
    return shutil.which(name) or next(
        (p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}") if os.access(p, os.X_OK)),
        None,
    )


class Runner:
    """Runs commands. In a dry run, commands that change something are only logged."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def tool(self, name: str) -> str:
        path = find_tool(name)
        if not path:
            raise RuntimeError(f"{name} not found on PATH")
        return path

    def query(self, args: list[str]) -> str:
        """Run a read-only command; its output, or "" if it failed."""
        r = run_command(args)
        return r.stdout if r and r.returncode == 0 else ""

    def change(self, args, *, env=None, shell=False, timeout=TOOL_TIMEOUT):
        log.info("%s %s", "[dry-run]" if self.dry_run else "run:", args if shell else " ".join(args))
        if self.dry_run:
            return
        r = run_command(args, env=env, shell=shell, timeout=timeout)
        if r and r.returncode != 0:
            log.warning("exit %d: %s", r.returncode, (r.stderr or r.stdout).strip())


def run_command(args, env=None, shell=False, timeout=TOOL_TIMEOUT) -> subprocess.CompletedProcess | None:
    """Run a command, giving up (None) if it doesn't finish in time.

    It runs in its own process group, so on timeout everything it started is killed too: nothing
    from a stuck hook may keep acting while the next action runs. Output goes to files rather than
    pipes, so a program a hook starts in the background (`&`) doesn't keep us waiting.
    """
    with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
        p = subprocess.Popen(
            args, shell=shell, env=env, stdout=out, stderr=err, text=True, start_new_session=True
        )
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("timed out after %ss: %s", timeout, args if shell else " ".join(args))
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                p.kill()  # group gone or not ours (macOS says EPERM); make sure of the command itself
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.error("can't kill %s (pid %d); moving on", args if shell else args[0], p.pid)
            return None
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(args, p.returncode, out.read(), err.read())
