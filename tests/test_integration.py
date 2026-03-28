"""Integration tests for actual Firestore connection.

Run with: uv run pytest tests/test_integration.py -v -m integration
These tests require actual GCP credentials and Firestore access.
"""

import os

import pytest

from er_query.client import query_er_by_date, query_er_by_email

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def check_env():
    """Skip integration tests if .env_dev is not configured."""
    if not os.path.exists(".env_dev"):
        pytest.skip("No .env_dev found — skipping integration tests")


class TestFirestoreIntegration:
    """Integration tests against real Firestore."""

    def test_query_by_known_email(self):
        """Query with an email known to exist in the sample data."""
        results = query_er_by_email("issein@google.com")
        print(f"\n📧 Results for issein@google.com: {len(results)} ERs found")
        for r in results:
            print(f"  - {r['er_name']}: {r['account_name']} ({r['account_sub_region']})")
        assert isinstance(results, list)
        # We expect at least 1 result based on sample data
        assert len(results) >= 1
        # Verify returned fields
        for r in results:
            assert "er_name" in r
            assert "account_name" in r
            assert "assigned_ce_email" in r
            assert r["assigned_ce_email"] == "issein@google.com"

    def test_query_by_unknown_email(self):
        """Query with a non-existent email should return empty list."""
        results = query_er_by_email("nonexistent_user_xyz@google.com")
        print(f"\n📧 Results for nonexistent_user_xyz@google.com: {len(results)}")
        assert results == []

    def test_query_by_year_2024(self):
        """Query for ERs created in 2024 (known data year)."""
        results = query_er_by_date(year=2024)
        print(f"\n📅 Results for year 2024: {len(results)} ERs found")
        for r in results[:5]:  # Show first 5
            print(f"  - {r['er_name']}: {r['account_name']}")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_query_by_year_month_2024_04(self):
        """Query for ERs created in April 2024 (known data month)."""
        results = query_er_by_date(year=2024, month=4)
        print(f"\n📅 Results for 2024-04: {len(results)} ERs found")
        for r in results[:5]:
            print(f"  - {r['er_name']}: {r['account_name']}")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_query_by_year_2025(self):
        """Query for ERs created in 2025."""
        results = query_er_by_date(year=2025)
        print(f"\n📅 Results for year 2025: {len(results)} ERs found")
        for r in results[:5]:
            print(f"  - {r['er_name']}: {r['account_name']}")
        assert isinstance(results, list)
        # May or may not have results depending on data

    def test_query_by_empty_date_range(self):
        """Query for a date range with no ERs."""
        results = query_er_by_date(year=2020, month=1)
        print(f"\n📅 Results for 2020-01: {len(results)} ERs found")
        assert results == []
