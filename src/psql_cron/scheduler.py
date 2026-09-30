"""Scheduler loop and multi-cron per-sync job execution management."""

import datetime
import logging
import signal
import time
from pathlib import Path

from croniter import croniter
from psql_cron.config import SyncConfig, find_all_sync_configs
from psql_cron.db import fetch_table_data
from psql_cron.export import export_sync

logger = logging.getLogger("psql_cron.scheduler")

SHUTDOWN = False


def _signal_handler(signum, frame):
    global SHUTDOWN
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    SHUTDOWN = True


def execute_single_sync(config: SyncConfig) -> bool:
    """Executes a single synchronization configuration."""
    logger.info(
        f"[{config.syncname}] Starting sync: {config.database}.{config.schema}.{config.table} -> {config.output_path}"
    )
    try:
        columns, rows = fetch_table_data(config)
        logger.info(f"[{config.syncname}] Fetched {len(rows)} rows from {config.schema}.{config.table}")
        return export_sync(config, columns, rows)
    except Exception as e:
        logger.error(f"[{config.syncname}] Sync failed: {e}")
        return False


def run_sync_cycle(syncs_dir: Path, target_sync: str | None = None) -> bool:
    """Discovers and runs all configured synchronizations immediately (one-shot)."""
    configs = find_all_sync_configs(syncs_dir, target_sync)
    if not configs:
        logger.warning(f"No valid synchronization configurations found in {syncs_dir}")
        return True

    all_ok = True
    for cfg in configs:
        if SHUTDOWN:
            break
        if not execute_single_sync(cfg):
            all_ok = False

    logger.info(f"Completed sync cycle: {len(configs)} configuration(s) processed.")
    return all_ok


def start_scheduler(syncs_dir: Path, default_cron: str | None = None, run_on_startup: bool = True):
    """
    Runs each synchronization according to all of its cron schedules defined inside its .ini file.
    Supports multiple cron schedules per sync (e.g. cron.1, cron.2).
    Continuously monitors the syncs directory for new or modified configurations.
    """
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(f"Starting multi-schedule cron engine monitoring directory: {syncs_dir}")

    # Track per-sync state:
    # {syncname: {"config": cfg, "cron_schedules": tuple, "cron_entries": list, "next_run": datetime}}
    sync_states: dict[str, dict] = {}

    if run_on_startup and not SHUTDOWN:
        logger.info("Executing initial startup sync for all configured syncs...")
        run_sync_cycle(syncs_dir)

    last_logged_target: str | None = None

    while not SHUTDOWN:
        now = datetime.datetime.now()
        current_configs = {cfg.syncname: cfg for cfg in find_all_sync_configs(syncs_dir)}

        # 1. Remove deleted syncs
        removed = set(sync_states.keys()) - set(current_configs.keys())
        for name in removed:
            logger.info(f"[{name}] Configuration removed. Descheduling.")
            del sync_states[name]

        # 2. Add or update sync schedules
        for name, cfg in current_configs.items():
            schedules_tuple = tuple(cfg.cron_schedules)

            # If new sync or cron schedules changed, recompute cron entries
            if name not in sync_states or sync_states[name]["cron_schedules"] != schedules_tuple:
                valid_entries = []
                for expr in cfg.cron_schedules:
                    if not croniter.is_valid(expr):
                        logger.error(f"[{name}] Invalid cron expression: '{expr}'. Skipping this rule.")
                        continue
                    try:
                        c_iter = croniter(expr, now)
                        nxt = c_iter.get_next(datetime.datetime)
                        valid_entries.append({"expr": expr, "iter": c_iter, "next_run": nxt})
                    except Exception as e:
                        logger.error(f"[{name}] Failed to initialize cron '{expr}': {e}")

                if not valid_entries:
                    logger.error(f"[{name}] No valid cron schedules found. Sync will be inactive.")
                    if name in sync_states:
                        del sync_states[name]
                    continue

                earliest_for_sync = min(e["next_run"] for e in valid_entries)
                sync_states[name] = {
                    "config": cfg,
                    "cron_schedules": schedules_tuple,
                    "cron_entries": valid_entries,
                    "next_run": earliest_for_sync,
                }
                cron_desc = ", ".join(f"'{e['expr']}'" for e in valid_entries)
                logger.info(
                    f"[{name}] Active schedule(s): [{cron_desc}]. Next run: {earliest_for_sync.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                # Update config (e.g. output_path, table or db credentials)
                sync_states[name]["config"] = cfg

        if not sync_states:
            time.sleep(3.0)
            continue

        # 3. Determine earliest execution across all active syncs
        earliest_time = min(state["next_run"] for state in sync_states.values())
        run_now = datetime.datetime.now()

        # Log next upcoming sync when target changes
        upcoming_labels = [
            f"[{name}] ({state['next_run'].strftime('%H:%M:%S')})"
            for name, state in sync_states.items()
            if abs((state["next_run"] - earliest_time).total_seconds()) < 1.0
        ]
        log_key = f"{earliest_time.strftime('%Y-%m-%d %H:%M:%S')}_{','.join(upcoming_labels)}"
        if log_key != last_logged_target:
            delay_sec = max(0.0, (earliest_time - run_now).total_seconds())
            logger.info(
                f"Next scheduled sync: {', '.join(upcoming_labels)} at {earliest_time.strftime('%Y-%m-%d %H:%M:%S')} (in {delay_sec:.1f}s)"
            )
            last_logged_target = log_key

        # 4. Check if any sync is due
        if run_now >= earliest_time:
            for name, state in list(sync_states.items()):
                if state["next_run"] <= run_now:
                    # Find which cron expression triggered
                    triggered_exprs = [
                        e["expr"] for e in state["cron_entries"] if e["next_run"] <= run_now
                    ]
                    expr_str = ", ".join(f"'{e}'" for e in triggered_exprs)
                    logger.info(f"[{name}] Triggering scheduled execution (matched: {expr_str})...")
                    execute_single_sync(state["config"])

                    # Advance all triggered cron entries
                    for entry in state["cron_entries"]:
                        if entry["next_run"] <= run_now:
                            try:
                                entry["next_run"] = entry["iter"].get_next(datetime.datetime)
                            except Exception as e:
                                logger.error(f"[{name}] Failed to calculate next run for '{entry['expr']}': {e}")

                    # Recalculate next run for this sync
                    state["next_run"] = min(e["next_run"] for e in state["cron_entries"])
                    logger.info(
                        f"[{name}] Next run scheduled for: {state['next_run'].strftime('%Y-%m-%d %H:%M:%S')}"
                    )
            # Reset log tracker so next loop logs updated target
            last_logged_target = None
            continue

        # 5. Short sleep (responsive to file changes & signals)
        time.sleep(1.0)

    logger.info("Scheduler stopped cleanly.")
