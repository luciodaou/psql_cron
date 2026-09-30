"""Database connection and query execution for psql_cron."""

import logging
import re
import pg8000.dbapi
from psql_cron.config import SyncConfig

logger = logging.getLogger("psql_cron.db")


def clean_whitespace(val):
    """Collapse any sequence of whitespace characters into a single space and strip."""
    if isinstance(val, str):
        return re.sub(r"\s+", " ", val).strip()
    return val


def fetch_table_data(config: SyncConfig) -> tuple[list[str], list[tuple]]:
    """
    Connects to the PostgreSQL database and retrieves all rows from the configured table/view.
    Returns (columns, cleaned_rows).
    """
    conn = None
    try:
        conn = pg8000.dbapi.connect(
            host=config.db_host,
            port=config.db_port,
            user=config.db_user,
            password=config.db_password,
            database=config.database,
        )
        cursor = conn.cursor()

        # Safely quote schema and table identifiers
        escaped_schema = config.schema.replace('"', '""')
        escaped_table = config.table.replace('"', '""')
        sql_query = f'SELECT * FROM "{escaped_schema}"."{escaped_table}";'

        logger.debug(f"[{config.syncname}] Executing query: {sql_query}")
        cursor.execute(sql_query)

        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        raw_rows = cursor.fetchall()

        cleaned_rows = [
            tuple(clean_whitespace(val) for val in row)
            for row in raw_rows
        ]
        return columns, cleaned_rows

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
