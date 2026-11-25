"""Initial snapshot: copy each PostgreSQL table into its ClickHouse journal.

Rows get `_op = 'I'` and `_lsn = 0`, so any change from the slot (`_lsn > 0`) wins over them.
A table whose journal already has snapshot rows is skipped. Nothing is replaced or dropped.
"""

import logging
import sys
from datetime import UTC, datetime

from dlt.common.pipeline import LoadInfo
from dlt.sources.credentials import ConnectionStringCredentials
from dlt.sources.sql_database import sql_database

from fitconnect.cdc_setup import SlotError, check_slot
from fitconnect.config import Settings, configure_logging, get_settings
from fitconnect.models import TABLES
from fitconnect.seed import get_engine
from fitconnect.warehouse import cdc_pipeline, ensure_schema, get_client, has_snapshot

logger = logging.getLogger(__name__)

PIPELINE_NAME = "fitconnect_snapshot"


def snapshot_entry(row: dict, read_at: datetime) -> dict:
    return {**row, "_op": "I", "_lsn": 0, "_ts": read_at}


def run_snapshot(
    settings: Settings, pipelines_dir: str | None = None
) -> LoadInfo | None:
    # The slot must exist first, or changes made during the snapshot are lost.
    check_slot(get_engine(settings))
    client = get_client(settings)
    ensure_schema(client, settings.ch_database)
    tables = [t for t in TABLES if not has_snapshot(client, settings.ch_database, t)]
    if not tables:
        logger.info("All tables already have a snapshot, nothing to do")
        return None

    source = sql_database(
        credentials=ConnectionStringCredentials(settings.pg_url()), table_names=tables
    )
    read_at = datetime.now(UTC)
    for resource in source.resources.values():
        resource.add_map(lambda row: snapshot_entry(row, read_at))
    info = cdc_pipeline(PIPELINE_NAME, settings, pipelines_dir).run(
        source, write_disposition="append"
    )
    logger.info("Snapshot of %s loaded: %s", ", ".join(tables), info)
    return info


def main() -> None:
    configure_logging()
    try:
        run_snapshot(get_settings())
    except SlotError as exc:
        logger.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
