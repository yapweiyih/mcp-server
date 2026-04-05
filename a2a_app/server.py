"""A2A server that exposes the ADK agent via the Agent-to-Agent protocol.

A2A (Agent-to-Agent) is an open protocol by Google that standardizes how
AI agents discover and communicate with each other. While MCP focuses on
tools and AG-UI on user interaction, A2A completes the trifecta by enabling
agent-to-agent collaboration.

This module wraps the existing ADK ER Query agent with A2A protocol support,
exposing it as a standalone A2A-compliant HTTP server. Other agents can
discover this agent's capabilities via its AgentCard and send it tasks.

Architecture:
    Remote Agent (A2A Client) --> A2A Protocol (HTTP) --> This Server --> ADK Agent --> MCP Tools

Two modes of operation:
    1. **Local A2A server** (this file): Uses `to_a2a()` from ADK to run a
       standalone Starlette-based A2A server for local development and testing.
    2. **Agent Engine** (a2a_app/deploy.py): Deploys to Vertex AI Agent
       Engine which natively serves A2A endpoints in production.

Usage:
    # Start the local A2A server:
    uv run python -m a2a_app.server

    # Or via Makefile:
    make a2a-server
"""

import logging
import os
import sys
import warnings

from dotenv import load_dotenv

# Suppress ADK experimental feature warnings (A2A support is marked experimental)
warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")

load_dotenv("adk_agent/.env")

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_a2a_app() -> None:
    """Create and run the A2A server wrapping the ADK ER Query agent.

    Uses the ADK `to_a2a()` utility which:
    1. Creates an A2A-compliant Starlette application
    2. Generates an AgentCard at /.well-known/agent.json
    3. Exposes /a2a endpoint for message handling
    4. Manages the ADK Runner lifecycle internally

    The server runs on the port specified by A2A_PORT env var (default: 8001).
    """
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    from adk_agent.agent import root_agent

    host = "0.0.0.0"
    port = int(os.getenv("A2A_PORT", "8001"))

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤝  A2A Server for ER Query Agent                       ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )
    print(f"  🔗  A2A endpoint   : http://localhost:{port}")
    print(f"  📇  Agent card     : http://localhost:{port}/.well-known/agent.json")
    print()

    # to_a2a() returns a Starlette app — run it with uvicorn
    app = to_a2a(root_agent, host="localhost", port=port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    create_a2a_app()
