"""Tests for the non-blocking long-running task tools.

Tests cover:
- submit_long_task: immediate return, state updates, background task creation
- check_task_status: polling in-progress and completed tasks
- check_pending_tasks_callback: notification injection on task completion
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adk_agent.tools import (
    _task_registry,
    check_pending_tasks_callback,
    check_task_status,
    submit_long_task,
)


@pytest.fixture(autouse=True)
def clear_task_registry():
    """Clear the task registry before each test."""
    _task_registry.clear()
    yield
    _task_registry.clear()


@pytest.fixture
def mock_tool_context():
    """Create a mock ToolContext with state dict."""
    ctx = MagicMock()
    ctx.state = {}
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

            result = submit_long_task("test_task", mock_tool_context)

        assert result["status"] == "submitted"
        assert result["task_name"] == "test_task"
        assert "submitted" in result["message"].lower()

    def test_sets_state_to_in_progress(self, mock_tool_context):
        """Should update session state to in_progress."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            submit_long_task("my_job", mock_tool_context)

        assert mock_tool_context.state["task_status"] == "in_progress"
        assert mock_tool_context.state["task_name"] == "my_job"

    def test_registers_task_in_registry(self, mock_tool_context):
        """Should register the task in _task_registry."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            submit_long_task("registry_test", mock_tool_context)

        assert "registry_test" in _task_registry
        assert _task_registry["registry_test"]["status"] == "in_progress"

    def test_creates_background_task(self, mock_tool_context):
        """Should call loop.create_task to schedule background work."""
        mock_loop = MagicMock()
        with patch("adk_agent.tools.asyncio.get_event_loop", return_value=mock_loop):
            submit_long_task("bg_test", mock_tool_context)

        mock_loop.create_task.assert_called_once()

    def test_returns_dict_type(self, mock_tool_context):
        """Should return a dict (required by ADK tool contract)."""
        with patch("adk_agent.tools.asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value = MagicMock()

            result = submit_long_task("type_check", mock_tool_context)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"status", "task_name", "message"}


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

    def test_returns_in_progress_for_running_task(self, mock_tool_context):
        """Should return in_progress for a submitted but incomplete task."""
        _task_registry["active_job"] = {
            "status": "in_progress",
            "task_name": "active_job",
        }

        result = check_task_status("active_job", mock_tool_context)

        assert result["status"] == "in_progress"
        assert mock_tool_context.state["task_status"] == "in_progress"

    def test_returns_completed_for_done_task(self, mock_tool_context):
        """Should return completed for a finished task."""
        _task_registry["done_job"] = {
            "status": "completed",
            "task_name": "done_job",
            "duration_seconds": 5,
            "message": "Task 'done_job' finished successfully after 5s.",
        }

        result = check_task_status("done_job", mock_tool_context)

        assert result["status"] == "completed"
        assert result["duration_seconds"] == 5
        assert mock_tool_context.state["task_status"] == "completed"
        assert "done_job" in mock_tool_context.state["task_result"]


# ---------------------------------------------------------------------------
# Tests for check_pending_tasks_callback
# ---------------------------------------------------------------------------


class TestCheckPendingTasksCallback:
    """Tests for the before_agent_callback."""

    async def test_no_notification_when_no_task(self, mock_callback_context):
        """Should set empty notification when no task is pending."""
        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""

    async def test_no_notification_when_already_completed(self, mock_callback_context):
        """Should not re-notify for tasks already marked completed."""
        mock_callback_context.state["task_name"] = "old_task"
        mock_callback_context.state["task_status"] = "completed"

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""

    async def test_injects_notification_on_completion(self, mock_callback_context):
        """Should inject notification when task transitions to completed."""
        mock_callback_context.state["task_name"] = "my_task"
        mock_callback_context.state["task_status"] = "in_progress"

        _task_registry["my_task"] = {
            "status": "completed",
            "task_name": "my_task",
            "duration_seconds": 5,
            "message": "Task 'my_task' finished successfully after 5s.",
        }

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        notification = mock_callback_context.state["task_completed_notification"]
        assert "my_task" in notification
        assert "completed" in notification.lower()
        assert mock_callback_context.state["task_status"] == "completed"

    async def test_no_notification_when_still_running(self, mock_callback_context):
        """Should not notify when task is still in progress."""
        mock_callback_context.state["task_name"] = "running_task"
        mock_callback_context.state["task_status"] = "in_progress"

        _task_registry["running_task"] = {
            "status": "in_progress",
            "task_name": "running_task",
        }

        await check_pending_tasks_callback(callback_context=mock_callback_context)

        assert mock_callback_context.state["task_completed_notification"] == ""


# ---------------------------------------------------------------------------
# Tests for _background_work (the actual async work)
# ---------------------------------------------------------------------------


class TestBackgroundWork:
    """Tests for the _background_work coroutine."""

    async def test_completes_and_updates_registry(self):
        """Should update _task_registry to completed after running."""
        from adk_agent.tools import _background_work

        _task_registry["bg_test"] = {"status": "in_progress", "task_name": "bg_test"}

        # Run with 0 duration to make it instant
        await _background_work("bg_test", duration=0)

        assert _task_registry["bg_test"]["status"] == "completed"
        assert _task_registry["bg_test"]["duration_seconds"] == 0
        assert "bg_test" in _task_registry["bg_test"]["message"]
