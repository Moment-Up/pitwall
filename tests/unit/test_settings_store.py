from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from pitwall.settings_store import SecretStore, SettingsStore, mask_secret


def test_sections_persist_merge_and_delete(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    s = SettingsStore(p)
    assert s.get("rig") == {}
    s.update("rig", {"wheel_base": "fanatec_gt_dd_pro", "torque_nm": 5})
    s.update("rig", {"torque_nm": 8, "pedals": "csl"})
    s.update("rig", {"pedals": None})
    assert SettingsStore(p).get("rig") == {"wheel_base": "fanatec_gt_dd_pro", "torque_nm": 8}
    if sys.platform != "win32":  # Windows has no mode bits: the folder's ACL keeps the file private
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_files_are_utf8_with_unix_newlines_on_every_os(tmp_path: Path) -> None:
    """Windows' default text encoding (cp1252) and newline (CRLF) must not leak into the data folder: the same
    files are read on a Mac and a PC."""
    p = tmp_path / "settings.json"
    SettingsStore(p).update("drivers", {"name": "José 李", "track": "Ste. Dévote"})
    raw = p.read_bytes()
    assert b"\r\n" not in raw and b"\n" in raw
    raw.decode("utf-8")  # never a locale code page
    assert SettingsStore(p).get("drivers") == {"name": "José 李", "track": "Ste. Dévote"}
    sec = tmp_path / "secrets.json"
    SecretStore(sec).set("custom_api_key", "kéy-🔑")
    assert b"\r\n" not in sec.read_bytes() and SecretStore(sec).get("custom_api_key") == "kéy-🔑"


def test_get_returns_a_copy(tmp_path: Path) -> None:
    s = SettingsStore(tmp_path / "s.json")
    s.update("llm", {"providers": {"a": {"model": "x"}}})
    got = s.get("llm")
    got["providers"]["a"]["model"] = "mutated"
    assert s.get("llm")["providers"]["a"]["model"] == "x"


def test_listener_called_after_save_and_failures_isolated(tmp_path: Path) -> None:
    s = SettingsStore(tmp_path / "s.json")
    seen: list[tuple[str, dict[str, Any]]] = []

    def boom(_section: str, _values: dict[str, Any]) -> None:
        raise RuntimeError("listener bug")

    s.subscribe("rig", boom)
    unsub = s.subscribe("rig", lambda sec, v: seen.append((sec, v)))
    s.update("rig", {"a": 1})
    unsub()
    s.update("rig", {"a": 2})
    assert seen == [("rig", {"a": 1})]


def test_unserialisable_value_rejected_without_touching_disk(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    s = SettingsStore(p)
    s.update("x", {"ok": 1})
    with pytest.raises(TypeError):
        s.update("x", {"bad": object()})
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": {"ok": 1}}
    assert s.get("x") == {"ok": 1}


def test_corrupt_file_is_kept_aside(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    s = SettingsStore(p)
    assert s.get("anything") == {}
    assert (tmp_path / "s.json.corrupt").read_text(encoding="utf-8") == "{not json"


def test_secrets_masked_env_override_and_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "secrets.json"
    s = SecretStore(p)
    s.set("anthropic_api_key", "sk-ant-api03-abcdefghijklmnop1234")
    if sys.platform != "win32":  # Windows has no mode bits: the folder's ACL keeps the file private
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert SecretStore(p).get("anthropic_api_key") == "sk-ant-api03-abcdefghijklmnop1234"
    shown = s.masked()["anthropic_api_key"]
    assert shown["source"] == "file" and shown["masked"] is not None
    assert "abcdefghijklmnop" not in shown["masked"] and shown["masked"].endswith("1234")
    monkeypatch.setenv("PITWALL_ANTHROPIC_API_KEY", "from-env-key-9999")
    assert s.get("anthropic_api_key") == "from-env-key-9999" and s.source("anthropic_api_key") == "env"
    monkeypatch.delenv("PITWALL_ANTHROPIC_API_KEY")
    s.set("anthropic_api_key", "")
    assert s.get("anthropic_api_key") is None and "anthropic_api_key" not in s.masked()


def test_mask_short_values_fully() -> None:
    assert mask_secret("abc") == "•••"
    assert "secret-middle" not in mask_secret("prefix-secret-middle-tail")
