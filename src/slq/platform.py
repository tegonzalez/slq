import os
import platform as _platform
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def logical_cwd() -> Path:
    """Return the working directory, preferring the ``PWD`` spelling.

    When ``PWD`` is absolute and names the same directory as the process
    working directory, return it; otherwise fall back to ``os.getcwd()``. This
    keeps a symlinked spelling stable across calls.
    """
    pwd = os.environ.get("PWD")
    if pwd and os.path.isabs(pwd):
        try:
            if same_path(Path(pwd), Path.cwd()):
                return Path(pwd)
        except OSError:
            pass
    return Path.cwd()


def same_path(a: Path, b: Path) -> bool:
    """Return whether ``a`` and ``b`` identify the same filesystem object.

    Uses ``(st_dev, st_ino)`` when both paths can be ``stat``ed; otherwise
    falls back to resolved path equality.  This treats a symlink and its
    target as the same path.
    """
    a = Path(a)
    b = Path(b)
    try:
        st_a = a.stat()
        st_b = b.stat()
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)
    return (st_a.st_dev, st_a.st_ino) == (st_b.st_dev, st_b.st_ino)


def _abi_tag() -> str:
    return "{}:{}:{}:{}:{}".format(
        _platform.machine(),
        sys.byteorder,
        sys.maxsize,
        ".".join(map(str, sys.version_info[:2])),
        sys.implementation.name,
    )


def _candidate_abi(candidate: str) -> Optional[str]:
    script = (
        "import platform, sys; "
        "print('{}:{}:{}:{}:{}'.format(platform.machine(), sys.byteorder, "
        "sys.maxsize, '.'.join(map(str, sys.version_info[:2])), "
        "sys.implementation.name))"
    )
    try:
        result = subprocess.run(
            [candidate, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode().strip()
    except UnicodeDecodeError:
        return None


def compatible_python(root: str) -> str:
    """Return the project-venv interpreter at ``root`` when it matches.

    The candidate interpreter is ``<root>/.venv/bin/python``. If it can run
    and reports the same machine, byteorder, word size, Python version, and
    implementation as the running process, return the candidate; otherwise fall
    back to ``sys.executable``. This prevents a venv built for a different
    platform or ABI from causing an exec failure.
    """
    candidate = Path(root) / ".venv" / "bin" / "python"
    if not candidate.is_file():
        return sys.executable
    candidate_str = str(candidate)
    if same_path(candidate, Path(sys.executable)):
        return candidate_str

    if _candidate_abi(candidate_str) == _abi_tag():
        return candidate_str
    return sys.executable


def exec_or_run(argv: List[str]) -> int:
    """Run ``argv`` as a child process.

    ``slq`` has no interactive passthrough command today, so this primitive is
    intentionally a stub. A future TTY-owning command can extend it with an
    explicit process-replacement path.
    """
    return subprocess.call(argv)
