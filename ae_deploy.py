import asyncio
import json
import logging
import os
import sys
import tomllib

import vertexai.agent_engines

# Load .env file manually from adk_agent/.env
_env_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "adk_agent", ".env"
)
if os.path.exists(_env_path):
    with open(_env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    key, value = line.split("=", 1)
                    val = value.strip()
                    if (val.startswith('"') and val.endswith('"')) or (
                        val.startswith("'") and val.endswith("'")
                    ):
                        val = val[1:-1]
                    os.environ[key.strip()] = val
                except ValueError:
                    pass  # Ignore malformed lines
import time

import vertexai

# Step descriptions
STEPS = [
    "Set environment variables and logging",
    "Initialize Vertex AI",
    "Local test (async)",
    "Deploy agent to Vertex AI",
    "Test deployed agent on cloud (sync)",
]

DISPLAY_NAME = os.getenv("DISPLAY_NAME", "GE Asset - MCP Server Agent")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = os.getenv("STAGING_BUCKET", "gs://wei-test")
ENV_VARS = {
    "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    "COLLECTION": os.getenv("COLLECTION", "accounts"),
    "DATABASE_ID": os.getenv("DATABASE_ID", "default"),
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
}


def load_requirements_from_pyproject() -> list[str]:
    """
    Reads dependencies dynamically from pyproject.toml in the workspace root.

    Returns:
        list[str]: A list of dependency strings.
    """
    _pyproject_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "pyproject.toml",
    )
    if not os.path.exists(_pyproject_path):
        print(f"pyproject.toml not found at {_pyproject_path}, using empty list.")
        return []

    try:
        with open(_pyproject_path, "rb") as f:
            data = tomllib.load(f)
        dependencies = data.get("project", {}).get("dependencies", [])
        print(f"Loaded {len(dependencies)} requirements from pyproject.toml")
        return dependencies
    except Exception as e:
        print(f"Error loading dependencies from pyproject.toml: {e}. Using empty list.")
        return []


# Remove MCP_SERVER_URL so the agent uses direct function tools instead
# of McpToolset. McpToolset holds SSE connections (TextIOWrapper) that
# cannot be pickled for Agent Engine deployment. Direct functions call
# Firestore directly and are fully picklable.
os.environ.pop("MCP_SERVER_URL", None)

EXTRA_PACKAGES = ["./adk_agent", "./er_query"]
REQUIREMENTS = load_requirements_from_pyproject()
logging.getLogger("google").setLevel(logging.ERROR)


def step_progress(step_idx):
    print(f"\n[Step {step_idx + 1}/{len(STEPS)}] {STEPS[step_idx]}")
    print()


# Timing decorator for steps
def timed_step(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"\n--- Step runtime: {end - start:.2f} seconds ---\n")
        return result

    return wrapper


def set_env_and_logging():
    step_progress(0)

    print("\n--- Configuration Settings ---")
    print(f"DISPLAY_NAME: {DISPLAY_NAME}")
    print(f"PROJECT_ID: {PROJECT_ID}")
    print(f"LOCATION: {LOCATION}")
    print(f"STAGING_BUCKET: {STAGING_BUCKET}")
    print(f"COLLECTION: {os.getenv('COLLECTION', 'expert_requests_dev')}")
    print(f"DATABASE_ID: {os.getenv('DATABASE_ID', 'ikigai-dev')}")
    print("-------------------------------\n")

    confirm = input("Confirm these settings? Proceed? [y/N]: ")
    if confirm.lower() != "y":
        print("Execution aborted by user.")
        sys.exit(0)

    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"  # Use Vertex AI API
    print("Environment variables set.")


def init_vertexai():
    step_progress(1)
    vertexai.init(
        project=PROJECT_ID,
        location=LOCATION,
        staging_bucket=STAGING_BUCKET,
    )
    print("Vertex AI initialized.")


def import_agent():
    from vertexai import agent_engines

    from adk_agent.agent import root_agent

    return agent_engines, root_agent


