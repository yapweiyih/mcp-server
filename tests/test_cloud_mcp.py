"""End-to-end test for the Cloud Run MCP server.

Tests the deployed MCP server by connecting via Streamable HTTP and
calling each tool with real parameters. Verifies actual data is returned.

Run with: make test-cloud
"""

import asyncio
import json
import os
import subprocess

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# Load MCP_SERVER_URL from adk_agent/.env (e.g. https://...run.app)
load_dotenv("adk_agent/.env")
_base_url = os.getenv("MCP_SERVER_URL")
if not _base_url:
    raise RuntimeError("MCP_SERVER_URL not set in adk_agent/.env")
MCP_SERVER_URL = f"{_base_url.rstrip('/')}/mcp"


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
    async with streamable_http_client(
        MCP_SERVER_URL, http_client=httpx.AsyncClient(headers=headers)
    ) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"   Tools found: {tool_names}")

            assert "search_er_by_email" in tool_names, "Missing search_er_by_email tool"
            assert "search_er_by_date" in tool_names, "Missing search_er_by_date tool"
            assert "get_er_fields" in tool_names, "Missing get_er_fields tool"
            print("   ✅ All 3 tools registered correctly")


async def test_search_by_email():
    """Test search_er_by_email returns expected ERs from Firestore."""
    test_email = os.getenv("TEST_CE_EMAIL", "issein@google.com")
    print(f"\n📧 Test: search_er_by_email('{test_email}')")

    headers = _get_auth_headers()
    async with streamable_http_client(
        MCP_SERVER_URL, http_client=httpx.AsyncClient(headers=headers)
    ) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_er_by_email",
                arguments={"assigned_ce_email": test_email},
            )

            # Parse the JSON text response
            text = result.content[0].text
            records = json.loads(text)

            assert isinstance(records, list), "Expected a JSON list"
            print(f"   Found {len(records)} ERs")
            for r in records[:5]:
                print(
                    f"   - {r['er_name']}: {r['account_name']} ({r['account_sub_region']})"
                )

            assert len(records) >= 1, f"Expected at least 1 ER for {test_email}"
            er_names = {r["er_name"] for r in records}
            assert "ER-431059" in er_names, "Expected ER-431059 in results"
            print("   ✅ Email query returned valid response")


async def test_search_by_date():
    """Test search_er_by_date returns expected ERs from Firestore."""
    print("\n📅 Test: search_er_by_date(year=2024, month=4)")

    headers = _get_auth_headers()
    async with streamable_http_client(
        MCP_SERVER_URL, http_client=httpx.AsyncClient(headers=headers)
    ) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "search_er_by_date",
                arguments={"year": 2024, "month": 4},
            )

            text = result.content[0].text
            records = json.loads(text)

            assert isinstance(records, list), "Expected a JSON list"
            print(f"   Found {len(records)} ERs")
            for r in records[:5]:
                print(f"   - {r['er_name']}: {r['account_name']}")

            assert len(records) >= 1, "Expected at least 1 ER for April 2024"
            er_names = {r["er_name"] for r in records}
            assert "ER-263385" in er_names, "Expected ER-263385 in results"
            print("   ✅ Date query returned valid response")


async def test_search_by_email_no_results():
    """Test that searching for a non-existent email returns empty."""
    print("\n📧 Test: search_er_by_email('nonexistent@google.com')")

    headers = _get_auth_headers()
    async with streamable_http_client(
        MCP_SERVER_URL, http_client=httpx.AsyncClient(headers=headers)
    ) as (
        read,
        write,
        _,
    ):
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


async def test_adk_agent_with_cloud_mcp():
    """Test ADK agent using the Cloud Run MCP server via Streamable HTTP.

    Creates an agent that connects to the deployed MCP server and
    verifies it can answer natural language queries using the remote tools.
    """
    import os

    from dotenv import load_dotenv
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import (
        StreamableHTTPConnectionParams,
    )
    from google.genai import types

    # Load Vertex AI config
    load_dotenv("adk_agent/.env")

    print("\n🤖 Test: ADK Agent with Cloud Run MCP Server")
    print(f"   MCP URL: {MCP_SERVER_URL}")

    # Create agent pointing to Cloud Run MCP server
    cloud_agent = Agent(
        name="cloud_er_agent",
        model="gemini-2.5-flash",
        instruction=(
            "You are an ER query assistant. Use search_er_by_email to find "
            "ERs by email and search_er_by_date to find ERs by date."
        ),
        tools=[
            McpToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=MCP_SERVER_URL,
                    headers=_get_auth_headers(),
                ),
            )
        ],
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=cloud_agent,
        app_name="cloud_test",
        session_service=session_service,
    )

    test_email = os.getenv("TEST_CE_EMAIL", "issein@google.com")

    # --- Test 1: Email query ---
    print(f"\n   📧 Agent query: 'Find ERs assigned to {test_email}'")
    session = await session_service.create_session(
        app_name="cloud_test", user_id="test"
    )
    final_text = ""
    async for event in runner.run_async(
        user_id="test",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Find ERs assigned to {test_email}")],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    print(f"   Response: {final_text[:300]}...")
    assert final_text, "Agent returned empty response"
    print("   ✅ Agent returned a response for email query")

    # --- Test 2: Date query ---
    print("\n   📅 Agent query: 'Show ERs from April 2024'")
    session2 = await session_service.create_session(
        app_name="cloud_test", user_id="test"
    )
    final_text2 = ""
    async for event in runner.run_async(
        user_id="test",
        session_id=session2.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text="Show ERs from April 2024")],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text2 = event.content.parts[0].text

    print(f"   Response: {final_text2[:300]}...")
    assert final_text2, "Agent returned empty response"
    print("   ✅ Agent returned a response for date query")


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
    await test_adk_agent_with_cloud_mcp()

    print("\n" + "=" * 60)
    print("✅ All cloud MCP server tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
