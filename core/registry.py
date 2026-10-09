"""SQLite registry of issued documents. One row per (doc_id, version). Stdlib sqlite3 only."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from core import data_dir

_COLS = ("doc_id", "version", "kid", "title", "source_name", "source_type", "pages",
         "source_sha256", "content_sha256", "file_sha256")
_SCHEMA = """CREATE TABLE IF NOT EXISTS docs (
    doc_id TEXT NOT NULL, version INTEGER NOT NULL, kid TEXT NOT NULL, title TEXT NOT NULL,
    source_name TEXT NOT NULL, source_type TEXT NOT NULL, pages INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL, content_sha256 TEXT NOT NULL, file_sha256 TEXT NOT NULL,
    status TEXT NOT NULL, issued_at TEXT NOT NULL, PRIMARY KEY (doc_id, version))"""
_INDEX = "CREATE INDEX IF NOT EXISTS docs_file_sha256 ON docs (file_sha256)"
_SELECT = """SELECT d.*, (SELECT MAX(version) FROM docs WHERE doc_id = d.doc_id) AS current_version FROM docs d"""


class Registry:
    """Entry dicts returned by get()/find_file()/list():
    {"doc_id", "version": int, "kid", "title", "source_name", "source_type" (txt|docx|pdf|xls|xlsx), "pages": int,
     "source_sha256" (the upload), "content_sha256" (converted PDF), "file_sha256" (issued PDF),
     "status": "active" | "revoked" | "superseded", "issued_at": ISO-8601 UTC str,
     "current_version": int (highest version of doc_id)}
    Open a new sqlite3 connection per call (the API is threaded); create the table if missing.
    v1 databases (fields/seal columns) are not migrated: delete runtime/registry.db before running v2.
    """

    def __init__(self, db_path: Path | None = None):
        """db_path defaults to core.data_dir() / "registry.db"."""
        self.db_path = Path(db_path) if db_path else data_dir() / "registry.db"

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        c.execute(_SCHEMA)
        c.execute(_INDEX)
        return c

    def next_version(self, doc_id: str) -> int:
        """1 for an unknown doc_id, else highest version + 1."""
        with closing(self._conn()) as c:
            return c.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()[0]

    def issue(self, entry: dict) -> None:
        """Insert as active and, in the same transaction, mark every earlier *active* version of doc_id as superseded.
        Raises ValueError if (doc_id, version) already exists, KeyError if entry lacks a column."""
        vals = [entry[k] for k in _COLS]
        with closing(self._conn()) as c, c:  # `with c` = one transaction, rolled back on error
            try:
                c.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?, 'active', ?)",
                          (*vals, datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"{entry['doc_id']} v{entry['version']} already exists") from e
            c.execute("UPDATE docs SET status = 'superseded' WHERE doc_id = ? AND version < ? AND status = 'active'",
                      (entry["doc_id"], entry["version"]))

    def get(self, doc_id: str, version: int | None = None) -> dict | None:
        """One entry (latest version when version is None), or None."""
        with closing(self._conn()) as c:
            row = c.execute(_SELECT + " WHERE d.doc_id = ? AND (? IS NULL OR d.version = ?) ORDER BY d.version DESC LIMIT 1",
                            (doc_id, version, version)).fetchone()
        return dict(row) if row else None

    def find_file(self, file_sha256: str) -> dict | None:
        """The entry whose issued PDF has this SHA-256, or None."""
        with closing(self._conn()) as c:
            row = c.execute(_SELECT + " WHERE d.file_sha256 = ? LIMIT 1", (file_sha256,)).fetchone()
        return dict(row) if row else None

    def revoke(self, doc_id: str) -> bool:
        """Mark every active version of doc_id as revoked. False if doc_id is unknown."""
        with closing(self._conn()) as c, c:
            known = c.execute("SELECT 1 FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
            c.execute("UPDATE docs SET status = 'revoked' WHERE doc_id = ? AND status = 'active'", (doc_id,))
        return bool(known)

    def list(self) -> list[dict]:
        """All entries, newest issued_at first."""
        with closing(self._conn()) as c:
            return [dict(r) for r in c.execute(_SELECT + " ORDER BY d.issued_at DESC, d.version DESC")]
