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

import json
import os
import sys

from google.adk.agents import Agent

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
   status "submitted" — the work runs in the background for the specified
   duration. If the user doesn't specify a duration, default to 10 seconds.
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


def search_er_by_email(assigned_ce_email: str) -> str:
    """Search Expert Requests by the assigned Customer Engineer's email.

    Args:
        assigned_ce_email: The email address of the assigned Customer
            Engineer (e.g., 'weiyih@google.com').

    Returns:
        A JSON string containing matching ER records with er_name,
        account_name, account_sub_region, assigned_ce_email, and details.
        Returns '[]' if no matching ERs are found.
    """
    from er_query.client import query_er_by_email as _query

    results = _query(assigned_ce_email)
    return json.dumps(results, indent=2, ensure_ascii=False)


def search_er_by_date(year: int, month: int | None = None) -> str:
    """Search Expert Requests by creation date (year or year+month).

    Args:
        year: The year to filter by (e.g., 2024 or 2025).
        month: Optional month to filter by (1-12).

    Returns:
        A JSON string containing matching ER records.
        Returns '[]' if no matching ERs are found.
    """
    from er_query.client import query_er_by_date as _query

    results = _query(year=year, month=month)
    return json.dumps(results, indent=2, ensure_ascii=False)


def get_er_fields(er_name: str, fields: str | None = None) -> str:
    """Get specific fields from an Expert Request by its ER name.

    Args:
        er_name: The ER identifier (e.g., 'ER-431059').
        fields: Optional comma-separated field names (e.g., 'fsa_status,product').

    Returns:
        A JSON string with the requested fields. Returns '[]' if not found.
    """
    from er_query.client import query_er_by_name as _query

    results = _query(er_name=er_name, fields=fields)
    return json.dumps(results, indent=2, ensure_ascii=False, default=str)


def _get_identity_token(audience: str) -> str | None:
    """Fetch a Google Cloud identity token for authenticated Cloud Run requests.

    Tries two methods in order:
    1. google.oauth2.id_token (works with service accounts, metadata server)
    2. gcloud CLI fallback (works with user credentials in local dev)

    Args:
        audience: The target audience URL (the Cloud Run service URL).

    Returns:
        The identity token string, or None if credentials are unavailable.
    """
    # Method 1: google.oauth2.id_token (service accounts, Cloud Run, GKE)
    try:
        from google.auth.transport.requests import Request as AuthRequest
        from google.oauth2 import id_token

        return id_token.fetch_id_token(AuthRequest(), audience)
    except Exception:
        pass

    # Method 2: gcloud CLI fallback (local development)
    try:
        import subprocess

        return subprocess.check_output(
            ["gcloud", "auth", "print-identity-token"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _get_tools() -> list:
    """Get the appropriate tools based on environment config.

    Uses MCP toolset if MCP_SERVER_URL is set (remote SSE mode),
    otherwise uses direct function tools (better for Agent Engine deployment
    since they can be pickled).

    Returns:
        List of tools for the agent.
    """
    mcp_server_url = os.getenv("MCP_SERVER_URL")

    if mcp_server_url:
        # Remote MCP server (Cloud Run deployment)
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams

        # Ensure URL ends with /sse (MCP SSE endpoint path)
        sse_url = mcp_server_url.rstrip("/")
        if not sse_url.endswith("/sse"):
            sse_url = f"{sse_url}/sse"

        # Cloud Run requires an identity token for authenticated services
        headers = {}
        token = _get_identity_token(mcp_server_url)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        return [
            McpToolset(
                connection_params=SseConnectionParams(
                    url=sse_url,
                    headers=headers,
                )
            ),
            submit_long_task,
            check_task_status,
        ]
    else:
        # Direct function tools (picklable for Agent Engine deployment)
        return [
            search_er_by_email,
            search_er_by_date,
            get_er_fields,
            submit_long_task,
            check_task_status,
        ]


# Define the root agent
root_agent = Agent(
    name="er_query_agent",
    model="gemini-2.5-flash",
    instruction=AGENT_INSTRUCTION,
    description="An agent that queries Expert Request data from Firestore and runs background tasks",
    tools=_get_tools(),
    before_agent_callback=check_pending_tasks_callback,
)
