#!/usr/bin/env bash
# shellcheck disable=SC2016 # single quotes on purpose: the pod shell or ClickHouse reads these
# Shows the CDC at work on a running deployment (`make up`): one UPDATE and one DELETE in
# PostgreSQL, then waits until the ClickHouse current state shows both and the replication slot
# has confirmed them. Exits 1 when this takes more than WAIT_SECONDS.
set -euo pipefail

NS=${NS:-fitconnect}
KUBECTL=${KUBECTL:-kubectl}
WAIT_SECONDS=${WAIT_SECONDS:-30}
SLOT=fitconnect_slot

# The SQL goes in as an argument; the passwords stay in the pods.
pg() {
    $KUBECTL exec -n "$NS" postgres-0 -- sh -c \
        'psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAq -c "$1"' sh "$1"
}

ch() {
    $KUBECTL exec -n "$NS" clickhouse-0 -c clickhouse -- sh -c \
        'clickhouse-client --user "$CH_USER" --password "$CH_PASSWORD" -d "$CH_DATABASE" -q "$1"' sh "$1"
}

slot_lsn() {
    pg "SELECT confirmed_flush_lsn FROM pg_replication_slots WHERE slot_name = '$SLOT'"
}

show() {
    echo "$1"
    echo "  PostgreSQL User 1 AccountStatus:      $(pg 'SELECT "AccountStatus" FROM "User" WHERE "UserID" = 1')"
    echo "  ClickHouse user 1 account_status:     $(ch 'SELECT account_status FROM `user` FINAL WHERE user_id = 1')"
    echo "  ClickHouse workout_exercise rows:     $(ch 'SELECT count() FROM workout_exercise FINAL')"
    echo "  PostgreSQL WorkoutExercise rows:      $(pg 'SELECT count(*) FROM "WorkoutExercise"')"
    echo "  Slot $SLOT confirmed_flush_lsn: $(slot_lsn)"
}

before_lsn=$(slot_lsn)
if [ -z "$before_lsn" ]; then
    echo "No replication slot $SLOT: run make up first" >&2
    exit 1
fi
IFS='|' read -r workout_id exercise_id \
    <<<"$(pg 'SELECT "WorkoutID", "ExerciseID" FROM "WorkoutExercise" ORDER BY 1, 2 LIMIT 1')"
if [ -z "$workout_id" ]; then
    echo "No WorkoutExercise row left to delete" >&2
    exit 1
fi
status="demo-$(date +%s)"

show "Before"
pg "UPDATE \"User\" SET \"AccountStatus\" = '$status' WHERE \"UserID\" = 1"
pg "DELETE FROM \"WorkoutExercise\" WHERE \"WorkoutID\" = $workout_id AND \"ExerciseID\" = $exercise_id"
echo "PostgreSQL: UPDATE User 1 AccountStatus = '$status'; DELETE WorkoutExercise ($workout_id, $exercise_id)"

visible="SELECT (SELECT account_status FROM \`user\` FINAL WHERE user_id = 1) = '$status'
    AND (SELECT count() FROM workout_exercise FINAL
         WHERE workout_id = $workout_id AND exercise_id = $exercise_id) = 0"
confirmed="SELECT confirmed_flush_lsn > '$before_lsn'::pg_lsn FROM pg_replication_slots
    WHERE slot_name = '$SLOT'"
start=$SECONDS
until [ "$(ch "$visible")" = 1 ]; do
    if ((SECONDS - start >= WAIT_SECONDS)); then
        echo "Timeout: ClickHouse does not show the changes after $WAIT_SECONDS s" >&2
        exit 1
    fi
    sleep 1
done
echo "ClickHouse shows both changes after $((SECONDS - start)) s"
until [ "$(pg "$confirmed")" = t ]; do
    if ((SECONDS - start >= WAIT_SECONDS)); then
        echo "Timeout: the slot did not confirm the changes after $WAIT_SECONDS s" >&2
        exit 1
    fi
    sleep 1
done
show "After"
