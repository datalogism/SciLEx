project = "SciLEx"
copyright = "2026, Celian Ringwald, Benjamin Navet, Yousouf Taghzouti, Fabien Gandon"
author = "Celian Ringwald, Benjamin Navet, Yousouf Taghzouti, Fabien Gandon"
release = "1.0.0"

extensions = [
    "myst_parser",
]

myst_heading_anchors = 3

myst_enable_extensions = [
    "colon_fence",
    "strikethrough",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "_tools", "wip", "superpowers", "decisions"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_logo = "../img/projectLogoScilex.png"
html_favicon = "../scilex/gui/assets/icon.png"

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
