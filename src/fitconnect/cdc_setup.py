"""Configure PostgreSQL CDC: replication slot, replica identity, publication."""

from sqlalchemy import text

from fitconnect.seed import get_engine

TABLES = ["User", "Profile", "Exercise", "Workout", "WorkoutExercise"]
SLOT_NAME = "fitconnect_slot"
PUB_NAME = "fitconnect_pub"


def main():
    """Set up replication slot, replica identity, and publication."""
    engine = get_engine()

    with engine.connect() as conn:
        # 1. Create logical replication slot (idempotent)
        exists = conn.execute(
            text("SELECT 1 FROM pg_replication_slots WHERE slot_name = :slot"),
            {"slot": SLOT_NAME},
        ).fetchone()

        if not exists:
            conn.execute(
                text(
                    "SELECT pg_create_logical_replication_slot(:slot, 'pgoutput')"
                ),
                {"slot": SLOT_NAME},
            )
            print(f"Replication slot '{SLOT_NAME}' created.")
        else:
            print(f"Replication slot '{SLOT_NAME}' already exists.")

        # 2. Set REPLICA IDENTITY FULL on all tables
        for table in TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" REPLICA IDENTITY FULL'))
        print("Replica identity set to FULL on all tables.")

        # 3. Create publication for all tables (idempotent)
        pub_exists = conn.execute(
            text("SELECT 1 FROM pg_publication WHERE pubname = :pub"),
            {"pub": PUB_NAME},
        ).fetchone()

        if not pub_exists:
            table_list = ", ".join(f'"{t}"' for t in TABLES)
            conn.execute(
                text(f"CREATE PUBLICATION {PUB_NAME} FOR TABLE {table_list}")
            )
            print(f"Publication '{PUB_NAME}' created.")
        else:
            print(f"Publication '{PUB_NAME}' already exists.")

        conn.commit()


if __name__ == "__main__":
    main()
