"""Tests for ER query functions using pytest mocks.

Tests cover:
- query_er_by_email: matching email, no results, multiple results
- query_er_by_date: year only, year+month, December edge case, invalid input
- _doc_to_er_record: field extraction and missing fields
"""

from unittest.mock import MagicMock, patch

import pytest

from er_query.client import (
    _doc_to_er_record,
    query_er_by_date,
    query_er_by_email,
    query_er_by_name,
)

# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_DOC_FULL = {
    "er_name": "ER-431059",
    "account_name": "Australian Postal Corporation",
    "account_sub_region": "AUNZ",
    "assigned_ce_email": "issein@google.com",
    "details": "[WHY]\nExplore new use case for Gemini Enterprise adoption",
    "created_at": "2025-10-30T03:08:56+00:00",
    "status": "Completed",
    "product": "Gemini Enterprise",
    "embedding": "some_vector_data",
    "fsa_status": "Completed",
    "fsa_assets": [{"type": "Scope Document", "url": ""}],
    "workload_name": "AusPost - Agentspace",
    "workload_gross_revenue": 1920000.0,
    "workload_gross_revenue_tracking": [{"amount": 1920000.0, "date": "2026-03-19"}],
    "content_hash": "abc123",
    "needs_embedding": False,
    "vector_id": "xyz",
}

SAMPLE_DOC_2 = {
    "er_name": "ER-500001",
    "account_name": "Acme Corp",
    "account_sub_region": "SEA",
    "assigned_ce_email": "weiyih@google.com",
    "details": "POC for Vertex AI Search",
    "created_at": "2025-06-15T10:00:00+00:00",
    "status": "In Progress",
}

SAMPLE_DOC_3 = {
    "er_name": "ER-500002",
    "account_name": "Beta Inc",
    "account_sub_region": "SEA",
    "assigned_ce_email": "weiyih@google.com",
    "details": "Gemini Code Assist deployment",
    "created_at": "2025-06-20T14:30:00+00:00",
    "status": "In Progress",
}

EXPECTED_RECORD_1 = {
    "er_name": "ER-431059",
    "account_name": "Australian Postal Corporation",
    "account_sub_region": "AUNZ",
    "assigned_ce_email": "issein@google.com",
    "details": "[WHY]\nExplore new use case for Gemini Enterprise adoption",
}

EXPECTED_RECORD_2 = {
    "er_name": "ER-500001",
    "account_name": "Acme Corp",
    "account_sub_region": "SEA",
    "assigned_ce_email": "weiyih@google.com",
    "details": "POC for Vertex AI Search",
}

EXPECTED_RECORD_3 = {
    "er_name": "ER-500002",
    "account_name": "Beta Inc",
    "account_sub_region": "SEA",
    "assigned_ce_email": "weiyih@google.com",
    "details": "Gemini Code Assist deployment",
}


# ---------------------------------------------------------------------------
# Helper to create mock Firestore documents
# ---------------------------------------------------------------------------


def _make_mock_doc(doc_dict: dict) -> MagicMock:
    """Create a mock Firestore document snapshot."""
    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = doc_dict
    mock_doc.id = doc_dict.get("er_name", "unknown")
    return mock_doc


def _make_mock_collection(docs: list[dict]) -> MagicMock:
    """Create a mock Firestore collection reference with query support.

    The mock supports chained .where() calls and .stream() iteration.
    """
    mock_query = MagicMock()
    mock_query.where.return_value = mock_query  # Allow chaining .where()
    mock_query.stream.return_value = [_make_mock_doc(d) for d in docs]

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query
    return mock_collection


# ---------------------------------------------------------------------------
# Tests for _doc_to_er_record
# ---------------------------------------------------------------------------


class TestDocToErRecord:
    """Tests for the _doc_to_er_record helper function."""

    def test_extracts_correct_fields(self):
        """Should extract only the 5 required fields from a full document."""
        result = _doc_to_er_record(SAMPLE_DOC_FULL)
        assert result == EXPECTED_RECORD_1

    def test_excludes_extra_fields(self):
        """Should not include fields like status, product, embedding."""
        result = _doc_to_er_record(SAMPLE_DOC_FULL)
        assert "status" not in result
        assert "product" not in result
        assert "embedding" not in result
        assert "created_at" not in result

    def test_missing_fields_default_to_empty_string(self):
        """Should return empty string for fields not present in the doc."""
        sparse_doc = {"er_name": "ER-999", "account_name": "Test"}
        result = _doc_to_er_record(sparse_doc)
        assert result["er_name"] == "ER-999"
        assert result["account_name"] == "Test"
        assert result["account_sub_region"] == ""
        assert result["assigned_ce_email"] == ""
        assert result["details"] == ""

    def test_empty_doc(self):
        """Should return all empty strings for an empty document."""
        result = _doc_to_er_record({})
        assert all(v == "" for v in result.values())
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Tests for query_er_by_email
# ---------------------------------------------------------------------------


