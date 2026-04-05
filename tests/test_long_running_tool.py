"""Tests for the non-blocking long-running task tools (append_event approach).

Tests cover:
- submit_long_task: immediate return, state updates, background task creation
- check_task_status: reading status from session state
- check_pending_tasks_callback: one-shot notification delivery lifecycle
- _background_work: append_event integration for completion and failure
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adk_agent.tools import (
    _background_work,
    check_pending_tasks_callback,
    check_task_status,
    submit_long_task,
)


@pytest.fixture
def mock_session_service():
    """Create a mock session service with async append_event."""
    service = MagicMock()
    service.append_event = AsyncMock()
    return service


@pytest.fixture
def mock_session():
    """Create a mock Session with required identifiers."""
    session = MagicMock()
    session.app_name = "test_app"
    session.user_id = "user_123"
    session.id = "session_456"
    return session


@pytest.fixture
def mock_tool_context(mock_session_service, mock_session):
    """Create a mock ToolContext with state dict and invocation context."""
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context = MagicMock()
    ctx._invocation_context.session_service = mock_session_service
    ctx._invocation_context.session = mock_session
    return ctx


@pytest.fixture
def mock_callback_context():
    """Create a mock CallbackContext with state dict."""
    ctx = MagicMock()
    ctx.state = {}
    return ctx


# ---------------------------------------------------------------------------
# Tests for submit_long_task
# ---------------------------------------------------------------------------


class TestSubmitLongTask:
    """Tests for the submit_long_task function."""

    def test_returns_immediately_with_submitted_status(self, mock_tool_context):
        """Should return immediately with status 'submitted', not block."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            result = submit_long_task("test_task", 5, mock_tool_context)

        assert result["status"] == "submitted"
        assert result["task_name"] == "test_task"
        assert result["duration"] == 5
        assert "submitted" in result["message"].lower()

    def test_sets_state_to_in_progress(self, mock_tool_context):
        """Should update session state to in_progress."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            submit_long_task("my_job", 10, mock_tool_context)

        assert mock_tool_context.state["task_status"] == "in_progress"
        assert mock_tool_context.state["task_name"] == "my_job"

    def test_creates_background_task_with_session_refs(self, mock_tool_context):
        """Should call loop.create_task with session service and session."""
        mock_loop = MagicMock()
        with patch("adk_agent.tools.asyncio.get_event_loop", return_value=mock_loop):
            submit_long_task("bg_test", 5, mock_tool_context)

        mock_loop.create_task.assert_called_once()

    def test_returns_dict_type(self, mock_tool_context):
        """Should return a dict (required by ADK tool contract)."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            result = submit_long_task("type_check", 7, mock_tool_context)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"status", "task_name", "duration", "message"}

    def test_duration_in_message(self, mock_tool_context):
        """Should include the custom duration in the response message."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            result = submit_long_task("dur_test", 15, mock_tool_context)

        assert "15" in result["message"]
        assert result["duration"] == 15


# ---------------------------------------------------------------------------
# Tests for check_task_status
# ---------------------------------------------------------------------------


class TestCheckTaskStatus:
    """Tests for the check_task_status function."""

    def test_returns_not_found_for_unknown_task(self, mock_tool_context):
        """Should return not_found for a task that was never submitted."""
        result = check_task_status("nonexistent", mock_tool_context)

        assert result["status"] == "not_found"
        assert "nonexistent" in result["message"]

    def test_returns_not_found_for_mismatched_name(self, mock_tool_context):
        """Should return not_found when task_name doesn't match stored name."""
        mock_tool_context.state["task_name"] = "actual_task"
        mock_tool_context.state["task_status"] = "in_progress"

        result = check_task_status("wrong_task", mock_tool_context)

        assert result["status"] == "not_found"

    def test_returns_in_progress_for_running_task(self, mock_tool_context):
        """Should return in_progress for a submitted but incomplete task."""
        mock_tool_context.state["task_name"] = "active_job"
        mock_tool_context.state["task_status"] = "in_progress"

        result = check_task_status("active_job", mock_tool_context)

        assert result["status"] == "in_progress"
        assert result["task_name"] == "active_job"
        assert "message" not in result  # No message for in-progress

    def test_returns_completed_for_done_task(self, mock_tool_context):
        """Should return completed with result message for a finished task."""
        mock_tool_context.state["task_name"] = "done_job"
        mock_tool_context.state["task_status"] = "completed"
        mock_tool_context.state["task_result"] = (
            "Task 'done_job' finished successfully after 5s."
        )

        result = check_task_status("done_job", mock_tool_context)

        assert result["status"] == "completed"
        assert "done_job" in result["message"]

    def test_returns_failed_status(self, mock_tool_context):
        """Should return failed with error message for a failed task."""
        mock_tool_context.state["task_name"] = "bad_job"
        mock_tool_context.state["task_status"] = "failed"
        mock_tool_context.state["task_result"] = "Task 'bad_job' failed unexpectedly."

        result = check_task_status("bad_job", mock_tool_context)

        assert result["status"] == "failed"
        assert "failed" in result["message"]


