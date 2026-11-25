# ADR: change data capture from PostgreSQL to ClickHouse

- Status: accepted
- Date: 2026-11-23

## Context

The project copies the FitConnect tables (`User`, `Profile`, `Exercise`, `Workout`,
`WorkoutExercise`) from PostgreSQL to ClickHouse. Before this decision, `fc-cdc` created a logical
replication slot and a publication, but no program read the slot. `fc-pipeline` did a full
`replace` load. The slot kept all WAL, and ClickHouse never received individual changes.

The target, for each table:

- a change journal `fitconnect.cdc_<table>`: snake_case source columns, `_op` (`I`, `U`, `D`),
  `_lsn` (WAL position of the change) and `_ts`;
- a current state `fitconnect.<table>`: `ReplacingMergeTree(_lsn, _deleted)` ordered by the
  primary key, read with `FINAL`;
- one reader-facing copy per table, changes visible in less than 30 s, and no `replace` run that
  drops a CDC table.

## Options

- **A. dlt verified source `pg_replication`.** `dlt init pg_replication clickhouse` copies the
  source into the project. It reads the slot with psycopg2 (pgoutput, protocol 1), decodes the
  messages, and confirms the slot only after a successful pipeline run.
- **B. Own consumer.** psycopg 3 with `pg_logical_slot_peek_binary_changes`, an own pgoutput
  decoder, `clickhouse-connect` writes, then `pg_replication_slot_advance`.

The rule fixed before the test: use A only if all seven gates pass, else use B.

## Spike

Scratch clone of the project, PostgreSQL 16.16 (`-c wal_level=logical`) and ClickHouse 24.8.14.39
in `docker run` containers, `fc-seed` and `fc-cdc` (slot `fitconnect_slot`, publication
`fitconnect_pub`), then `uv run dlt init pg_replication clickhouse` and
`uv add "psycopg2-binary>=2.9.9"`. dlt stayed at 1.23.0. The spike took about 25 minutes.

| Gate | Check | Command | Result |
| --- | --- | --- | --- |
| G1 | Snapshot counts 10/10/10/104/426 | `init_replication(..., initial_snapshot="direct")`, `pipeline.run`, `SELECT count()` per table | Pass: 10, 10, 10, 104, 426 (1.6 s) |
| G2 | One INSERT, UPDATE, DELETE correct in current state | `INSERT` exercise 11, `UPDATE` user 1 status, `DELETE` workout_exercise (1, 2); one run | Pass: all three correct, 426 to 425 rows |
| G3 | `confirmed_flush_lsn` advances | `SELECT confirmed_flush_lsn FROM pg_replication_slots` between runs | Pass: `0/1575F18` to `0/15C06F0`; the slot is confirmed at the start of the next run |
| G4 | Kill mid-run, rerun: one row per key, no lost change | `kill -9` during load, then during extract (one transaction of about 255,000 updates and 1,000 inserts); rerun; compare with PostgreSQL | Pass: 425 keys, `sum(rep_count)` equal to PostgreSQL in both cases; a kill during load reloads the pending package, a kill during extract reads the changes again |
| G5 | Change visible in less than 30 s, loop period at most 10 s | loop with a 10 s period, change in PostgreSQL, poll ClickHouse | Pass: 9.3 s, 6.8 s, 7.3 s; an idle run takes 0.1 to 0.3 s |
| G6 | Journal (`_op`, `_lsn`, `_ts`) from a small wrapper, copied source not edited | 25-line `add_yield_map` wrapper on `replication_resource` | Pass: rows `(11, I)`, `(11, U)`, `(11, D)` with increasing `_lsn` |
| G7 | Python 3.13, cp313 wheels, `uv lock` | `uv run python -V`, `uv lock --check` | Pass: 3.13, `psycopg2-binary` 2.9.13 with cp313 wheels, lock check exit 0 |

Facts found during G6 that shape the design:

- The source marks a delete with `_dlt_deleted_ts` (commit time). An update row has the key with
  the value `None`. An insert row has no `_dlt_deleted_ts` key. The source README documents only
  the delete marker, so the insert and update split depends on the row shape of the copied
  version.
- The source exposes the commit time only for deletes.
- The source sends hints that make each table a `merge` table. A wrapper that writes a journal
  table with the same name gets conflicting hints. The `stream_changes` helper of the same source
  gives the rows without these hints.
- A primary key change gives a `D` row for the old key and a `U` row for the new key, with the
  same `_lsn`.
