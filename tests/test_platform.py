import os
import sys
from pathlib import Path

from slq import platform


def test_same_path_for_identical_file(tmp_path: Path) -> None:
    p = tmp_path / "a"
    p.write_text("x")
    assert platform.same_path(p, p) is True


def test_same_path_for_symlink_and_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("x")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert platform.same_path(target, link) is True


def test_same_path_for_different_files(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("x")
    b.write_text("y")
    assert platform.same_path(a, b) is False


def test_same_path_for_resolved_nonexistent_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    link.symlink_to(target)
    other = tmp_path / "other"
    other.symlink_to(target)
    assert platform.same_path(link, other) is True


def _make_venv_python(tmp_path: Path, contents: bytes) -> Path:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    candidate = venv_bin / "python"
    candidate.write_bytes(contents)
    os.chmod(candidate, 0o755)
    return candidate


def test_compatible_python_prefers_same_interpreter(tmp_path: Path) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    candidate = venv_bin / "python"
    candidate.symlink_to(sys.executable)
    assert platform.compatible_python(str(tmp_path)) == str(candidate)


def test_compatible_python_falls_back_on_mismatch(tmp_path: Path) -> None:
    _make_venv_python(tmp_path, b"not an executable\n")
    assert platform.compatible_python(str(tmp_path)) == sys.executable


def test_compatible_python_does_not_trust_matching_binary_magic(tmp_path: Path) -> None:
    source = Path(sys.executable)
    _make_venv_python(tmp_path, source.read_bytes()[:1024])
    assert platform.compatible_python(str(tmp_path)) == sys.executable


def test_compatible_python_falls_back_on_missing_venv(tmp_path: Path) -> None:
    assert platform.compatible_python(str(tmp_path)) == sys.executable


def test_logical_cwd_prefers_pwd_when_same_directory(tmp_path: Path) -> None:
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        os.environ["PWD"] = str(tmp_path)
        assert platform.logical_cwd() == tmp_path
    finally:
        os.chdir(original)


def test_logical_cwd_falls_back_to_getcwd_when_pwd_differs(tmp_path: Path) -> None:
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        os.environ["PWD"] = "/not/the/same/directory"
        assert platform.logical_cwd() == Path(tmp_path)
    finally:
        os.chdir(original)


def test_compatible_python_uses_venv_with_different_magic_but_same_abi(tmp_path: Path) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    candidate = venv_bin / "python"
    candidate.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if len(sys.argv) >= 3 and sys.argv[1] == '-c':\n"
        "    exec(compile(sys.argv[2], '<string>', 'exec'))\n"
    )
    os.chmod(candidate, 0o755)
    assert platform.compatible_python(str(tmp_path)) == str(candidate)


def test_compatible_python_falls_back_on_abi_mismatch(tmp_path: Path) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    candidate = venv_bin / "python"
    candidate.write_text("#!/bin/sh\nprintf 'foreign:big:0:0.0:other\\n'\n")
    os.chmod(candidate, 0o755)
    assert platform.compatible_python(str(tmp_path)) == sys.executable
