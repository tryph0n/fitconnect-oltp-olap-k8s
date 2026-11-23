from fitconnect.models import TABLES, Base


def test_tables_match_the_models():
    assert set(TABLES) == set(Base.metadata.tables)
    assert len(TABLES) == 5


def test_primary_keys():
    keys = {
        name: [c.name for c in table.primary_key.columns]
        for name, table in Base.metadata.tables.items()
    }
    assert keys == {
        "User": ["UserID"],
        "Profile": ["ProfileID"],
        "Exercise": ["ExerciseID"],
        "Workout": ["WorkoutID"],
        "WorkoutExercise": ["WorkoutID", "ExerciseID"],
    }
