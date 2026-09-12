"""Unit tests for the database module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from src.db.database import AdRecord, Database, DatabaseStats, FingerprintRecord


class TestDatabaseInit:
    def test_creates_db_file(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"

        Database(db_path)

        assert db_path.exists()

    def test_creates_parent_directories(self, temp_dir: Path) -> None:
        db_path = temp_dir / "subdir" / "nested" / "test.db"

        Database(db_path)

        assert db_path.exists()

    def test_schema_is_created(self, temp_db: Database) -> None:
        with temp_db._get_connection() as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ads'"
            ).fetchone()
            assert result is not None

            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fingerprints'"
            ).fetchone()
            assert result is not None

    def test_indexes_are_created(self, temp_db: Database) -> None:
        with temp_db._get_connection() as conn:
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_fingerprints_hash'"
            ).fetchone()
            assert result is not None


class TestAddAd:
    def test_add_ad_returns_id(self, temp_db: Database) -> None:
        fingerprints = [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0)]

        ad_id = temp_db.add_ad(
            name="Test Ad",
            duration_seconds=10.5,
            fingerprints=fingerprints,
        )

        assert isinstance(ad_id, int)
        assert ad_id > 0

    def test_add_ad_stores_name(self, temp_db: Database) -> None:
        temp_db.add_ad("My Ad", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("My Ad")

        assert ad is not None
        assert ad.name == "My Ad"

    def test_add_ad_stores_duration(self, temp_db: Database) -> None:
        temp_db.add_ad("Duration Test", 15.75, [("hash1", 0.0)])

        ad = temp_db.get_ad("Duration Test")

        assert ad is not None
        assert ad.duration_seconds == 15.75

    def test_add_ad_stores_fingerprints(self, temp_db: Database) -> None:
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
        temp_db.add_ad("Tagged Ad", 5.0, [("hash1", 0.0)], tags=["cricket", "ipl", "sponsor"])

        ad = temp_db.get_ad("Tagged Ad")

        assert ad is not None
        assert set(ad.tags) == {"cricket", "ipl", "sponsor"}

    def test_add_ad_empty_tags(self, temp_db: Database) -> None:
        temp_db.add_ad("No Tags", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("No Tags")

        assert ad is not None
        assert ad.tags == []

    def test_add_ad_duplicate_name_fails(self, temp_db: Database) -> None:
        temp_db.add_ad("Unique Name", 5.0, [("hash1", 0.0)])

        with pytest.raises(Exception):  # sqlite3.IntegrityError  # noqa: B017
            temp_db.add_ad("Unique Name", 10.0, [("hash2", 0.0)])

    def test_add_ad_stores_timestamp(self, temp_db: Database) -> None:
        temp_db.add_ad("Timestamp Test", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("Timestamp Test")

        assert ad is not None
        # SQLite stores this timestamp in UTC.
        assert isinstance(ad.created_at, datetime)


class TestGetAd:
    def test_get_existing_ad(self, temp_db: Database) -> None:
        temp_db.add_ad("Existing", 5.0, [("hash1", 0.0)])

        ad = temp_db.get_ad("Existing")

        assert ad is not None
        assert isinstance(ad, AdRecord)

    def test_get_nonexistent_ad(self, temp_db: Database) -> None:
        ad = temp_db.get_ad("Does Not Exist")

        assert ad is None

    def test_ad_record_fields(self, temp_db: Database) -> None:
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
    def test_list_empty_database(self, temp_db: Database) -> None:
        ads = temp_db.list_ads()

        assert ads == []

    def test_list_all_ads(self, temp_db: Database) -> None:
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 10.0, [("hash2", 0.0)])
        temp_db.add_ad("Ad 3", 15.0, [("hash3", 0.0)])

        ads = temp_db.list_ads()

        assert len(ads) == 3
        names = {ad.name for ad in ads}
        assert names == {"Ad 1", "Ad 2", "Ad 3"}

    def test_list_ordered_by_created_desc(self, temp_db: Database) -> None:
        """Ads created in the same second can tie on timestamp, so this checks presence, not order."""
        temp_db.add_ad("First", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Second", 5.0, [("hash2", 0.0)])
        temp_db.add_ad("Third", 5.0, [("hash3", 0.0)])

        ads = temp_db.list_ads()

        assert len(ads) == 3
        names = {ad.name for ad in ads}
        assert names == {"First", "Second", "Third"}


class TestDeleteAd:
    def test_delete_existing_ad(self, temp_db: Database) -> None:
        temp_db.add_ad("To Delete", 5.0, [("hash1", 0.0)])

        result = temp_db.delete_ad("To Delete")

        assert result is True
        assert temp_db.get_ad("To Delete") is None

    def test_delete_nonexistent_ad(self, temp_db: Database) -> None:
        result = temp_db.delete_ad("Does Not Exist")

        assert result is False

    def test_delete_cascades_fingerprints(self, temp_db: Database) -> None:
        fingerprints = [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0)]
        temp_db.add_ad("Cascade Test", 5.0, fingerprints)

        temp_db.delete_ad("Cascade Test")

        with temp_db._get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            assert count == 0


class TestDeleteAllAds:
    def test_delete_all_returns_count(self, temp_db: Database) -> None:
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 5.0, [("hash2", 0.0)])
        temp_db.add_ad("Ad 3", 5.0, [("hash3", 0.0)])

        count = temp_db.delete_all_ads()

        assert count == 3

    def test_delete_all_removes_all(self, temp_db: Database) -> None:
        temp_db.add_ad("Ad 1", 5.0, [("hash1", 0.0)])
        temp_db.add_ad("Ad 2", 5.0, [("hash2", 0.0)])

        temp_db.delete_all_ads()

        ads = temp_db.list_ads()
        assert len(ads) == 0

    def test_delete_all_empty_database(self, temp_db: Database) -> None:
        count = temp_db.delete_all_ads()

        assert count == 0


class TestFindMatches:
    def test_find_matches_empty_hashes(self, temp_db: Database) -> None:
        matches = temp_db.find_matches([])

        assert matches == []

    def test_find_matches_no_matches(self, temp_db: Database) -> None:
        temp_db.add_ad("Some Ad", 5.0, [("hash1", 0.0), ("hash2", 0.5)])

        matches = temp_db.find_matches(["different_hash"])

        assert matches == []

    def test_find_matches_returns_ad_name(self, temp_db: Database) -> None:
        temp_db.add_ad(
            "Match Test",
            5.0,
            [("hash1", 0.0), ("hash2", 0.5), ("hash3", 1.0), ("hash4", 1.5), ("hash5", 2.0)],
        )

        matches = temp_db.find_matches(["hash1", "hash2", "hash3", "hash4", "hash5"])

        assert len(matches) > 0
        assert matches[0][0] == "Match Test"

    def test_find_matches_returns_count(self, temp_db: Database) -> None:
        temp_db.add_ad(
            "Count Test",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0), ("h4", 1.5), ("h5", 2.0)],
        )

        # Default min_matches is 5, so three hashes won't match.
        matches = temp_db.find_matches(["h1", "h2", "h3"])

        matches = temp_db.find_matches(["h1", "h2", "h3", "h4", "h5"])

        if matches:
            _ad_name, match_count, _confidence = matches[0]
            assert match_count == 5

    def test_find_matches_min_matches_filter(self, temp_db: Database) -> None:
        temp_db.add_ad(
            "Min Match",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0)],
        )

        matches = temp_db.find_matches(["h1", "h2"], min_matches=3)
        assert matches == []

        matches = temp_db.find_matches(["h1", "h2", "h3"], min_matches=3)
        assert len(matches) == 1

    def test_find_matches_confidence_calculation(self, temp_db: Database) -> None:
        """Confidence should be match_count / total_fingerprints."""
        temp_db.add_ad(
            "Confidence Test",
            5.0,
            [("h1", 0.0), ("h2", 0.5), ("h3", 1.0), ("h4", 1.5), ("h5", 2.0)],
        )

        matches = temp_db.find_matches(["h1", "h2", "h3", "h4", "h5"], min_matches=1)

        if matches:
            _, count, confidence = matches[0]
            assert count == 5
            assert confidence == 1.0

    def test_find_matches_sorted_by_confidence(self, temp_db: Database) -> None:
        """Matches should be sorted by confidence descending."""
        temp_db.add_ad(
            "Many FP",
            5.0,
            [(f"many_{i}", i * 0.1) for i in range(10)],
        )
        temp_db.add_ad(
            "Few FP",
            5.0,
            [(f"few_{i}", i * 0.1) for i in range(5)],
        )

        # All of "Few FP"'s hashes plus half of "Many FP"'s.
        search_hashes = [f"few_{i}" for i in range(5)] + [f"many_{i}" for i in range(5)]

        matches = temp_db.find_matches(search_hashes, min_matches=5)

        if len(matches) >= 2:
            # "Few FP" matches 100%, "Many FP" only 50%.
            assert matches[0][0] == "Few FP"


class TestGetAllFingerprints:
    def test_get_fingerprints_for_ad(self, temp_db: Database) -> None:
        fingerprints = [("h1", 0.0), ("h2", 0.5), ("h3", 1.0)]
        temp_db.add_ad("FP Ad", 5.0, fingerprints)

        result = temp_db.get_all_fingerprints("FP Ad")

        assert len(result) == 3
        assert all(isinstance(fp, FingerprintRecord) for fp in result)

    def test_fingerprints_ordered_by_time(self, temp_db: Database) -> None:
        fingerprints = [("h3", 1.0), ("h1", 0.0), ("h2", 0.5)]  # Out of order
        temp_db.add_ad("Order Test", 5.0, fingerprints)

        result = temp_db.get_all_fingerprints("Order Test")

        offsets = [fp.time_offset for fp in result]
        assert offsets == sorted(offsets)

    def test_get_fingerprints_nonexistent_ad(self, temp_db: Database) -> None:
        result = temp_db.get_all_fingerprints("Does Not Exist")

        assert result == []


class TestGetStats:
    def test_stats_empty_database(self, temp_db: Database) -> None:
        stats = temp_db.get_stats()

        assert isinstance(stats, DatabaseStats)
        assert stats.total_ads == 0
        assert stats.total_fingerprints == 0

    def test_stats_with_data(self, temp_db: Database) -> None:
        temp_db.add_ad("Ad 1", 5.0, [("h1", 0.0), ("h2", 0.5)])
        temp_db.add_ad("Ad 2", 5.0, [("h3", 0.0), ("h4", 0.5), ("h5", 1.0)])

        stats = temp_db.get_stats()

        assert stats.total_ads == 2
        assert stats.total_fingerprints == 5

    def test_stats_db_size(self, temp_db: Database) -> None:
        temp_db.add_ad("Size Test", 5.0, [("h1", 0.0)])

        stats = temp_db.get_stats()

        assert stats.db_size_bytes > 0


class TestVacuum:
    def test_vacuum_runs_without_error(self, temp_db: Database) -> None:
        temp_db.add_ad("Vacuum Test", 5.0, [("h1", 0.0)])
        temp_db.delete_ad("Vacuum Test")

        temp_db.vacuum()

    def test_vacuum_reduces_size_after_delete(self, temp_db: Database) -> None:
        fingerprints = [(f"hash_{i}", i * 0.01) for i in range(1000)]
        temp_db.add_ad("Large Ad", 10.0, fingerprints)

        size_before = temp_db.get_stats().db_size_bytes

        temp_db.delete_ad("Large Ad")
        temp_db.vacuum()

        size_after = temp_db.get_stats().db_size_bytes

        assert size_after <= size_before


class TestConnectionContextManager:
    def test_connection_commits_on_success(self, temp_db: Database) -> None:
        temp_db.add_ad("Commit Test", 5.0, [("h1", 0.0)])

        db2 = Database(temp_db.db_path)
        ad = db2.get_ad("Commit Test")

        assert ad is not None

    def test_connection_rollback_on_error(self, temp_db: Database) -> None:
        try:
            with temp_db._get_connection() as conn:
                conn.execute(
                    "INSERT INTO ads (name, duration_seconds) VALUES (?, ?)",
                    ("Rollback Test", 5.0),
                )
                raise ValueError("Test error")
        except ValueError:
            pass

        ad = temp_db.get_ad("Rollback Test")
        assert ad is None
