"""The PRISMA funnel: stages, losses and the SVG."""

from scilex.gui.services import prisma_funnel as funnel
from scilex.gui.services.prisma import Prisma


def flow() -> Prisma:
    f = Prisma()
    f.identification.count = 900
    f.other_sources.count = 100
    f.removed_before.count = 400
    f.removed_before.lines = ["duplicates: 300", "no abstract: 100"]
    f.screened.count = 600
    f.kept = 500
    f.excluded.count = 160
    f.excluded.lines = ["excluded in ③ Screen: 60", "excluded by C1 – Period: 100"]
    f.included.count = 120
    f.included.lines = ["plus 20 marked maybe"]
    f.pending.count = 300
    return f


def test_stages_and_losses():
    found = funnel.stages(flow())
    assert [(s.label, s.count, s.lost) for s in found] == [
        ("Identified", 1000, 0),
        ("In the corpus", 600, 400),
        ("Eligible", 500, 100),
        ("Screened", 200, 0),  # 300 still to screen: not lost
        ("Included", 120, 80),
    ]
    assert found[2].reasons == ["excluded by C1 – Period: 100"]
    assert found[3].note == "300 still to screen"
    assert found[4].reasons == ["excluded in ③ Screen: 60", "plus 20 marked maybe"]


def test_svg_is_self_contained():
    picture = funnel.svg(funnel.stages(flow()))
    assert picture.startswith("<svg") and "<script" not in picture
    assert picture.count("<path") == 5
    assert "−400" in picture and "300 still to screen" in picture
    assert "12 % of identified" in picture
    assert funnel.svg([]) == ""


def test_without_identification_count():
    f = flow()
    f.identification.count = None
    assert funnel.stages(f)[0].count == 1000  # corpus + removed before
