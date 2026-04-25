"""Deploy ADK agent to Vertex AI Agent Engine with optional Agent Identity.

This script deploys the ER Query ADK agent to Vertex AI Agent Engine Runtime.
It supports two deployment modes:

1. **Standard** (default): Uses service accounts for authentication.
   The agent inherits the project's default service account permissions.

2. **Agent Identity** (--agent-identity): Provisions a unique per-agent
   identity (SPIFFE-based) using the v1beta1 API. This enables
   least-privilege IAM access control tied to the agent lifecycle.

The script follows a deploy pipeline:
    Load env → Validate → Local test → Deploy → Cloud test → Update .env

Usage:
    # Deploy with defaults (loads adk_agent/.env):
    uv run python ae_deploy.py

    # Deploy with explicit env file:
    uv run python ae_deploy.py --env adk_agent/.env

    # Deploy with Agent Identity:
    uv run python ae_deploy.py --agent-identity

    # Skip tests for faster iteration:
    uv run python ae_deploy.py --skip-local-test --skip-cloud-test

    # Or via Makefile:
    make deploy-adk-agent-engine
"""

import asyncio
import json
import logging
import os
import sys
import time
import tomllib  # Python 3.11+
from pathlib import Path

import click
import vertexai
from dotenv import load_dotenv
from vertexai import types


def load_requirements_from_pyproject() -> list[str]:
    """Load dependencies from pyproject.toml file.

    Reads the pyproject.toml file in the script's directory and extracts
    the dependencies list from the [project] section.

    Returns:
        list[str]: List of dependency strings from pyproject.toml.

    Raises:
        FileNotFoundError: If pyproject.toml is not found.
        ValueError: If no dependencies are defined in pyproject.toml.

    Example return value:
        ['google-adk>=1.16.0', 'google-cloud-firestore>=2.0.0']
    """
    pyproject_path = Path(__file__).parent / "pyproject.toml"

    if not pyproject_path.exists():
        raise FileNotFoundError(
            f"pyproject.toml not found at {pyproject_path}. "
            "Cannot load dependencies for deployment."
        )

    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    dependencies = pyproject_data.get("project", {}).get("dependencies", [])

    if not dependencies:
        raise ValueError(
            "No dependencies found in pyproject.toml. "
            "Please ensure [project.dependencies] is defined."
        )

    return dependencies


def load_and_validate_env(env_file: str) -> dict[str, str]:
    """Load and validate required environment variables from a .env file.

    Args:
        env_file: Path to the .env file to load.

    Returns:
        dict[str, str]: Dictionary of validated environment variable values
            with keys: PROJECT_ID, LOCATION, DISPLAY_NAME, STAGING_BUCKET,
            COLLECTION, DATABASE_ID.

    Raises:
        FileNotFoundError: If the specified .env file does not exist.
        ValueError: If any required environment variables are missing.

    Example return value:
        {
            'PROJECT_ID': 'hello-world-418507',
            'LOCATION': 'us-central1',
            'DISPLAY_NAME': 'ER Query Agent',
            'STAGING_BUCKET': 'gs://2025-adk',
            'COLLECTION': 'expert_requests_dev',
            'DATABASE_ID': 'expert-request-dev',
        }
    """
    env_path = Path(env_file)
    if not env_path.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file}")

    load_dotenv(env_path, override=True)

    env_mapping = {
        "PROJECT_ID": "GOOGLE_CLOUD_PROJECT",
        "LOCATION": "GOOGLE_CLOUD_LOCATION",
        "DISPLAY_NAME": "DISPLAY_NAME",
        "STAGING_BUCKET": "STAGING_BUCKET",
        "COLLECTION": "COLLECTION",
        "DATABASE_ID": "DATABASE_ID",
    }

    values = {}
    missing = []
    for key, env_var in env_mapping.items():
        val = os.getenv(env_var)
        if val is None:
            missing.append(env_var)
        else:
            values[key] = val

    if missing:
        raise ValueError(
            f"Missing required environment variables in {env_file}: "
            f"{', '.join(missing)}"
        )

    return values


