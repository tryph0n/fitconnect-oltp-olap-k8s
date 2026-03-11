"""FitConnect dlt pipeline: PostgreSQL -> ClickHouse full load."""

import dlt
from dlt.sources.credentials import ConnectionStringCredentials
from dlt.sources.sql_database import sql_database

from fitconnect.config import settings


TABLES = ["User", "Profile", "Exercise", "Workout", "WorkoutExercise"]


def main() -> None:
    """Run full-load pipeline from PostgreSQL to ClickHouse."""
    credentials = ConnectionStringCredentials(settings.pg_url)

    pipeline = dlt.pipeline(
        pipeline_name="fitconnect_pg_to_ch",
        destination=dlt.destinations.clickhouse(credentials=settings.ch_credentials),
        dataset_name="fitconnect",
    )

    source = sql_database(credentials=credentials, table_names=TABLES)

    info = pipeline.run(source, write_disposition="replace")
    print(info)


if __name__ == "__main__":
    main()
