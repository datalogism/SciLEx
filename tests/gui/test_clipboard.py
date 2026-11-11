"""Copying the job log: system clipboard tool, and the panel's Copy log button."""

import asyncio
import subprocess
from unittest import mock

import pytest
from nicegui.testing import user_simulation

from scilex.gui.components.job_panel import JobPanel
from scilex.gui.services import clipboard


def test_copy_text_pipes_text_to_the_platform_tool():
    with (
        mock.patch.object(
            clipboard, "_clipboard_command", return_value=(["pbcopy"], "utf-8")
        ),
        mock.patch.object(clipboard.subprocess, "run") as run,
    ):
        assert clipboard.copy_text("05:02 — done")
    assert run.call_args.args[0] == ["pbcopy"]
    assert run.call_args.kwargs["input"] == "05:02 — done".encode()


def test_copy_text_reports_failure():
    with (
        mock.patch.object(
            clipboard, "_clipboard_command", return_value=(["pbcopy"], "utf-8")
        ),
        mock.patch.object(
            clipboard.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "pbcopy"),
        ),
    ):
        assert not clipboard.copy_text("x")
    with mock.patch.object(clipboard, "_clipboard_command", return_value=None):
        assert not clipboard.copy_text("x")


@pytest.mark.anyio
async def test_copy_log_button_copies_the_whole_log(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag")

    def root():
        JobPanel(ctx, review, "export")

    async with user_simulation(root) as user:
        await user.open("/")
        job = ctx.runner.start_task(review, "export", lambda job: "Done.")
        while job.is_active:
            await asyncio.sleep(0.01)
        job.logs[:] = [f"line {index}" for index in range(120)]
        await user.should_see(
            marker="export-copy-log", retries=20
        )  # shown once a job exists
        with mock.patch.object(clipboard, "copy_text", return_value=True) as copy_text:
            user.find(marker="export-copy-log").click()
        copied = copy_text.call_args.args[0]
        assert copied.splitlines() == job.logs  # all 120 lines, not only the 50 shown
