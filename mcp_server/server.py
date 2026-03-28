"""MCP server exposing Expert Request query tools.

This server wraps the Firestore query functions as MCP tools so they
can be consumed by any MCP-compatible client (e.g., ADK agents, Claude,
or other LLM orchestrators).

Why FastMCP?
    FastMCP (from the `mcp` package) provides a clean, decorator-based
    API for defining MCP tools. It handles JSON schema generation,
    input validation, and the stdio/SSE transport layer automatically.
    This is the recommended approach per the MCP specification.

Usage:
    Local stdio mode:  uv run python -m mcp_server.server
    SSE mode (Cloud Run): Set MCP_TRANSPORT=sse and PORT env vars
"""

import json
import os

from mcp.server.fastmcp import FastMCP

from er_query.client import query_er_by_date, query_er_by_email

# Create the MCP server instance
mcp = FastMCP(
    "ER Query Server",
    instructions=(
        "This server provides tools for querying Expert Request (ER) data "
        "from Firestore. Use query_er_by_email to find ERs assigned to a "
        "specific Customer Engineer, or query_er_by_date to find ERs "
        "created in a specific year or month."
    ),
)


@mcp.tool()
def search_er_by_email(assigned_ce_email: str) -> str:
    """Search Expert Requests by the assigned Customer Engineer's email.

    Use this tool when you need to find all Expert Requests (ERs) assigned
    to a specific person. The email should be a Google corporate email
    (e.g., weiyih@google.com).

    Args:
        assigned_ce_email: The email address of the assigned Customer
            Engineer (e.g., 'weiyih@google.com').

    Returns:
        A JSON string containing a list of matching ER records. Each record
        includes: er_name, account_name, account_sub_region,
        assigned_ce_email, and details.

        Returns '[]' if no matching ERs are found.

    Example:
        search_er_by_email("weiyih@google.com")
        -> '[{"er_name": "ER-431059", "account_name": "Acme Corp", ...}]'
    """
    results = query_er_by_email(assigned_ce_email)
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def search_er_by_date(year: int, month: int | None = None) -> str:
    """Search Expert Requests by creation date (year or year+month).

    Use this tool when you need to find ERs created in a specific time
    period. You can search by year only, or narrow down to a specific
    month within a year.

    Args:
        year: The year to filter by (e.g., 2024 or 2025).
        month: Optional month to filter by (1-12). If not provided,
            returns all ERs for the entire year.

    Returns:
        A JSON string containing a list of matching ER records. Each record
        includes: er_name, account_name, account_sub_region,
        assigned_ce_email, and details.

        Returns '[]' if no matching ERs are found.

    Example:
        search_er_by_date(2025, 10)
        -> '[{"er_name": "ER-431059", "account_name": "AusPost", ...}]'
    """
    results = query_er_by_date(year=year, month=month)
    return json.dumps(results, indent=2, ensure_ascii=False)


def main():
    """Run the MCP server.

    Supports two transport modes:
    - stdio (default): For local development and testing
    - sse: For Cloud Run deployment (set MCP_TRANSPORT=sse)
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio")

    if transport == "sse":
        port = int(os.getenv("PORT", "8080"))
        mcp.run(transport="sse", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