def update_env_file(
    env_file: str,
    engine_id: str,
    effective_identity: str = "N/A",
) -> None:
    """Update the .env file with the deployed ENGINE_ID and AGENT_IDENTITY.

    Reads the existing .env file, updates or appends ENGINE_ID and
    AGENT_IDENTITY values, and writes back. Preserves all other variables.

    Args:
        env_file: Path to the .env file to update.
        engine_id: The deployed Agent Engine ID.
        effective_identity: The effective agent identity principal string.
            Defaults to "N/A" for standard (non-identity) deployments.

    Returns:
        None
    """
    env_path = Path(env_file)
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    updates = {
        "ENGINE_ID": engine_id,
        "AGENT_IDENTITY": effective_identity,
    }

    # Track which keys we've already updated in-place
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        matched = False
        for key, value in updates.items():
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                updated_keys.add(key)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    # Append any keys that weren't already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")

    click.echo(f"\n📝 Updated {env_file}:")
    for key, value in updates.items():
        click.echo(f"  {key}={value}")


def import_agent():
    """Import the root agent and AdkApp wrapper.

    Removes MCP_SERVER_URL from environment before importing so the agent
    uses direct function tools (picklable) instead of McpToolset (which
    holds SSE/HTTP connections that cannot be pickled for Agent Engine).

    Returns:
        tuple: (AdkApp class, root_agent instance)
    """
    # Remove MCP_SERVER_URL so the agent uses direct function tools instead
    # of McpToolset. McpToolset holds connections that cannot be pickled
    # for Agent Engine deployment. Direct functions call Firestore directly.
    os.environ.pop("MCP_SERVER_URL", None)

    from vertexai.agent_engines import AdkApp

    from adk_agent.agent import root_agent

    return AdkApp, root_agent


async def run_local_test(env_config: dict[str, str]) -> None:
    """Run a local test of the agent before deploying.

    Creates a local AdkApp instance and runs a test query to verify the
    agent works correctly before cloud deployment.

    Args:
        env_config: Dictionary with validated environment variables.

    Returns:
        None
    """
    click.echo("\n🧪 Running local test...")

    AdkApp, root_agent = import_agent()
    app = AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )

    session = await app.async_create_session(user_id="u_123")
    prompt = "list er for alex.chen@example.com"
    click.echo(f"  Session created. Sending prompt: '{prompt}'")

    async for event in app.async_stream_query(
        user_id="u_123",
        session_id=session.id,
        message=prompt,
    ):
        content = event.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if "text" in part:
                click.echo(f"  📝 Text: {part['text']}")
            if "function_call" in part:
                fc = part["function_call"]
                click.echo(f"  🔧 Function Call: {fc.get('name')}")
            if "function_response" in part:
                fr = part["function_response"]
                click.echo(f"  📨 Function Response: {fr.get('name')}")

    click.echo("  ✅ Local test completed.\n")


def deploy_with_agent_identity(
    env_config: dict[str, str],
    requirements: list[str],
    extra_packages: list[str],
    env_vars: dict[str, str],
) -> tuple[str, str]:
    """Deploy agent to Vertex AI Agent Engine with Agent Identity.

    Uses the v1beta1 API and vertexai.Client() to provision a unique
    per-agent identity (SPIFFE-based) during deployment. This identity
    enables least-privilege IAM access control tied to the agent lifecycle.

    Args:
        env_config: Dictionary with validated environment variables.
        requirements: List of pip dependency strings for the agent.
        extra_packages: List of local package paths to include.
        env_vars: Dictionary of environment variables to set at runtime.

    Returns:
        tuple[str, str]: A tuple of (engine_id, effective_identity).

    Example return value:
        ('8031269435392131072', 'principal://agents.global.org-123...')
    """
    click.echo("\n🚀 Deploying agent WITH Agent Identity (v1beta1 API)...")

    AdkApp, root_agent = import_agent()
    app = AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )

    client = vertexai.Client(
        project=env_config["PROJECT_ID"],
        location=env_config["LOCATION"],
        http_options=dict(api_version="v1beta1"),
    )

    remote_app = client.agent_engines.create(
        agent=app,
        config={
            "display_name": env_config["DISPLAY_NAME"],
            "identity_type": types.IdentityType.AGENT_IDENTITY,
            "requirements": requirements,
            "extra_packages": extra_packages,
            "staging_bucket": env_config["STAGING_BUCKET"],
            "env_vars": env_vars,
        },
    )

    engine_id = remote_app.api_resource.name.split("/")[-1]

    effective_identity = (
        remote_app.api_resource.spec.effective_identity
        if hasattr(remote_app.api_resource.spec, "effective_identity")
        else "N/A"
    )

    click.echo(f"  ✅ Agent deployed successfully!")
    click.echo(f"  🆔 ENGINE_ID: {engine_id}")
    click.echo(f"  🔐 Effective Identity: {effective_identity}")

    return engine_id, effective_identity


