#!/usr/bin/env python3
"""Cross-platform console-free source launcher for the Tkinter interface."""

from pathlib import Path

from app.subtitle_gui import launch_portable_wrapper


if __name__ == "__main__":
    raise SystemExit(launch_portable_wrapper(Path(__file__).resolve()))
