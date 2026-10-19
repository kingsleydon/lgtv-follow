"""Pairing keys, one per TV address, in a small JSON file only the user can read."""

import io
import pickle
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import KEY_PATH, LEGACY_KEY_PATH
from .state import read_json, write_json


class KeyStore:
    def __init__(self, path: Path = KEY_PATH, legacy_path: Path = LEGACY_KEY_PATH):
        self.path = path
        self.legacy_path = legacy_path

    def get(self, host: str) -> str | None:
        key = read_json(self.path).get(host)
        if key is None and (key := _legacy_key(self.legacy_path, host)):
            self.set(host, key)  # carry it over, so upgrading never means pairing again
        return key

    def set(self, host: str, key: str):
        write_json(self.path, {**read_json(self.path), host: key}, mode=0o600)


class _StrOnly(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError("not a plain string")


def _legacy_key(path: Path, host: str) -> str | None:
    """A key stored by versions before 0.3 (bscpylgtv's sqlitedict: a pickled string per host)."""
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM unnamed WHERE key = ?", (host,)).fetchone()
        key = row and _StrOnly(io.BytesIO(row[0])).load()  # strings need no classes: nothing runs
    except Exception:
        return None  # unreadable: pair again
    return key if isinstance(key, str) else None
