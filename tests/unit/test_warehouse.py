from fitconnect.warehouse import column_name, ddl_statements, journal_name, table_name


def test_names():
    assert table_name("WorkoutExercise") == "workout_exercise"
    assert journal_name("User") == "cdc_user"
    assert column_name("DemoVideoURL") == "demo_video_url"
    assert column_name("Order") == "order"


def _statement(statements, start):
    return next(s for s in statements if s.startswith(start))


def test_ddl_journal_state_and_view():
    statements = ddl_statements("fitconnect")
    assert statements[0] == "CREATE DATABASE IF NOT EXISTS `fitconnect`"
    assert len(statements) == 1 + 3 * 5

    journal = _statement(
        statements, "CREATE TABLE IF NOT EXISTS `fitconnect`.`cdc_workout_exercise`"
    )
    assert "`order` Nullable(Int64)" in journal
    assert "`_op` LowCardinality(String)" in journal
    assert journal.endswith(
        "ENGINE = ReplacingMergeTree ORDER BY (`workout_id`, `exercise_id`, `_lsn`)"
    )

    state = _statement(statements, "CREATE TABLE IF NOT EXISTS `fitconnect`.`user` ")
    assert "`username` String," in state
    assert "`last_login` Nullable(Date32)" in state
    assert "`user_id` Int64" in state
    assert state.endswith(
        "ENGINE = ReplacingMergeTree(`_lsn`, `_deleted`) ORDER BY (`user_id`)"
    )

    view = _statement(
        statements, "CREATE MATERIALIZED VIEW IF NOT EXISTS `fitconnect`.`cdc_user_mv`"
    )
    assert "TO `fitconnect`.`user`" in view
    assert view.endswith(
        "toUInt8(`_op` = 'D') AS `_deleted` FROM `fitconnect`.`cdc_user`"
    )


def test_ddl_types():
    workout = _statement(
        ddl_statements("db"), "CREATE TABLE IF NOT EXISTS `db`.`workout` "
    )
    assert "`workout_date` Date32" in workout
    assert "`calories_burned` Nullable(Float64)" in workout
    assert "`notes` Nullable(String)" in workout
