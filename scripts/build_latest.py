#!/usr/bin/env python3
"""Compatibility wrapper for updating the stable NIGHT SIGNAL URL.

The stable URL is site/index.html. It now shows the latest issue directly and
also keeps links to recent dated issues. The actual work lives in sync_site.py.
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("sync_site.py")), run_name="__main__")
