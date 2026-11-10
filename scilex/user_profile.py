"""The SciLEx user: an ORCID iD is required to use the app and to build knowledge graphs.

Stored in ``user.yml`` next to the review registry, in the per-OS user
configuration directory. The ORCID iD identifies who collected, screened and
annotated: it is the creator of the knowledge graphs SciLEx exports.

The iD is checked locally (format and ISO 7064 11-2 check digit). Looking it up
on the ORCID public API (:func:`lookup_name`) is optional and only shows the
name registered for it; proving the user owns the iD needs ORCID sign-in
(OAuth), which needs a client registered with ORCID (``ORCID_CLIENT_ID``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

PROFILE_FILENAME = "user.yml"
ORCID_PATTERN = re.compile(r"^(\d{4})-?(\d{4})-?(\d{4})-?(\d{3}[\dX])$")
ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")
ORCID_PUBLIC_API = "https://pub.orcid.org/v3.0"


class InvalidOrcidError(ValueError):
    """The text is not a valid ORCID iD."""


def default_profile_path() -> Path:
    """Return ``user.yml`` in the per-OS user configuration directory.

    Same folder as the desktop app's review registry; without platformdirs (the
    command line without the ``gui`` extra) ``~/.config/scilex`` is used.
    """
    try:
        from platformdirs import user_config_path
    except ImportError:
        return Path.home() / ".config" / "scilex" / PROFILE_FILENAME
    return user_config_path("scilex") / PROFILE_FILENAME


def check_digit(base_digits: str) -> str:
    """ISO 7064 11-2 check character of the first 15 digits of an ORCID iD."""
    total = 0
    for digit in base_digits:
        total = (total + int(digit)) * 2
    result = (12 - total % 11) % 11
    return "X" if result == 10 else str(result)


def normalize_orcid(text: str) -> str:
    """Return the canonical ``0000-0000-0000-0000`` form of an ORCID iD.

    Accepts the bare iD, with or without dashes, or its ``https://orcid.org/`` URL.

    Raises:
        InvalidOrcidError: If the format or the check digit is wrong.
    """
    value = (text or "").strip()
    for prefix in ORCID_URL_PREFIXES:
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
            break
    match = ORCID_PATTERN.match(value.upper())
    if not match:
        raise InvalidOrcidError(
            "An ORCID iD has 16 characters, like 0000-0002-1825-0097."
        )
    digits = "".join(match.groups())
    if check_digit(digits[:15]) != digits[15]:
        raise InvalidOrcidError(
            "This ORCID iD has a wrong check digit: check for a typo."
        )
    return "-".join(match.groups())


def orcid_uri(orcid: str) -> str:
    """Return the IRI of an ORCID iD (``https://orcid.org/...``)."""
    return f"https://orcid.org/{normalize_orcid(orcid)}"


def lookup_name(orcid: str, timeout: float = 10) -> str | None:
    """Return the public name registered for ``orcid`` on orcid.org (None: unknown).

    Raises:
        ConnectionError: If orcid.org cannot be reached.
    """
    import requests

    url = f"{ORCID_PUBLIC_API}/{normalize_orcid(orcid)}/person"
    try:
        response = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except requests.RequestException as exc:
        raise ConnectionError(f"orcid.org cannot be reached ({exc})") from exc
    if response.status_code == 404:
        return None
    if not response.ok:
        raise ConnectionError(f"orcid.org answered {response.status_code}")
    name = (response.json() or {}).get("name") or {}
    given = ((name.get("given-names") or {}).get("value") or "").strip()
    family = ((name.get("family-name") or {}).get("value") or "").strip()
    credit = ((name.get("credit-name") or {}).get("value") or "").strip()
    return credit or " ".join(part for part in (given, family) if part) or ""


@dataclass
class UserProfile:
    """The person using SciLEx."""

    path: Path
    orcid: str = ""
    name: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> UserProfile:
        """Read the profile (an empty one when the file is missing or unreadable)."""
        path = Path(path) if path is not None else default_profile_path()
        profile = cls(path=path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return profile
        if isinstance(data, dict):
            try:
                profile.orcid = normalize_orcid(str(data.get("orcid") or ""))
            except InvalidOrcidError:
                profile.orcid = ""
            profile.name = str(data.get("name") or "")
        return profile

    @property
    def is_complete(self) -> bool:
        """True when the user may use the app (a valid ORCID iD is set)."""
        return bool(self.orcid)

    @property
    def orcid_uri(self) -> str:
        """IRI of the user's ORCID iD ('' when none)."""
        return f"https://orcid.org/{self.orcid}" if self.orcid else ""

    def set(self, orcid: str, name: str = "") -> None:
        """Validate and save the user's ORCID iD (and name).

        Raises:
            InvalidOrcidError: If ``orcid`` is not a valid ORCID iD.
        """
        self.orcid = normalize_orcid(orcid)
        self.name = name.strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump({"orcid": self.orcid, "name": self.name}, allow_unicode=True),
            encoding="utf-8",
        )