@timed_step
async def local_test():
    step_progress(2)
    reasoning_engines, root_agent = import_agent()
    app = reasoning_engines.AdkApp(
        agent=root_agent,
        enable_tracing=True,
    )
    session = await app.async_create_session(user_id="u_123")
    PROMPT = "What expert requests are assigned to weiyih@google.com?"
    print("Local test session created.")
    async for event in app.async_stream_query(
        user_id="u_123",
        session_id=session.id,
        message=PROMPT,
    ):
        print("*" * 40)
        content = event.get("content", {})
        parts = content.get("parts", [])

        for part in parts:
            if "thought_signature" in part:
                print(f"Thought Signature: {part['thought_signature']}")

            if "function_call" in part:
                func_call = part["function_call"]
                print(f"Function Call - Name: {func_call.get('name')}")
                print(f"Function Call - Args: {func_call.get('args')}")

            if "function_response" in part:
                func_response = part["function_response"]
                print(f"Function Response - Name: {func_response.get('name')}")
                print(f"Function Response - Result: {func_response.get('response')}")

            if "text" in part:
                print(f"Text: {part['text']}")
    print("Local test completed.")


@timed_step
def deploy_agent():
    step_progress(3)
    from vertexai import agent_engines

    agent_engines, root_agent = import_agent()
    app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)
    remote_app = agent_engines.create(
        display_name=DISPLAY_NAME,
        agent_engine=app,
        requirements=REQUIREMENTS,
        extra_packages=EXTRA_PACKAGES,
        env_vars=ENV_VARS,
    )
    ENGINE_ID = remote_app.resource_name.split("/")[-1]
    print(f"Agent deployed. ENGINE_ID: {ENGINE_ID}")
    return ENGINE_ID


@timed_step
async def test_on_cloud(engine_id):
    step_progress(4)
    adk_app = vertexai.agent_engines.get(
        f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{engine_id}"
    )
    session = await adk_app.async_create_session(user_id="u_123")
    print(f"Cloud test session created: {session}")
    for PROMPT in ["What expert requests are assigned to weiyih@google.com?"]:
        print(f"\nPrompt: {PROMPT}")
        async for event in adk_app.async_stream_query(
            user_id="u_123",
            session_id=session["id"],
            message=PROMPT,
        ):
            print("*" * 40)
            content = event.get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                if "thought_signature" in part:
                    print(f"Thought Signature: {part['thought_signature']}")

                if "function_call" in part:
                    func_call = part["function_call"]
                    print(f"Function Call - Name: {func_call.get('name')}")
                    print(f"Function Call - Args: {func_call.get('args')}")

                if "function_response" in part:
                    func_response = part["function_response"]
                    print(f"Function Response - Name: {func_response.get('name')}")
                    print(
                        f"Function Response - Result: {func_response.get('response')}"
                    )

                if "text" in part:
                    print(f"Text: {part['text']}")
    print("Cloud test completed.")


def update_env_file(engine_id: str) -> None:
    """
    Updates the .env file with the newly deployed ENGINE_ID.

    Args:
         engine_id: The unique identifier for the deployed engine.

    Returns:
         None. Modifies the file in-place.
    """
    _env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "adk_agent", ".env"
    )
    if not os.path.exists(_env_path):
        print(f".env file not found at {_env_path}, skipping update.")
        return

    lines = []
    updated = False
    with open(_env_path, "r") as f:
        for line in f:
            if line.startswith("ENGINE_ID="):
                lines.append(f"ENGINE_ID={engine_id}\n")
                updated = True
            else:
                lines.append(line)

    if not updated:
        lines.append(f"ENGINE_ID={engine_id}\n")

    with open(_env_path, "w") as f:
        f.writelines(lines)
    print(f"Updated .env with ENGINE_ID={engine_id}\n")


def main():
    try:
        set_env_and_logging()
        init_vertexai()
        asyncio.run(local_test())
        engine_id = deploy_agent()
        update_env_file(engine_id)
        asyncio.run(test_on_cloud(engine_id))
        print(f"\nAll {len(STEPS)}/{len(STEPS)} steps completed successfully.")
    except Exception as e:
        print(f"\nError: {e}")
        print("Aborting further steps.")
        sys.exit(1)


if __name__ == "__main__":
    main()
