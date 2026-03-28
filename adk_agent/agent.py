"""ADK agent for querying Expert Request data via MCP tools.

This agent connects to the ER Query MCP server and uses its tools
to answer user questions about Expert Requests. It supports two
connection modes:

1. **stdio** (default/local): Spawns the MCP server as a subprocess
   and communicates via stdin/stdout. Best for local development.

2. **SSE** (remote/Cloud Run): Connects to a deployed MCP server
   via HTTP SSE. Set MCP_SERVER_URL env var to the Cloud Run URL.

Why MCP over direct function calls?
    Using MCP decouples the agent from the data layer. The same MCP
    server can serve multiple clients (ADK agents, Claude, VSCode, etc.)
    and can be deployed/scaled independently. This is the recommended
    pattern for production agent architectures.
"""

import os
import sys

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    SseConnectionParams,
    StdioConnectionParams,
)
from mcp import StdioServerParameters

AGENT_INSTRUCTION = """You are an Expert Request (ER) query assistant. You help users
find information about Expert Requests from the Firestore database.

You have access to two tools:

1. **search_er_by_email**: Search ERs by the assigned Customer Engineer's email.
   Use this when the user asks about ERs assigned to a specific person.

2. **search_er_by_date**: Search ERs by creation date (year or year+month).
   Use this when the user asks about ERs from a specific time period.

Guidelines:
- Always use the appropriate tool to answer queries. Never make up ER data.
- When presenting results, format them clearly with ER name, account name,
  sub-region, and a brief summary of the details.
- If a query returns many results, summarize the count and highlight
  the most notable ones.
- If no results are found, clearly state that no matching ERs were found.
- For date queries, if the user says "this year" or "last year", calculate
  the appropriate year.
- For email queries, assume @google.com domain if not specified.
"""


def _get_mcp_toolset() -> McpToolset:
    """Create the appropriate MCP toolset based on environment config.

    Returns:
        McpToolset configured for either stdio (local) or SSE (remote)
        connection to the ER Query MCP server.
    """
    mcp_server_url = os.getenv("MCP_SERVER_URL")

    if mcp_server_url:
        # Remote MCP server (Cloud Run deployment)
        return McpToolset(
            connection_params=SseConnectionParams(url=mcp_server_url),
        )
    else:
        # Local MCP server via stdio subprocess
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


# Define the root agent
root_agent = Agent(
    name="er_query_agent",
    model="gemini-2.0-flash",
    instruction=AGENT_INSTRUCTION,
    description="An agent that queries Expert Request data from Firestore",
    tools=[_get_mcp_toolset()],
)
