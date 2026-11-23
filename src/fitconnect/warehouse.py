"""ClickHouse side of the CDC: table names, DDL, and the dlt pipelines."""

import clickhouse_connect
import dlt
from clickhouse_connect.driver.client import Client
from dlt.common.normalizers.naming.snake_case import NamingConvention
from sqlalchemy import Column, Date, Float, Integer, String

from fitconnect.config import Settings
from fitconnect.models import TABLES, Base

DATASET = "cdc"
"""dlt dataset; with the separator `_`, dlt writes the table `user` to `cdc_user`."""

DLT_STATE_TABLE = f"{DATASET}__dlt_pipeline_state"

_naming = NamingConvention()

_CH_TYPES = (
    (Integer, "Int64"),
    (Float, "Float64"),
    (Date, "Date32"),
    (String, "String"),
)


def table_name(source_table: str) -> str:
    """ClickHouse name of the current state of a PostgreSQL table, e.g. `WorkoutExercise`."""
    return _naming.normalize_table_identifier(source_table)


def journal_name(source_table: str) -> str:
    return f"{DATASET}_{table_name(source_table)}"


def column_name(source_column: str) -> str:
    return _naming.normalize_identifier(source_column)


def _quote(name: str) -> str:
    return f"`{name}`"


def _column_type(column: Column) -> str:
    for sql_type, ch_type in _CH_TYPES:
        if isinstance(column.type, sql_type):
            break
    else:
        raise TypeError(f"No ClickHouse type for {column.table.name}.{column.name}")
    if column.nullable and not column.primary_key:
        return f"Nullable({ch_type})"
    return ch_type


def ddl_statements(database: str) -> list[str]:
    """CREATE statements, idempotent: journal, current state and the view between them."""
    statements = [f"CREATE DATABASE IF NOT EXISTS {_quote(database)}"]
    for source_table in TABLES:
        table = Base.metadata.tables[source_table]
        columns = [column_name(c.name) for c in table.columns]
        key = ", ".join(_quote(column_name(c.name)) for c in table.primary_key.columns)
        source_columns = ",\n".join(
            f"    {_quote(column_name(c.name))} {_column_type(c)}"
            for c in table.columns
        )
        journal = f"{_quote(database)}.{_quote(journal_name(source_table))}"
        state = f"{_quote(database)}.{_quote(table_name(source_table))}"
        view = f"{_quote(database)}.{_quote(journal_name(source_table) + '_mv')}"
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {journal} (\n{source_columns},\n"
            "    `_op` LowCardinality(String),\n    `_lsn` UInt64,\n"
            "    `_ts` DateTime64(6, 'UTC'),\n    `_dlt_load_id` String,\n"
            "    `_dlt_id` String\n"
            f") ENGINE = ReplacingMergeTree ORDER BY ({key}, `_lsn`)"
        )
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {state} (\n{source_columns},\n"
            "    `_lsn` UInt64,\n    `_ts` DateTime64(6, 'UTC'),\n    `_deleted` UInt8\n"
            f") ENGINE = ReplacingMergeTree(`_lsn`, `_deleted`) ORDER BY ({key})"
        )
        selected = ", ".join(_quote(c) for c in columns)
        statements.append(
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS {view} TO {state} AS SELECT "
            f"{selected}, `_lsn`, `_ts`, toUInt8(`_op` = 'D') AS `_deleted` FROM {journal}"
        )
    return statements


def get_client(settings: Settings) -> Client:
    return clickhouse_connect.get_client(
        host=settings.ch_host,
        port=settings.ch_http_port,
        username=settings.ch_user,
        password=settings.ch_password,
    )


def ensure_schema(client: Client, database: str) -> None:
    for statement in ddl_statements(database):
        client.command(statement)


def truncate_cdc_tables(client: Client, database: str) -> None:
    """Empties the journals, the current states and the dlt pipeline state (stored LSN)."""
    names = [journal_name(t) for t in TABLES] + [table_name(t) for t in TABLES]
    for name in names + [DLT_STATE_TABLE]:
        client.command(f"TRUNCATE TABLE IF EXISTS {_quote(database)}.{_quote(name)}")


def has_snapshot(client: Client, database: str, source_table: str) -> bool:
    """True when the journal already holds snapshot rows (`_lsn = 0`) for the table."""
    journal = f"{_quote(database)}.{_quote(journal_name(source_table))}"
    return bool(
        client.query(f"SELECT count() FROM {journal} WHERE `_lsn` = 0").result_rows[0][
            0
        ]
    )


def cdc_pipeline(
    name: str, settings: Settings, pipelines_dir: str | None = None
) -> dlt.Pipeline:
    """dlt pipeline that appends to the journals in the dataset `cdc`."""
    return dlt.pipeline(
        pipeline_name=name,
        destination=dlt.destinations.clickhouse(
            credentials=settings.ch_credentials, dataset_table_separator="_"
        ),
        dataset_name=DATASET,
        pipelines_dir=pipelines_dir,
    )
