"""JobPanel reports every job that ends after the page opened, even a very fast one."""

import asyncio

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from scilex.gui.components.job_panel import JobPanel

pytestmark = pytest.mark.anyio


async def test_fast_job_finishing_between_ticks_is_reported(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag")
    finished = []

    def root():
        JobPanel(ctx, review, "export", on_finished=lambda job: finished.append(job.id))

    async with user_simulation(root) as user:
        await user.open("/")
        job = ctx.runner.start_task(review, "export", lambda job: "Done.")
        for _ in range(50):  # the job ends long before the first 0.5 s tick
            if not job.is_active:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.7)
        assert finished == [job.id]
        await asyncio.sleep(0.6)
        assert finished == [job.id]  # reported once only


async def test_job_finished_before_page_opened_is_not_reported(ctx, tmp_path):
    review = ctx.workspace.create_review(tmp_path / "rag", name="rag")
    job = ctx.runner.start_task(review, "export", lambda job: "Done.")
    while job.is_active:
        await asyncio.sleep(0.01)
    finished = []

    def root():
        JobPanel(ctx, review, "export", on_finished=lambda j: finished.append(j.id))
        ui.label("ready")

    async with user_simulation(root) as user:
        await user.open("/")
        await asyncio.sleep(0.7)
        assert finished == []
