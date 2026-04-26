"""Manage and test a deployed ADK agent on Vertex AI Agent Engine.

Provides subcommands to smoke test and configure IAM for deployed agents.

Usage:
    # Smoke test using ENGINE_ID from .env:
    uv run python ae_cloud_test.py test

    # Test a specific engine ID:
    uv run python ae_cloud_test.py test --engine-id 8270852469328707584

    # Custom prompt:
    uv run python ae_cloud_test.py test --message "How many ERs in 2024?"

    # Grant IAM role to agent identity:
    uv run python ae_cloud_test.py grant-iam --role roles/datastore.user

    # Grant with explicit identity:
    uv run python ae_cloud_test.py grant-iam \
        --role roles/datastore.user \
        --member "principal://agents.global.org-..."

    # Or via Makefile:
    make test-cloud-agent
    make grant-iam-agent ROLE=roles/datastore.user
"""

import asyncio
import json
import logging
import os
import subprocess
import sys

import click
import vertexai
from dotenv import load_dotenv


# ---------- Shared helpers ----------


def load_env_config(env_file: str) -> dict[str, str]:
    """Load environment variables from .env file.

    Args:
        env_file: Path to the .env file.

    Returns:
        dict[str, str]: Dictionary with keys PROJECT_ID, LOCATION,
            ENGINE_ID, AGENT_IDENTITY (if present).
    """
    load_dotenv(env_file, override=True)
    return {
        "PROJECT_ID": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        "LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        "ENGINE_ID": os.getenv("ENGINE_ID", ""),
        "AGENT_IDENTITY": os.getenv("AGENT_IDENTITY", ""),
    }


# ---------- Test subcommand ----------


async def test_on_cloud(
    project_id: str,
    location: str,
    engine_id: str,
    message: str,
    verbose: bool = False,
) -> None:
    """Run a smoke test against a deployed agent on Vertex AI Agent Engine.

    Retrieves the deployed agent engine, creates a session, and sends
    a test prompt via async streaming to verify the agent responds
    correctly in the cloud environment.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., 'us-central1').
        engine_id: The Engine ID of the deployed agent to test.
        message: The test prompt to send.
        verbose: If True, print raw event structure for debugging.

    Returns:
        None
    """
    click.echo("\n☁️  Running cloud smoke test...")

    resource_name = (
        f"projects/{project_id}"
        f"/locations/{location}"
        f"/reasoningEngines/{engine_id}"
    )

    click.echo(f"  Resource: {resource_name}")

    vertexai.init(project=project_id, location=location)
    from vertexai import agent_engines

    live_app = agent_engines.get(resource_name)

    session = live_app.create_session(user_id="u_test")
    session_id = session.get("id", session) if isinstance(session, dict) else session
    click.echo(f"  Session created: {session_id}")

    request_json = json.dumps(
        {
            "user_id": "u_test",
            "session_id": session_id,
            "message": {
                "parts": [{"text": message}],
                "role": "user",
            },
        }
    )

    click.echo(f"  Sending prompt: '{message}'")
    click.echo()

    async for event_group in live_app.streaming_agent_run_with_events(
        request_json=request_json,
    ):
        if verbose:
            click.echo(f"  [DEBUG] event_group keys: {list(event_group.keys())}")

        for event in event_group.get("events", []):
            if verbose:
                click.echo(f"  [DEBUG] event keys: {list(event.keys())}")

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

            # Handle cases where content might be at event level directly
            if not parts and verbose:
                click.echo(
                    f"  [DEBUG] event (no parts): "
                    f"{json.dumps(event, default=str)[:300]}"
                )

    click.echo("\n  ✅ Cloud smoke test completed.")


# ---------- Grant IAM subcommand ----------


def grant_iam_to_agent(
    project_id: str,
    member: str,
    role: str,
) -> None:
    """Grant an IAM role to an agent identity on a GCP project.

    Runs `gcloud projects add-iam-policy-binding` to bind the specified
    IAM role to the agent's principal identity. This is required when
    using Agent Identity so the agent can access GCP resources (e.g.,
    Firestore, Cloud Storage) with its own credentials.

    Args:
        project_id: GCP project ID to bind the role on.
        member: The principal member string for the agent identity,
            e.g. "principal://agents.global.org-<org-id>.system.id.goog/..."
        role: The IAM role to grant, e.g. "roles/datastore.user".

    Returns:
        None

    Raises:
        SystemExit: If the gcloud command fails.
    """
    click.echo(f"\n🔐 Granting IAM role to agent identity...")
    click.echo(f"  Project: {project_id}")
    click.echo(f"  Member:  {member}")
    click.echo(f"  Role:    {role}")

    cmd = [
        "gcloud",
        "projects",
        "add-iam-policy-binding",
        project_id,
        f"--member={member}",
        f"--role={role}",
        "--condition=None",
        "--format=json",
        "--quiet",
    ]

    click.echo(f"\n  Running: {' '.join(cmd[:6])} ...")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        click.echo(f"\n  ❌ Failed to grant IAM role:")
        click.echo(f"  {result.stderr.strip()}")
        sys.exit(1)

    click.echo(f"\n  ✅ IAM role '{role}' granted to agent identity.")


