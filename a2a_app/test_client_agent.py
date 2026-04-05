"""Test script where a local ADK agent calls a remote A2A agent.

This demonstrates agent-to-agent communication: a local "orchestrator"
agent delegates work to the ER Query agent deployed as an A2A service
on Agent Engine. The orchestrator uses ADK's `RemoteA2aAgent` to
transparently communicate with the remote agent via the A2A protocol.

The pattern:
    1. Local orchestrator agent receives user query
    2. Orchestrator delegates to remote ER Query agent via A2A
    3. Remote agent processes with MCP tools + Firestore
    4. Result flows back through A2A to the orchestrator
    5. Orchestrator presents the final answer

This is the canonical "agent calling agent" pattern where each agent
can be independently developed, deployed, and scaled.

Usage:
    # Call the deployed Agent Engine A2A agent:
    uv run python -m a2a_app.test_client_agent --resource-id RESOURCE_ID

    # Call a local A2A server (started via `make a2a-server`):
    uv run python -m a2a_app.test_client_agent --local

    # Custom message:
    uv run python -m a2a_app.test_client_agent --resource-id RESOURCE_ID \\
        --message "How many ERs were created in 2024?"

    # Or via Makefile:
    make test-a2a-client RESOURCE_ID=12345
"""

import asyncio
import logging
import os

import click
from dotenv import load_dotenv

load_dotenv("adk_agent/.env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_orchestrator_with_remote_a2a(
    agent_card_url: str,
) -> "Agent":
    """Build a local ADK orchestrator that delegates to a remote A2A agent.

    The orchestrator is a simple LLM agent that uses `RemoteA2aAgent` as a
    sub-agent. When the user asks about Expert Requests, the orchestrator
    delegates to the remote ER Query agent via A2A protocol.

    Args:
        agent_card_url: URL to the remote agent's card endpoint.
            For local: http://localhost:8001/.well-known/agent.json
            For Agent Engine: constructed from resource ID.

    Returns:
        Agent: A configured ADK agent with remote A2A sub-agent.
    """
    from google.adk.agents import Agent
    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

    # Create a remote A2A agent reference
    remote_er_agent = RemoteA2aAgent(
        name="remote_er_query_agent",
        description=(
            "A remote agent that queries Expert Request (ER) data from "
            "Firestore. It can search ERs by email, date, or specific fields. "
            "Delegate any questions about Expert Requests to this agent."
        ),
        agent_card=agent_card_url,
    )

    # Build the local orchestrator
    orchestrator = Agent(
        name="orchestrator_agent",
        model="gemini-2.0-flash",
        instruction="""You are an orchestrator agent that helps users by
        delegating tasks to specialized sub-agents.

        You have access to a remote ER Query agent that can:
        - Search Expert Requests by email
        - Search Expert Requests by date
        - Get specific fields from an ER
        - Submit and check background tasks

        When the user asks about Expert Requests, delegate to the
        remote_er_query_agent. Present the results clearly to the user.

        For general questions, answer directly without delegation.
        """,
        description="Orchestrator that delegates to remote A2A agents",
        sub_agents=[remote_er_agent],
    )

    return orchestrator


async def run_orchestrator(
    agent_card_url: str,
    message: str,
) -> str:
    """Run the orchestrator agent with a user message.

    Creates a Runner, establishes a session, and sends the message
    through the orchestrator which may delegate to the remote A2A agent.

    Args:
        agent_card_url: URL to the remote agent's agent card.
        message: The user's query message.

    Returns:
        The final response text from the orchestrator.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    orchestrator = _build_orchestrator_with_remote_a2a(agent_card_url)

    session_service = InMemorySessionService()
    runner = Runner(
        agent=orchestrator,
        app_name="a2a_orchestrator_test",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="a2a_orchestrator_test",
        user_id="test_user",
    )

    click.echo(f"📨 Sending to orchestrator: {message}")
    click.echo(f"🔗 Remote agent card: {agent_card_url}")
    click.echo()

    final_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        ),
    ):
        # Log intermediate events
        if event.content and event.content.parts:
            author = event.author or "unknown"
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    click.echo(f"  [{author}] {part.text[:200]}")

        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(
                p.text for p in event.content.parts if hasattr(p, "text") and p.text
            )

    return final_text


def _get_agent_card_url_from_resource(
    project_id: str,
    location: str,
    resource_id: str,
) -> str:
    """Get the agent card URL for a deployed Agent Engine A2A agent.

    For Agent Engine deployments, the agent card URL is constructed from
    the resource name. The RemoteA2aAgent uses this to discover the
    remote agent's capabilities.

    Args:
        project_id: GCP project ID.
        location: GCP region.
        resource_id: Agent Engine resource ID.

    Returns:
        The full URL to the agent's well-known agent card endpoint.
    """
    # Agent Engine A2A URL pattern
    # The agent card is available at the authenticated endpoint
    # RemoteA2aAgent handles the discovery
    base_url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project_id}/locations/{location}/"
        f"reasoningEngines/{resource_id}"
    )
    return f"{base_url}/.well-known/agent.json"


@click.command()
@click.option(
    "--resource-id",
    type=str,
    default=None,
    help="Agent Engine resource ID (for remote Agent Engine agent)",
)
@click.option(
    "--local",
    "use_local",
    is_flag=True,
    default=False,
    help="Use local A2A server at localhost:8001 instead of Agent Engine",
)
@click.option(
    "--local-port",
    type=int,
    default=8001,
    help="Port of the local A2A server (default: 8001)",
)
@click.option(
    "--project-id",
    type=str,
    default=None,
    help="GCP project ID (default: from env)",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help="GCP region (default: from env or us-central1)",
)
@click.option(
    "--message",
    type=str,
    default="Find all ERs assigned to issein@google.com",
    help="Message to send through the orchestrator",
)
def test_a2a_client(
    resource_id: str,
    use_local: bool,
    local_port: int,
    project_id: str,
    location: str,
    message: str,
) -> None:
    """Test an ADK agent calling a remote A2A agent."""

    if not resource_id and not use_local:
        click.echo(
            "❌ Error: Provide --resource-id for Agent Engine "
            "or --local for local A2A server."
        )
        raise SystemExit(1)

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "ikigai-dev-376122")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    # Determine agent card URL
    if use_local:
        agent_card_url = f"http://localhost:{local_port}/.well-known/agent.json"
    else:
        agent_card_url = _get_agent_card_url_from_resource(
            project_id, location, resource_id
        )

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 ADK AGENT → A2A REMOTE AGENT TEST 🤖                 ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(f"📋 Test Parameters:")
    click.echo(f"  Mode:        {'Local' if use_local else 'Agent Engine'}")
    click.echo(f"  Agent Card:  {agent_card_url}")
    click.echo(f"  Message:     {message}")
    click.echo()

    result = asyncio.run(
        run_orchestrator(
            agent_card_url=agent_card_url,
            message=message,
        )
    )

    click.echo("\n" + "=" * 60)
    click.echo("📄 Final Response from Orchestrator:")
    click.echo(result)
    click.echo("\n✅ Agent-to-Agent test complete!")


if __name__ == "__main__":
    test_a2a_client()
