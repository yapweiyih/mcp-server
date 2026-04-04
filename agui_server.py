"""AG-UI server that exposes the ADK agent via the AG-UI protocol.

AG-UI (Agent-User Interaction) is an open, event-based protocol by CopilotKit
that standardizes how AI agents connect to user-facing applications. It sits
alongside MCP (tools) and A2A (agent-to-agent) in the agentic protocol stack.

This module wraps the existing ADK ER Query agent with the `ag-ui-adk`
middleware and exposes it as a FastAPI endpoint. The frontend (CopilotKit /
Next.js) connects to this endpoint via Server-Sent Events (SSE) to get
real-time streaming responses.

Architecture:
    Frontend (CopilotKit) --> AG-UI Protocol (SSE) --> This Server --> ADK Agent --> MCP Tools

Usage:
    # Start the AG-UI server:
    uv run python agui_server.py

    # Or via Makefile:
    make agui-server
"""

import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ag_ui_adk import ADKAgent, AGUIToolset, add_adk_fastapi_endpoint
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    SseConnectionParams,
    StdioConnectionParams,
)
from mcp import StdioServerParameters

from adk_agent.tools import (
    check_pending_tasks_callback,
    check_task_status,
    submit_long_task,
)

load_dotenv()

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noise from middleware internals
logging.getLogger("ag_ui_adk").setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────
# Agent instruction (same as the original agent)
# ─────────────────────────────────────────────────────────────
AGENT_INSTRUCTION = """You are an Expert Request (ER) query assistant. You help users
find information about Expert Requests from the Firestore database.

You have access to these tools:

1. **search_er_by_email** – Search ERs by CE email.
2. **search_er_by_date** – Search ERs by creation date.
3. **get_er_fields** – Get specific fields from an ER by name (e.g. ER-431059).
4. **submit_long_task** – Submit a background task (returns immediately).
5. **check_task_status** – Check a previously submitted task.

{task_completed_notification}

Guidelines:
- Always use the appropriate tool. Never make up ER data.
- Format results clearly with ER name, account, sub-region.
- If no results found, say so.
- For email queries, assume @google.com if not specified.
- Map user field names to actual field names (e.g. "fsa asset" → "fsa_assets").
"""


def _get_mcp_toolset() -> McpToolset:
    """Create the appropriate MCP toolset based on environment config.

    Returns:
        McpToolset configured for either stdio (local) or SSE (remote)
        connection to the ER Query MCP server.
    """
    import sys

    mcp_server_url = os.getenv("MCP_SERVER_URL")

    if mcp_server_url:
        return McpToolset(
            connection_params=SseConnectionParams(url=mcp_server_url),
        )
    else:
        return McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "mcp_server"],
                    env={
                        **os.environ,
                        "PYTHONPATH": os.getcwd(),
                    },
                ),
            ),
        )


def create_adk_agent() -> Agent:
    """Create the ADK agent with MCP tools and custom tools.

    Returns:
        Agent: A fully configured ADK agent for ER queries.
    """
    return Agent(
        name="er_query_agent",
        model="gemini-2.0-flash",
        instruction=AGENT_INSTRUCTION,
        description=(
            "An agent that queries Expert Request data from Firestore "
            "and runs background tasks"
        ),
        tools=[
            _get_mcp_toolset(),
            AGUIToolset(),  # Accept tools from the AG-UI frontend
            submit_long_task,
            check_task_status,
        ],
        before_agent_callback=check_pending_tasks_callback,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application with AG-UI endpoint.

    Returns:
        FastAPI: The configured application ready to serve AG-UI requests.
    """
    app = FastAPI(
        title="ER Query Agent – AG-UI Server",
        description="ADK agent exposed via the AG-UI protocol for CopilotKit integration",
        version="0.1.0",
    )

    # CORS – allow the Next.js frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # Next.js dev
            "http://localhost:5173",  # Vite dev
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- AG-UI middleware wrapping the ADK agent ---
    adk_agent = create_adk_agent()

    agui_agent = ADKAgent(
        adk_agent=adk_agent,
        app_name="er_query_app",
        user_id="demo_user",
        session_timeout_seconds=3600,
        use_in_memory_services=True,
    )

    # Expose the agent at /agui endpoint (POST — AG-UI protocol uses SSE over POST)
    add_adk_fastapi_endpoint(app, agui_agent, path="/agui")

    @app.get("/agui")
    async def agui_info() -> dict:
        """Info page when someone hits /agui with GET (e.g. browser).

        The AG-UI protocol uses POST with SSE streaming — this GET handler
        just returns a helpful message instead of a confusing 405.
        """
        return {
            "endpoint": "/agui",
            "protocol": "AG-UI",
            "method": "POST (SSE streaming)",
            "note": (
                "This endpoint accepts POST requests from CopilotKit / AG-UI clients. "
                "Open http://localhost:3000 in your browser for the chat UI."
            ),
        }

    # --- Health / info endpoints ---
    @app.get("/")
    async def root() -> dict:
        """Root endpoint with service info."""
        return {
            "service": "ER Query Agent – AG-UI Server",
            "version": "0.1.0",
            "protocol": "AG-UI (https://ag-ui.com)",
            "endpoints": {
                "agui": "/agui",
                "health": "/health",
                "docs": "/docs",
            },
        }

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "healthy", "agent": "er_query_agent"}

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("AGUI_PORT", "8000"))

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖  AG-UI Server for ER Query Agent                     ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )
    print(f"  🔗  AG-UI endpoint : http://localhost:{port}/agui")
    print(f"  📚  API docs       : http://localhost:{port}/docs")
    print(f"  🏥  Health check   : http://localhost:{port}/health")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
