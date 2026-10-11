"""install.json, the shared lock and ``.env`` editing (CRLF, quotes, ``export``, duplicates, mode 0600)."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from pitwall.install.layout import (
    EXIT_NEEDS_USER,
    InstallError,
    InstallState,
    ensure_data_dir_line,
    env_port,
    install_lock,
    is_anchored,
    load_state,
    read_env_value,
    save_state,
    version_dir,
    write_private_text,
)

DATE = "2026-10-11"


def test_state_round_trip_is_atomic_and_validated(tmp_path: Path) -> None:
    st = InstallState(
        home=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        current="v0.2.0",
        previous="v0.1.0",
        versions=["v0.2.0", "v0.1.0", "v0.10.0-rc.1"],
        service="launchd",
        installed_by="install.sh",
        updated_unix=1.5,
    )
    save_state(tmp_path, st)
    raw = json.loads((tmp_path / "install.json").read_text())
    assert raw["schema"] == 1 and raw["versions"] == ["v0.1.0", "v0.2.0", "v0.10.0-rc.1"] and raw["staged"] is None
    assert set(raw) == {
        "schema", "home", "data_dir", "current", "previous", "staged", "versions", "service", "installed_by", "updated_unix",
    }  # fmt: skip
    assert load_state(tmp_path) == st
    assert not list(tmp_path.glob(".install.json.*"))  # the temporary file was renamed into place
    (tmp_path / "install.json").write_text('{"schema": 2, "current": "v0.2.0"}')
    assert load_state(tmp_path) is None
    (tmp_path / "install.json").write_text('{"schema": 1, "current": "../x"}')
    assert load_state(tmp_path) is None
    (tmp_path / "install.json").write_text("{")
    assert load_state(tmp_path) is None
    with pytest.raises(InstallError):
        version_dir(tmp_path, "../../etc")


def test_lock_is_exclusive_and_a_stale_one_is_taken_over(tmp_path: Path) -> None:
    with install_lock(tmp_path) as lock:
        assert lock.is_dir()
        with pytest.raises(InstallError) as e, install_lock(tmp_path):
            pass
        assert e.value.code == EXIT_NEEDS_USER
    assert not (tmp_path / ".install.lock").exists()
    stale = tmp_path / ".install.lock"
    stale.mkdir()
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    with install_lock(tmp_path):
        pass
    assert not stale.exists()


def test_read_env_value_and_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nexport PITWALL_HTTP_PORT=8831\r\nPITWALL_DATA_DIR='/x y/data' # data\npitwall_http_port = \"8832\"\n",
        encoding="utf-8",
    )
    assert read_env_value(env, "PITWALL_DATA_DIR") == "/x y/data"
    assert read_env_value(env, "PITWALL_HTTP_PORT") == "8832"  # last one wins; names ignore case, like the server
    monkeypatch.delenv("PITWALL_HTTP_PORT", raising=False)
    assert env_port(env) == 8832
    monkeypatch.setenv("PITWALL_HTTP_PORT", "8833")
    assert env_port(env) == 8833
    monkeypatch.delenv("PITWALL_HTTP_PORT")
    assert env_port(tmp_path / "missing") == 8770
    assert read_env_value(tmp_path / "missing", "X") is None


def test_env_line_added_when_missing_keeping_crlf(tmp_path: Path) -> None:
    data = tmp_path / "data"
    text = "# my settings\r\nPITWALL_LLM_ENABLED=false\r\n"
    e = ensure_data_dir_line(text, data, base=None, rewrite_relative=True, date=DATE)
    assert e.changed and "\n" not in e.text.replace("\r\n", "")  # every line ending is CRLF
    assert e.text.startswith(text)
    assert e.text.endswith(f"PITWALL_DATA_DIR={data}\r\n")
    assert str(data) not in e.note  # the note never carries values


def test_env_absolute_kept_and_relative_rewritten(tmp_path: Path) -> None:
    data = tmp_path / "data"
    keep = 'export PITWALL_DATA_DIR="/Users/me/pitwall-data"  # mine\nPITWALL_TTS_VOICE=bm_fable\n'
    e = ensure_data_dir_line(keep, data, base=tmp_path / "pitwall-v0.1.0", rewrite_relative=True, date=DATE)
    assert not e.changed and e.text == keep
    rel = "PITWALL_TTS_VOICE=bm_fable\nexport PITWALL_DATA_DIR = data\n"
    e = ensure_data_dir_line(rel, data, base=tmp_path / "pitwall-v0.1.0", rewrite_relative=True, date=DATE)
    lines = e.text.splitlines()
    assert e.changed and lines[0] == "PITWALL_TTS_VOICE=bm_fable"
    assert lines[1].startswith("# Rewritten by the Pitwall installer") and "'data'" in lines[1]
    assert lines[2] == f"export PITWALL_DATA_DIR = {data}"
    e = ensure_data_dir_line(rel, data, base=None, rewrite_relative=False, date=DATE)
    assert not e.changed


def test_env_duplicates_are_commented_out(tmp_path: Path) -> None:
    text = "PITWALL_DATA_DIR=/a\nPITWALL_DATA_DIR=/b\n"
    e = ensure_data_dir_line(text, tmp_path, base=None, rewrite_relative=True, date=DATE)
    lines = e.text.splitlines()
    assert lines[0].startswith("# disabled by the Pitwall installer") and lines[0].endswith("PITWALL_DATA_DIR=/a")
    assert lines[1] == "PITWALL_DATA_DIR=/b"
    assert read_env_value_text(e.text) == "/b"


def read_env_value_text(text: str) -> str | None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".env"
        p.write_text(text, encoding="utf-8")
        return read_env_value(p, "PITWALL_DATA_DIR")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_private_write_is_0600(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    write_private_text(p, b"A=1\n")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and p.read_bytes() == b"A=1\n"


def test_rooted_windows_paths_are_kept() -> None:
    """``\\data`` or ``/data`` on Windows is on the current drive, not inside the version folder: never rewritten."""
    assert is_anchored(PureWindowsPath("C:/Pitwall/data")) and is_anchored(PureWindowsPath("/Pitwall/data"))
    assert is_anchored(PureWindowsPath("\\\\server\\share\\data")) and is_anchored(PurePosixPath("/srv/data"))
    assert not is_anchored(PureWindowsPath("data")) and not is_anchored(PurePosixPath("data"))


def test_private_write_is_byte_for_byte(tmp_path: Path) -> None:
    """No newline translation (``os.open`` is in text mode on Windows unless asked for binary)."""
    p = tmp_path / ".env"
    data = b"# mine\r\nA=1\r\nB=2\n" + "C=caf\u00e9\n".encode()
    write_private_text(p, data)
    assert p.read_bytes() == data
