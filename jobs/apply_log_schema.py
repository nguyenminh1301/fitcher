"""Kept for existing scripts: ``python -m jobs.apply_log_schema`` runs ``python -m jobs.migrate``."""

import sys

from jobs.migrate import main

if __name__ == "__main__":
    sys.exit(main())