# ---------------------------------------------------------------------------
# Tests for check_pending_tasks_callback
# ---------------------------------------------------------------------------


class TestCheckPendingTasksCallback:
    """Tests for the before_agent_callback (one-shot notification lifecycle)."""

    async def test_no_notification_when_empty(self, mock_callback_context):
        """Should set empty notification when no task is pending."""
        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""

    async def test_marks_notification_as_delivered_on_first_see(
        self, mock_callback_context
    ):
        """Turn N: notification exists → mark as delivered, leave for agent."""
        mock_callback_context.state["task_completed_notification"] = (
            "IMPORTANT: Background task 'my_task' has just completed!"
        )

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        # Notification should still be there (agent hasn't seen it yet)
        assert "my_task" in mock_callback_context.state["task_completed_notification"]
        # But marked as delivered for cleanup next turn
        assert mock_callback_context.state["_task_notification_delivered"] is True

    async def test_clears_notification_after_delivery(self, mock_callback_context):
        """Turn N+1: notification was delivered → clear it."""
        mock_callback_context.state["task_completed_notification"] = (
            "IMPORTANT: Background task 'my_task' has just completed!"
        )
        mock_callback_context.state["_task_notification_delivered"] = True

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""
        assert mock_callback_context.state["_task_notification_delivered"] is False

    async def test_no_notification_when_no_task_submitted(self, mock_callback_context):
        """Should be no-op when there's no notification at all."""
        mock_callback_context.state["task_completed_notification"] = ""

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""
        assert "_task_notification_delivered" not in mock_callback_context.state

    async def test_full_lifecycle(self, mock_callback_context):
        """Test the complete 3-turn notification lifecycle."""
        state = mock_callback_context.state

        # Turn 1: No notification yet
        await check_pending_tasks_callback(callback_context=mock_callback_context)
        assert state["task_completed_notification"] == ""

        # Simulate: background worker writes notification via append_event
        state["task_completed_notification"] = "IMPORTANT: Task completed!"

        # Turn 2: Notification arrives → mark as delivered
        await check_pending_tasks_callback(callback_context=mock_callback_context)
        assert state["task_completed_notification"] == "IMPORTANT: Task completed!"
        assert state["_task_notification_delivered"] is True

        # Turn 3: Already delivered → clear
        await check_pending_tasks_callback(callback_context=mock_callback_context)
        assert state["task_completed_notification"] == ""
        assert state["_task_notification_delivered"] is False


# ---------------------------------------------------------------------------
# Tests for _background_work (append_event integration)
# ---------------------------------------------------------------------------


class TestBackgroundWork:
    """Tests for the _background_work coroutine."""

    async def test_completes_and_appends_event(
        self, mock_session_service, mock_session
    ):
        """Should call session_service.append_event with completion state_delta."""
        await _background_work("bg_test", 0, mock_session_service, mock_session)

        mock_session_service.append_event.assert_called_once()
        call_args = mock_session_service.append_event.call_args
        event = call_args[0][1]  # second positional arg is the Event

        assert event.author == "system"
        assert event.invocation_id == "bg_bg_test"
        assert event.actions.state_delta["task_status"] == "completed"
        assert "bg_test" in event.actions.state_delta["task_result"]
        assert "bg_test" in event.actions.state_delta["task_completed_notification"]

    async def test_event_contains_result_message(
        self, mock_session_service, mock_session
    ):
        """Should include duration in the result message."""
        await _background_work("msg_test", 0, mock_session_service, mock_session)

        event = mock_session_service.append_event.call_args[0][1]
        assert "0s" in event.actions.state_delta["task_result"]

    async def test_passes_session_to_append_event(
        self, mock_session_service, mock_session
    ):
        """Should pass the session object to append_event for state lookup."""
        await _background_work("session_test", 0, mock_session_service, mock_session)

        call_args = mock_session_service.append_event.call_args
        assert call_args[0][0] is mock_session  # first positional arg is session

    async def test_handles_failure_gracefully(self, mock_session_service, mock_session):
        """Should persist failure state via append_event when work raises."""
        # Make sleep raise to simulate work failure
        with patch("adk_agent.tools.asyncio.sleep", side_effect=RuntimeError("boom")):
            await _background_work("fail_test", 5, mock_session_service, mock_session)

        # Should have appended a failure event
        mock_session_service.append_event.assert_called_once()
        event = mock_session_service.append_event.call_args[0][1]
        assert event.actions.state_delta["task_status"] == "failed"
        assert "FAILED" in event.actions.state_delta["task_completed_notification"]
