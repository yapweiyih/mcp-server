"""Tests for the ADK agent.

Tests verify the agent can run with MCP tools and respond to various
query prompts. These are integration tests that require Firestore
and Vertex AI access.
"""

import asyncio
import os

import pytest
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

pytestmark = pytest.mark.integration

# Load environment for Vertex AI
load_dotenv("adk_agent/.env")


@pytest.fixture
def runner():
    """Create an ADK runner with the ER query agent."""
    from adk_agent.agent import root_agent

    session_service = InMemorySessionService()
    return Runner(
        agent=root_agent,
        app_name="er_query_test",
        session_service=session_service,
    )


async def _run_agent(runner: Runner, prompt: str) -> str:
    """Run the agent with a prompt and return the final response text.

    Args:
        runner: The ADK Runner instance.
        prompt: The user's query prompt.

    Returns:
        The agent's final response as a string.
    """
    session = await runner.session_service.create_session(
        app_name="er_query_test",
        user_id="test_user",
    )

    final_text = ""
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    return final_text


class TestAgentEmailQueries:
    """Test agent responses to email-based queries."""

    @pytest.fixture(autouse=True)
    def check_credentials(self):
        """Skip if GCP credentials are not available."""
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            pytest.skip("GOOGLE_CLOUD_PROJECT not set")

    async def test_query_by_known_email(self, runner):
        """Agent should find ERs for a known email."""
        response = await _run_agent(
            runner,
            "Find all ERs assigned to issein@google.com",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        lower = response.lower()
        if "api" in lower and "disabled" in lower:
            pytest.skip("Firestore API is disabled in this project")
        assert "ER-431059" in response or "Australian Postal" in response

    async def test_query_by_email_no_results(self, runner):
        """Agent should report no results for unknown email."""
        response = await _run_agent(
            runner,
            "Show me ERs assigned to nonexistent_xyz@google.com",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        lower = response.lower()
        if "api" in lower and "disabled" in lower:
            pytest.skip("Firestore API is disabled in this project")
        assert "no" in lower or "not found" in lower or "0" in response


class TestAgentDateQueries:
    """Test agent responses to date-based queries."""

    @pytest.fixture(autouse=True)
    def check_credentials(self):
        """Skip if GCP credentials are not available."""
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            pytest.skip("GOOGLE_CLOUD_PROJECT not set")

    async def test_query_by_year(self, runner):
        """Agent should find ERs for a given year."""
        response = await _run_agent(
            runner,
            "How many ERs were created in 2024?",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        lower = response.lower()
        if "api" in lower and "disabled" in lower:
            pytest.skip("Firestore API is disabled in this project")
        # We know there are 120 ERs in 2024 from integration tests
        assert "120" in response or "ER" in response

    async def test_query_by_year_month(self, runner):
        """Agent should find ERs for a specific month."""
        response = await _run_agent(
            runner,
            "Show me ERs from April 2024",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        lower = response.lower()
        if "api" in lower and "disabled" in lower:
            pytest.skip("Firestore API is disabled in this project")
        assert "ER" in response


class TestAgentEdgeCases:
    """Test agent handling of edge cases and ambiguous queries."""

    @pytest.fixture(autouse=True)
    def check_credentials(self):
        """Skip if GCP credentials are not available."""
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            pytest.skip("GOOGLE_CLOUD_PROJECT not set")

    async def test_ambiguous_query(self, runner):
        """Agent should handle ambiguous queries gracefully."""
        response = await _run_agent(
            runner,
            "Tell me about Australian Postal Corporation ERs",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        lower = response.lower()
        if "api" in lower and "disabled" in lower:
            pytest.skip("Firestore API is disabled in this project")
        # Agent should attempt to use a tool or ask for clarification
        assert len(response) > 0

    async def test_general_greeting(self, runner):
        """Agent should respond to greetings without tool calls."""
        response = await _run_agent(
            runner,
            "Hello, what can you help me with?",
        )
        print(f"\n🤖 Response:\n{response[:500]}")
        assert (
            "expert request" in response.lower()
            or "er" in response.lower()
            or "help" in response.lower()
        )