- With a deleted local pipeline folder, the next run restores the state (last LSN) from the
  ClickHouse table `cdc__dlt_pipeline_state` and adds no duplicate.

## Decision

All gates pass: option A. The consumer uses the copied source `pg_replication/` without edits,
plus a small dlt resource in `src/fitconnect/cdc_consumer.py`:

- `stream_changes(..., hard_delete=False)` gives the change rows. `hard_delete=False` keeps the
  real values of a deleted row (with `True`, the source replaces NULL values with placeholders).
- The resource writes only journal rows (`write_disposition="append"`), with `_op` from the row
  shape above, `_lsn` from `_dlt_lsn`, and `_ts` = the time the consumer read the change (UTC).
- It stores the last commit LSN in the dlt resource state, like `replication_resource`.
- The dlt dataset is `cdc` with `dataset_table_separator="_"`, so the table `user` becomes
  `fitconnect.cdc_user`. dlt also creates `cdc__dlt_loads`, `cdc__dlt_pipeline_state`,
  `cdc__dlt_version` and `cdc_dlt_sentinel_table`.

ClickHouse tables (created by `fc-cdc-setup` from the SQLAlchemy models, `IF NOT EXISTS`):

| Table | Engine | Role |
| --- | --- | --- |
| `cdc_<table>` | `ReplacingMergeTree ORDER BY (<key>, _lsn)` | Journal. A replay of the same change after a crash collapses at merge time |
| `<table>` | `ReplacingMergeTree(_lsn, _deleted) ORDER BY <key>` | Current state, read with `FINAL` (deleted rows are hidden) |
| `cdc_<table>_mv` | Materialized view, journal to current state | `_deleted = (_op = 'D')` |

Roles of the entry points:

- `fc-cdc-setup` (was `fc-cdc`): `REPLICA IDENTITY FULL`, the publication, then the slot, and the
  ClickHouse tables. The slot comes after the publication: pgoutput reads the publication as it
  was at the WAL position of each change, and fails on changes written before the publication
  existed. It runs before the snapshot, so the slot holds every change made after it.
- `fc-pipeline`: the initial snapshot. dlt `sql_database` appends each table to its journal with
  `_op = 'I'` and `_lsn = 0`. It skips a table whose journal already has snapshot rows. It never
  uses `replace`.
- `fc-cdc-consumer`: a loop (default period 5 s). Each run reads the new changes and loads them,
  then writes a heartbeat file. It exits with an error when the slot is missing or its
  `wal_status` is `lost`.

Why the snapshot and the stream agree: the slot exists before the snapshot reads the tables, and
a change always has `_lsn > 0`. A change that the snapshot already contains is applied again with
a higher version, which gives the same final row.

## Consequences

- The project keeps about 3,100 lines of copied third-party code (Apache License 2.0, kept in
  `pg_replication/LICENSE.txt`). ruff does not check it. An update is a new `dlt init` and a new
  run of the tests.
- Tests check the row shape that the journal depends on (insert, update and delete in a real
  database), so a source update that changes it fails the tests.
- `_ts` is not the commit time for inserts and updates.
- The journal is at least once: after a crash during a load, the same change can be stored again
  until a merge. Read it with `FINAL` for exact counts. The current state is not affected.
- `TRUNCATE` and DDL are not replicated (the source logs a warning for `TRUNCATE`).
- A slot with no consumer keeps WAL. PostgreSQL runs with `max_slot_wal_keep_size=256MB`. When the
  slot becomes `lost`, run `fc-cdc-setup --reset` (new slot, empty ClickHouse CDC tables), then
  `fc-pipeline` for a new snapshot.
- Only one consumer may read the slot: the Kubernetes Deployment has one replica and the
  `Recreate` strategy.

## Pinned versions

| Item | Version |
| --- | --- |
| Python | 3.13 |
| dlt | 1.23.0 |
| Verified source `pg_replication` | 1.0.2, `dlt-hub/verified-sources` commit `952bf8d` (2026-11-18) |
| psycopg2-binary | 2.9.13 |
| PostgreSQL image | `postgres:16.16` |
| ClickHouse image | `clickhouse/clickhouse-server:24.8.14.39` |
| Local S3 server (optional) | `motoserver/moto:5.2.5` |

The integration tests (testcontainers 4.15.0) read the PostgreSQL and ClickHouse image tags from
the manifests in `k8s/`, so the tests and the cluster use the same versions.
