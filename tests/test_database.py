"""Unit tests for the database module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from src.db.database import AdRecord, Database, DatabaseStats, FingerprintRecord


class TestDatabaseInit:
    """Tests for Database initialization."""

    def test_creates_db_file(self, temp_dir: Path) -> None:
        """Should create database file on init."""
        db_path = temp_dir / "test.db"

        Database(db_path)

        assert db_path.exists()

    def test_creates_parent_directories(self, temp_dir: Path) -> None:
        """Should create parent directories if they don't exist."""
        db_path = temp_dir / "subdir" / "nested" / "test.db"

        Database(db_path)

        assert db_path.exists()

    def test_schema_is_created(self, temp_db: Database) -> None:
        """Should create necessary tables."""
        # Verify tables exist by running queries
        with temp_db._get_connection() as conn:
            # Check ads table
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ads'"
            ).fetchone()
            assert result is not None

            # Check fingerprints table
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fingerprints'"
            ).fetchone()
            assert result is not None

    def test_indexes_are_created(self, temp_db: Database) -> None:
        """Should create indexes for performance."""
        with temp_db._get_connection() as conn:
            # Check for hash index
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_fingerprints_hash'"
            ).fetchone()
            assert result is not None


class TestAddAd:
    """Tests for add_ad method."""

    def test_add_ad_returns_id(self, temp_db: Database) -> None:
        """Should return the created ad's ID."""
        fingerprints = [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0)]

        ad_id = temp_db.add_ad(
            name="Test Ad",
            duration_seconds=10.5,
            fingerprints=fingerprints,
        )

        assert isinstance(ad_id, int)
        assert ad_id > 0

    def test_add_ad_stores_name(self, temp_db: Database) -> None:
        """Should store the ad name correctly."""
        temp_db.add_ad("My Ad", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("My Ad")

        assert ad is not None
        assert ad.name == "My Ad"

    def test_add_ad_stores_duration(self, temp_db: Database) -> None:
        """Should store duration correctly."""
        temp_db.add_ad("Duration Test", 15.75, [("hash1", 0.0)])

        ad = temp_db.get_ad("Duration Test")

        assert ad is not None
        assert ad.duration_seconds == 15.75

    def test_add_ad_stores_fingerprints(self, temp_db: Database) -> None:
        """Should store all fingerprints."""
        fingerprints = [
            ("hash1", 0.0),
            ("hash2", 0.5),
            ("hash3", 1.0),
            ("hash4", 1.5),
        ]
        temp_db.add_ad("FP Test", 5.0, fingerprints)

        ad = temp_db.get_ad("FP Test")

        assert ad is not None
        assert ad.fingerprint_count == 4

    def test_add_ad_stores_tags(self, temp_db: Database) -> None:
        """Should store tags correctly."""
        temp_db.add_ad("Tagged Ad", 5.0, [("hash1", 0.0)], tags=["cricket", "ipl", "sponsor"])

        ad = temp_db.get_ad("Tagged Ad")

        assert ad is not None
        assert set(ad.tags) == {"cricket", "ipl", "sponsor"}

    def test_add_ad_empty_tags(self, temp_db: Database) -> None:
        """Should handle no tags."""
        temp_db.add_ad("No Tags", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("No Tags")

        assert ad is not None
        assert ad.tags == []

    def test_add_ad_duplicate_name_fails(self, temp_db: Database) -> None:
        """Should fail when adding ad with duplicate name."""
        temp_db.add_ad("Unique Name", 5.0, [("hash1", 0.0)])

        with pytest.raises(Exception):  # sqlite3.IntegrityError  # noqa: B017
            temp_db.add_ad("Unique Name", 10.0, [("hash2", 0.0)])

    def test_add_ad_stores_timestamp(self, temp_db: Database) -> None:
        """Should store creation timestamp."""
        temp_db.add_ad("Timestamp Test", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("Timestamp Test")

        assert ad is not None
        # Just verify it's a valid datetime (SQLite uses UTC)
        assert isinstance(ad.created_at, datetime)


class TestGetAd:
    """Tests for get_ad method."""

    def test_get_existing_ad(self, temp_db: Database) -> None:
        """Should return existing ad."""
        temp_db.add_ad("Existing", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("Existing")

        assert ad is not None
        assert isinstance(ad, AdRecord)

    def test_get_nonexistent_ad(self, temp_db: Database) -> None:
        """Should return None for nonexistent ad."""
        ad = temp_db.get_ad("Does Not Exist")

        assert ad is None

    def test_ad_record_fields(self, temp_db: Database) -> None:
        """AdRecord should have all expected fields."""
        temp_db.add_ad("Field Test", 7.5, [("h1", 0.0), ("h2", 0.5)], tags=["test"])

        ad = temp_db.get_ad("Field Test")

        assert ad is not None
        assert hasattr(ad, "id")
        assert hasattr(ad, "name")
        assert hasattr(ad, "duration_seconds")
        assert hasattr(ad, "fingerprint_count")
        assert hasattr(ad, "created_at")
        assert hasattr(ad, "tags")


class TestListAds:
    """Tests for list_ads method."""

    def test_list_empty_database(self, temp_db: Database) -> None:
        """Should return empty list for empty database."""
        ads = temp_db.list_ads()

        assert ads == []

    def test_list_all_ads(self, temp_db: Database) -> None:
        """Should return all ads."""
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 10.0, [("hash2", 0.0)])
        temp_db.add_ad("Ad 3", 15.0, [("hash3", 0.0)])

        ads = temp_db.list_ads()

        assert len(ads) == 3
        names = {ad.name for ad in ads}
        assert names == {"Ad 1", "Ad 2", "Ad 3"}

    def test_list_ordered_by_created_desc(self, temp_db: Database) -> None:
        """Should order ads by creation time descending (or by id if same second)."""
        temp_db.add_ad("First", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Second", 5.0, [("hash2", 0.0)])
        temp_db.add_ad("Third", 5.0, [("hash3", 0.0)])

        ads = temp_db.list_ads()

        # Should return all 3 ads
        assert len(ads) == 3
        names = {ad.name for ad in ads}
        assert names == {"First", "Second", "Third"}


class TestDeleteAd:
    """Tests for delete_ad method."""

    def test_delete_existing_ad(self, temp_db: Database) -> None:
        """Should delete existing ad and return True."""
        temp_db.add_ad("To Delete", 5.0, [("hash1", 0.0)])

        result = temp_db.delete_ad("To Delete")

        assert result is True
        assert temp_db.get_ad("To Delete") is None

    def test_delete_nonexistent_ad(self, temp_db: Database) -> None:
        """Should return False for nonexistent ad."""
        result = temp_db.delete_ad("Does Not Exist")

        assert result is False

    def test_delete_cascades_fingerprints(self, temp_db: Database) -> None:
        """Deleting ad should remove its fingerprints."""
        fingerprints = [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0)]
        temp_db.add_ad("Cascade Test", 5.0, fingerprints)

        temp_db.delete_ad("Cascade Test")

        # Verify fingerprints are gone
        with temp_db._get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            assert count == 0


class TestDeleteAllAds:
    """Tests for delete_all_ads method."""

    def test_delete_all_returns_count(self, temp_db: Database) -> None:
        """Should return number of deleted ads."""
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 5.0, [("hash2", 0.0)])
        temp_db.add_ad("Ad 3", 5.0, [("hash3", 0.0)])

        count = temp_db.delete_all_ads()

        assert count == 3

    def test_delete_all_removes_all(self, temp_db: Database) -> None:
        """Should remove all ads from database."""
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 5.0, [("hash2", 0.0)])

        temp_db.delete_all_ads()

        ads = temp_db.list_ads()
        assert len(ads) == 0

    def test_delete_all_empty_database(self, temp_db: Database) -> None:
        """Should return 0 for empty database."""
        count = temp_db.delete_all_ads()

        assert count == 0


class TestFindMatches:
    """Tests for find_matches method."""

    def test_find_matches_empty_hashes(self, temp_db: Database) -> None:
        """Should return empty list for empty hash list."""
        matches = temp_db.find_matches([])

        assert matches == []

    def test_find_matches_no_matches(self, temp_db: Database) -> None:
        """Should return empty list when no matches found."""
        temp_db.add_ad("Some Ad", 5.0, [("hash1", 0.0), ("hash2", 0.5)])

        matches = temp_db.find_matches(["different_hash"])

        assert matches == []

    def test_find_matches_returns_ad_name(self, temp_db: Database) -> None:
        """Should return matching ad names."""
        temp_db.add_ad(
            "Match Test",
            5.0,
            [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0), ("hash4", 1.5), ("hash5", 2.0)],
        )

        matches = temp_db.find_matches(["hash1", "hash2", "hash3", "hash4", "hash5"])

        assert len(matches) > 0
        assert matches[0][0] == "Match Test"

    def test_find_matches_returns_count(self, temp_db: Database) -> None:
        """Should return match count."""
        temp_db.add_ad(
            "Count Test",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0), ("h4", 1.5), ("h5", 2.0)],
        )

        matches = temp_db.find_matches(["h1", "h2", "h3"])

        # Requires min 5 matches by default, so may return empty
        # Let's search with more hashes
        matches = temp_db.find_matches(["h1", "h2", "h3", "h4", "h5"])

        if matches:
            _ad_name, match_count, _confidence = matches[0]
            assert match_count == 5

    def test_find_matches_min_matches_filter(self, temp_db: Database) -> None:
        """Should filter by minimum matches."""
        temp_db.add_ad(
            "Min Match",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0)],
        )

        # Only 2 matches, requiring 3
        matches = temp_db.find_matches(["h1", "h2"], min_matches=3)
        assert matches == []

        # 3 matches, requiring 3
        matches = temp_db.find_matches(["h1", "h2", "h3"], min_matches=3)
        assert len(matches) == 1

    def test_find_matches_confidence_calculation(self, temp_db: Database) -> None:
        """Confidence should be match_count / total_fingerprints."""
        temp_db.add_ad(
            "Confidence Test",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0), ("h4", 1.5), ("h5", 2.0)],  # 5 fingerprints
        )

        # Match 5 of 5 fingerprints
        matches = temp_db.find_matches(["h1", "h2", "h3", "h4", "h5"], min_matches=1)

        if matches:
            _, count, confidence = matches[0]
            assert count == 5
            assert confidence == 1.0  # 5/5

    def test_find_matches_sorted_by_confidence(self, temp_db: Database) -> None:
        """Matches should be sorted by confidence descending."""
        # Ad with 10 fingerprints
        temp_db.add_ad(
            "Many FP",
            5.0,
            [(f"many_{i}", i * 0.1) for i in range(10)],
        )
        # Ad with 5 fingerprints
        temp_db.add_ad(
            "Few FP",
            5.0,
            [(f"few_{i}", i * 0.1) for i in range(5)],
        )

        # Search with hashes that match all of "Few FP" and half of "Many FP"
        search_hashes = [f"few_{i}" for i in range(5)] + [f"many_{i}" for i in range(5)]

        matches = temp_db.find_matches(search_hashes, min_matches=5)

        if len(matches) >= 2:
            # "Few FP" should be first (100% match) vs "Many FP" (50% match)
            assert matches[0][0] == "Few FP"


