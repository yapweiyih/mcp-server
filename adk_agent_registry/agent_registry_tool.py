"""Use Agent Registry to discover and orchestrate a remote A2A agent.

Demonstrates how to use the ADK Agent Registry integration to:
1. Look up a registered A2A agent by its resource name
2. Create a local orchestrator agent with the remote agent as a sub-agent
3. Run the orchestrator to delegate tasks to the remote agent

Usage:
    uv run python adk_agent_registry/agent_registry_tool.py
"""

import os

from google.adk.agents import Agent
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.genai import types

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "hello-world-418507")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_NAME = os.getenv(
    "REGISTRY_AGENT_NAME",
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/"
    "agentregistry-00000000-0000-0000-3997-7518432f3dfb",
)

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


def create_orchestrator_agent() -> Agent:
    """Create an orchestrator agent with a remote A2A agent as sub-agent.

    Uses the Agent Registry to discover and connect to a remote A2A agent,
    then wraps it as a sub-agent of a local orchestrator.

    Returns:
        Agent: An ADK Agent configured with the remote agent as a sub-agent.
    """
    registry = AgentRegistry(project_id=PROJECT_ID, location=LOCATION)
    remote_agent = registry.get_remote_a2a_agent(AGENT_NAME)

    orchestrator = Agent(
        name="er_query_agent",
        description=(
            "An AI agent that queries Expert Request data from Firestore "
            "and manages background tasks. Supports searching by email, "
            "date, and specific ER fields."
        ),
        model=Gemini(
            model="gemini-2.5-flash",
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        sub_agents=[remote_agent],
    )

    return orchestrator


def list_registered_agents():
    """List all agents registered in the Agent Registry."""
    registry = AgentRegistry(project_id=PROJECT_ID, location=LOCATION)
    agents_response = registry.list_agents()

    if "agents" in agents_response:
        for agent in agents_response["agents"]:
            print(f"Display Name: {agent.get('displayName')}")
            print(f"Resource Name (AGENT_NAME): {agent.get('name')}")
            print("-" * 20)
    else:
        print("No agents found in registry.")


if __name__ == "__main__":
    agent = create_orchestrator_agent()
    print(f"✅ Orchestrator agent created: {agent.name}")
    print(f"   Sub-agents: {[sa.name for sa in agent.sub_agents]}")
