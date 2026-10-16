#!/usr/bin/env python3
"""Nyanga, the manga downloader: opens the GUI."""

import multiprocessing

if __name__ == "__main__":
    # In the exe, worker processes start the exe itself; this hands them their job instead of a new window.
    multiprocessing.freeze_support()
    # Imported here so the worker processes that build files don't load Qt.
    from gui import main

    main()
