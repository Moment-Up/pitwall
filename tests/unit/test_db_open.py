"""Opening the database: Windows retries a transient "database is locked" (openers racing on one file); macOS keeps
raising at once, as before."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pitwall.storage import db as db_mod


def _flaky_connect(monkeypatch: pytest.MonkeyPatch, error: str, failures: int) -> list[int]:
    real = db_mod.Database.connect
    calls: list[int] = []

    def connect(self: db_mod.Database) -> sqlite3.Connection:
        calls.append(1)
        if len(calls) <= failures:
            raise sqlite3.OperationalError(error)
        return real(self)

    monkeypatch.setattr(db_mod.Database, "connect", connect)
    monkeypatch.setattr(db_mod.time, "sleep", lambda _s: None)
    return calls


def test_windows_retries_a_locked_database_while_opening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "is_windows", lambda: True)
    calls = _flaky_connect(monkeypatch, "database is locked", failures=2)
    db = db_mod.Database(tmp_path / "pitwall.sqlite3")
    assert len(calls) == 3
    with db.read() as c:
        assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(
            db_mod.SCHEMA_VERSION
        )


def test_windows_gives_up_after_the_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "is_windows", lambda: True)
    calls = _flaky_connect(monkeypatch, "database is locked", failures=99)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db_mod.Database(tmp_path / "pitwall.sqlite3")
    assert len(calls) == len(db_mod._OPEN_RETRY_S) + 1


def test_other_errors_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "is_windows", lambda: True)
    calls = _flaky_connect(monkeypatch, "disk I/O error", failures=1)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        db_mod.Database(tmp_path / "pitwall.sqlite3")
    assert len(calls) == 1


def test_macos_raises_a_locked_database_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_mod, "is_windows", lambda: False)
    calls = _flaky_connect(monkeypatch, "database is locked", failures=1)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db_mod.Database(tmp_path / "pitwall.sqlite3")
    assert len(calls) == 1  # unchanged behaviour: no retry
