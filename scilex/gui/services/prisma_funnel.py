"""The PRISMA flow as a funnel: each stage narrower than the one before.

From :class:`scilex.gui.services.prisma.Prisma`, the papers go through:

1. **Identified**: the collect plus the extensions (snowballing, imports…);
2. **In the corpus**: after duplicates and the automatic filters;
3. **Eligible**: after the eligibility criteria and the discards of people;
4. **Screened**: those with a decision in ③ Screen (the rest is still to do);
5. **Included**.

Each band is as wide as its count (relative to the first), joined to the
next by smooth curves, mirrored around the centre; beside each step, what
was lost and why. The figure is a self-contained SVG string (no script), so
it is shown in the Overview and exported as it is.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from scilex.gui.services.prisma import Prisma

# Light to dark: the funnel darkens as it narrows.
FILLS = ("#c6d4f5", "#9bb3ec", "#6f92e2", "#4269d0", "#2f4fa8")
DARK_TEXT_UNTIL = 2  # the first bands carry dark text, the others white
WIDTH, BAND, GAP = 780, 58, 3
LABEL_W = 130  # stage names on the left
FUNNEL_X, FUNNEL_W = 140, 380  # funnel area; notes on the right
MIN_SHARE = 0.15  # the narrowest band still holds its count


@dataclass
class Stage:
    """One band of the funnel."""

    label: str
    count: int
    lost: int = 0  # papers lost between the previous stage and this one
    reasons: list[str] = field(default_factory=list)
    note: str = ""  # e.g. papers still to screen (not lost)


def stages(flow: Prisma) -> list[Stage]:
    """The stages of ``flow`` that have a count, in order."""
    found: list[Stage] = []
    corpus = flow.screened.count
    identified = None
    if flow.identification.count is not None:
        identified = flow.identification.count + (flow.other_sources.count or 0)
    elif corpus is not None and flow.removed_before.count is not None:
        identified = corpus + flow.removed_before.count
    if identified is not None:
        found.append(Stage("Identified", identified))
    if corpus is None:
        return found
    found.append(
        Stage(
            "In the corpus",
            corpus,
            reasons=list(flow.removed_before.lines) or ["duplicates and filters"],
        )
    )
    kept = flow.kept if flow.kept is not None else corpus
    found.append(
        Stage(
            "Eligible",
            kept,
            reasons=[
                line
                for line in flow.excluded.lines
                if not line.startswith("excluded in ③ Screen")
            ],
        )
    )
    pending = flow.pending.count or 0
    decided = max(kept - pending, 0)
    found.append(
        Stage(
            "Screened",
            decided,
            note=f"{pending:,} still to screen" if pending else "",
        )
    )
    included = flow.included.count or 0
    found.append(
        Stage(
            "Included",
            included,
            reasons=[
                line
                for line in flow.excluded.lines + flow.included.lines
                if line.startswith(("excluded in ③ Screen", "plus "))
            ],
        )
    )
    for previous, stage in zip(found, found[1:], strict=False):
        stage.lost = max(previous.count - stage.count, 0)
        if stage.note:  # still to screen: not lost
            stage.lost = 0
    return found


def _width(count: int, first: int) -> float:
    share = count / first if first else 0
    return FUNNEL_W * max(share, MIN_SHARE)


def svg(found: list[Stage]) -> str:
    """The funnel of ``found`` as an SVG document (``""`` when empty)."""
    if not found:
        return ""
    first = max(found[0].count, 1)
    centre = FUNNEL_X + FUNNEL_W / 2
    height = len(found) * (BAND + GAP) + 8
    esc = html.escape
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'role="img" aria-label="PRISMA funnel" '
        'style="width:100%;max-width:780px;height:auto;'
        'font-family:system-ui,-apple-system,Segoe UI,sans-serif">',
    ]
    for i, stage in enumerate(found):
        top = 4 + i * (BAND + GAP)
        bottom = top + BAND
        w_top = _width(stage.count, first)
        nxt = found[i + 1].count if i + 1 < len(found) else stage.count * 0.85
        w_bot = _width(int(nxt), first)
        mid = (top + bottom) / 2
        # Smooth sides: a cubic curve from this band's width to the next one's.
        left = (
            f"M{centre - w_top / 2:.1f},{top} "
            f"C{centre - w_top / 2:.1f},{mid} {centre - w_bot / 2:.1f},{mid} "
            f"{centre - w_bot / 2:.1f},{bottom}"
        )
        right = (
            f"L{centre + w_bot / 2:.1f},{bottom} "
            f"C{centre + w_bot / 2:.1f},{mid} {centre + w_top / 2:.1f},{mid} "
            f"{centre + w_top / 2:.1f},{top} Z"
        )
        fill = FILLS[min(i, len(FILLS) - 1)]
        text = "#1f2328" if i < DARK_TEXT_UNTIL else "#ffffff"
        share = 100 * stage.count / first
        parts.append(
            f'<path d="{left} {right}" fill="{fill}">'
            f"<title>{esc(stage.label)}: {stage.count:,} ({share:.1f} %)</title></path>"
        )
        parts.append(
            f'<text x="{centre:.1f}" y="{mid + 5:.1f}" text-anchor="middle" '
            f'font-size="15" font-weight="700" fill="{text}">'
            f"{stage.count:,}</text>"
            # Stage name and share, on the left: readable however narrow.
            f'<text x="{LABEL_W}" y="{mid - 2:.1f}" text-anchor="end" '
            f'font-size="12.5" font-weight="600" fill="currentColor">'
            f"{esc(stage.label)}</text>"
            f'<text x="{LABEL_W}" y="{mid + 13:.1f}" text-anchor="end" '
            f'font-size="11" fill="currentColor" fill-opacity="0.7">'
            + (f"{share:.0f} % of identified" if i else "100 %")
            + "</text>"
        )
        # Notes on the right: what was lost on the way to this stage.
        x = FUNNEL_X + FUNNEL_W + 24
        lines = []
        if stage.lost:
            lines.append((f"−{stage.lost:,}", "#c0392b", 600))
            lines += [(reason, "currentColor", 400) for reason in stage.reasons[:2]]
            if len(stage.reasons) > 2:
                lines.append((f"+ {len(stage.reasons) - 2} more", "currentColor", 400))
        if stage.note:
            lines.append((stage.note, "#a15c00", 600))
        y = top + 16
        for content, colour, weight in lines[:4]:
            parts.append(
                f'<text x="{x}" y="{y}" font-size="11.5" fill="{colour}" '
                f'font-weight="{weight}">{esc(content[:60])}</text>'
            )
            y += 14
    parts.append("</svg>")
    return "".join(parts)
