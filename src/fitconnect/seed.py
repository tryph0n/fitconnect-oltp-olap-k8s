"""Load the CSV files into PostgreSQL. A table that already has rows is skipped."""

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from fitconnect.config import Settings, configure_logging, get_settings
from fitconnect.models import Base

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "input"

# Parent tables before child tables (foreign keys).
CSV_TABLES = [
    ("users.csv", "User"),
    ("exercises.csv", "Exercise"),
    ("profiles.csv", "Profile"),
    ("workouts.csv", "Workout"),
    ("workout_exercises.csv", "WorkoutExercise"),
]

DATE_COLUMNS = ["JoinDate", "LastLogin", "BirthDate", "WorkoutDate"]


def get_engine(settings: Settings | None = None) -> Engine:
    return create_engine((settings or get_settings()).pg_url(), pool_pre_ping=True)


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Converts CSV text to the column types of the models."""
    df = df.copy()
    for column in DATE_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column]).dt.date
    if "WorkoutPlanID" in df.columns:
        # Empty cells become NULL, the other values stay integers.
        df["WorkoutPlanID"] = pd.to_numeric(
            df["WorkoutPlanID"], errors="coerce"
        ).astype("Int64")
    return df


def reset_sequences(engine: Engine) -> None:
    """Moves each serial sequence to max(id): explicit IDs from the CSV do not move it."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for column in table.primary_key.columns:
                sequence = conn.execute(
                    text("SELECT pg_get_serial_sequence(:table, :column)"),
                    {"table": f'"{table.name}"', "column": column.name},
                ).scalar()
                if sequence is None:
                    continue
                conn.execute(
                    text(
                        f'SELECT setval(:sequence, COALESCE(MAX("{column.name}"), 1),'
                        f' MAX("{column.name}") IS NOT NULL) FROM "{table.name}"'
                    ),
                    {"sequence": sequence},
                )


def seed(engine: Engine, data_dir: Path = DATA_DIR) -> None:
    Base.metadata.create_all(engine)
    for csv_name, table_name in CSV_TABLES:
        with engine.connect() as conn:
            has_rows = conn.execute(
                text(f'SELECT EXISTS (SELECT 1 FROM "{table_name}")')
            ).scalar()
        if has_rows:
            logger.info("Table %s already has rows, skipped", table_name)
            continue
        df = prepare_frame(pd.read_csv(data_dir / csv_name))
        df.to_sql(table_name, engine, if_exists="append", index=False)
        logger.info("Loaded %s into %s (%d rows)", csv_name, table_name, len(df))
    reset_sequences(engine)


def main() -> None:
    configure_logging()
    seed(get_engine())


if __name__ == "__main__":
    main()