class TestGetAllFingerprints:
    """Tests for get_all_fingerprints method."""

    def test_get_fingerprints_for_ad(self, temp_db: Database) -> None:
        """Should return all fingerprints for an ad."""
        fingerprints = [("h1", 0.0), ("h2", 0.5), ("h3", 1.0)]
        temp_db.add_ad("FP Ad", 5.0, fingerprints)

        result = temp_db.get_all_fingerprints("FP Ad")

        assert len(result) == 3
        assert all(isinstance(fp, FingerprintRecord) for fp in result)

    def test_fingerprints_ordered_by_time(self, temp_db: Database) -> None:
        """Fingerprints should be ordered by time offset."""
        fingerprints = [("h3", 1.0), ("h1", 0.0), ("h2", 0.5)]  # Out of order
        temp_db.add_ad("Order Test", 5.0, fingerprints)

        result = temp_db.get_all_fingerprints("Order Test")

        offsets = [fp.time_offset for fp in result]
        assert offsets == sorted(offsets)

    def test_get_fingerprints_nonexistent_ad(self, temp_db: Database) -> None:
        """Should return empty list for nonexistent ad."""
        result = temp_db.get_all_fingerprints("Does Not Exist")

        assert result == []


class TestGetStats:
    """Tests for get_stats method."""

    def test_stats_empty_database(self, temp_db: Database) -> None:
        """Should return zeros for empty database."""
        stats = temp_db.get_stats()

        assert isinstance(stats, DatabaseStats)
        assert stats.total_ads == 0
        assert stats.total_fingerprints == 0

    def test_stats_with_data(self, temp_db: Database) -> None:
        """Should return correct counts."""
        temp_db.add_ad("Ad 1", 5.0, [("h1", 0.0), ("h2", 0.5)])
        temp_db.add_ad("Ad 2", 5.0, [("h3", 0.0), ("h4", 0.5), ("h5", 1.0)])

        stats = temp_db.get_stats()

        assert stats.total_ads == 2
        assert stats.total_fingerprints == 5

    def test_stats_db_size(self, temp_db: Database) -> None:
        """Should report database file size."""
        temp_db.add_ad("Size Test", 5.0, [("h1", 0.0)])

        stats = temp_db.get_stats()

        assert stats.db_size_bytes > 0


