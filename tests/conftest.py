import os

import pytest

os.environ.setdefault("RUNTIME__DLTHUB_TELEMETRY", "false")


@pytest.fixture(scope="session", autouse=True)
def _outside_the_project(tmp_path_factory):
    """Runs every test in an empty folder without PG_/CH_/CDC_ variables: no test reads a .env."""
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(tmp_path_factory.mktemp("cwd"))
        for name in list(os.environ):
            if name.startswith(("PG_", "CH_", "CDC_")):
                mp.delenv(name)
        yield
