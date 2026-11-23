from datetime import UTC, datetime

import dlt

from fitconnect import cdc_consumer
from fitconnect.cdc_consumer import changes, journal_entry
from fitconnect.config import Settings
from fitconnect.pipeline import snapshot_entry
from pg_replication.helpers import ChangesBatch

READ_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_journal_entry_operations():
    insert = journal_entry({"UserID": 1, "_dlt_lsn": 10}, READ_AT)
    update = journal_entry(
        {"UserID": 1, "_dlt_lsn": 11, "_dlt_deleted_ts": None}, READ_AT
    )
    delete = journal_entry(
        {"UserID": 1, "_dlt_lsn": 12, "_dlt_deleted_ts": READ_AT}, READ_AT
    )
    assert insert == {"UserID": 1, "_op": "I", "_lsn": 10, "_ts": READ_AT}
    assert update == {"UserID": 1, "_op": "U", "_lsn": 11, "_ts": READ_AT}
    assert delete == {"UserID": 1, "_op": "D", "_lsn": 12, "_ts": READ_AT}


def test_snapshot_entry():
    assert snapshot_entry({"UserID": 1}, READ_AT) == {
        "UserID": 1,
        "_op": "I",
        "_lsn": 0,
        "_ts": READ_AT,
    }


def test_changes_start_at_the_stored_lsn(monkeypatch, tmp_path):
    calls = []

    def fake_stream_changes(**kwargs):
        calls.append(kwargs["start_lsn"])
        lsn = 100 * len(calls)
        hints = dlt.mark.with_hints(
            [], dlt.mark.make_hints(table_name="User", write_disposition="merge")
        )
        rows = dlt.mark.with_table_name(
            [{"UserID": len(calls), "_dlt_lsn": lsn}], "User"
        )
        yield ChangesBatch([hints, rows], lsn)

    monkeypatch.setattr(cdc_consumer, "stream_changes", fake_stream_changes)
    settings = Settings(_env_file=None, pg_password="x", ch_password="x")
    pipeline = dlt.pipeline(
        pipeline_name="unit_changes", destination="dummy", pipelines_dir=str(tmp_path)
    )

    pipeline.extract(changes(settings))
    pipeline.extract(changes(settings))
    pipeline.normalize()

    assert calls == [0, 100]
    table = pipeline.default_schema.get_table("user")
    assert table["write_disposition"] == "append"
    assert {"user_id", "_op", "_lsn", "_ts"} <= set(table["columns"])
