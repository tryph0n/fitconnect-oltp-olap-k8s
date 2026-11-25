import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from fitconnect.config import Settings


def test_passwords_are_required():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)
    missing = {e["loc"][0] for e in error.value.errors() if e["type"] == "missing"}
    assert missing == {"pg_password", "ch_password"}


def test_env_file_keys_for_images_and_s3_are_ignored(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PG_PASSWORD=pg-secret\nCH_PASSWORD=ch-secret\nPOSTGRES_USER=postgres\n"
        "POSTGRES_PASSWORD=pg-secret\nCLICKHOUSE_DB=fitconnect\nCLICKHOUSE_PASSWORD=ch-secret\n"
        "S3_ENDPOINT=http://moto:5000/bucket/data/\nS3_ACCESS_KEY_ID=test\n"
    )
    settings = Settings(_env_file=env_file)
    assert settings.pg_password == "pg-secret"
    assert settings.ch_password == "ch-secret"


def test_pg_url_escapes_the_password():
    settings = Settings(
        _env_file=None, pg_password="p@ss:w/rd", ch_password="x", pg_port=5433
    )
    url = make_url(settings.pg_url())
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss:w/rd"
    assert (url.host, url.port, url.database) == ("localhost", 5433, "postgres")
    assert make_url(settings.pg_url("postgresql")).drivername == "postgresql"


def test_ch_credentials():
    settings = Settings(_env_file=None, pg_password="x", ch_password="secret")
    assert settings.ch_credentials == {
        "host": "localhost",
        "port": 9000,
        "http_port": 8123,
        "username": "default",
        "password": "secret",
        "database": "fitconnect",
        "secure": 0,
    }


def test_empty_passwords_are_refused():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, pg_password="", ch_password="")
    assert {e["type"] for e in error.value.errors()} == {"string_too_short"}
