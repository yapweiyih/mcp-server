"""End-to-end test: start MCP Streamable HTTP server, then call tools/list.

This script spins up the MCP server in streamable-http mode as a subprocess,
waits for it to become ready, connects via the MCP Python SDK's Streamable
HTTP client, calls initialize + tools/list, validates the response, then
tears down.

Usage:
    uv run python tests/test_mcp_http.py          # standalone
    make test-mcp                                  # via Makefile

Why Streamable HTTP?
    Streamable HTTP is the modern MCP transport that replaces SSE.
    It uses a single /mcp endpoint with standard HTTP POST requests
    and is required by Gemini Enterprise / Agentspace. SSE is now
    considered legacy.

Why integration test?
    The unit tests in test_mcp_server.py mock the query layer and test
    tool functions in isolation. This test verifies the *transport*
    layer works: the server boots, accepts Streamable HTTP connections,
    and responds to the MCP protocol handshake + tools/list correctly.
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time

# ── Expected tool names exposed by the MCP server ──────────────────
EXPECTED_TOOLS = {"search_er_by_email", "search_er_by_date", "get_er_fields"}

# ── Config ─────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 18080  # Use a non-standard port to avoid conflicts
STARTUP_TIMEOUT = 15  # seconds to wait for server readiness
MCP_URL = f"http://{HOST}:{PORT}/mcp"


def _port_is_open(host: str, port: int) -> bool:
    """Check whether a TCP port is accepting connections.

    Args:
        host: Hostname or IP to probe.
        port: Port number to check.

    Returns:
        True if the port is open (server is listening), False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def start_mcp_server() -> subprocess.Popen:
    """Start the MCP server in Streamable HTTP mode as a background subprocess.

    Returns:
        The Popen handle for the server process.

    Raises:
        RuntimeError: If the server fails to start within STARTUP_TIMEOUT.
    """
    env = {**os.environ, "MCP_TRANSPORT": "streamable-http", "PORT": str(PORT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(
                f"MCP server exited early (rc={proc.returncode}): {stderr}"
            )
        if _port_is_open(HOST, PORT):
            return proc
        time.sleep(0.3)

    proc.kill()
    stderr = proc.stderr.read().decode() if proc.stderr else ""
    raise RuntimeError(f"MCP server did not start within {STARTUP_TIMEOUT}s: {stderr}")


def stop_mcp_server(proc: subprocess.Popen) -> None:
    """Gracefully stop the MCP server subprocess.

    Args:
        proc: The Popen handle returned by start_mcp_server.
    """
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


async def run_tools_list() -> list[dict]:
    """Connect to the MCP Streamable HTTP server and call tools/list.

    Returns:
        A list of tool info dicts, each with at least 'name' and
        'description' keys.

    Raises:
        AssertionError: If the MCP handshake or tools/list fails.
    """
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            assert init_result is not None, "MCP initialize returned None"

            tools_result = await session.list_tools()
            assert tools_result is not None, "tools/list returned None"

            return [
                {"name": t.name, "description": t.description}
                for t in tools_result.tools
            ]


def main() -> int:
    """Run the MCP Streamable HTTP integration test.

    Returns:
        0 on success, 1 on failure.
    """
    print(f"🚀 Starting MCP Streamable HTTP server on {HOST}:{PORT} ...")
    proc = None
    try:
        proc = start_mcp_server()
        print(f"✅ Server is up (pid={proc.pid})")

        print(f"🔌 Connecting to {MCP_URL} ...")
        tools = asyncio.run(run_tools_list())

        # ── Validate ───────────────────────────────────────────────
        tool_names = {t["name"] for t in tools}
        print(f"📋 Tools returned: {sorted(tool_names)}")

        missing = EXPECTED_TOOLS - tool_names
        if missing:
            print(f"❌ FAIL — missing tools: {missing}")
            return 1

        # Print tool details
        for t in tools:
            print(f"   • {t['name']}: {t['description'][:80]}...")

        print(f"✅ PASS — all {len(EXPECTED_TOOLS)} expected tools found")
        return 0

    except Exception as e:
        print(f"❌ FAIL — {e}")
        return 1

    finally:
        if proc:
            print("🛑 Stopping MCP server ...")
            stop_mcp_server(proc)
            print("   Server stopped.")


if __name__ == "__main__":
    sys.exit(main())
