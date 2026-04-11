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
    agent_card,
) -> "Agent":
    """Build a local ADK orchestrator that delegates to a remote A2A agent.

    The orchestrator is a simple LLM agent that uses `RemoteA2aAgent` as a
    sub-agent. When the user asks about Expert Requests, the orchestrator
    delegates to the remote ER Query agent via A2A protocol.

    Args:
        agent_card: Either a URL string (for local servers) or an AgentCard
            object (for Agent Engine, pre-fetched via Vertex AI SDK).

    Returns:
        Agent: A configured ADK agent with remote A2A sub-agent.
    """
    from google.adk.agents import Agent
    from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

    # For AgentCard objects (Agent Engine), create an authenticated client
    # with the correct transport (HTTP+JSON, not the default jsonrpc).
    kwargs = {}
    if not isinstance(agent_card, str):
        import httpx
        from a2a.client import ClientConfig, ClientFactory
        from a2a.types import TransportProtocol
        from google.auth import default
        from google.auth.transport.requests import Request

        credentials, _ = default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())

        kwargs["a2a_client_factory"] = ClientFactory(
            config=ClientConfig(
                httpx_client=httpx.AsyncClient(
                    headers={
                        "Authorization": f"Bearer {credentials.token}",
                        "Content-Type": "application/json",
                    },
                    timeout=httpx.Timeout(timeout=120),
                ),
                supported_transports=[TransportProtocol.http_json],
            ),
        )

    # Create a remote A2A agent reference
    remote_er_agent = RemoteA2aAgent(
        name="remote_er_query_agent",
        description=(
            "A remote agent that queries Expert Request (ER) data from "
            "Firestore. It can search ERs by email, date, or specific fields. "
            "Delegate any questions about Expert Requests to this agent."
        ),
        agent_card=agent_card,
        **kwargs,
    )

    # Build the local orchestrator
    orchestrator = Agent(
        name="orchestrator_agent",
        model="gemini-2.5-flash",
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
    agent_card,
    message: str,
) -> str:
    """Run the orchestrator agent with a user message.

    Creates a Runner, establishes a session, and sends the message
    through the orchestrator which may delegate to the remote A2A agent.

    Args:
        agent_card: AgentCard object or URL string for the remote agent.
        message: The user's query message.

    Returns:
        The final response text from the orchestrator.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    orchestrator = _build_orchestrator_with_remote_a2a(agent_card)

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
    click.echo(f"🔗 Remote agent card: {agent_card}")
    click.echo()

    final_text = ""
    last_agent_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        ),
    ):
        if not event.content or not event.content.parts:
            continue

        author = event.author or "unknown"
        for part in event.content.parts:
            if hasattr(part, "text") and part.text:
                click.echo(f"  [{author}] {part.text[:200]}")
            elif hasattr(part, "function_call") and part.function_call:
                click.echo(f"  [{author}] → calling {part.function_call.name}")
            elif hasattr(part, "function_response") and part.function_response:
                click.echo(
                    f"  [{author}] ← response from {part.function_response.name}"
                )

        # Extract text from this event
        text = "".join(
            p.text for p in event.content.parts if hasattr(p, "text") and p.text
        )

        if text:
            last_agent_text = text

        if event.is_final_response() and text:
            final_text = text

    # Fall back to the last text we saw from any agent if is_final_response
    # didn't produce text (common with remote A2A delegation patterns).
    return final_text or last_agent_text


async def _fetch_agent_card_from_engine(
    project_id: str,
    location: str,
    resource_id: str,
):
    """Fetch the AgentCard from a deployed Agent Engine A2A agent.

    Agent Engine doesn't expose /.well-known/agent.json as a static URL.
    Instead, the agent card is served through the Vertex AI API via the
    authenticated `handle_authenticated_agent_card()` method.

    This function uses the Vertex AI SDK to fetch the card and returns
    an AgentCard object that can be passed directly to RemoteA2aAgent.

    Args:
        project_id: GCP project ID.
        location: GCP region.
        resource_id: Agent Engine resource ID.

    Returns:
        AgentCard: The resolved agent card object.
    """
    import vertexai
    from a2a.types import AgentCard
    from google.genai import types as genai_types

    client = vertexai.Client(
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    resource_name = (
        f"projects/{project_id}/locations/{location}" f"/reasoningEngines/{resource_id}"
    )
    remote_agent = client.agent_engines.get(name=resource_name)

    card_raw = await remote_agent.handle_authenticated_agent_card()

    # Normalize to AgentCard object
    if isinstance(card_raw, AgentCard):
        return card_raw
    elif isinstance(card_raw, dict):
        return AgentCard(**card_raw)
    elif hasattr(card_raw, "model_dump"):
        return AgentCard(**card_raw.model_dump(exclude_none=True))
    else:
        return AgentCard(**dict(card_raw))


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

    resource_id = resource_id or os.getenv("A2A_ENGINE_ID")
    if not resource_id and not use_local:
        raise click.UsageError(
            "Missing --resource-id. Set A2A_ENGINE_ID in adk_agent/.env, "
            "pass --resource-id, or use --local."
        )

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "ikigai-dev-376122")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 ADK AGENT → A2A REMOTE AGENT TEST 🤖                 ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    # Resolve agent card: URL string for local, AgentCard object for Agent Engine
    if use_local:
        agent_card_url = f"http://localhost:{local_port}/.well-known/agent.json"
        agent_card = agent_card_url  # RemoteA2aAgent fetches from URL

        click.echo(f"📋 Test Parameters:")
        click.echo(f"  Mode:        Local")
        click.echo(f"  Agent Card:  {agent_card_url}")
        click.echo(f"  Message:     {message}")
        click.echo()

        import httpx

        try:
            resp = httpx.get(agent_card_url, timeout=3)
            click.echo(f"✅ Local A2A server reachable (status {resp.status_code})")
        except Exception:
            click.echo(
                "❌ Error: Cannot reach local A2A server at "
                f"{agent_card_url}\n"
                "   Start it first with: make a2a-server"
            )
            raise SystemExit(1)
    else:
        # Agent Engine: fetch AgentCard via Vertex AI SDK (authenticated).
        # The /.well-known/agent.json URL doesn't work for Agent Engine —
        # agent cards are served through the Vertex AI API, not as static files.
        click.echo(f"📋 Test Parameters:")
        click.echo(f"  Mode:        Agent Engine")
        click.echo(f"  Resource ID: {resource_id}")
        click.echo(f"  Project:     {project_id}")
        click.echo(f"  Location:    {location}")
        click.echo(f"  Message:     {message}")
        click.echo()

        click.echo("📇 Fetching agent card from Agent Engine...")
        agent_card = asyncio.run(
            _fetch_agent_card_from_engine(project_id, location, resource_id)
        )
        click.echo(f"✅ Agent card resolved: {agent_card.name}")

    result = asyncio.run(
        run_orchestrator(
            agent_card=agent_card,
            message=message,
        )
    )

    click.echo("\n" + "=" * 60)
    click.echo("📄 Final Response from Orchestrator:")
    click.echo(result or "(empty response — check server logs)")
    click.echo("\n✅ Agent-to-Agent test complete!")


if __name__ == "__main__":
    test_a2a_client()
