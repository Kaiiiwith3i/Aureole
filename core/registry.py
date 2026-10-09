"""SQLite registry of issued documents. One row per (doc_id, version). Stdlib sqlite3 only."""
from pathlib import Path


class Registry:
    """Entry dicts returned by get()/list():
    {"doc_id": str, "version": int, "kid": str, "fields": dict (long keys), "seal": str,
     "status": "active" | "revoked" | "superseded", "issued_at": ISO-8601 UTC str, "current_version": int (highest version of doc_id)}
    Open a new sqlite3 connection per call (the API is threaded); create the table if missing.
    """

    def __init__(self, db_path: Path | None = None):
        """db_path defaults to core.data_dir() / "registry.db"."""
        raise NotImplementedError

    def next_version(self, doc_id: str) -> int:
        """1 for an unknown doc_id, else highest version + 1."""
        raise NotImplementedError

    def issue(self, doc_id: str, version: int, kid: str, fields: dict[str, str], seal: str) -> None:
        """Insert as active and, in the same transaction, mark every earlier *active* version of doc_id as superseded.
        Raises ValueError if (doc_id, version) already exists."""
        raise NotImplementedError

    def get(self, doc_id: str, version: int | None = None) -> dict | None:
        """One entry (latest version when version is None), or None."""
        raise NotImplementedError

    def revoke(self, doc_id: str) -> bool:
        """Mark every active version of doc_id as revoked. False if doc_id is unknown."""
        raise NotImplementedError

    def list(self) -> list[dict]:
        """All entries, newest issued_at first."""
        raise NotImplementedError