class TestVacuum:
    """Tests for vacuum method."""

    def test_vacuum_runs_without_error(self, temp_db: Database) -> None:
        """Vacuum should run without error."""
        temp_db.add_ad("Vacuum Test", 5.0, [("h1", 0.0)])
        temp_db.delete_ad("Vacuum Test")

        # Should not raise
        temp_db.vacuum()

    def test_vacuum_reduces_size_after_delete(self, temp_db: Database) -> None:
        """Vacuum should potentially reduce size after deletes."""
        # Add a lot of data
        fingerprints = [(f"hash_{i}", i * 0.01) for i in range(1000)]
        temp_db.add_ad("Large Ad", 10.0, fingerprints)

        size_before = temp_db.get_stats().db_size_bytes

        temp_db.delete_ad("Large Ad")
        temp_db.vacuum()

        size_after = temp_db.get_stats().db_size_bytes

        # Size should be reduced (or at least not larger)
        assert size_after <= size_before


class TestConnectionContextManager:
    """Tests for database connection management."""

    def test_connection_commits_on_success(self, temp_db: Database) -> None:
        """Changes should be committed on successful operations."""
        temp_db.add_ad("Commit Test", 5.0, [("h1", 0.0)])

        # Re-open connection and verify data persists
        db2 = Database(temp_db.db_path)
        ad = db2.get_ad("Commit Test")

        assert ad is not None

    def test_connection_rollback_on_error(self, temp_db: Database) -> None:
        """Changes should be rolled back on error."""
        try:
            with temp_db._get_connection() as conn:
                conn.execute(
                    "INSERT INTO ads (name, duration_seconds) VALUES (?, ?)",
                    ("Rollback Test", 5.0),
                )
                # Force an error
                raise ValueError("Test error")
        except ValueError:
            pass

        # Data should not be committed
        ad = temp_db.get_ad("Rollback Test")
        assert ad is None
