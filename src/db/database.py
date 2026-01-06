"""SQLite database management for storing ad fingerprints."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from config.settings import DEFAULT_DB_FILE
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AdRecord:
    """Represents a stored advertisement."""

    id: int
    name: str
    duration_seconds: float
    fingerprint_count: int
    created_at: datetime
    tags: list[str]


@dataclass
class FingerprintRecord:
    """Represents a single fingerprint hash."""

    id: int
    ad_id: int
    hash_value: str
    time_offset: float


@dataclass
class DatabaseStats:
    """Database statistics."""

    total_ads: int
    total_fingerprints: int
    db_size_bytes: int


class Database:
    """SQLite database for ad fingerprints."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    duration_seconds REAL NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    hash_value TEXT NOT NULL,
                    time_offset REAL NOT NULL,
                    FOREIGN KEY (ad_id) REFERENCES ads(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_fingerprints_hash
                ON fingerprints(hash_value);

                CREATE INDEX IF NOT EXISTS idx_fingerprints_ad_id
                ON fingerprints(ad_id);
                """
            )
        logger.debug(f"Database initialized at {self.db_path}")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_ad(
        self,
        name: str,
        duration_seconds: float,
        fingerprints: list[tuple[str, float]],
        tags: list[str] | None = None,
    ) -> int:
        """Add a new ad with its fingerprints.

        Args:
            name: Unique name for the ad
            duration_seconds: Duration of the audio
            fingerprints: List of (hash_value, time_offset) tuples
            tags: Optional tags for categorization

        Returns:
            ID of the created ad record
        """
        tags_str = ",".join(tags or [])

        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ads (name, duration_seconds, tags)
                VALUES (?, ?, ?)
                """,
                (name, duration_seconds, tags_str),
            )
            ad_id = cursor.lastrowid

            if ad_id is None:
                raise RuntimeError("Failed to insert ad record")

            # Bulk insert fingerprints
            conn.executemany(
                """
                INSERT INTO fingerprints (ad_id, hash_value, time_offset)
                VALUES (?, ?, ?)
                """,
                [(ad_id, h, t) for h, t in fingerprints],
            )

            logger.info(
                f"Added ad '{name}' with {len(fingerprints)} fingerprints"
            )
            return ad_id

    def get_ad(self, name: str) -> AdRecord | None:
        """Get ad by name."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, COUNT(f.id) as fingerprint_count
                FROM ads a
                LEFT JOIN fingerprints f ON a.id = f.ad_id
                WHERE a.name = ?
                GROUP BY a.id
                """,
                (name,),
            ).fetchone()

            if not row:
                return None

            return AdRecord(
                id=row["id"],
                name=row["name"],
                duration_seconds=row["duration_seconds"],
                fingerprint_count=row["fingerprint_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
                tags=row["tags"].split(",") if row["tags"] else [],
            )

    def list_ads(self) -> list[AdRecord]:
        """List all stored ads."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT a.*, COUNT(f.id) as fingerprint_count
                FROM ads a
                LEFT JOIN fingerprints f ON a.id = f.ad_id
                GROUP BY a.id
                ORDER BY a.created_at DESC
                """
            ).fetchall()

            return [
                AdRecord(
                    id=row["id"],
                    name=row["name"],
                    duration_seconds=row["duration_seconds"],
                    fingerprint_count=row["fingerprint_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    tags=row["tags"].split(",") if row["tags"] else [],
                )
                for row in rows
            ]

    def delete_ad(self, name: str) -> bool:
        """Delete an ad and its fingerprints.

        Returns:
            True if ad was deleted, False if not found
        """
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM ads WHERE name = ?",
                (name,),
            )
            deleted = cursor.rowcount > 0

            if deleted:
                logger.info(f"Deleted ad '{name}'")
            return deleted

    def delete_all_ads(self) -> int:
        """Delete all ads.

        Returns:
            Number of ads deleted
        """
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM ads")
            count = cursor.rowcount
            logger.info(f"Deleted {count} ads")
            return count

    def find_matches(
        self,
        hashes: list[str],
        min_matches: int = 5,
    ) -> list[tuple[str, int, float]]:
        """Find ads matching the given fingerprint hashes.

        Args:
            hashes: List of fingerprint hashes to match
            min_matches: Minimum number of matching hashes required

        Returns:
            List of (ad_name, match_count, confidence) tuples, sorted by confidence
        """
        if not hashes:
            return []

        with self._connection() as conn:
            placeholders = ",".join("?" * len(hashes))
            rows = conn.execute(
                f"""
                SELECT a.name, COUNT(f.id) as match_count,
                       COUNT(f.id) * 1.0 / (
                           SELECT COUNT(*) FROM fingerprints
                           WHERE ad_id = a.id
                       ) as confidence
                FROM fingerprints f
                JOIN ads a ON f.ad_id = a.id
                WHERE f.hash_value IN ({placeholders})
                GROUP BY a.id
                HAVING match_count >= ?
                ORDER BY confidence DESC
                """,
                (*hashes, min_matches),
            ).fetchall()

            return [
                (row["name"], row["match_count"], row["confidence"])
                for row in rows
            ]

    def get_all_fingerprints(self, ad_name: str) -> list[FingerprintRecord]:
        """Get all fingerprints for a specific ad."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT f.* FROM fingerprints f
                JOIN ads a ON f.ad_id = a.id
                WHERE a.name = ?
                ORDER BY f.time_offset
                """,
                (ad_name,),
            ).fetchall()

            return [
                FingerprintRecord(
                    id=row["id"],
                    ad_id=row["ad_id"],
                    hash_value=row["hash_value"],
                    time_offset=row["time_offset"],
                )
                for row in rows
            ]

    def get_stats(self) -> DatabaseStats:
        """Get database statistics."""
        with self._connection() as conn:
            ad_count = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
            fp_count = conn.execute(
                "SELECT COUNT(*) FROM fingerprints"
            ).fetchone()[0]

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return DatabaseStats(
            total_ads=ad_count,
            total_fingerprints=fp_count,
            db_size_bytes=db_size,
        )

    def vacuum(self) -> None:
        """Optimize database by running VACUUM."""
        with self._connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuumed")
