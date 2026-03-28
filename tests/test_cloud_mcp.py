"""End-to-end test for the Cloud Run MCP server.

Tests the deployed MCP server by connecting via SSE and calling
each tool with real parameters. Verifies actual data is returned.

Run with: make test-cloud
"""

import asyncio
import json
import subprocess

from mcp import ClientSession
from mcp.client.sse import sse_client

# Cloud Run service URL
MCP_SERVER_URL = "https://er-mcp-server-462396196470.us-central1.run.app/sse"


def _get_auth_headers() -> dict[str, str]:
    """Get Google Cloud identity token for authenticated requests.

    Returns:
        A dict with the Authorization header.
    """
    token = subprocess.check_output(
        ["gcloud", "auth", "print-identity-token"],
        text=True,
    ).strip()
    return {"Authorization": f"Bearer {token}"}


async def test_tools_list():
    """Test that the MCP server lists both tools correctly."""
    print("\n📋 Test: tools/list")

    headers = _get_auth_headers()
    async with sse_client(MCP_SERVER_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"   Tools found: {tool_names}")

            assert "search_er_by_email" in tool_names, "Missing search_er_by_email tool"
            assert "search_er_by_date" in tool_names, "Missing search_er_by_date tool"
            print("   ✅ Both tools registered correctly")


async def test_search_by_email():
    """Test search_er_by_email returns real data from Firestore."""
    print("\n📧 Test: search_er_by_email('issein@google.com')")

    headers = _get_auth_headers()
    async with sse_client(MCP_SERVER_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_er_by_email",
                arguments={"assigned_ce_email": "issein@google.com"},
            )

            # Parse the JSON text response
            text = result.content[0].text
            records = json.loads(text)

            print(f"   Found {len(records)} ERs")
            for r in records:
                print(f"   - {r['er_name']}: {r['account_name']} ({r['account_sub_region']})")

            assert len(records) >= 1, "Expected at least 1 ER for issein@google.com"
            assert any(
                r["er_name"] == "ER-431059" for r in records
            ), "Expected ER-431059 in results"
            print("   ✅ Email query returns correct data")


async def test_search_by_date():
    """Test search_er_by_date returns real data from Firestore."""
    print("\n📅 Test: search_er_by_date(year=2024, month=4)")

    headers = _get_auth_headers()
    async with sse_client(MCP_SERVER_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_er_by_date",
                arguments={"year": 2024, "month": 4},
            )

            text = result.content[0].text
            records = json.loads(text)

            print(f"   Found {len(records)} ERs")
            for r in records[:5]:
                print(f"   - {r['er_name']}: {r['account_name']}")

            assert len(records) >= 1, "Expected at least 1 ER for April 2024"
            print("   ✅ Date query returns correct data")


async def test_search_by_email_no_results():
    """Test that searching for a non-existent email returns empty."""
    print("\n📧 Test: search_er_by_email('nonexistent@google.com')")

    headers = _get_auth_headers()
    async with sse_client(MCP_SERVER_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_er_by_email",
                arguments={"assigned_ce_email": "nonexistent_xyz_123@google.com"},
            )

            text = result.content[0].text
            records = json.loads(text)

            print(f"   Found {len(records)} ERs")
            assert records == [], "Expected empty list for non-existent email"
            print("   ✅ Returns empty list correctly")


async def main():
    """Run all cloud MCP server tests."""
    print("=" * 60)
    print("☁️  Cloud Run MCP Server Tests")
    print(f"   URL: {MCP_SERVER_URL}")
    print("=" * 60)

    await test_tools_list()
    await test_search_by_email()
    await test_search_by_date()
    await test_search_by_email_no_results()

    print("\n" + "=" * 60)
    print("✅ All cloud MCP server tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
