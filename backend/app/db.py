"""Small SQLite repository with durable, explicit job state transitions."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid.uuid4().hex


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 prompt TEXT NOT NULL DEFAULT '', consent_confirmed INTEGER NOT NULL CHECK(consent_confirmed=1),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id), category TEXT NOT NULL,
 filename TEXT NOT NULL, media_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
 relative_path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_character ON assets(character_id, created_at);
CREATE TABLE IF NOT EXISTS presets (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id), name TEXT NOT NULL,
 parameters TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, module TEXT NOT NULL, workflow TEXT NOT NULL,
 mapping TEXT NOT NULL, inspection TEXT NOT NULL, validation TEXT,
 original_path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, module TEXT NOT NULL, character_id TEXT NOT NULL REFERENCES characters(id),
 workflow_id TEXT NOT NULL REFERENCES workflows(id), status TEXT NOT NULL,
 parameters TEXT NOT NULL, asset_inputs TEXT NOT NULL, prompt_id TEXT,
 client_id TEXT NOT NULL, progress TEXT, error TEXT, output_assets TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS job_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_characters (
 character_id TEXT PRIMARY KEY REFERENCES characters(id), active_revision_id TEXT,
 principal_asset_id TEXT REFERENCES assets(id), default_outfit_asset_id TEXT REFERENCES assets(id)
);
CREATE TABLE IF NOT EXISTS lab_revisions (
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id),
 sheet_asset_id TEXT NOT NULL REFERENCES assets(id), created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lab_revision_character ON lab_revisions(character_id,created_at);
CREATE TABLE IF NOT EXISTS lab_assets (
 asset_id TEXT PRIMARY KEY REFERENCES assets(id), character_id TEXT NOT NULL REFERENCES characters(id),
 stage TEXT NOT NULL, category TEXT NOT NULL, approval TEXT NOT NULL DEFAULT 'pending',
 priority INTEGER NOT NULL DEFAULT 0, revision_id TEXT REFERENCES lab_revisions(id),
 legacy INTEGER NOT NULL DEFAULT 0, outfit_name TEXT, job_id TEXT REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS lab_asset_character ON lab_assets(character_id,stage,revision_id);
CREATE TABLE IF NOT EXISTS lab_workflows (
 workflow_id TEXT PRIMARY KEY REFERENCES workflows(id), stage TEXT NOT NULL,
 config TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_jobs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), character_id TEXT NOT NULL REFERENCES characters(id),
 stage TEXT NOT NULL, revision_id TEXT REFERENCES lab_revisions(id), context TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(characters)")}
            if "attributes" not in columns:
                conn.execute("ALTER TABLE characters ADD COLUMN attributes TEXT NOT NULL DEFAULT '{}'")
            if conn.execute("PRAGMA user_version").fetchone()[0] < 3:
                conn.execute("PRAGMA user_version=3")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def one(self, sql: str, args=()):
        with self.connect() as conn:
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, args=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def execute(self, sql: str, args=()):
        with self.connect() as conn:
            return conn.execute(sql, args).rowcount

    def transition(self, job_id: str, status: str, *, allowed=None, error=None, prompt_id=None, outputs=None, detail=None):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or (allowed and row["status"] not in allowed):
                return False
            conn.execute("UPDATE jobs SET status=?,error=?,prompt_id=COALESCE(?,prompt_id),output_assets=COALESCE(?,output_assets),updated_at=? WHERE id=?", (status, encode(error) if error else None, prompt_id, encode(outputs) if outputs is not None else None, now(), job_id))
            conn.execute("INSERT INTO job_events(job_id,status,detail,created_at) VALUES(?,?,?,?)", (job_id, status, encode(detail) if detail is not None else None, now()))
            return True


class InstanceLock:
    """An OS lock prevents two local servers submitting the same persistent queue."""
    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def acquire(self):
        try:
            import os
            self.handle = open(self.path, "a+b")
            # Windows denies reading a byte another process has locked; use stat instead.
            if os.fstat(self.handle.fileno()).st_size == 0:
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            if self.handle:
                self.handle.close()
            self.handle = None
            raise RuntimeError("This data directory already has a running CharacterLock backend. Use one API process.") from exc

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None
