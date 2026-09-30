"""Data export handlers for JSON and CSV file formats."""

import csv
import datetime
import decimal
import json
import logging
from pathlib import Path
from uuid import UUID

from psql_cron.config import SyncConfig

logger = logging.getLogger("psql_cron.export")


def json_serializer(obj):
    """Custom JSON serializer for complex Python types."""
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    elif isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    elif isinstance(obj, set):
        return list(obj)
    return str(obj)


def export_json(config: SyncConfig, columns: list[str], rows: list[tuple]) -> bool:
    """Exports rows as JSON records, atomically overwriting previous file."""
    json_file = config.output_path / f"{config.syncname}.json"
    tmp_file = config.output_path / f".{config.syncname}.json.tmp"
    try:
        records = [dict(zip(columns, row)) for row in rows]
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(records, f, default=json_serializer, indent=2, ensure_ascii=False)
        tmp_file.replace(json_file)
        size_kb = json_file.stat().st_size / 1024
        logger.info(f"[{config.syncname}] JSON saved to {json_file} ({size_kb:.2f} KB, {len(rows)} records)")
        return True
    except Exception as e:
        logger.error(f"[{config.syncname}] Failed to export JSON: {e}")
        if tmp_file.exists():
            tmp_file.unlink(missing_ok=True)
        return False


def export_csv(config: SyncConfig, columns: list[str], rows: list[tuple]) -> bool:
    """Exports rows as CSV with Excel-compatible UTF-8 BOM, atomically overwriting previous file."""
    csv_file = config.output_path / f"{config.syncname}.csv"
    tmp_file = config.output_path / f".{config.syncname}.csv.tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8", newline="") as f:
            f.write("\ufeff")  # BOM for Excel
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(columns)
            writer.writerows(rows)
        tmp_file.replace(csv_file)
        size_kb = csv_file.stat().st_size / 1024
        logger.info(f"[{config.syncname}] CSV saved to {csv_file} ({size_kb:.2f} KB, {len(rows)} records)")
        return True
    except Exception as e:
        logger.error(f"[{config.syncname}] Failed to export CSV: {e}")
        if tmp_file.exists():
            tmp_file.unlink(missing_ok=True)
        return False


def export_sync(config: SyncConfig, columns: list[str], rows: list[tuple]) -> bool:
    """Executes all enabled exports for the given configuration."""
    config.output_path.mkdir(parents=True, exist_ok=True)
    all_ok = True

    if config.json:
        if not export_json(config, columns, rows):
            all_ok = False

    if config.csv:
        if not export_csv(config, columns, rows):
            all_ok = False

    return all_ok
