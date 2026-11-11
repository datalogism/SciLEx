"""Copy text to the system clipboard from Python.

The browser Clipboard API needs a user gesture that a NiceGUI round trip does
not keep, and pywebview does not always allow it, so the app calls the
operating system's own clipboard tool instead (the server runs on the user's
machine, also in ``--browser`` mode).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def _clipboard_command() -> tuple[list[str], str] | None:
    """Command that reads the clipboard text on stdin, and the encoding it expects."""
    if sys.platform == "darwin":
        return ["pbcopy"], "utf-8"
    if sys.platform == "win32":
        return ["clip"], "utf-16"  # with a BOM, clip reads the text as Unicode
    for command in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        if shutil.which(command[0]):
            return command, "utf-8"
    return None


def copy_text(text: str) -> bool:
    """Put ``text`` on the clipboard; False if no clipboard tool worked."""
    found = _clipboard_command()
    if found is None:
        return False
    command, encoding = found
    try:
        # pbcopy decodes stdin with the locale, which a bundled app may not set.
        environment = {**os.environ, "LANG": os.environ.get("LANG") or "en_US.UTF-8"}
        subprocess.run(
            command, input=text.encode(encoding), env=environment, check=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not copy to the clipboard with %s: %s", command[0], error)
        return False
    return True
