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

from adk_agent.tools import (
    check_pending_tasks_callback,
    check_task_status,
    submit_long_task,
)

AGENT_INSTRUCTION = """You are an Expert Request (ER) query assistant. You help users
find information about Expert Requests from the Firestore database.

You have access to three tools:

1. **search_er_by_email**: Search ERs by the assigned Customer Engineer's email.
   Use this when the user asks about ERs assigned to a specific person.

2. **search_er_by_date**: Search ERs by creation date (year or year+month).
   Use this when the user asks about ERs from a specific time period.

3. **get_er_fields**: Get specific fields from an ER by its name (e.g., ER-431059).
   Use this when the user asks about a specific ER and wants to see particular
   fields or attributes. The user may ask for any combination of fields like:
   - FSA fields: fsa_assets, fsa_status, fsa_flight_status, fsa_status_tracking,
     fsa_weekly_update, fsa_workload_gross_revenue_tracking
   - Workload fields: workload_name, workload_gross_revenue,
     workload_gross_revenue_tracking, workload_progress, workload_pillar
   - Basic fields: details, product, status, priority, account_name
   - People: assigned_ce_email, assigned_ce_name, requestor_name, requestor_email
   - Opportunity: opportunity_name, opportunity_amount, opportunity_stage_name
   - Engagement: engagement_type, engagement_tier, engagement_priority
   Pass the requested field names as a comma-separated string in the `fields`
   parameter. If no specific fields are mentioned, omit `fields` to return all.

4. **submit_long_task**: Submit a dummy long-running background task.
   Use this when the user asks to submit, start, or run a dummy task,
   background task, or long-running task. This returns IMMEDIATELY with
   status "submitted" — the work runs in the background (~5 seconds).
   Tell the user the task has been submitted and they can check status later.

5. **check_task_status**: Check whether a previously submitted task has
   completed. Use this when the user asks "is my task done?" or "check
   status of <task_name>".

{task_completed_notification}

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
- When the user mentions a specific ER number (like ER-431059), use
  get_er_fields. Map user field names to actual field names (e.g.,
  "fsa asset" -> "fsa_assets", "fsa status" -> "fsa_status").
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
    description="An agent that queries Expert Request data from Firestore and runs background tasks",
    tools=[
        _get_mcp_toolset(),
        submit_long_task,
        check_task_status,
    ],
    before_agent_callback=check_pending_tasks_callback,
)