def deploy_without_agent_identity(
    env_config: dict[str, str],
    requirements: list[str],
    extra_packages: list[str],
    env_vars: dict[str, str],
) -> str:
    """Deploy agent to Vertex AI Agent Engine without Agent Identity.

    Uses the standard agent_engines.create() API (backward compatible).
    The agent will use service accounts for authentication.

    Args:
        env_config: Dictionary with validated environment variables.
        requirements: List of pip dependency strings for the agent.
        extra_packages: List of local package paths to include.
        env_vars: Dictionary of environment variables to set at runtime.

    Returns:
        str: The Engine ID of the deployed agent.

    Example return value:
        '8031269435392131072'
    """
    click.echo("\n🚀 Deploying agent WITHOUT Agent Identity (standard API)...")

    vertexai.init(
        project=env_config["PROJECT_ID"],
        location=env_config["LOCATION"],
        staging_bucket=env_config["STAGING_BUCKET"],
    )

    AdkApp, root_agent = import_agent()
    app = AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )

    from vertexai import agent_engines

    remote_app = agent_engines.create(
        display_name=env_config["DISPLAY_NAME"],
        agent_engine=app,
        requirements=requirements,
        extra_packages=extra_packages,
        env_vars=env_vars,
    )

    engine_id = remote_app.resource_name.split("/")[-1]

    click.echo(f"  ✅ Agent deployed successfully!")
    click.echo(f"  🆔 ENGINE_ID: {engine_id}")

    return engine_id


async def test_on_cloud(env_config: dict[str, str], engine_id: str) -> None:
    """Run a smoke test against the deployed agent on Vertex AI.

    Retrieves the deployed agent engine, creates a session, and sends
    a test prompt via async streaming to verify the agent responds
    correctly in the cloud environment.

    Args:
        env_config: Dictionary with validated environment variables.
        engine_id: The Engine ID of the deployed agent to test.

    Returns:
        None
    """
    click.echo("\n☁️  Running cloud smoke test...")

    resource_name = (
        f"projects/{env_config['PROJECT_ID']}"
        f"/locations/{env_config['LOCATION']}"
        f"/reasoningEngines/{engine_id}"
    )

    live_app = vertexai.agent_engines.get(resource_name)
    session = live_app.create_session(user_id="u_123")
    session_id = session.get("id", session) if isinstance(session, dict) else session
    click.echo(f"  Session created: {session_id}")

    prompt = "list er for alex.chen@example.com"
    request_json = json.dumps(
        {
            "user_id": "u_123",
            "session_id": session_id,
            "message": {
                "parts": [{"text": prompt}],
                "role": "user",
            },
        }
    )

    click.echo(f"  Sending prompt: '{prompt}'")

    async for event_group in live_app.streaming_agent_run_with_events(
        request_json=request_json,
    ):
        for event in event_group.get("events", []):
            content = event.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if "function_call" in part:
                    fc = part["function_call"]
                    click.echo(f"  🔧 Function Call: {fc.get('name')}")
                elif "function_response" in part:
                    fr = part["function_response"]
                    click.echo(f"  📨 Function Response: {fr.get('name')}")
                elif "text" in part:
                    click.echo(f"  📝 Text: {part['text']}")

    click.echo("  ✅ Cloud smoke test completed.\n")