class TestQueryErByEmail:
    """Tests for the query_er_by_email function."""

    @patch("er_query.client._get_collection_ref")
    def test_returns_matching_records(self, mock_get_coll):
        """Should return records matching the given email."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_email("issein@google.com")

        assert len(results) == 1
        assert results[0] == EXPECTED_RECORD_1

    @patch("er_query.client._get_collection_ref")
    def test_returns_empty_for_no_match(self, mock_get_coll):
        """Should return empty list when no ERs match the email."""
        mock_get_coll.return_value = _make_mock_collection([])

        results = query_er_by_email("nobody@google.com")

        assert results == []

    @patch("er_query.client._get_collection_ref")
    def test_returns_multiple_records(self, mock_get_coll):
        """Should return all matching records for an email with multiple ERs."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_2, SAMPLE_DOC_3])

        results = query_er_by_email("weiyih@google.com")

        assert len(results) == 2
        assert results[0] == EXPECTED_RECORD_2
        assert results[1] == EXPECTED_RECORD_3

    @patch("er_query.client._get_collection_ref")
    def test_only_returns_required_fields(self, mock_get_coll):
        """Should only return the 5 required fields, not the full doc."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_email("issein@google.com")

        assert set(results[0].keys()) == {
            "er_name",
            "account_name",
            "account_sub_region",
            "assigned_ce_email",
            "details",
        }


# ---------------------------------------------------------------------------
# Tests for query_er_by_name
# ---------------------------------------------------------------------------


class TestQueryErByName:
    """Tests for the query_er_by_name function."""

    @patch("er_query.client._get_collection_ref")
    def test_returns_specific_fields(self, mock_get_coll):
        """Should return only the requested fields plus er_name."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="fsa_status,product")

        assert len(results) == 1
        assert results[0]["er_name"] == "ER-431059"
        assert results[0]["fsa_status"] == "Completed"
        assert results[0]["product"] == "Gemini Enterprise"
        assert "embedding" not in results[0]
        assert "account_name" not in results[0]

    @patch("er_query.client._get_collection_ref")
    def test_returns_fsa_assets_and_status(self, mock_get_coll):
        """Should return fsa_assets and fsa_status when requested."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="fsa_assets,fsa_status")

        assert len(results) == 1
        assert results[0]["er_name"] == "ER-431059"
        assert results[0]["fsa_assets"] == [{"type": "Scope Document", "url": ""}]
        assert results[0]["fsa_status"] == "Completed"

    @patch("er_query.client._get_collection_ref")
    def test_returns_workload_fields(self, mock_get_coll):
        """Should return workload-related fields when requested."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name(
            "ER-431059",
            fields="workload_name,workload_gross_revenue,workload_gross_revenue_tracking",
        )

        assert len(results) == 1
        assert results[0]["er_name"] == "ER-431059"
        assert results[0]["workload_name"] == "AusPost - Agentspace"
        assert results[0]["workload_gross_revenue"] == 1920000.0
        assert results[0]["workload_gross_revenue_tracking"] == [
            {"amount": 1920000.0, "date": "2026-03-19"}
        ]

    @patch("er_query.client._get_collection_ref")
    def test_returns_details_and_product(self, mock_get_coll):
        """Should return details and product when requested."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="details,product")

        assert len(results) == 1
        assert results[0]["er_name"] == "ER-431059"
        assert "Gemini Enterprise" in results[0]["product"]
        assert "[WHY]" in results[0]["details"]

    @patch("er_query.client._get_collection_ref")
    def test_returns_all_fields_when_no_fields_specified(self, mock_get_coll):
        """Should return all fields (except excluded) when fields is None."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059")

        assert len(results) == 1
        # Should include non-excluded fields
        assert results[0]["er_name"] == "ER-431059"
        assert results[0]["fsa_status"] == "Completed"
        assert results[0]["product"] == "Gemini Enterprise"
        # Should exclude internal fields
        assert "embedding" not in results[0]
        assert "content_hash" not in results[0]
        assert "vector_id" not in results[0]
        assert "needs_embedding" not in results[0]

    @patch("er_query.client._get_collection_ref")
    def test_returns_empty_for_nonexistent_er(self, mock_get_coll):
        """Should return empty list when ER doesn't exist."""
        mock_get_coll.return_value = _make_mock_collection([])

        results = query_er_by_name("ER-999999", fields="fsa_status")

        assert results == []

    @patch("er_query.client._get_collection_ref")
    def test_nonexistent_field_returns_none(self, mock_get_coll):
        """Should return None for requested fields that don't exist in the doc."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="nonexistent_field")

        assert len(results) == 1
        assert results[0]["er_name"] == "ER-431059"
        assert results[0]["nonexistent_field"] is None

    @patch("er_query.client._get_collection_ref")
    def test_handles_whitespace_in_fields(self, mock_get_coll):
        """Should handle whitespace around field names in comma-separated list."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields=" fsa_status , product ")

        assert len(results) == 1
        assert results[0]["fsa_status"] == "Completed"
        assert results[0]["product"] == "Gemini Enterprise"

    @patch("er_query.client._get_collection_ref")
    def test_empty_fields_string_returns_all(self, mock_get_coll):
        """Should return all fields when fields is an empty string."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="")

        assert len(results) == 1
        # Should behave like fields=None (return all non-excluded)
        assert "er_name" in results[0]
        assert "embedding" not in results[0]

    @patch("er_query.client._get_collection_ref")
    def test_er_name_always_included(self, mock_get_coll):
        """Should always include er_name even if not in fields list."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_name("ER-431059", fields="product")

        assert len(results) == 1
        assert "er_name" in results[0]
        assert results[0]["er_name"] == "ER-431059"


