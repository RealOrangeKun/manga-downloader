#!/usr/bin/env python3
"""Manga downloader: opens the GUI."""

if __name__ == "__main__":
    # Imported here so the worker processes that build files don't load Qt.
    from gui import main

    main()
