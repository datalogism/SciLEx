"""PyInstaller entry script: start the SciLEx desktop app."""

import sys

from scilex.gui.app import run

if __name__ == "__main__":
    sys.exit(run())
