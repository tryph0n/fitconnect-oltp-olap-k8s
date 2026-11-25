"""Read the replication slot in a loop and append the changes to the ClickHouse journals.

Each run reads the changes committed up to now, loads them, then confirms them on the slot at
the start of the next run (dlt resource state). A run stopped in the middle is read again: a
change can reach the journal twice, never zero times.
"""

import logging
import signal
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import dlt
from dlt.extract.items import TableNameMeta
from dlt.sources.credentials import ConnectionStringCredentials
from sqlalchemy import Engine

from fitconnect.cdc_setup import PUB_NAME, SLOT_NAME, SlotError, check_slot
from fitconnect.config import Settings, configure_logging, get_settings
from fitconnect.seed import get_engine
from fitconnect.warehouse import cdc_pipeline
from pg_replication.helpers import stream_changes
from pg_replication.schema_types import DELETED_TS, LSN

logger = logging.getLogger(__name__)

PIPELINE_NAME = "fitconnect_cdc"


def journal_entry(row: dict, read_at: datetime) -> dict:
    """Turns a change row of the source into a journal row.

    The source gives inserts without the delete column, updates with it set to None and
    deletes with it set to the commit time.
    """
    entry = {k: v for k, v in row.items() if k not in (LSN, DELETED_TS)}
    if DELETED_TS not in row:
        entry["_op"] = "I"
    elif row[DELETED_TS] is None:
        entry["_op"] = "U"
    else:
        entry["_op"] = "D"
    entry["_lsn"] = row[LSN]
    entry["_ts"] = read_at
    return entry


@dlt.resource(name="changes", write_disposition="append", standalone=True)
def changes(settings: Settings) -> Iterator:
    state = dlt.current.resource_state()
    for batch in stream_changes(
        credentials=ConnectionStringCredentials(settings.pg_url("postgresql")),
        slot_name=SLOT_NAME,
        pub_name=PUB_NAME,
        start_lsn=state.get("last_commit_lsn", 0),
        hard_delete=False,
    ):
        read_at = datetime.now(UTC)
        for item in batch.items:
            # Skip the table hints of the source: they would make each table a merge table.
            if isinstance(item.meta, TableNameMeta) and item.data:
                rows = [journal_entry(row, read_at) for row in item.data]
                yield dlt.mark.with_table_name(rows, item.meta.table_name)
        state["last_commit_lsn"] = batch.last_commit_lsn


def run_once(
    settings: Settings, pipeline: dlt.Pipeline, engine: Engine
) -> dict[str, int]:
    """Loads the changes committed up to now; returns the rows written per journal table."""
    check_slot(engine)
    pipeline.run(changes(settings))
    normalized = pipeline.last_trace.last_normalize_info
    counts = normalized.row_counts if normalized else {}
    return {table: n for table, n in counts.items() if not table.startswith("_dlt")}


def run_forever(
    settings: Settings, stop: threading.Event, pipelines_dir: str | None = None
) -> int:
    pipeline = cdc_pipeline(PIPELINE_NAME, settings, pipelines_dir)
    engine = get_engine(settings)
    heartbeat = Path(settings.cdc_heartbeat_file)
    while not stop.is_set():
        started = time.monotonic()
        try:
            rows = run_once(settings, pipeline, engine)
        except SlotError as exc:
            logger.error("%s", exc)
            return 1
        heartbeat.touch()
        elapsed = time.monotonic() - started
        logger.info("Run done in %.1f s, journal rows: %s", elapsed, rows or "none")
        stop.wait(max(0.0, settings.cdc_poll_seconds - elapsed))
    logger.info("Stopped")
    return 0


def main() -> None:
    configure_logging()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    sys.exit(run_forever(get_settings(), stop))


if __name__ == "__main__":
    main()
