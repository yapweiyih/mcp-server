"""Retrieve the A2A agent card from a deployed Agent Engine instance.

Fetches the authenticated agent card JSON from the Agent Engine
using the Vertex AI SDK and prints it in pretty-printed JSON format.

Usage:
    # Uses A2A_ENGINE_ID from adk_agent/.env by default:
    uv run python ge_get_agent_card.py

    # Or specify a resource ID explicitly:
    uv run python ge_get_agent_card.py --resource-id 7981724891688730624

    # Use ENGINE_ID (ADK agent) instead of A2A:
    uv run python ge_get_agent_card.py --resource-id 3034520701022240768
"""

import asyncio
import json
import os

import click
from dotenv import load_dotenv

load_dotenv("adk_agent/.env")


def _to_dict(obj: object) -> dict:
    """Convert a Pydantic model, A2A type, or dict to a plain dict.

    Args:
        obj: A Pydantic BaseModel, A2A type, or dict.

    Returns:
        A plain dictionary representation of the object.
    """
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json", exclude_none=True)
        except Exception:
            return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


async def get_agent_card(
    project_id: str,
    location: str,
    resource_id: str,
) -> dict:
    """Retrieve the authenticated agent card from Agent Engine.

    Uses the Vertex AI SDK to connect to the deployed reasoning engine
    and fetch its A2A agent card.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., us-central1).
        resource_id: The Agent Engine resource ID.

    Returns:
        A dictionary containing the agent card fields such as:
        'name', 'description', 'url', 'version', 'skills',
        'protocolVersion', 'defaultInputModes', 'defaultOutputModes',
        'capabilities'.

    Example return value:
        {
            "protocolVersion": "0.3.0",
            "name": "ER Query Agent",
            "description": "An AI agent that queries Expert Requests",
            "url": "https://...",
            "version": "1.0.0",
            "skills": [...]
        }
    """
    import vertexai
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
    return _to_dict(card_raw)


@click.command()
@click.option(
    "--resource-id",
    type=str,
    default=None,
    help="Agent Engine resource ID (default: A2A_ENGINE_ID from .env)",
)
@click.option(
    "--project-id",
    type=str,
    default=None,
    help="GCP project ID (default: GOOGLE_CLOUD_PROJECT from .env)",
)
@click.option(
    "--location",
    type=str,
    default=None,
    help="GCP region (default: GOOGLE_CLOUD_LOCATION from .env or us-central1)",
)
def main(
    resource_id: str,
    project_id: str,
    location: str,
) -> None:
    """Retrieve and display the A2A agent card in JSON format."""

    resource_id = resource_id or os.getenv("A2A_ENGINE_ID")
    if not resource_id:
        raise click.UsageError(
            "Missing --resource-id. Set A2A_ENGINE_ID in adk_agent/.env "
            "or pass --resource-id."
        )

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise click.UsageError(
            "Missing --project-id. Set GOOGLE_CLOUD_PROJECT in adk_agent/.env."
        )

    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    click.echo(f"📇 Fetching agent card...", err=True)
    click.echo(f"   Project:     {project_id}", err=True)
    click.echo(f"   Location:    {location}", err=True)
    click.echo(f"   Resource ID: {resource_id}", err=True)
    click.echo(err=True)

    card = asyncio.run(
        get_agent_card(
            project_id=project_id,
            location=location,
            resource_id=resource_id,
        )
    )

    # Output clean JSON to stdout (metadata goes to stderr)
    click.echo(json.dumps(card, indent=2, default=str))


if __name__ == "__main__":
    main()
