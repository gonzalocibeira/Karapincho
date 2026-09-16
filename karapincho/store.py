# SPDX-License-Identifier: GPL-3.0-or-later
import json
import shutil
import sqlite3
import time
import uuid

from . import config


class Store:
    def __init__(self, path=None):
        self.path = path or config.DATA / "jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                status TEXT NOT NULL, stage TEXT NOT NULL, title TEXT NOT NULL,
                source TEXT NOT NULL, source_type TEXT NOT NULL,
                warnings TEXT NOT NULL DEFAULT '[]', error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                progress REAL NOT NULL DEFAULT 0)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "elapsed_seconds" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN elapsed_seconds REAL")
            if "lyric_settings" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN lyric_settings TEXT NOT NULL DEFAULT '{}'")
            if "lyric_source" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN lyric_source TEXT")
            if "started_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN started_at REAL")
            for name, declaration in {
                "processing_mode": "TEXT NOT NULL DEFAULT 'quality'",
                "export_receipt": "TEXT NOT NULL DEFAULT '{}'",
                "cleaned_at": "REAL",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_history ON jobs(created DESC, id DESC)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        result["warnings"] = json.loads(result["warnings"])
        result["lyric_settings"] = json.loads(result["lyric_settings"])
        result["cancel_requested"] = bool(result["cancel_requested"])
        result["export_receipt"] = json.loads(result["export_receipt"])
        return result

    def create(self, source_type, source, title, job_id=None, lyric_settings=None, processing_mode="quality"):
        if processing_mode not in ("quality", "fast"):
            raise ValueError("Choose Quality or Fast processing")
        job_id = job_id or uuid.uuid4().hex
        now = time.time()
        with self.connect() as db:
            db.execute(
                """INSERT INTO jobs
                (id,created,updated,status,stage,title,source,source_type,elapsed_seconds,lyric_settings,processing_mode)
                VALUES (?,?,?,'queued','acquire',?,?,?,0,?,?)""",
                (job_id, now, now, title, source, source_type,
                 json.dumps(lyric_settings or {}, ensure_ascii=False), processing_mode),
            )
        return self.get(job_id)

    def get(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def all(self):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")]

    def feed(self, limit=20, before=None):
        with self.connect() as db:
            active = [self.decode(r) for r in db.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY created,id")]
            where, params = "", []
            if before:
                cursor = db.execute("SELECT created,id FROM jobs WHERE id=?", (before,)).fetchone()
                if cursor:
                    where = " AND (created < ? OR (created = ? AND id < ?))"
                    params = [cursor["created"], cursor["created"], cursor["id"]]
            rows = [self.decode(r) for r in db.execute(
                "SELECT * FROM jobs WHERE status NOT IN ('queued','running')" + where
                + " ORDER BY created DESC,id DESC LIMIT ?", (*params, limit + 1))]
            return {"active": active, "recent": rows[:limit],
                    "next": rows[limit - 1]["id"] if len(rows) > limit else None}

    def settings(self):
        with self.connect() as db:
            return dict(db.execute("SELECT key,value FROM settings").fetchall())

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, value))

    def update(self, job_id, **values):
        allowed = {"status", "stage", "title", "warnings", "error", "cancel_requested", "progress", "lyric_source"}
        allowed |= {"export_receipt", "cleaned_at"}
        if not values.keys() <= allowed:
            raise ValueError("Invalid job fields")
        if "warnings" in values:
            values["warnings"] = json.dumps(values["warnings"], ensure_ascii=False)
        if "export_receipt" in values:
            values["export_receipt"] = json.dumps(values["export_receipt"], ensure_ascii=False)
        values["updated"] = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row and "status" in values and values["status"] != "running" and row["started_at"] is not None:
                values["elapsed_seconds"] = (row["elapsed_seconds"] or 0) + max(
                    0, values["updated"] - row["started_at"]
                )
                values["started_at"] = None
            db.execute(
                f"UPDATE jobs SET {','.join(k + '=?' for k in values)} WHERE id=?", (*values.values(), job_id)
            )

    def rebuild(self, job_id, settings, processing_mode=None):
        if processing_mode is not None and processing_mode not in ("quality", "fast"):
            raise ValueError("Choose Quality or Fast processing")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,cleaned_at,processing_mode FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in ("completed", "failed", "cancelled"):
                raise ValueError("Wait for the song to stop before correcting lyrics")
            if row["cleaned_at"] is not None:
                raise ValueError("Working files were cleaned up. Create a new job to process this song again.")
            db.execute("UPDATE jobs SET lyric_settings=?, status='queued', cancel_requested=0, "
                       "error=NULL, warnings='[]', progress=0, lyric_source=NULL, processing_mode=?, updated=? WHERE id=?",
                       (json.dumps(settings, ensure_ascii=False), processing_mode or row["processing_mode"],
                        time.time(), job_id))
        return self.get(job_id)

    def recover(self):
        with self.connect() as db:
            # After an abrupt exit, only count through the last saved progress.
            db.execute("""UPDATE jobs SET
                elapsed_seconds=COALESCE(elapsed_seconds,0)+MAX(0,updated-started_at),
                started_at=NULL WHERE started_at IS NOT NULL""")
            db.execute(
                "UPDATE jobs SET status='cancelled' WHERE cancel_requested=1 AND status IN ('running','queued')"
            )
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def next(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                now = time.time()
                db.execute(
                    "UPDATE jobs SET status='running', updated=?, started_at=?, "
                    "elapsed_seconds=COALESCE(elapsed_seconds,0) WHERE id=?", (now, now, row["id"])
                )
                row = db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            return self.decode(row)

    def request_cancel(self, job_id):
        with self.connect() as db:
            # A queued song may be claimed between the API read and this write.
            db.execute(
                "UPDATE jobs SET cancel_requested=1, "
                "status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END, updated=? "
                "WHERE id=? AND status IN ('queued','running')", (time.time(), job_id)
            )

    def delete(self, job_id):
        with self.connect() as db:
            # Serialize with retry and worker claims so files cannot be deleted mid-generation.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in ("completed", "failed", "cancelled"):
                raise ValueError("Cancel the song and wait for it to stop before deleting it")
            for category in ("jobs", "library"):
                folder = config.DATA / category / job_id
                if folder.is_symlink():
                    folder.unlink()
                elif folder.exists():
                    shutil.rmtree(folder)
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
