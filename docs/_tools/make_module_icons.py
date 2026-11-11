"""Draw the module and sub-module icons of the documentation from the app icon.

Every icon reuses the flint emblem of the SciLEx logo (the silex stone and its
"S", ``scilex/gui/assets/logo.png``):

- a **module banner** (``docs/_static/modules/<key>.png``): the emblem, the
  step number of the desktop app in a black disc, and the module name in the
  heavy lettering of the logo;
- a **sub-module badge** (``docs/_static/modules/sub/<module>-<key>.png``): a
  smaller, lighter emblem with the sub-module name;
- the **module map** (``docs/_static/modules/map.png``): every module as a
  tile, in the order of the review workflow.

Run it again after renaming or adding a module::

    python docs/_tools/make_module_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO = ROOT / "scilex" / "gui" / "assets" / "logo.png"
OUT = ROOT / "docs" / "_static" / "modules"
EMBLEM_WIDTH = 110  # the stone and its "S" end here in logo.png

# key -> (step number or "", title, [(sub key, sub title), ...])
MODULES: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "workspace": (
        "",
        "Workspace",
        [
            ("reviews", "Reviews"),
            ("profile", "ORCID profile"),
            ("keys", "API keys"),
            ("jobs", "Running jobs"),
        ],
    ),
    "overview": (
        "",
        "Overview",
        [
            ("prisma", "PRISMA flow"),
            ("review-card", "Review card"),
            ("history", "History"),
            ("checks", "Things to check"),
        ],
    ),
    "explore": (
        "",
        "Explore",
        [
            ("filters", "Filters"),
            ("breakdown", "Break down by"),
            ("notice", "Paper notice"),
            ("enrich-one", "Enrich one paper"),
        ],
    ),
    "configure": (
        "1",
        "Configure",
        [
            ("search", "Search"),
            ("filters", "Filters"),
            ("citations", "Citations"),
            ("vpn", "VPN rotation"),
        ],
    ),
    "collect": (
        "2",
        "Collect",
        [
            ("collection", "Collection"),
            ("aggregation", "Aggregation"),
            ("filtering", "Filtering pipeline"),
        ],
    ),
    "criteria": (
        "",
        "Criteria",
        [
            ("test", "Test"),
            ("apply", "Apply"),
            ("exceptions", "Exceptions"),
        ],
    ),
    "screen": (
        "3",
        "Screen",
        [
            ("decisions", "Decisions"),
            ("filters", "Filters"),
        ],
    ),
    "annotate": (
        "4",
        "Annotate",
        [
            ("grid", "Annotation grid"),
            ("annotators", "Annotators"),
            ("workflow-tags", "Workflow tags"),
            ("agreement", "Agreement study"),
            ("report", "Annotation report"),
        ],
    ),
    "extend": (
        "5",
        "Extend",
        [
            ("new-collect", "New collect"),
            ("snowball", "Snowballing"),
            ("keywords", "Keyword suggestions"),
            ("bibtex", "BibTeX import"),
            ("zotero", "Zotero"),
        ],
    ),
    "consolidate": (
        "",
        "Consolidate",
        [
            ("duplicates", "Duplicates"),
            ("filters", "Filters"),
            ("subcorpora", "Sub-corpora"),
        ],
    ),
    "enrich": (
        "6",
        "Enrich",
        [
            ("citations", "Citations"),
            ("pwc", "Papers with Code"),
            ("crossref", "Crossref"),
            ("lpwc", "Linked Papers With Code"),
            ("orkg", "ORKG"),
            ("search-keywords", "Search keywords"),
            ("paper-types", "Paper types"),
            ("metrics", "Citation metrics"),
        ],
    ),
    "analyses": (
        "7",
        "Analyses",
        [
            ("charts", "Charts"),
            ("graph", "Graph"),
            ("accessibility", "Accessibility"),
            ("annotations", "Annotations"),
            ("summaries", "Summaries"),
        ],
    ),
    "export": (
        "8",
        "Export",
        [
            ("bibtex", "BibTeX"),
            ("csv", "CSV"),
            ("turtle", "RDF/Turtle"),
            ("zotero", "Zotero push"),
            ("kg", "Knowledge graph"),
        ],
    ),
    "zotero": (
        "",
        "Zotero",
        [
            ("group", "Zotero group"),
            ("members", "Members"),
            ("sync", "Sync"),
            ("tags", "Tag conventions"),
        ],
    ),
}

HEAVY_FONTS = ("ariblk.ttf", "Arial Black.ttf", "DejaVuSans-Bold.ttf")
BOLD_FONTS = ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf")
FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts/truetype/dejavu"),
)


def _font(names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for directory in FONT_DIRS:
        for name in names:
            path = directory / name
            if path.is_file():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def emblem(height: int, lighten: float = 0.0) -> Image.Image:
    """The flint stone and its "S", cut out of the logo, at ``height`` pixels."""
    logo = Image.open(LOGO).convert("RGBA")
    stone = logo.crop((0, 0, EMBLEM_WIDTH, logo.height))
    stone = stone.crop(stone.getbbox())
    width = round(stone.width * height / stone.height)
    stone = stone.resize((width, height), Image.LANCZOS)
    if lighten:
        alpha = stone.getchannel("A")
        stone = ImageEnhance.Brightness(stone.convert("RGB")).enhance(1 + lighten)
        stone = stone.convert("RGBA")
        stone.putalpha(alpha.point(lambda a: int(a * (1 - lighten / 2))))
    return stone


def _number_disc(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, text: str):
    draw.ellipse((x, y, x + size, y + size), fill="black", outline="white", width=3)
    font = _font(HEAVY_FONTS, int(size * 0.62))
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (x + (size - (box[2] - box[0])) / 2 - box[0], y + (size - (box[3] - box[1])) / 2 - box[1]),
        text,
        font=font,
        fill="white",
    )


def banner(number: str, title: str, height: int = 120) -> Image.Image:
    """Emblem + number disc + module name, like the logo."""
    stone = emblem(height)
    font = _font(HEAVY_FONTS, int(height * 0.48))
    text_box = font.getbbox(title)
    gap = int(height * 0.15)
    width = stone.width + gap + (text_box[2] - text_box[0]) + 8
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.alpha_composite(stone, (0, 0))
    draw = ImageDraw.Draw(image)
    if number:
        disc = int(height * 0.42)
        _number_disc(draw, stone.width - disc + 6, height - disc - 2, disc, number)
    draw.text(
        (stone.width + gap - text_box[0], (height - (text_box[3] - text_box[1])) / 2 - text_box[1]),
        title,
        font=font,
        fill="black",
    )
    return image


def badge(title: str, height: int = 44) -> Image.Image:
    """Small, lighter emblem + sub-module name."""
    stone = emblem(height, lighten=0.9)
    font = _font(BOLD_FONTS, int(height * 0.48))
    text_box = font.getbbox(title)
    gap = int(height * 0.25)
    width = stone.width + gap + (text_box[2] - text_box[0]) + 6
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.alpha_composite(stone, (0, 0))
    ImageDraw.Draw(image).text(
        (stone.width + gap - text_box[0], (height - (text_box[3] - text_box[1])) / 2 - text_box[1]),
        title,
        font=font,
        fill=(40, 40, 40, 255),
    )
    return image


def module_map(columns: int = 5) -> Image.Image:
    """Every module as a tile: emblem, number and name, workflow order."""
    tile_w, tile_h, pad = 300, 210, 24
    rows = -(-len(MODULES) // columns)
    image = Image.new(
        "RGBA", (columns * tile_w + pad * 2, rows * tile_h + pad * 2), (255, 255, 255, 0)
    )
    draw = ImageDraw.Draw(image)
    title_font = _font(HEAVY_FONTS, 30)
    sub_font = _font(BOLD_FONTS, 15)
    for i, (number, title, subs) in enumerate(MODULES.values()):
        x = pad + (i % columns) * tile_w
        y = pad + (i // columns) * tile_h
        draw.rounded_rectangle(
            (x + 6, y + 6, x + tile_w - 6, y + tile_h - 6),
            radius=18,
            fill=(255, 255, 255, 255),
            outline=(30, 30, 30, 255),
            width=3,
        )
        stone = emblem(86)
        image.alpha_composite(stone, (x + 22, y + 20))
        if number:
            _number_disc(draw, x + 22 + stone.width - 30, y + 20 + 86 - 38, 38, number)
        room = tile_w - (22 + stone.width + 14) - 20
        font = title_font
        while draw.textlength(title, font=font) > room and font.size > 16:
            font = _font(HEAVY_FONTS, font.size - 1)
        draw.text((x + 22 + stone.width + 14, y + 44 + (30 - font.size) // 2), title, font=font, fill="black")
        names = ", ".join(sub for _, sub in subs)
        line, lines = "", []
        for word in names.split(" "):
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=sub_font) > tile_w - 50:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        for n, text in enumerate(lines[:4]):
            draw.text((x + 24, y + 118 + n * 20), text, font=sub_font, fill=(70, 70, 70, 255))
    return image


def main() -> int:
    (OUT / "sub").mkdir(parents=True, exist_ok=True)
    for key, (number, title, subs) in MODULES.items():
        banner(number, title).save(OUT / f"{key}.png", optimize=True)
        for sub_key, sub_title in subs:
            badge(sub_title).save(OUT / "sub" / f"{key}-{sub_key}.png", optimize=True)
    module_map().save(OUT / "map.png", optimize=True)
    emblem(256).save(OUT / "emblem.png", optimize=True)
    print(f"Icons written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
