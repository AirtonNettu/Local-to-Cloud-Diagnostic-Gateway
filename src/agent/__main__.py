"""Entry point for ``python -m agent``."""

from __future__ import annotations

import sys

from agent.main import main

if __name__ == "__main__":
    sys.exit(main())