@click.command()
@click.option(
    "--env",
    "env_file",
    type=str,
    default="adk_agent/.env",
    help="Path to the .env file (default: adk_agent/.env)",
)
@click.option(
    "--agent-identity/--no-agent-identity",
    default=False,
    help="Deploy with Agent Identity (default: disabled). "
    "Use --agent-identity to deploy with per-agent identity.",
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
def deploy(
    env_file: str,
    agent_identity: bool,
    skip_local_test: bool,
    skip_cloud_test: bool,
) -> None:
    """Deploy ADK agent to Vertex AI Agent Engine.

    Loads environment from the specified .env file, optionally runs a local
    test, deploys the agent, optionally runs a cloud smoke test, and writes
    the ENGINE_ID back to the .env file.
    """
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("google").setLevel(logging.ERROR)

    identity_mode = (
        "WITH Agent Identity"
        if agent_identity
        else "WITHOUT Agent Identity (service account)"
    )

    click.echo(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 DEPLOYING AGENT TO VERTEX AI AGENT ENGINE 🤖         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    # --- Step 1: Load and validate environment ---
    click.echo(f"📋 Loading environment from: {env_file}")
    try:
        env_config = load_and_validate_env(env_file)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"  ❌ Error: {e}")
        sys.exit(1)

    # --- Step 2: Load requirements ---
    requirements = load_requirements_from_pyproject()
    extra_packages = ["./adk_agent", "./er_query"]
    env_vars = {
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "COLLECTION": env_config["COLLECTION"],
        "DATABASE_ID": env_config["DATABASE_ID"],
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
    }

    # --- Display configuration ---
    click.echo(f"\n📋 Deployment Parameters:")
    click.echo(f"  Project:         {env_config['PROJECT_ID']}")
    click.echo(f"  Location:        {env_config['LOCATION']}")
    click.echo(f"  Display Name:    {env_config['DISPLAY_NAME']}")
    click.echo(f"  Staging Bucket:  {env_config['STAGING_BUCKET']}")
    click.echo(f"  Collection:      {env_config['COLLECTION']}")
    click.echo(f"  Database ID:     {env_config['DATABASE_ID']}")
    click.echo(f"  Identity Mode:   {identity_mode}")
    click.echo(f"  Skip Local Test: {skip_local_test}")
    click.echo(f"  Skip Cloud Test: {skip_cloud_test}")
    click.echo(f"  Requirements:    {len(requirements)} packages")
    for dep in requirements:
        click.echo(f"    - {dep}")
    click.echo(f"  Extra Packages:  {extra_packages}")

    # --- Confirm before proceeding ---
    if not click.confirm("\n🔍 Proceed with deployment?", default=True):
        click.echo("❌ Deployment cancelled.")
        sys.exit(0)

    # --- Step 3: Set environment variables ---
    os.environ["GOOGLE_CLOUD_PROJECT"] = env_config["PROJECT_ID"]
    os.environ["GOOGLE_CLOUD_LOCATION"] = env_config["LOCATION"]
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

    # --- Step 4: Local test (optional) ---
    if not skip_local_test:
        try:
            asyncio.run(run_local_test(env_config))
        except Exception as e:
            click.echo(f"  ❌ Local test failed: {e}")
            sys.exit(1)
    else:
        click.echo("\n⏭️  Skipping local test.")

    # --- Step 5: Deploy ---
    start = time.perf_counter()
    effective_identity = "N/A"
    try:
        if agent_identity:
            engine_id, effective_identity = deploy_with_agent_identity(
                env_config=env_config,
                requirements=requirements,
                extra_packages=extra_packages,
                env_vars=env_vars,
            )
        else:
            engine_id = deploy_without_agent_identity(
                env_config=env_config,
                requirements=requirements,
                extra_packages=extra_packages,
                env_vars=env_vars,
            )
    except Exception as e:
        click.echo(f"  ❌ Deployment failed: {e}")
        sys.exit(1)

    elapsed = time.perf_counter() - start
    click.echo(f"\n  ⏱️  Deployment took {elapsed:.2f} seconds")

    # --- Step 6: Cloud smoke test (optional) ---
    if not skip_cloud_test:
        try:
            asyncio.run(test_on_cloud(env_config=env_config, engine_id=engine_id))
        except Exception as e:
            click.echo(f"  ⚠️  Cloud test failed: {e}")
            click.echo("  (Deployment succeeded — agent is live but test failed)")
    else:
        click.echo("\n⏭️  Skipping cloud smoke test.")

    # --- Step 7: Write ENGINE_ID and AGENT_IDENTITY back to .env file ---
    update_env_file(
        env_file=env_file,
        engine_id=engine_id,
        effective_identity=effective_identity,
    )

    # --- Summary ---
    click.echo(
        f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   ✅ DEPLOYMENT COMPLETE                                  ║
    ║                                                           ║
    ║   ENGINE_ID: {engine_id:<43s} ║
    ║   Identity:  {'Agent Identity' if agent_identity else 'Service Account':<43s} ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )


if __name__ == "__main__":
    deploy()
