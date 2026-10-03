"""Small durable store for one server process. SQLite commits precede emitted events."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from .config import ROOT


def connect():
    path = Path(os.environ.get("HAGGLE_DB", str(ROOT / "runs" / "haggle.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return db


def save(kind, key, data):
    with closing(connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, key, json.dumps(data, ensure_ascii=False)))


def load(kind):
    with closing(connect()) as db:
        return {key: json.loads(data) for key, data in db.execute("SELECT id,data FROM records WHERE kind=?", (kind,))}
