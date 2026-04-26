"""Smoke test a deployed ADK agent on Vertex AI Agent Engine.

Connects to a deployed Agent Engine instance and sends a test prompt
via async streaming to verify the agent responds correctly.

Usage:
    # Test using ENGINE_ID from .env:
    uv run python ae_cloud_test.py

    # Test a specific engine ID:
    uv run python ae_cloud_test.py --engine-id 8270852469328707584

    # Custom prompt:
    uv run python ae_cloud_test.py --message "How many ERs in 2024?"

    # Or via Makefile:
    make test-cloud-agent
"""

import asyncio
import json
import logging
import os
import sys

import click
import vertexai
from dotenv import load_dotenv


async def test_on_cloud(
    project_id: str,
    location: str,
    engine_id: str,
    message: str,
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

    click.echo("\n  ✅ Cloud smoke test completed.")


@click.command()
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
def cloud_test(
    env_file: str,
    engine_id: str | None,
    project_id: str | None,
    location: str | None,
    message: str,
) -> None:
    """Smoke test a deployed ADK agent on Vertex AI Agent Engine."""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("google").setLevel(logging.ERROR)

    # Load .env
    load_dotenv(env_file, override=True)

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    engine_id = engine_id or os.getenv("ENGINE_ID")

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
            )
        )
    except Exception as e:
        click.echo(f"\n  ❌ Cloud test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cloud_test()
