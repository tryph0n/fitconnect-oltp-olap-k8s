import datetime

import pandas as pd
import pytest

from fitconnect.models import Base
from fitconnect.seed import CSV_TABLES, DATA_DIR, prepare_frame

EXPECTED_ROWS = {
    "User": 10,
    "Exercise": 10,
    "Profile": 10,
    "Workout": 104,
    "WorkoutExercise": 426,
}


@pytest.mark.parametrize(("csv_name", "table_name"), CSV_TABLES)
def test_csv_files_match_the_models(csv_name, table_name):
    df = prepare_frame(pd.read_csv(DATA_DIR / csv_name))
    assert len(df) == EXPECTED_ROWS[table_name]
    assert list(df.columns) == [
        c.name for c in Base.metadata.tables[table_name].columns
    ]


def test_parent_tables_load_first():
    order = [table for _, table in CSV_TABLES]
    for table in order:
        for key in Base.metadata.tables[table].foreign_keys:
            assert order.index(key.column.table.name) < order.index(table)


def test_prepare_frame_converts_dates_and_empty_ids():
    raw = pd.DataFrame(
        {
            "WorkoutID": [1, 2],
            "WorkoutPlanID": [None, "7"],
            "WorkoutDate": ["2025-04-28", "2025-10-13"],
        }
    )
    df = prepare_frame(raw)
    assert df["WorkoutDate"].tolist() == [
        datetime.date(2025, 4, 28),
        datetime.date(2025, 10, 13),
    ]
    assert df["WorkoutPlanID"].isna().tolist() == [True, False]
    assert df["WorkoutPlanID"].iloc[1] == 7
    assert raw["WorkoutDate"].iloc[0] == "2025-04-28"
