"""Annotation guideline: the Markdown manual that goes with the grid.

Same layout as SciLEx Annotator's guideline (``scilex_annotator.guideline``):
a ``## <DIMENSION>`` section whose heading is a dimension of the grid is the
guidance for that dimension only (sent with that question to an LLM, shown
next to it to a person); everything else is the general part.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

GUIDELINE_FILENAME = "annotation_guideline.md"
_HEADING = re.compile(r"## +(\S+)\s*(?:\n|$)")


@dataclass
class Guideline:
    general: str = ""
    sections: dict[str, str] = field(default_factory=dict)  # DIMENSION -> text
    other_headings: list[str] = field(
        default_factory=list
    )  # ## headings, not dimensions

    def for_dimension(self, dimension: str) -> str:
        return self.sections.get(dimension.strip().upper(), "")


def parse_guideline(text: str, dimensions: Iterable[str]) -> Guideline:
    """Split ``text`` into the general part and one section per known dimension."""
    known = {d.strip().upper() for d in dimensions}
    general: list[str] = []
    sections: dict[str, str] = {}
    others: list[str] = []
    for part in re.split(r"(?m)^(?=## )", text or ""):
        match = _HEADING.match(part)
        name = match.group(1).upper() if match else ""
        if name in known:
            sections[name] = part.strip().removesuffix("---").strip()
        else:
            if match:
                others.append(match.group(1))
            general.append(part)
    return Guideline("".join(general).strip(), sections, others)


@dataclass(frozen=True)
class Coverage:
    """Which grid dimensions the guideline explains."""

    covered: list[str]
    missing: list[str]  # dimensions with no ## section
    has_general: bool


def coverage(guideline: Guideline, dimensions: Iterable[str]) -> Coverage:
    dims = [d.strip().upper() for d in dimensions]
    return Coverage(
        covered=[d for d in dims if d in guideline.sections],
        missing=[d for d in dims if d not in guideline.sections],
        has_general=bool(guideline.general.strip()),
    )
