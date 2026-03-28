"""Tests for MCP server tools.

Tests verify that MCP tool functions correctly wrap the underlying
query functions and return proper JSON responses.
"""

import json
from unittest.mock import patch

from mcp_server.server import search_er_by_date, search_er_by_email

SAMPLE_RESULT = [
    {
        "er_name": "ER-431059",
        "account_name": "Australian Postal Corporation",
        "account_sub_region": "AUNZ",
        "assigned_ce_email": "issein@google.com",
        "details": "[WHY]\nExplore new use case",
    }
]


class TestSearchErByEmail:
    """Tests for the search_er_by_email MCP tool."""

    @patch("mcp_server.server.query_er_by_email")
    def test_returns_json_string(self, mock_query):
        """Should return a valid JSON string."""
        mock_query.return_value = SAMPLE_RESULT

        result = search_er_by_email("issein@google.com")

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    @patch("mcp_server.server.query_er_by_email")
    def test_returns_correct_data(self, mock_query):
        """Should return the correct data from the query function."""
        mock_query.return_value = SAMPLE_RESULT

        result = search_er_by_email("issein@google.com")

        parsed = json.loads(result)
        assert parsed[0]["er_name"] == "ER-431059"
        assert parsed[0]["account_name"] == "Australian Postal Corporation"

    @patch("mcp_server.server.query_er_by_email")
    def test_empty_result(self, mock_query):
        """Should return '[]' when no results found."""
        mock_query.return_value = []

        result = search_er_by_email("nobody@google.com")

        assert json.loads(result) == []

    @patch("mcp_server.server.query_er_by_email")
    def test_passes_email_to_query(self, mock_query):
        """Should pass the email parameter to the query function."""
        mock_query.return_value = []

        search_er_by_email("test@google.com")

        mock_query.assert_called_once_with("test@google.com")


class TestSearchErByDate:
    """Tests for the search_er_by_date MCP tool."""

    @patch("mcp_server.server.query_er_by_date")
    def test_year_only_returns_json(self, mock_query):
        """Should return valid JSON for year-only query."""
        mock_query.return_value = SAMPLE_RESULT

        result = search_er_by_date(2025)

        parsed = json.loads(result)
        assert len(parsed) == 1

    @patch("mcp_server.server.query_er_by_date")
    def test_year_and_month_returns_json(self, mock_query):
        """Should return valid JSON for year+month query."""
        mock_query.return_value = SAMPLE_RESULT

        result = search_er_by_date(2025, 10)

        parsed = json.loads(result)
        assert len(parsed) == 1

    @patch("mcp_server.server.query_er_by_date")
    def test_passes_params_to_query(self, mock_query):
        """Should pass year and month to the query function."""
        mock_query.return_value = []

        search_er_by_date(2025, 6)

        mock_query.assert_called_once_with(year=2025, month=6)

    @patch("mcp_server.server.query_er_by_date")
    def test_month_none_when_not_provided(self, mock_query):
        """Should pass month=None when not provided."""
        mock_query.return_value = []

        search_er_by_date(2025)

        mock_query.assert_called_once_with(year=2025, month=None)

    @patch("mcp_server.server.query_er_by_date")
    def test_handles_unicode_in_results(self, mock_query):
        """Should handle Unicode characters in account names."""
        mock_query.return_value = [
            {
                "er_name": "ER-999",
                "account_name": "Telefónica España",
                "account_sub_region": "EMEA",
                "assigned_ce_email": "test@google.com",
                "details": "Test with ñ and é",
            }
        ]

        result = search_er_by_date(2025)

        parsed = json.loads(result)
        assert "Telefónica" in parsed[0]["account_name"]
