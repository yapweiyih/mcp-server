"""Deploy the ER Query agent to Vertex AI Agent Engine as an A2A service.

This script deploys the ADK agent to Agent Engine, which provides:
- Managed infrastructure (auto-scaling, health checks, logging)
- Native A2A protocol endpoints (message send, task status, agent card)
- Built-in session management via Vertex AI Sessions

The deployment uses ADK's built-in `A2aAgentExecutor` with `InMemoryRunner`
to bridge the A2A protocol and the ADK agent — no custom executor needed.
Once deployed, the agent can be accessed via:
- Vertex AI SDK: `remote_agent.on_message_send(...)`
- A2A Python SDK: `a2a_client.send_message(...)`
- Raw HTTP: POST to the agent's A2A URL

The deploy pipeline:
    Local test → Deploy → Cloud test → Update .env

Prerequisites:
    - GCP project with Vertex AI and Agent Engine APIs enabled
    - `gcloud auth application-default login` for authentication
    - A Cloud Storage bucket for staging artifacts

Usage:
    uv run python -m a2a_app.deploy
    uv run python -m a2a_app.deploy --skip-local-test
    uv run python -m a2a_app.deploy --skip-local-test --skip-cloud-test
    uv run python -m a2a_app.deploy --staging-bucket gs://my-bucket
    uv run python -m a2a_app.deploy --display-name "ER Query Agent (prod)"

    # Or via Makefile:
    make deploy-a2a-agent-engine
"""

import asyncio
import json
import logging
import os
import sys
import time

import click
from dotenv import load_dotenv

load_dotenv("adk_agent/.env")

# Remove MCP_SERVER_URL so the agent uses direct function tools instead
# of McpToolset. McpToolset can't connect to the local MCP server from
# Agent Engine, leaving only submit_long_task and check_task_status.
os.environ.pop("MCP_SERVER_URL", None)

logging.basicConfig(level=logging.INFO)
logging.getLogger("google").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def _update_env_file(engine_id: str) -> None:
    """Write the deployed A2A engine resource ID into adk_agent/.env.

    Adds or updates the A2A_ENGINE_ID entry so other scripts (e.g.
    test_remote.py) can read it without passing --resource-id manually.

    Args:
        engine_id: The Agent Engine resource ID returned after deployment.

    Returns:
        None. Modifies adk_agent/.env in-place.
    """
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "adk_agent", ".env"
    )
    env_path = os.path.normpath(env_path)

    if not os.path.exists(env_path):
        click.echo(f"⚠️  .env file not found at {env_path}, skipping update.")
        return

    lines = []
    updated = False
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("A2A_ENGINE_ID="):
                lines.append(f"A2A_ENGINE_ID={engine_id}\n")
                updated = True
            else:
                lines.append(line)

    if not updated:
        lines.append(f"A2A_ENGINE_ID={engine_id}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)
    click.echo(f"\n📝 Updated .env with A2A_ENGINE_ID={engine_id}")


def _build_a2a_agent():
    """Build the A2aAgent instance for deployment to Agent Engine.

    Uses ADK's built-in A2aAgentExecutor with InMemoryRunner to bridge
    the A2A protocol and the ADK agent. This replaces a custom executor
    with ~5 lines of code — the executor automatically handles task state
    management, session/artifact services, and event streaming.

    Returns:
        A2aAgent: A fully configured A2A agent ready for local testing
        or deployment.
    """
    from a2a.types import AgentSkill
    from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
    from google.adk.runners import InMemoryRunner
    from vertexai.preview.reasoning_engines import A2aAgent
    from vertexai.preview.reasoning_engines.templates.a2a import create_agent_card

    from adk_agent.agent import root_agent

    # ── 1. Agent Card ────────────────────────────────────────────────
    er_search_skill = AgentSkill(
        id="search_expert_requests",
        name="Search Expert Requests",
        description=(
            "Search and retrieve Expert Request (ER) data from Firestore. "
            "Can search by assigned CE email, creation date, or specific ER fields."
        ),
        tags=["Expert Request", "ER", "Firestore", "Search"],
        examples=[
            "Find all ERs assigned to user@google.com",
            "How many ERs were created in 2024?",
            "Show me the FSA status of ER-431059",
            "What ERs were created in April 2024?",
        ],
    )

    background_task_skill = AgentSkill(
        id="background_tasks",
        name="Background Task Management",
        description=(
            "Submit and monitor long-running background tasks. "
            "Tasks run asynchronously and can be checked for completion."
        ),
        tags=["Tasks", "Background", "Async"],
        examples=[
            "Submit a background task called data_sync for 10 seconds",
            "Check the status of my task",
        ],
    )

    agent_card = create_agent_card(
        agent_name=root_agent.name,
        description=(
            "An AI agent that queries Expert Request data from Firestore "
            "and manages background tasks. Supports searching by email, "
            "date, and specific ER fields."
        ),
        skills=[er_search_skill, background_task_skill],
    )

    # ── 2. Assemble A2aAgent with built-in executor ──────────────────
    # A2aAgentExecutor handles all A2A ↔ ADK bridging automatically:
    # - Task state management (submit, start_work, complete, failed)
    # - Session/artifact/memory services (in-memory via InMemoryRunner)
    # - Event streaming and text extraction
    a2a_agent = A2aAgent(
        agent_card=agent_card,
        agent_executor_builder=lambda: A2aAgentExecutor(
            runner=InMemoryRunner(
                app_name=root_agent.name,
                agent=root_agent,
            )
        ),
    )

    return a2a_agent


async def _run_local_test(a2a_agent) -> None:
    """Run a local test of the A2A agent before deploying.

    Verifies the agent card is valid and sends a test message to confirm
    the agent executor works correctly.

    Args:
        a2a_agent: The A2aAgent instance to test.

    Returns:
        None

    Raises:
        Exception: If the local test fails.
    """
    click.echo("\n🧪 Running local test...")

    a2a_agent.set_up()

    # Test 1: Verify agent card
    card = await a2a_agent.handle_authenticated_agent_card(request=None, context=None)
    click.echo(f"  📇 Agent Card: {card.get('name', 'unknown')} — OK")

    # Test 2: Send a test message
    from starlette.requests import Request

    message_data = {
        "message": {
            "messageId": "test-message-001",
            "content": [{"text": "Hello, what can you help me with?"}],
            "role": "ROLE_USER",
        },
    }
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
    }

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(message_data).encode("utf-8"),
            "more_body": False,
        }

    request = Request(scope, receive=receive)
    response = await a2a_agent.on_message_send(request=request, context=None)
    click.echo(f"  📨 Message send: OK (got response)")

    click.echo("  ✅ Local test completed.\n")


