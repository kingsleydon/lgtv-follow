import os
import pickle
import sqlite3
import stat

from lgtv_follow.keys import KeyStore


def legacy_db(path, host, value: bytes):
    """A key database as bscpylgtv's sqlitedict wrote it."""
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unnamed (key TEXT PRIMARY KEY, value BLOB)")
        db.execute("INSERT INTO unnamed VALUES (?, ?)", (host, value))
    return path


def test_set_and_get_keep_the_file_private(tmp_path):
    keys = KeyStore(tmp_path / "keys.json", tmp_path / "none.sqlite")
    keys.set("10.0.0.2", "abc")
    assert keys.get("10.0.0.2") == "abc" and keys.get("10.0.0.3") is None
    assert stat.S_IMODE(os.stat(keys.path).st_mode) == 0o600


def test_imports_a_key_from_older_versions(tmp_path):
    legacy = legacy_db(tmp_path / "tv-key.sqlite", "10.0.0.2", pickle.dumps("old-key"))
    keys = KeyStore(tmp_path / "keys.json", legacy)
    assert keys.get("10.0.0.2") == "old-key"
    legacy.unlink()
    assert keys.get("10.0.0.2") == "old-key"  # carried over


def test_legacy_import_runs_no_code(tmp_path):
    class Exploit:
        def __reduce__(self):
            return (os.system, (f"touch {tmp_path / 'pwned'}",))

    legacy = legacy_db(tmp_path / "tv-key.sqlite", "10.0.0.2", pickle.dumps(Exploit()))
    assert KeyStore(tmp_path / "keys.json", legacy).get("10.0.0.2") is None
    assert not (tmp_path / "pwned").exists()
