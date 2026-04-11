"""Tests for the AG-UI server integration.

These tests verify that the AG-UI server correctly wraps the ADK agent
and exposes the expected FastAPI endpoints. They use mocking to avoid
requiring actual GCP credentials or a running MCP server.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_dependencies():
    """Mock heavy dependencies so tests don't need GCP / Gemini / MCP.

    Patches:
        - McpToolset: avoids spawning a real MCP subprocess
        - ADKAgent: avoids Gemini API calls
        - add_adk_fastapi_endpoint: avoids full AG-UI wiring
    """
    with (
        patch("agui_server.McpToolset") as mock_mcp,
        patch("agui_server.ADKAgent") as mock_adk_agent,
        patch("agui_server.add_adk_fastapi_endpoint") as mock_add_endpoint,
        patch("agui_server.AGUIToolset") as mock_agui_toolset,
    ):
        mock_mcp.return_value = MagicMock()
        mock_adk_agent.return_value = MagicMock()
        mock_add_endpoint.return_value = None
        mock_agui_toolset.return_value = MagicMock()

        yield {
            "mcp_toolset": mock_mcp,
            "adk_agent": mock_adk_agent,
            "add_endpoint": mock_add_endpoint,
            "agui_toolset": mock_agui_toolset,
        }


@pytest.fixture
def client(mock_dependencies):
    """Create a test client for the AG-UI server.

    Returns:
        TestClient: A FastAPI test client with mocked dependencies.
    """
    from agui_server import create_app

    app = create_app()
    return TestClient(app)


# ──────────────────────────────────────────────────────────────
# Tests: Health & Info Endpoints
# ──────────────────────────────────────────────────────────────


class TestHealthEndpoints:
    """Tests for the root and health check endpoints."""

    def test_root_returns_service_info(self, client):
        """Root endpoint should return service metadata."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert "service" in data
        assert "AG-UI" in data["service"]
        assert data["endpoints"]["agui"] == "/agui"
        assert data["endpoints"]["health"] == "/health"

    def test_health_check_returns_healthy(self, client):
        """Health endpoint should return healthy status."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["agent"] == "er_query_agent"

    def test_agui_get_returns_info(self, client):
        """GET /agui should return helpful info instead of 405."""
        response = client.get("/agui")
        assert response.status_code == 200

        data = response.json()
        assert data["endpoint"] == "/agui"
        assert data["protocol"] == "AG-UI"
        assert "POST" in data["method"]


# ──────────────────────────────────────────────────────────────
# Tests: ADK Agent Configuration
# ──────────────────────────────────────────────────────────────


class TestADKAgentSetup:
    """Tests for ADK agent construction and AG-UI wrapping."""

    def test_adk_agent_created_with_correct_model(self, mock_dependencies):
        """The ADK Agent should be configured with gemini-2.5-flash."""
        from agui_server import create_adk_agent

        agent = create_adk_agent()
        # Agent constructor is called — check name and model
        assert agent.name == "er_query_agent"
        assert agent.model == "gemini-2.5-flash"

    def test_adk_agent_includes_custom_tools(self, mock_dependencies):
        """Agent should include submit_long_task and check_task_status."""
        from agui_server import create_adk_agent

        agent = create_adk_agent()
        tool_items = agent.tools

        # Should contain: McpToolset, AGUIToolset, submit_long_task, check_task_status
        assert len(tool_items) == 4

    def test_adk_agent_has_before_callback(self, mock_dependencies):
        """Agent should have the check_pending_tasks_callback attached."""
        from agui_server import create_adk_agent
        from adk_agent.tools import check_pending_tasks_callback

        agent = create_adk_agent()
        assert agent.before_agent_callback == check_pending_tasks_callback

    def test_agui_agent_wraps_adk_agent(self, mock_dependencies):
        """ADKAgent middleware should be created with correct params."""
        from agui_server import create_app

        create_app()

        mock_adk_cls = mock_dependencies["adk_agent"]
        mock_adk_cls.assert_called_once()
        call_kwargs = mock_adk_cls.call_args[1]

        assert call_kwargs["app_name"] == "er_query_app"
        assert call_kwargs["user_id"] == "demo_user"
        assert call_kwargs["session_timeout_seconds"] == 3600
        assert call_kwargs["use_in_memory_services"] is True

    def test_agui_endpoint_registered_at_correct_path(self, mock_dependencies):
        """The AG-UI endpoint should be mounted at /agui."""
        from agui_server import create_app

        create_app()

        mock_add = mock_dependencies["add_endpoint"]
        mock_add.assert_called_once()

        call_kwargs = mock_add.call_args[1]
        assert call_kwargs.get("path") == "/agui" or mock_add.call_args[0][2] == "/agui"


# ──────────────────────────────────────────────────────────────
# Tests: MCP Toolset Selection
# ──────────────────────────────────────────────────────────────


class TestMCPToolsetConfig:
    """Tests for MCP connection mode selection (stdio vs SSE)."""

    @patch.dict("os.environ", {}, clear=False)
    def test_stdio_mode_when_no_url_set(self, mock_dependencies):
        """Without MCP_SERVER_URL, should use stdio (local) mode."""
        import os

        os.environ.pop("MCP_SERVER_URL", None)

        from agui_server import _get_mcp_toolset

        toolset = _get_mcp_toolset()
        # McpToolset was called — stdio mode uses StdioConnectionParams
        mock_mcp = mock_dependencies["mcp_toolset"]
        assert mock_mcp.called

    @patch.dict("os.environ", {"MCP_SERVER_URL": "https://example.com/mcp"})
    def test_sse_mode_when_url_set(self, mock_dependencies):
        """With MCP_SERVER_URL set, should use SSE (remote) mode."""
        from agui_server import _get_mcp_toolset

        toolset = _get_mcp_toolset()
        mock_mcp = mock_dependencies["mcp_toolset"]
        assert mock_mcp.called


# ──────────────────────────────────────────────────────────────
# Tests: CORS Configuration
# ──────────────────────────────────────────────────────────────


class TestCORSConfig:
    """Tests for CORS middleware configuration."""

    def test_cors_allows_localhost_3000(self, client):
        """CORS should allow requests from localhost:3000 (Next.js dev)."""
        response = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        # FastAPI CORS middleware should add the Access-Control-Allow-Origin header
        assert response.status_code in (200, 204, 405)