async def _run_cloud_test(
    project_id: str,
    location: str,
    resource_id: str,
) -> None:
    """Run a smoke test against the deployed A2A agent on Agent Engine.

    Fetches the agent card and sends a test message to verify the agent
    responds correctly in the cloud environment.

    Args:
        project_id: GCP project ID.
        location: GCP region.
        resource_id: The Agent Engine resource ID.

    Returns:
        None
    """
    import vertexai
    from google.genai import types as genai_types

    click.echo("\n☁️  Running cloud smoke test...")

    client = vertexai.Client(
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    resource_name = (
        f"projects/{project_id}/locations/{location}" f"/reasoningEngines/{resource_id}"
    )

    remote_agent = client.agent_engines.get(name=resource_name)

    # Test 1: Fetch agent card
    card = await remote_agent.handle_authenticated_agent_card()
    card_name = (
        card.get("name", "unknown")
        if isinstance(card, dict)
        else getattr(card, "name", "unknown")
    )
    click.echo(f"  📇 Agent Card: {card_name} — OK")

    # Test 2: Send a test message
    response = await remote_agent.async_on_message_send(
        message={
            "role": "user",
            "parts": [{"text": "hi?"}],
        },
    )
    click.echo(f"  📨 Message send: OK")

    # Extract any text from the response
    if isinstance(response, dict):
        result = response.get("result", {})
        artifacts = result.get("artifacts", [])
        for artifact in artifacts:
            parts = artifact.get("parts", [])
            for part in parts:
                if "text" in part:
                    text_preview = part["text"][:100]
                    click.echo(f"  📝 Response: {text_preview}...")

    click.echo("  ✅ Cloud smoke test completed.\n")


@click.command()
@click.option(
    "--project-id",
    type=str,
    default=None,
    help="GCP project ID (default: from env GOOGLE_CLOUD_PROJECT)",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help="GCP region (default: from env GOOGLE_CLOUD_LOCATION or us-central1)",
)
@click.option(
    "--staging-bucket",
    type=str,
    default=None,
    help="GCS bucket for staging (e.g., gs://my-bucket). Auto-created if not set.",
)
@click.option(
    "--display-name",
    type=str,
    default="ER Query Agent (A2A)",
    help="Display name for the deployed agent",
)
@click.option(
    "--skip-local-test",
    is_flag=True,
    default=False,
    help="Skip the local test before deploying.",
)
@click.option(
    "--skip-cloud-test",
    is_flag=True,
    default=False,
    help="Skip the cloud smoke test after deploying.",
)
def deploy_agent_engine(
    project_id: str,
    location: str,
    staging_bucket: str,
    display_name: str,
    skip_local_test: bool,
    skip_cloud_test: bool,
) -> None:
    """Deploy the ER Query ADK agent to Vertex AI Agent Engine as A2A.

    Pipeline: Local test → Deploy → Cloud test → Update .env
    """

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "ikigai-dev-376122")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🚀 DEPLOYING ER QUERY AGENT TO AGENT ENGINE (A2A) 🚀    ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo("📋 Deployment Parameters:")
    click.echo(f"  Project:         {project_id}")
    click.echo(f"  Location:        {location}")
    click.echo(f"  Display Name:    {display_name}")
    click.echo(f"  Staging Bucket:  {staging_bucket or '(auto)'}")
    click.echo(f"  Skip Local Test: {skip_local_test}")
    click.echo(f"  Skip Cloud Test: {skip_cloud_test}")

    # --- Confirm before proceeding ---
    if not click.confirm("\n🔍 Proceed with deployment?", default=True):
        click.echo("❌ Deployment cancelled.")
        sys.exit(0)

    # --- Step 1: Build A2A agent ---
    click.echo("\n🔧 Building A2A agent...")
    a2a_agent = _build_a2a_agent()

    # --- Step 2: Local test (optional) ---
    if not skip_local_test:
        try:
            asyncio.run(_run_local_test(a2a_agent))
        except Exception as e:
            click.echo(f"  ❌ Local test failed: {e}")
            sys.exit(1)
    else:
        click.echo("\n⏭️  Skipping local test.")

    # --- Step 3: Deploy ---
    click.echo("🚀 Deploying to Agent Engine (this takes a few minutes)...")

    import vertexai
    from google.genai import types as genai_types

    client = vertexai.Client(
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    a2a_agent.set_up()

    deploy_config = {
        "requirements": [
            "google-cloud-aiplatform[agent_engines,adk]",
            "a2a-sdk>=0.3.4",
            "google-adk[a2a]",
            "google-cloud-firestore>=2.19.0",
            "python-dotenv>=1.0.0",
            "pydantic>=2.0.0",
            "mcp[cli]>=1.0.0",
        ],
        "display_name": display_name,
        "description": (
            "ER Query Agent deployed as A2A service. "
            "Queries Expert Request data from Firestore."
        ),
        "env_vars": {
            # Note: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION are
            # reserved and auto-set by Agent Engine — do not include them.
            "GOOGLE_GENAI_USE_VERTEXAI": "True",
            "COLLECTION": os.getenv("COLLECTION", "expert_requests_dev"),
            "DATABASE_ID": os.getenv("DATABASE_ID", "ikigai-dev"),
        },
        "extra_packages": ["adk_agent", "er_query", "mcp_server"],
    }

    staging_bucket = staging_bucket or os.getenv("STAGING_BUCKET")
    if staging_bucket:
        deploy_config["staging_bucket"] = staging_bucket

    start = time.perf_counter()
    try:
        remote_agent = client.agent_engines.create(
            agent=a2a_agent,
            config=deploy_config,
        )
    except Exception as e:
        click.echo(f"  ❌ Deployment failed: {e}")
        sys.exit(1)

    elapsed = time.perf_counter() - start
    click.echo(f"\n  ⏱️  Deployment took {elapsed:.2f} seconds")

    resource_name = remote_agent.api_resource.name
    resource_id = resource_name.split("/")[-1]

    click.echo(f"  ✅ Agent deployed successfully!")
    click.echo(f"  🆔 Resource ID: {resource_id}")

    # --- Step 4: Cloud smoke test (optional) ---
    if not skip_cloud_test:
        try:
            asyncio.run(
                _run_cloud_test(
                    project_id=project_id,
                    location=location,
                    resource_id=resource_id,
                )
            )
        except Exception as e:
            click.echo(f"  ⚠️  Cloud test failed: {e}")
            click.echo("  (Deployment succeeded — agent is live but test failed)")
    else:
        click.echo("\n⏭️  Skipping cloud smoke test.")

    # --- Step 5: Update .env ---
    _update_env_file(resource_id)

    # --- Summary ---
    click.echo(
        f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   ✅ A2A DEPLOYMENT COMPLETE                              ║
    ║                                                           ║
    ║   Resource ID: {resource_id:<41s} ║
    ║   Project:     {project_id:<41s} ║
    ║   Location:    {location:<41s} ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(
        f"🔗 To test: uv run python -m a2a_app.test_remote --resource-id {resource_id}"
    )


if __name__ == "__main__":
    deploy_agent_engine()
