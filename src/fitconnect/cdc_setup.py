"""Prepare the CDC: publication, replication slot and ClickHouse tables.

Run it before the snapshot (`fc-pipeline`), so the slot keeps every change made after it.
`--reset` drops the slot and empties the ClickHouse CDC tables first: use it when the slot is
lost, then run `fc-pipeline` again.
"""

import argparse
import logging
import sys

from sqlalchemy import Connection, Engine, text

from fitconnect.config import Settings, configure_logging, get_settings
from fitconnect.models import TABLES
from fitconnect.seed import get_engine
from fitconnect.warehouse import ensure_schema, get_client, truncate_cdc_tables

logger = logging.getLogger(__name__)

SLOT_NAME = "fitconnect_slot"
PUB_NAME = "fitconnect_pub"


class SlotError(RuntimeError):
    """The replication slot cannot be used."""


def _slot(conn: Connection) -> tuple[str | None, bool] | None:
    row = conn.execute(
        text(
            "SELECT wal_status, active FROM pg_replication_slots WHERE slot_name = :slot"
        ),
        {"slot": SLOT_NAME},
    ).first()
    return None if row is None else (row.wal_status, row.active)


def check_slot(engine: Engine) -> None:
    """Raises `SlotError` when the slot is missing or lost (WAL removed)."""
    with engine.connect() as conn:
        slot = _slot(conn)
    if slot is None:
        raise SlotError(f"Replication slot {SLOT_NAME} not found: run fc-cdc-setup")
    if slot[0] == "lost":
        raise SlotError(
            f"Replication slot {SLOT_NAME} is lost: run fc-cdc-setup --reset, then fc-pipeline"
        )


def setup_postgres(engine: Engine) -> None:
    """Idempotent. The slot comes last, so every change it holds is published in full."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" REPLICA IDENTITY FULL'))
        logger.info("Replica identity FULL on %s", ", ".join(TABLES))

        if conn.execute(
            text("SELECT 1 FROM pg_publication WHERE pubname = :pub"), {"pub": PUB_NAME}
        ).first():
            logger.info("Publication %s already exists", PUB_NAME)
        else:
            table_list = ", ".join(f'"{t}"' for t in TABLES)
            conn.execute(text(f"CREATE PUBLICATION {PUB_NAME} FOR TABLE {table_list}"))
            logger.info("Publication %s created", PUB_NAME)

        if _slot(conn) is not None:
            logger.info("Replication slot %s already exists", SLOT_NAME)
        else:
            conn.execute(
                text("SELECT pg_create_logical_replication_slot(:slot, 'pgoutput')"),
                {"slot": SLOT_NAME},
            )
            logger.info("Replication slot %s created", SLOT_NAME)


def drop_slot(engine: Engine) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        slot = _slot(conn)
        if slot is None:
            return
        if slot[1]:
            raise SlotError(
                f"Replication slot {SLOT_NAME} is in use: stop the consumer first"
            )
        conn.execute(
            text("SELECT pg_drop_replication_slot(:slot)"), {"slot": SLOT_NAME}
        )
        logger.info("Replication slot %s dropped", SLOT_NAME)


def setup(settings: Settings, reset: bool = False) -> None:
    engine = get_engine(settings)
    client = get_client(settings)
    if reset:
        drop_slot(engine)
        truncate_cdc_tables(client, settings.ch_database)
        logger.info("ClickHouse CDC tables emptied")
    setup_postgres(engine)
    ensure_schema(client, settings.ch_database)
    logger.info("ClickHouse tables ready in database %s", settings.ch_database)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop the slot and empty the ClickHouse CDC tables first",
    )
    args = parser.parse_args(argv)
    configure_logging()
    try:
        setup(get_settings(), reset=args.reset)
    except SlotError as exc:
        logger.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
