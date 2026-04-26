"""Use Agent Registry to discover, list, and orchestrate remote agents.

Provides CLI subcommands to:
1. List all registered A2A agents and MCP servers
2. Create a local orchestrator agent with a remote A2A agent as sub-agent

Usage:
    # List all registered agents and MCP servers:
    uv run python adk_agent_registry/agent_registry_tool.py list

    # Create orchestrator with a remote A2A agent:
    uv run python adk_agent_registry/agent_registry_tool.py orchestrate

    # Specify a custom agent name:
    uv run python adk_agent_registry/agent_registry_tool.py orchestrate \
        --agent-name "projects/.../agents/agentregistry-..."
"""

import os

import click
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.models import Gemini
from google.genai import types

load_dotenv("adk_agent_registry/.env", override=True)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "hello-world-418507")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
AGENT_NAME = os.getenv(
    "REGISTRY_AGENT_NAME",
    f"projects/{PROJECT_ID}/locations/{LOCATION}/agents/"
    "agentregistry-00000000-0000-0000-3997-7518432f3dfb",
)

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


def list_registered_agents(
    project_id: str,
    location: str,
) -> list[dict]:
    """List all A2A agents registered in the Agent Registry.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., 'us-central1').

    Returns:
        list[dict]: List of agent dictionaries from the registry.
    """
    registry = AgentRegistry(project_id=project_id, location=location)
    response = registry.list_agents()
    return response.get("agents", [])


def list_registered_mcp_servers(
    project_id: str,
    location: str,
) -> list[dict]:
    """List all MCP servers registered in the Agent Registry.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., 'us-central1').

    Returns:
        list[dict]: List of MCP server dictionaries from the registry.
    """
    registry = AgentRegistry(project_id=project_id, location=location)
    response = registry.list_mcp_servers()
    return response.get("mcpServers", [])


def create_orchestrator_agent(
    project_id: str,
    location: str,
    agent_name: str,
) -> Agent:
    """Create an orchestrator agent with a remote A2A agent as sub-agent.

    Uses the Agent Registry to discover and connect to a remote A2A agent,
    then wraps it as a sub-agent of a local orchestrator.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., 'us-central1').
        agent_name: Full resource name of the remote A2A agent in Agent Registry.

    Returns:
        Agent: An ADK Agent configured with the remote agent as a sub-agent.
    """
    registry = AgentRegistry(project_id=project_id, location=location)
    remote_agent = registry.get_remote_a2a_agent(agent_name)

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


# ---------- CLI ----------


@click.group()
def cli():
    """Agent Registry CLI — list and orchestrate registered agents."""
    pass


@cli.command()
@click.option(
    "--project-id",
    type=str,
    default=None,
    help=f"GCP project ID (default: {PROJECT_ID})",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help=f"GCP region (default: {LOCATION})",
)
def list(
    project_id: str | None,
    location: str | None,
) -> None:
    """List all registered A2A agents and MCP servers."""
    project_id = project_id or PROJECT_ID
    location = location or LOCATION

    click.echo(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   📋 AGENT REGISTRY — List Resources                      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(f"  Project:  {project_id}")
    click.echo(f"  Location: {location}")

    # List A2A agents
    click.echo("\n── A2A Agents ──────────────────────────────────────────────")
    agents = list_registered_agents(project_id, location)
    if agents:
        for agent in agents:
            click.echo(f"  📌 {agent.get('displayName', 'N/A')}")
            click.echo(f"     Resource:  {agent.get('name', 'N/A')}")

            # Protocol type (A2A_AGENT or CUSTOM)
            protocols = agent.get("protocols", [])
            proto_types = [p.get("type", "?") for p in protocols]
            click.echo(f"     Protocol:  {', '.join(proto_types)}")

            # Framework (from attributes)
            attrs = agent.get("attributes", {})
            framework = attrs.get(
                "agentregistry.googleapis.com/system/Framework", {}
            ).get("framework", "N/A")
            click.echo(f"     Framework: {framework}")

            # Runtime reference (reasoning engine URI)
            runtime_ref = attrs.get(
                "agentregistry.googleapis.com/system/RuntimeReference", {}
            ).get("uri", "")
            if runtime_ref:
                click.echo(f"     Runtime:   {runtime_ref}")

            # Created time
            created = agent.get("createTime", "")
            if created:
                click.echo(f"     Created:   {created[:19]}")

            # Description
            desc = agent.get("description", "")
            if desc:
                click.echo(f"     Desc:      {desc[:80]}")

            # Skills
            skills = agent.get("skills", [])
            if skills:
                skill_names = [s.get("name", "?") for s in skills]
                click.echo(f"     Skills:    {', '.join(skill_names)}")

            click.echo()
    else:
        click.echo("  (no agents found)")

    # List MCP servers
    click.echo("── MCP Servers ─────────────────────────────────────────────")
    servers = list_registered_mcp_servers(project_id, location)
    if servers:
        for server in servers:
            click.echo(f"  📡 {server.get('displayName', 'N/A')}")
            click.echo(f"     Resource: {server.get('name', 'N/A')}")
            desc = server.get("description", "")
            if desc:
                click.echo(f"     Desc:     {desc[:80]}")
            created = server.get("createTime", "")
            if created:
                click.echo(f"     Created:  {created[:19]}")
            click.echo()
    else:
        click.echo("  (no MCP servers found)")

    click.echo(f"\n  Total: {len(agents)} agents, {len(servers)} MCP servers")


@cli.command()
@click.option(
    "--project-id",
    type=str,
    default=None,
    help=f"GCP project ID (default: {PROJECT_ID})",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help=f"GCP region (default: {LOCATION})",
)
@click.option(
    "--agent-name",
    type=str,
    default=None,
    help="Full resource name of remote A2A agent (default: REGISTRY_AGENT_NAME from env)",
)
def orchestrate(
    project_id: str | None,
    location: str | None,
    agent_name: str | None,
) -> None:
    """Create an orchestrator agent with a remote A2A sub-agent."""
    project_id = project_id or PROJECT_ID
    location = location or LOCATION
    agent_name = agent_name or AGENT_NAME

    click.echo(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 AGENT REGISTRY — Create Orchestrator                 ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(f"  Project:    {project_id}")
    click.echo(f"  Location:   {location}")
    click.echo(f"  Agent Name: {agent_name}")

    agent = create_orchestrator_agent(
        project_id=project_id,
        location=location,
        agent_name=agent_name,
    )

    click.echo(f"\n  ✅ Orchestrator agent created: {agent.name}")
    click.echo(f"     Sub-agents: {[sa.name for sa in agent.sub_agents]}")


if __name__ == "__main__":
    cli()
