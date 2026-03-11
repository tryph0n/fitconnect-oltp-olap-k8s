"""Load CSV files into PostgreSQL tables."""

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

from fitconnect.config import settings
from fitconnect.models import Base

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "input"

# Order matters: parent tables before children (FK constraints)
TABLES = [
    ("users.csv", "User"),
    ("exercises.csv", "Exercise"),
    ("profiles.csv", "Profile"),
    ("workouts.csv", "Workout"),
    ("workout_exercises.csv", "WorkoutExercise"),
]


def get_engine():
    """Create SQLAlchemy engine from centralized settings."""
    return create_engine(settings.pg_url, pool_pre_ping=True)


def main():
    """Create tables and load CSV data into PostgreSQL."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("Tables created.")

    date_columns = ["JoinDate", "LastLogin", "BirthDate", "WorkoutDate"]

    for csv_name, table_name in TABLES:
        df = pd.read_csv(DATA_DIR / csv_name)
        # Parse date columns so pandas sends proper date types to PG
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col]).dt.date
        # WorkoutPlanID comes as empty string from CSV -> convert to None
        if "WorkoutPlanID" in df.columns:
            df["WorkoutPlanID"] = (
                pd.to_numeric(df["WorkoutPlanID"], errors="coerce")
                .astype("Int64")
            )
        df.to_sql(table_name, engine, if_exists="append", index=False)
        print(f"Loaded {csv_name} -> {table_name} ({len(df)} rows)")


if __name__ == "__main__":
    main()
