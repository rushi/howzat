"""SQLite database for storing ad fingerprints.

This module provides persistent storage for ad fingerprints. When you
record an ad, its fingerprints are stored here. When listening, we
compare live audio fingerprints against these stored ones.

DATABASE STRUCTURE:
==================

Two tables:

1. ads - Information about each stored advertisement
   - id: Unique identifier
   - name: Human-readable name (e.g., "Dream11-Ad")
   - duration_seconds: How long the original ad was
   - tags: Comma-separated tags for organization
   - created_at: When the ad was recorded

2. fingerprints - The actual fingerprint hashes
   - id: Unique identifier
   - ad_id: Which ad this fingerprint belongs to (foreign key)
   - hash_value: The fingerprint hash (16 char hex string)
   - time_offset: When in the ad this fingerprint occurs

INDEXES:
========
- idx_fingerprints_hash: Fast lookup by hash value (critical for matching)
- idx_fingerprints_ad_id: Fast lookup by ad (for deletion)

HOW MATCHING WORKS:
==================
When we have a list of hashes from live audio, we query the database
to find which ads contain those hashes. The more hashes that match,
the higher the confidence that we're hearing that ad.

Example query (simplified):
    SELECT ad_name, COUNT(*) as matches
    FROM fingerprints
    WHERE hash_value IN (hash1, hash2, hash3, ...)
    GROUP BY ad_name
    ORDER BY matches DESC
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config.settings import DEFAULT_DB_FILE
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# DATA CLASSES (Simple containers for database records)
# =============================================================================


@dataclass
class AdRecord:
    """Information about a stored advertisement.

    Attributes:
        id: Database primary key
        name: Human-readable ad name (e.g., "Dream11-Ad")
        duration_seconds: Original ad duration
        fingerprint_count: How many fingerprints this ad has
        created_at: When the ad was recorded
        tags: List of tags for organization
    """

    id: int
    name: str
    duration_seconds: float
    fingerprint_count: int
    created_at: datetime
    tags: list[str]


@dataclass
class FingerprintRecord:
    """A single fingerprint hash from the database.

    Attributes:
        id: Database primary key
        ad_id: ID of the ad this fingerprint belongs to
        hash_value: The actual fingerprint hash (16 char hex string)
        time_offset: When in the ad this fingerprint occurs (seconds)
    """

    id: int
    ad_id: int
    hash_value: str
    time_offset: float


@dataclass
class DatabaseStats:
    """Statistics about the database.

    Attributes:
        total_ads: Number of stored advertisements
        total_fingerprints: Total number of fingerprint hashes
        db_size_bytes: Size of the database file in bytes
    """

    total_ads: int
    total_fingerprints: int
    db_size_bytes: int


# =============================================================================
# MAIN DATABASE CLASS
# =============================================================================


class Database:
    """SQLite database for ad fingerprints.

    This class handles all database operations - creating tables,
    adding ads, searching for matches, etc.

    Example usage:
        db = Database()

        # Add an ad
        db.add_ad(
            name="Dream11-Ad",
            duration_seconds=30.0,
            fingerprints=[("hash1", 0.5), ("hash2", 1.0), ...]
        )

        # List all ads
        for ad in db.list_ads():
            print(f"{ad.name}: {ad.fingerprint_count} fingerprints")

        # Find matches
        matches = db.find_matches(["hash1", "hash2", ...])
        for name, count, confidence in matches:
            print(f"{name}: {count} hits, {confidence:.0%} confidence")
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize the database.

        Creates the database file and tables if they don't exist.

        Args:
            db_path: Path to database file (uses default if None)
        """
        self.db_path = db_path or DEFAULT_DB_FILE

        # Create parent directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables and indexes if they don't exist.

        This is called automatically on initialization.
        """
        with self._get_connection() as connection:
            connection.executescript(
                """
                -- Ads table: stores information about each advertisement
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    duration_seconds REAL NOT NULL,
                    tags TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                -- Fingerprints table: stores all fingerprint hashes
                CREATE TABLE IF NOT EXISTS fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ad_id INTEGER NOT NULL,
                    hash_value TEXT NOT NULL,
                    time_offset REAL NOT NULL,
                    FOREIGN KEY (ad_id) REFERENCES ads(id) ON DELETE CASCADE
                );

                -- Index on hash_value for fast lookups during matching
                CREATE INDEX IF NOT EXISTS idx_fingerprints_hash
                ON fingerprints(hash_value);

                -- Index on ad_id for fast deletion
                CREATE INDEX IF NOT EXISTS idx_fingerprints_ad_id
                ON fingerprints(ad_id);
                """
            )
        logger.debug(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with proper cleanup.

        This is a context manager that handles:
        - Opening the connection
        - Setting row_factory for dict-like access
        - Enabling foreign keys and WAL mode
        - Committing on success
        - Rolling back on error
        - Closing the connection

        Usage:
            with self._get_connection() as conn:
                conn.execute("SELECT * FROM ads")
        """
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row  # Access columns by name
        connection.execute("PRAGMA foreign_keys = ON")  # Enable foreign keys
        connection.execute("PRAGMA journal_mode = WAL")  # Better concurrent read/write
        connection.execute("PRAGMA busy_timeout = 5000")  # Wait 5s if locked

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # =========================================================================
    # ADDING ADS
    # =========================================================================

    def add_ad(
        self,
        name: str,
        duration_seconds: float,
        fingerprints: list[tuple[str, float]],
        tags: list[str] | None = None,
    ) -> int:
        """Add a new ad with its fingerprints to the database.

        Args:
            name: Unique name for this ad (e.g., "Dream11-Ad")
            duration_seconds: How long the ad is
            fingerprints: List of (hash_value, time_offset) tuples
            tags: Optional tags for organization (e.g., ["cricket", "ipl"])

        Returns:
            The database ID of the newly created ad

        Raises:
            sqlite3.IntegrityError: If an ad with this name already exists

        Example:
            ad_id = db.add_ad(
                name="Dream11-Ad",
                duration_seconds=30.0,
                fingerprints=[
                    ("abc123...", 0.5),
                    ("def456...", 1.0),
                    ...
                ],
                tags=["cricket", "betting"]
            )
        """
        # Convert tags list to comma-separated string
        tags_string = ",".join(tags or [])

        with self._get_connection() as connection:
            # Insert the ad record
            cursor = connection.execute(
                """
                INSERT INTO ads (name, duration_seconds, tags)
                VALUES (?, ?, ?)
                """,
                (name, duration_seconds, tags_string),
            )
            ad_id = cursor.lastrowid

            if ad_id is None:
                raise RuntimeError("Failed to insert ad record")

            # Insert all fingerprints in bulk (much faster than one at a time)
            fingerprint_rows = []
            for hash_value, time_offset in fingerprints:
                fingerprint_rows.append((ad_id, hash_value, time_offset))

            connection.executemany(
                """
                INSERT INTO fingerprints (ad_id, hash_value, time_offset)
                VALUES (?, ?, ?)
                """,
                fingerprint_rows,
            )

            logger.info(f"Added ad '{name}' with {len(fingerprints)} fingerprints")
            return ad_id

    # =========================================================================
    # QUERYING ADS
    # =========================================================================

    def get_ad(self, name: str) -> AdRecord | None:
        """Get an ad by its name.

        Args:
            name: The ad name to look up

        Returns:
            AdRecord if found, None if not found

        Example:
            ad = db.get_ad("Dream11-Ad")
            if ad:
                print(f"Found: {ad.fingerprint_count} fingerprints")
        """
        with self._get_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    a.*,
                    COUNT(f.id) as fingerprint_count
                FROM ads a
                LEFT JOIN fingerprints f ON a.id = f.ad_id
                WHERE a.name = ?
                GROUP BY a.id
                """,
                (name,),
            ).fetchone()

            if row is None:
                return None

            # Convert tags string back to list
            tags_list = row["tags"].split(",") if row["tags"] else []

            return AdRecord(
                id=row["id"],
                name=row["name"],
                duration_seconds=row["duration_seconds"],
                fingerprint_count=row["fingerprint_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
                tags=tags_list,
            )

    def list_ads(self) -> list[AdRecord]:
        """List all stored ads.

        Returns:
            List of AdRecord objects, sorted by creation date (newest first)

        Example:
            for ad in db.list_ads():
                print(f"{ad.name}: {ad.fingerprint_count} fingerprints")
        """
        with self._get_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.*,
                    COUNT(f.id) as fingerprint_count
                FROM ads a
                LEFT JOIN fingerprints f ON a.id = f.ad_id
                GROUP BY a.id
                ORDER BY a.name ASC
                """
            ).fetchall()

            ads = []
            for row in rows:
                tags_list = row["tags"].split(",") if row["tags"] else []
                ad = AdRecord(
                    id=row["id"],
                    name=row["name"],
                    duration_seconds=row["duration_seconds"],
                    fingerprint_count=row["fingerprint_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    tags=tags_list,
                )
                ads.append(ad)

            return ads

    # =========================================================================
    # DELETING ADS
    # =========================================================================

    def delete_ad(self, name: str) -> bool:
        """Delete an ad and all its fingerprints.

        Args:
            name: Name of the ad to delete

        Returns:
            True if the ad was deleted, False if not found

        Example:
            if db.delete_ad("Dream11-Ad"):
                print("Ad deleted")
            else:
                print("Ad not found")
        """
        with self._get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM ads WHERE name = ?",
                (name,),
            )
            was_deleted = cursor.rowcount > 0

            if was_deleted:
                logger.info(f"Deleted ad '{name}'")

            return was_deleted

    def delete_all_ads(self) -> int:
        """Delete ALL ads from the database.

        Use with caution! This removes all stored fingerprints.

        Returns:
            Number of ads that were deleted

        Example:
            count = db.delete_all_ads()
            print(f"Deleted {count} ads")
        """
        with self._get_connection() as connection:
            cursor = connection.execute("DELETE FROM ads")
            deleted_count = cursor.rowcount
            logger.info(f"Deleted {deleted_count} ads")
            return deleted_count

    def rename_ad(self, old_name: str, new_name: str) -> bool:
        """Rename an ad.

        Args:
            old_name: Current name of the ad
            new_name: New name for the ad

        Returns:
            True if renamed, False if old_name not found

        Raises:
            sqlite3.IntegrityError: If new_name already exists

        Example:
            if db.rename_ad("Old-Ad", "New-Ad"):
                print("Renamed")
        """
        with self._get_connection() as connection:
            cursor = connection.execute(
                "UPDATE ads SET name = ? WHERE name = ?",
                (new_name, old_name),
            )
            was_renamed = cursor.rowcount > 0

            if was_renamed:
                logger.info(f"Renamed ad '{old_name}' to '{new_name}'")

            return was_renamed

    # =========================================================================
    # MATCHING FINGERPRINTS
    # =========================================================================

    def find_matches(
        self,
        hash_values: list[str],
        min_matches: int = 5,
    ) -> list[tuple[str, int, float]]:
        """Find ads matching the given fingerprint hashes.

        This is the core matching function. Given a list of hashes from
        live audio, it finds which stored ads contain those hashes and
        calculates a confidence score.

        Args:
            hash_values: List of fingerprint hashes from live audio
            min_matches: Minimum matching hashes required (filters noise)

        Returns:
            List of (ad_name, match_count, confidence) tuples,
            sorted by confidence (highest first).

            confidence = matching_hashes / input_hashes

        Example:
            matches = db.find_matches(["hash1", "hash2", ...])
            if matches:
                best_name, best_count, best_conf = matches[0]
                print(f"Best match: {best_name} ({best_conf:.0%})")
        """
        # Handle empty input
        if not hash_values:
            return []

        input_hash_count = len(hash_values)

        with self._get_connection() as connection:
            # Build SQL query with placeholders for all hashes
            placeholders = ",".join("?" * len(hash_values))

            # Query to find matching ads
            # For each ad, count how many of the input hashes match
            # confidence = matches / input_hashes (what % of captured audio matched)
            rows = connection.execute(
                f"""
                SELECT
                    a.name,
                    COUNT(f.id) as match_count,
                    COUNT(f.id) * 1.0 / ? as confidence
                FROM fingerprints f
                JOIN ads a ON f.ad_id = a.id
                WHERE f.hash_value IN ({placeholders})
                GROUP BY a.id
                HAVING match_count >= ?
                ORDER BY confidence DESC
                """,
                (input_hash_count, *hash_values, min_matches),
            ).fetchall()

            # Convert to list of tuples
            results = []
            for row in rows:
                results.append((row["name"], row["match_count"], row["confidence"]))

            return results

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_all_fingerprints(self, ad_name: str) -> list[FingerprintRecord]:
        """Get all fingerprints for a specific ad.

        Useful for debugging or exporting.

        Args:
            ad_name: Name of the ad

        Returns:
            List of FingerprintRecord objects, sorted by time offset
        """
        with self._get_connection() as connection:
            rows = connection.execute(
                """
                SELECT f.*
                FROM fingerprints f
                JOIN ads a ON f.ad_id = a.id
                WHERE a.name = ?
                ORDER BY f.time_offset
                """,
                (ad_name,),
            ).fetchall()

            fingerprints = []
            for row in rows:
                fp = FingerprintRecord(
                    id=row["id"],
                    ad_id=row["ad_id"],
                    hash_value=row["hash_value"],
                    time_offset=row["time_offset"],
                )
                fingerprints.append(fp)

            return fingerprints

    def get_stats(self) -> DatabaseStats:
        """Get database statistics.

        Returns:
            DatabaseStats with counts and file size

        Example:
            stats = db.get_stats()
            print(f"Ads: {stats.total_ads}")
            print(f"Fingerprints: {stats.total_fingerprints}")
            print(f"Size: {stats.db_size_bytes / 1024:.1f} KB")
        """
        with self._get_connection() as connection:
            # Count ads
            ad_count = connection.execute("SELECT COUNT(*) FROM ads").fetchone()[0]

            # Count fingerprints
            fingerprint_count = connection.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[
                0
            ]

        # Get file size
        file_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return DatabaseStats(
            total_ads=ad_count,
            total_fingerprints=fingerprint_count,
            db_size_bytes=file_size,
        )

    def vacuum(self) -> None:
        """Optimize the database by reclaiming unused space.

        Call this after deleting many ads to reduce file size.
        """
        with self._get_connection() as connection:
            connection.execute("VACUUM")
        logger.info("Database vacuumed")