# ---------- CLI ----------


@click.group()
def cli():
    """Manage and test deployed ADK agents on Vertex AI Agent Engine."""
    pass


@cli.command()
@click.option(
    "--env",
    "env_file",
    type=str,
    default="adk_agent/.env",
    help="Path to the .env file (default: adk_agent/.env)",
)
@click.option(
    "--engine-id",
    type=str,
    default=None,
    help="Agent Engine ID to test (default: ENGINE_ID from .env)",
)
@click.option(
    "--project-id",
    type=str,
    default=None,
    help="GCP project ID (default: from .env)",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help="GCP region (default: from .env)",
)
@click.option(
    "--message",
    type=str,
    default="list er for alex.chen@example.com",
    help="Test prompt to send to the agent",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Show raw event structure for debugging",
)
def test(
    env_file: str,
    engine_id: str | None,
    project_id: str | None,
    location: str | None,
    message: str,
    verbose: bool,
) -> None:
    """Smoke test a deployed ADK agent on Agent Engine."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("google").setLevel(logging.ERROR)

    env = load_env_config(env_file)
    project_id = project_id or env["PROJECT_ID"]
    location = location or env["LOCATION"]
    engine_id = engine_id or env["ENGINE_ID"]

    if not project_id:
        click.echo("❌ Error: GOOGLE_CLOUD_PROJECT not set. Use --project-id or .env")
        sys.exit(1)

    if not engine_id:
        click.echo("❌ Error: ENGINE_ID not set. Use --engine-id or set in .env")
        sys.exit(1)

    click.echo(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🧪 CLOUD SMOKE TEST — Agent Engine                      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(f"📋 Test Parameters:")
    click.echo(f"  Project:    {project_id}")
    click.echo(f"  Location:   {location}")
    click.echo(f"  Engine ID:  {engine_id}")
    click.echo(f"  Message:    {message}")

    try:
        asyncio.run(
            test_on_cloud(
                project_id=project_id,
                location=location,
                engine_id=engine_id,
                message=message,
                verbose=verbose,
            )
        )
    except Exception as e:
        click.echo(f"\n  ❌ Cloud test failed: {e}")
        sys.exit(1)


@cli.command("grant-iam")
@click.option(
    "--env",
    "env_file",
    type=str,
    default="adk_agent/.env",
    help="Path to the .env file (default: adk_agent/.env)",
)
@click.option(
    "--project-id",
    type=str,
    default=None,
    help="GCP project ID to bind the role on (default: from .env)",
)
@click.option(
    "--member",
    type=str,
    default=None,
    help="Agent identity principal string (default: AGENT_IDENTITY from .env)",
)
@click.option(
    "--role",
    type=str,
    required=True,
    help="IAM role to grant, e.g. roles/datastore.user",
)
def grant_iam(
    env_file: str,
    project_id: str | None,
    member: str | None,
    role: str,
) -> None:
    """Grant an IAM role to the agent identity.

    Binds the specified IAM role to the agent's principal identity on
    the GCP project. Required for Agent Identity deployments so the
    agent can access resources like Firestore or Cloud Storage.

    Example:
        uv run python ae_cloud_test.py grant-iam --role roles/datastore.user
    """
    env = load_env_config(env_file)
    project_id = project_id or env["PROJECT_ID"]
    member = member or env["AGENT_IDENTITY"]

    if not project_id:
        click.echo("❌ Error: GOOGLE_CLOUD_PROJECT not set. Use --project-id or .env")
        sys.exit(1)

    if not member or member == "N/A":
        click.echo(
            "❌ Error: AGENT_IDENTITY not set or is 'N/A'.\n"
            "  This agent was not deployed with --agent-identity.\n"
            "  Use --member to provide an explicit principal, or\n"
            "  redeploy with: uv run python ae_deploy.py --agent-identity"
        )
        sys.exit(1)

    # Ensure member has the principal:// prefix
    if not member.startswith("principal://"):
        member = f"principal://{member}"

    click.echo(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🔐 GRANT IAM ROLE — Agent Identity                      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    grant_iam_to_agent(
        project_id=project_id,
        member=member,
        role=role,
    )


if __name__ == "__main__":
    cli()
