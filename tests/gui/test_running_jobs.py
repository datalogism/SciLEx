"""The running-jobs button: count, list, cancel."""

import threading

import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services.jobs import wait_for

pytestmark = pytest.mark.anyio


async def test_running_job_is_listed_and_can_be_cancelled(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag_kg")
    release = threading.Event()

    def body(job):
        while not release.is_set() and not job.cancel_event.is_set():
            release.wait(0.05)
        return "done"

    job = ctx.runner.start_task(review, "analysis-crossref", body)
    try:
        async with user_simulation(build_root(ctx)) as user:
            await user.open("/")
            await user.should_see(marker="jobs-button")
            assert user.find(marker="jobs-count").elements.pop().text == "1"
            user.find(marker="jobs-button").click()
            await user.should_see("crossref on rag_kg", retries=20)
            user.find(marker=f"job-cancel-{job.id}").click()
            await wait_for(job)
            assert job.status in ("cancelled", "completed")
    finally:
        release.set()
    assert ctx.runner.recent_jobs()[0] is job
