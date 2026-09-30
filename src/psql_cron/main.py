"""Command-line interface and main entrypoint for psql_cron."""

import argparse
import logging
import os
import sys
from pathlib import Path

from psql_cron.config import (
    DEFAULT_CRON_SCHEDULE,
    DEFAULT_SYNCS_DIR,
    RUN_ON_STARTUP,
    RUN_ONCE,
)
from psql_cron.scheduler import run_sync_cycle, start_scheduler


def setup_logging():
    """Configures application-wide logging."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main CLI entry point."""
    setup_logging()
    logger = logging.getLogger("psql_cron")

    parser = argparse.ArgumentParser(
        description="psql_cron - PostgreSQL Automated Table Synchronizer"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        default=RUN_ONCE,
        help="Run synchronization once and exit immediately",
    )
    parser.add_argument(
        "--sync",
        type=str,
        default=None,
        help="Execute only a specific sync by name (stem of .ini file)",
    )
    parser.add_argument(
        "--syncs-dir",
        type=str,
        default=DEFAULT_SYNCS_DIR,
        help="Directory containing *.ini synchronization files",
    )
    parser.add_argument(
        "--cron",
        type=str,
        default=DEFAULT_CRON_SCHEDULE,
        help="Cron expression for scheduling daemon execution",
    )

    args = parser.parse_args()
    syncs_dir = Path(args.syncs_dir)

    if args.once:
        logger.info("Executing in one-shot mode.")
        success = run_sync_cycle(syncs_dir, target_sync=args.sync)
        sys.exit(0 if success else 1)
    else:
        start_scheduler(syncs_dir, args.cron, run_on_startup=RUN_ON_STARTUP)


if __name__ == "__main__":
    main()
