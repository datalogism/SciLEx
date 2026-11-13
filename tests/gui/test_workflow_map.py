"""The review workflow map of the Overview."""

import pytest
from nicegui.testing import user_simulation

from scilex.gui.app import build_root
from scilex.gui.services import journal, prisma, screening, workflow_map
from tests.gui.test_prisma import review  # noqa: F401  (fixture)

MAIN = {"keywords": [["rag"], ["graph"]], "apis": ["OpenAlex"], "years": [2022, 2024]}


def test_steps_follow_the_review(review):  # noqa: F811
    screening.set_decision(review, "doi:10.1/a", screening.INCLUDE)
    journal.append(review.folder, "job:analysis-citations")
    journal.append(review.folder, "job:analysis-snowball")
    steps = {
        s.key: s
        for s in workflow_map.compute(
            review,
            prisma.compute(review, MAIN),
            journal.load(review.folder),
            MAIN,
        )
    }
    assert list(steps) == [key for key, *_ in workflow_map.STEPS]
    assert steps["configure"].progress == 100
    assert steps["configure"].value == "2 keywords · 1 APIs"
    assert steps["collect"].progress == 100
    screen = steps["screen"]
    assert screen.value == "2 / 3 decided" and screen.progress == 67
    assert screen.todo == ["1 papers still to screen"]
    assert steps["criteria"].progress == 0  # defaults, never saved
    # Snowballed after the last consolidation: consolidate again.
    assert steps["consolidate"].value == "needed"
    assert 0 < steps["enrich"].progress < 100
    assert "citations" in steps["enrich"].facts[0]
    assert steps["export"].progress == 0


def test_svg_has_every_step_and_loop():
    steps = [
        workflow_map.StepState(key, code, name, progress=50)
        for key, code, name, _ in workflow_map.STEPS
    ]
    picture = workflow_map.svg(steps, "screen")
    assert picture.count('class="wf-stg') == 10
    assert picture.count('class="loop"') == 3
    assert "emitEvent('scilex_workflow_stage', 'screen')" in picture
    assert 'class="wf-stg on" data-step="screen"' in picture
    assert "<script" not in picture


@pytest.mark.anyio
async def test_overview_shows_the_map(ctx, review):  # noqa: F811
    async with user_simulation(build_root(ctx)) as user:
        await user.open(f"/review/{review.id}")
        await user.should_see(marker="workflow-map", retries=40)
        await user.should_see(marker="workflow-detail")
        await user.should_see(marker="workflow-open")
