"""Named presets layered between code defaults and the user's ``scilex.yml``."""

import copy

PRESETS: dict[str, dict] = {
    "literature_review": {
        "filters": {
            "require": ["abstract", "year"],
            "citations": True,
            "abstract_quality": 60,
        },
    },
    "bibliometrics": {
        "filters": {
            "require": [],
            "citations": False,
            "abstract_quality": None,
        },
        "ranking": {"max_papers": None},
    },
}


def get_preset(name: str) -> dict:
    """Return a deep copy of the preset ``name``.

    Args:
        name: Preset name, a key of ``PRESETS``.

    Returns:
        The preset as a raw settings dictionary.

    Raises:
        KeyError: If the preset does not exist.
    """
    return copy.deepcopy(PRESETS[name])