# ---------------------------------------------------------------------------
# Tests for query_er_by_date
# ---------------------------------------------------------------------------


class TestQueryErByDate:
    """Tests for the query_er_by_date function."""

    @patch("er_query.client._get_collection_ref")
    def test_year_only_query(self, mock_get_coll):
        """Should return ERs created in the specified year."""
        mock_get_coll.return_value = _make_mock_collection(
            [SAMPLE_DOC_FULL, SAMPLE_DOC_2]
        )

        results = query_er_by_date(year=2025)

        assert len(results) == 2

    @patch("er_query.client._get_collection_ref")
    def test_year_and_month_query(self, mock_get_coll):
        """Should return ERs created in the specified year and month."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_date(year=2025, month=10)

        assert len(results) == 1
        assert results[0] == EXPECTED_RECORD_1

    @patch("er_query.client._get_collection_ref")
    def test_no_results_for_empty_month(self, mock_get_coll):
        """Should return empty list for month with no ERs."""
        mock_get_coll.return_value = _make_mock_collection([])

        results = query_er_by_date(year=2024, month=1)

        assert results == []

    @patch("er_query.client._get_collection_ref")
    def test_december_edge_case(self, mock_get_coll):
        """Should correctly handle December (month 12) boundary."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_date(year=2025, month=12)

        # Should not raise; December boundary should be Jan 1 of next year
        assert len(results) == 1

    def test_invalid_month_raises_error(self):
        """Should raise ValueError for month outside 1-12."""
        with pytest.raises(ValueError, match="Month must be between 1 and 12"):
            query_er_by_date(year=2025, month=0)

        with pytest.raises(ValueError, match="Month must be between 1 and 12"):
            query_er_by_date(year=2025, month=13)

    def test_negative_year_raises_error(self):
        """Should raise ValueError for negative year."""
        with pytest.raises(ValueError, match="Year must be non-negative"):
            query_er_by_date(year=-1)

    @patch("er_query.client._get_collection_ref")
    def test_january_boundary(self, mock_get_coll):
        """Should correctly handle January (month 1) boundary."""
        mock_get_coll.return_value = _make_mock_collection([])

        results = query_er_by_date(year=2025, month=1)

        assert results == []

    @patch("er_query.client._get_collection_ref")
    def test_returns_only_required_fields(self, mock_get_coll):
        """Should only return the 5 required fields for date queries."""
        mock_get_coll.return_value = _make_mock_collection([SAMPLE_DOC_FULL])

        results = query_er_by_date(year=2025)

        assert set(results[0].keys()) == {
            "er_name",
            "account_name",
            "account_sub_region",
            "assigned_ce_email",
            "details",
        }
