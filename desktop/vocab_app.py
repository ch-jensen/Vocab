"""Launcher for the packaged desktop app (the script PyInstaller freezes)."""

import sys

from vocab.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
