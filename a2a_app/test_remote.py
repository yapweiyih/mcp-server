"""Test script to call the A2A agent endpoint deployed on Agent Engine.

This script demonstrates three ways to interact with a deployed A2A agent:
1. **Vertex AI SDK** - Using the native Python SDK methods
2. **A2A Python SDK** - Using the official A2A client library
3. **Raw HTTP** - Using httpx to call the REST endpoints directly

Each method performs the same operations:
- Retrieve the agent card (discover capabilities)
- Send a message (create a task)
- Get the task result

Usage:
    # Test with Vertex AI SDK (default):
    uv run python -m a2a_app.test_remote --resource-id RESOURCE_ID

    # Test with A2A SDK:
    uv run python -m a2a_app.test_remote --resource-id RESOURCE_ID --method a2a-sdk

    # Test with raw HTTP:
    uv run python -m a2a_app.test_remote --resource-id RESOURCE_ID --method http

    # Or via Makefile:
    make test-a2a-remote RESOURCE_ID=12345
"""

import asyncio
import json
import logging
import os

import click
from dotenv import load_dotenv

load_dotenv("adk_agent/.env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _to_dict(obj) -> dict:
    """Convert a Pydantic model, A2A type, or dict to a plain dict.

    The Vertex AI SDK may return Pydantic models, A2A SDK types, or dicts
    depending on the version. This helper normalizes for safe `.get()` access.

    Args:
        obj: A Pydantic BaseModel, A2A type, or dict.

    Returns:
        A plain dictionary.
    """
    if isinstance(obj, dict):
        return obj
    # Pydantic v2 models
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json", exclude_none=True)
        except Exception:
            return obj.model_dump()
    # Pydantic v1 models
    if hasattr(obj, "dict"):
        return obj.dict()
    # Last resort: use json serialization
    try:
        import json as _json

        return _json.loads(_json.dumps(obj, default=str))
    except Exception:
        return {"raw": str(obj)}


async def test_with_vertex_sdk(
    project_id: str,
    location: str,
    resource_id: str,
    message: str,
) -> dict:
    """Test the deployed A2A agent using the Vertex AI SDK.

    This is the simplest method — the SDK handles authentication and
    request formatting automatically.

    Args:
        project_id: GCP project ID.
        location: GCP region (e.g., us-central1).
        resource_id: The Agent Engine resource ID.
        message: The message to send to the agent.

    Returns:
        A dict with 'card', 'send_response', and 'task_response' keys.
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

    # 1. Get agent card
    click.echo("📇 Retrieving agent card...")
    card_raw = await remote_agent.handle_authenticated_agent_card()
    card = _to_dict(card_raw)
    click.echo(f"   Agent: {card.get('name', 'unknown')}")
    click.echo(f"   Skills: {len(card.get('skills', []))}")

    # 2. Send a message
    click.echo(f"\n📨 Sending message: {message}")
    message_data = {
        "messageId": "test-remote-001",
        "role": "user",
        "parts": [{"kind": "text", "text": message}],
    }
    send_raw = await remote_agent.on_message_send(**message_data)
    click.echo(f"\n📊 Raw send response type: {type(send_raw).__name__}")
    click.echo(json.dumps(_to_dict(send_raw), indent=2, default=str))

    # Extract task ID from response (handles both dict and Pydantic models)
    task_id = None
    if hasattr(send_raw, "result") and hasattr(send_raw.result, "id"):
        task_id = send_raw.result.id
    elif hasattr(send_raw, "id"):
        task_id = send_raw.id
    elif isinstance(send_raw, dict):
        task_id = send_raw.get("task", {}).get("id") or send_raw.get("id")
    click.echo(f"   Task ID: {task_id or 'N/A'}")

    # 3. Get task status
    task_response = None
    if task_id:
        click.echo(f"\n🔍 Getting task status for: {task_id}")
        task_raw = await remote_agent.on_get_task(id=task_id)
        task_response = _to_dict(task_raw)
        click.echo(json.dumps(task_response, indent=2, default=str))

        # Try to extract artifacts from response
        task_data = (
            task_response.get("task", task_response)
            if isinstance(task_response, dict)
            else task_response
        )
        if isinstance(task_data, dict):
            artifacts = task_data.get("artifacts", [])
            for artifact in artifacts:
                parts = artifact.get("parts", []) if isinstance(artifact, dict) else []
                for part in parts:
                    text = part.get("text", "") if isinstance(part, dict) else ""
                    if text:
                        click.echo(f"\n📄 Response:\n{text[:500]}")

    return {
        "card": card,
        "send_response": _to_dict(send_raw),
        "task_response": task_response,
    }


async def test_with_a2a_sdk(
    project_id: str,
    location: str,
    resource_id: str,
    message: str,
) -> dict:
    """Test the deployed A2A agent using the official A2A Python SDK.

    Uses the A2A ClientFactory to create a properly configured client
    that handles the A2A protocol details.

    Args:
        project_id: GCP project ID.
        location: GCP region.
        resource_id: The Agent Engine resource ID.
        message: The message to send.

    Returns:
        A dict with 'card', 'send_response' keys.
    """
    import httpx
    import vertexai
    from a2a.client import ClientConfig, ClientFactory
    from a2a.types import Message, Part, TextPart, TransportProtocol
    from google.auth import default
    from google.auth.transport.requests import Request
    from google.genai import types as genai_types

    # Get the agent card URL from Agent Engine
    client = vertexai.Client(
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    resource_name = (
        f"projects/{project_id}/locations/{location}" f"/reasoningEngines/{resource_id}"
    )
    remote_agent = client.agent_engines.get(name=resource_name)

    # Get the authenticated agent card first
    click.echo("📇 Retrieving agent card via Vertex SDK...")
    card_raw = await remote_agent.handle_authenticated_agent_card()
    card_data = _to_dict(card_raw)

    # Get credentials for A2A SDK
    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    # Create A2A client from agent card
    from a2a.types import AgentCard

    # Use the raw card if it's already an AgentCard, otherwise construct one
    agent_card = card_raw if isinstance(card_raw, AgentCard) else AgentCard(**card_data)

    factory = ClientFactory(
        ClientConfig(
            supported_transports=[TransportProtocol.http_json],
            use_client_preference=True,
            httpx_client=httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json",
                }
            ),
        )
    )
    a2a_client = factory.create(agent_card)

    # Send message via A2A SDK
    click.echo(f"\n📨 Sending message via A2A SDK: {message}")
    msg = Message(
        message_id="a2a-sdk-test-001",
        role="user",
        parts=[Part(root=TextPart(text=message))],
    )

    import pprint

    response_iterator = a2a_client.send_message(msg)
    responses = []
    async for chunk in response_iterator:
        responses.append(chunk)
        pprint.pp(chunk)

    return {
        "card": card_data,
        "send_response": responses,
    }


async def test_with_http(
    project_id: str,
    location: str,
    resource_id: str,
    message: str,
) -> dict:
    """Test the deployed A2A agent using raw HTTP requests.

    Demonstrates the underlying HTTP protocol — useful for debugging
    or integrating from non-Python clients.

    Args:
        project_id: GCP project ID.
        location: GCP region.
        resource_id: The Agent Engine resource ID.
        message: The message to send.

    Returns:
        A dict with 'card', 'send_response', 'task_response' keys.
    """
    import httpx
    import vertexai
    from google.auth import default
    from google.auth.transport.requests import Request
    from google.genai import types as genai_types

    # Get the A2A URL from the agent card
    client = vertexai.Client(
        project=project_id,
        location=location,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )

    resource_name = (
        f"projects/{project_id}/locations/{location}" f"/reasoningEngines/{resource_id}"
    )
    remote_agent = client.agent_engines.get(name=resource_name)

    # Get card to find the A2A URL
    card_raw = await remote_agent.handle_authenticated_agent_card()
    card_data = _to_dict(card_raw)
    a2a_url = card_data.get("url", "")

    # Auth
    credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    # 1. Get agent card via HTTP
    click.echo(f"📇 Getting agent card from: {a2a_url}/v1/card")
    async with httpx.AsyncClient() as http_client:
        card_response = await http_client.get(f"{a2a_url}/v1/card", headers=headers)
        click.echo(f"   Status: {card_response.status_code}")

        # 2. Send message via HTTP
        click.echo(f"\n📨 Sending message via HTTP: {message}")
        payload = {
            "message": {
                "messageId": "http-test-001",
                "role": "1",
                "content": [{"text": message}],
            },
        }
        send_response = await http_client.post(
            f"{a2a_url}/v1/message:send",
            json=payload,
            headers=headers,
        )
        send_data = send_response.json()
        click.echo(f"   Status: {send_response.status_code}")

        # 3. Get task
        task_id = send_data.get("task", {}).get("id")
        task_data = None
        if task_id:
            click.echo(f"\n🔍 Getting task: {task_id}")
            task_response = await http_client.get(
                f"{a2a_url}/v1/tasks/{task_id}",
                headers=headers,
            )
            task_data = task_response.json()
            click.echo(f"   Status: {task_response.status_code}")

    return {
        "card": card_response.json() if card_response.status_code == 200 else {},
        "send_response": send_data,
        "task_response": task_data,
    }


@click.command()
@click.option(
    "--resource-id",
    type=str,
    required=True,
    help="Agent Engine resource ID (from deployment output)",
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
    "--method",
    type=click.Choice(["vertex-sdk", "a2a-sdk", "http"]),
    default="vertex-sdk",
    help="Which client method to use for testing",
)
@click.option(
    "--message",
    type=str,
    default="Find all ERs assigned to issein@google.com",
    help="Message to send to the agent",
)
def test_remote_a2a(
    resource_id: str,
    project_id: str,
    location: str,
    method: str,
    message: str,
) -> None:
    """Test the deployed A2A agent on Agent Engine."""

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "ikigai-dev-376122")
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    print(
        """
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🧪 TESTING DEPLOYED A2A AGENT ON AGENT ENGINE 🧪        ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    )

    click.echo(f"📋 Test Parameters:")
    click.echo(f"  Resource ID: {resource_id}")
    click.echo(f"  Project:     {project_id}")
    click.echo(f"  Location:    {location}")
    click.echo(f"  Method:      {method}")
    click.echo(f"  Message:     {message}")
    click.echo()

    test_fn = {
        "vertex-sdk": test_with_vertex_sdk,
        "a2a-sdk": test_with_a2a_sdk,
        "http": test_with_http,
    }[method]

    result = asyncio.run(
        test_fn(
            project_id=project_id,
            location=location,
            resource_id=resource_id,
            message=message,
        )
    )

    click.echo("\n" + "=" * 60)
    click.echo("📊 Full Response:")
    click.echo(json.dumps(result, indent=2, default=str))
    click.echo("\n✅ Test complete!")


if __name__ == "__main__":
    test_remote_a2a()
