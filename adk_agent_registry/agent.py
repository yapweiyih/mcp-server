"""ADK agent that retrieves MCP tools from Google Cloud Agent Registry.

This agent connects to an MCP server registered in Agent Registry and
uses its tools to answer user questions about Expert Requests.

Why Agent Registry over direct MCP connection?
    Agent Registry acts as a centralized catalog of MCP servers and their
    tools. Instead of hardcoding MCP server URLs, the agent discovers
    tools via the registry. This enables:
    - Centralized tool governance and discoverability
    - Runtime identity and access control via IAM
    - Tool versioning and lifecycle management
    - Multi-agent architectures where agents share tools

Usage:
    cd adk_agent_registry
    adk run .
"""

import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.auth import default
from google.genai import types

# Load environment from adk_agent_registry/.env
load_dotenv("adk_agent_registry/.env")

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Google Cloud configuration
_, project_id = default()
LOCATION = os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_REGISTRY_NAME = os.environ.get(
    "AGENT_REGISTRY_NAME",
    "agentregistry-00000000-0000-0000-9888-0de72f508e99",
)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

AGENT_INSTRUCTION = """You are an Expert Request (ER) query assistant. You help users
find information about Expert Requests from the Firestore database.

Guidelines:
- Always use the appropriate tool to answer queries. Never make up ER data.
- When presenting results, format them clearly with ER name, account name,
  sub-region, and a brief summary of the details.
- If a query returns many results, summarize the count and highlight
  the most notable ones.
- If no results are found, clearly state that no matching ERs were found.
- For date queries, if the user says "this year" or "last year", calculate
  the appropriate year.
- When the user mentions a specific ER number (like ER-430001), use
  get_er_fields. Map user field names to actual field names (e.g.,
  "fsa asset" -> "fsa_assets", "fsa status" -> "fsa_status").
"""

# Retrieve MCP tools from Agent Registry
logger.info("=" * 60)
logger.info("🤖 Initializing ER Query Agent (Agent Registry)")
logger.info("=" * 60)

mcp_server_resource = (
    f"projects/{project_id}/locations/{LOCATION}/mcpServers/{AGENT_REGISTRY_NAME}"
)
logger.info("📡 Agent Registry MCP server: %s", mcp_server_resource)

registry = AgentRegistry(project_id=project_id, location=LOCATION)
mcp_toolset = registry.get_mcp_toolset(mcp_server_resource)
logger.info("✅ MCP toolset loaded from Agent Registry")

# Define the root agent
root_agent = Agent(
    name="er_query_agent_registry",
    description="An agent that queries Expert Request data using tools from Agent Registry",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[mcp_toolset],
)

logger.info("✅ Agent ready")
