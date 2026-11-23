"""PostgreSQL to ClickHouse, end to end, in real containers.

The tests run in file order and share the two databases: each test starts from the state that
the test before it left.
"""

import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from fitconnect import cdc_consumer
from fitconnect.cdc_setup import PUB_NAME, SLOT_NAME, SlotError, drop_slot, setup
from fitconnect.models import TABLES
from fitconnect.pipeline import run_snapshot
from fitconnect.seed import seed
from fitconnect.warehouse import cdc_pipeline, journal_name, table_name

pytestmark = pytest.mark.integration

SEED_ROWS = {
    "User": 10,
    "Profile": 10,
    "Exercise": 10,
    "Workout": 104,
    "WorkoutExercise": 426,
}


def pg_rows(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def pg_run(engine, sql, **params):
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def pg_counts(engine):
    return {t: pg_rows(engine, f'SELECT count(*) FROM "{t}"')[0][0] for t in TABLES}


def state_counts(ch_client, settings):
    return {
        t: ch_client.command(
            f"SELECT count() FROM `{settings.ch_database}`.`{table_name(t)}` FINAL"
        )
        for t in TABLES
    }


def journal(ch_client, settings, source_table, where="1"):
    """Returns the journal rows as dicts, oldest change first."""
    result = ch_client.query(
        f"SELECT * FROM `{settings.ch_database}`.`{journal_name(source_table)}` "
        f"WHERE {where} ORDER BY _lsn"
    )
    return list(result.named_results())


def duplicates(ch_client, settings, source_table, key):
    name = f"`{settings.ch_database}`.`{journal_name(source_table)}`"
    return ch_client.command(f"SELECT count() - uniqExact({key}, _lsn) FROM {name}")


def confirmed_lsn(engine):
    sql = "SELECT confirmed_flush_lsn - '0/0'::pg_lsn FROM pg_replication_slots WHERE slot_name = :s"
    return int(pg_rows(engine, sql, s=SLOT_NAME)[0][0])


@pytest.fixture
def consumer(settings, tmp_path):
    """A consumer pipeline with a new local folder: the state must come from ClickHouse."""
    return cdc_pipeline(cdc_consumer.PIPELINE_NAME, settings, str(tmp_path))


def test_seed_loads_each_table_once(engine):
    seed(engine)
    seed(engine)
    assert pg_counts(engine) == SEED_ROWS
    pg_run(engine, 'INSERT INTO "Exercise" ("Name") VALUES (\'Plank\')')
    assert pg_rows(engine, 'SELECT max("ExerciseID") FROM "Exercise"')[0][0] == 11
    pg_run(engine, 'DELETE FROM "Exercise" WHERE "ExerciseID" = 11')


def test_snapshot_needs_the_slot(settings, tmp_path):
    with pytest.raises(SlotError, match="fc-cdc-setup"):
        run_snapshot(settings, str(tmp_path))


def test_setup_is_idempotent(settings, engine, ch_client):
    setup(settings)
    setup(settings)
    slots = pg_rows(engine, "SELECT plugin, slot_type FROM pg_replication_slots")
    assert slots == [("pgoutput", "logical")]
    published = pg_rows(
        engine,
        "SELECT tablename FROM pg_publication_tables WHERE pubname = :p",
        p=PUB_NAME,
    )
    assert {row[0] for row in published} == set(TABLES)
    identities = pg_rows(
        engine,
        "SELECT relreplident FROM pg_class WHERE relname = ANY(:names)",
        names=list(TABLES),
    )
    assert [row[0] for row in identities] == ["f"] * 5
    tables = ch_client.query(
        "SELECT name, engine FROM system.tables WHERE database = {db:String}",
        parameters={"db": settings.ch_database},
    ).result_rows
    engines = dict(tables)
    for t in TABLES:
        assert engines[journal_name(t)] == "ReplacingMergeTree"
        assert engines[table_name(t)] == "ReplacingMergeTree"
        assert engines[f"{journal_name(t)}_mv"] == "MaterializedView"


def test_snapshot_loads_each_table_once(settings, engine, ch_client, tmp_path):
    assert run_snapshot(settings, str(tmp_path / "first")) is not None
    assert run_snapshot(settings, str(tmp_path / "second")) is None
    assert state_counts(ch_client, settings) == SEED_ROWS
    rows = journal(ch_client, settings, "User")
    assert len(rows) == 10
    assert {(row["_op"], row["_lsn"]) for row in rows} == {("I", 0)}
    assert rows[0]["username"].startswith("user")


def test_changes_reach_the_journal_and_the_state(settings, engine, ch_client, consumer):
    pg_run(engine, 'INSERT INTO "Exercise" ("Name") VALUES (\'Burpee\')')
    pg_run(
        engine, 'UPDATE "User" SET "AccountStatus" = \'Suspended\' WHERE "UserID" = 1'
    )
    pg_run(
        engine,
        'DELETE FROM "WorkoutExercise" WHERE "WorkoutID" = 1 AND "ExerciseID" = 2',
    )

    rows = cdc_consumer.run_once(settings, consumer, engine)

    assert rows == {"exercise": 1, "user": 1, "workout_exercise": 1}
    (insert,) = journal(ch_client, settings, "Exercise", "_lsn > 0")
    assert (insert["exercise_id"], insert["name"], insert["_op"]) == (12, "Burpee", "I")
    (update,) = journal(ch_client, settings, "User", "_lsn > 0")
    assert (update["user_id"], update["account_status"], update["_op"]) == (
        1,
        "Suspended",
        "U",
    )
    (delete,) = journal(ch_client, settings, "WorkoutExercise", "_lsn > 0")
    assert (delete["workout_id"], delete["exercise_id"], delete["_op"]) == (1, 2, "D")
    assert (delete["rep_count"], delete["order"]) == (11, 2)
    assert insert["_lsn"] < update["_lsn"] < delete["_lsn"]

    assert state_counts(ch_client, settings) == pg_counts(engine)
    status = ch_client.command(
        f"SELECT account_status FROM `{settings.ch_database}`.`user` FINAL WHERE user_id = 1"
    )
    assert status == "Suspended"


def test_slot_advances_after_a_run(settings, engine, consumer):
    before = confirmed_lsn(engine)
    pg_run(
        engine, 'UPDATE "User" SET "LastLogin" = DATE \'2026-01-02\' WHERE "UserID" = 2'
    )
    cdc_consumer.run_once(settings, consumer, engine)
    cdc_consumer.run_once(settings, consumer, engine)
    assert confirmed_lsn(engine) > before


def test_restart_without_local_state_adds_no_duplicate(
    settings, engine, ch_client, consumer
):
    pg_run(engine, 'UPDATE "Workout" SET "Rating" = 5 WHERE "WorkoutID" = 3')
    assert cdc_consumer.run_once(settings, consumer, engine) == {"workout": 1}
    assert cdc_consumer.run_once(settings, consumer, engine) == {}
    assert len(journal(ch_client, settings, "User", "_lsn > 0")) == 2
    assert duplicates(ch_client, settings, "Workout", "workout_id") == 0
    assert (
        duplicates(ch_client, settings, "WorkoutExercise", "workout_id, exercise_id")
        == 0
    )
    assert state_counts(ch_client, settings) == pg_counts(engine)


def test_loop_stops_on_request(settings, engine, ch_client, tmp_path):
    stop = threading.Event()
    result = {}
    loop = threading.Thread(
        target=lambda: result.update(
            code=cdc_consumer.run_forever(settings, stop, str(tmp_path))
        )
    )
    loop.start()
    pg_run(engine, 'UPDATE "Profile" SET "TargetWeight" = 70 WHERE "ProfileID" = 1')
    query = f"SELECT target_weight FROM `{settings.ch_database}`.`profile` FINAL WHERE profile_id = 1"
    for _ in range(60):
        if ch_client.command(query) == 70:
            break
        stop.wait(0.5)
    stop.set()
    loop.join(timeout=30)
    assert ch_client.command(query) == 70
    assert Path(settings.cdc_heartbeat_file).exists()
    assert result == {"code": 0}


def test_reset_starts_a_new_slot_and_snapshot(
    settings, engine, ch_client, tmp_path, consumer
):
    setup(settings, reset=True)
    assert state_counts(ch_client, settings) == dict.fromkeys(TABLES, 0)
    run_snapshot(settings, str(tmp_path))
    assert cdc_consumer.run_once(settings, consumer, engine) == {}
    assert state_counts(ch_client, settings) == pg_counts(engine)
    assert {row["_op"] for row in journal(ch_client, settings, "User")} == {"I"}


def test_consumer_stops_without_the_slot(settings, engine, consumer):
    drop_slot(engine)
    with pytest.raises(SlotError, match="fc-cdc-setup"):
        cdc_consumer.run_once(settings, consumer, engine)
