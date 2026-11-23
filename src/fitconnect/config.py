"""Settings from environment variables and an optional .env file."""

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Connection settings. Passwords have no default: a missing or empty one stops the program."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env also holds keys for the database images (POSTGRES_*, CLICKHOUSE_*) and S3.
        extra="ignore",
    )

    pg_user: str = "postgres"
    pg_password: str = Field(min_length=1)
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "postgres"

    ch_host: str = "localhost"
    ch_port: int = 9000
    ch_http_port: int = 8123
    ch_user: str = "default"
    ch_password: str = Field(min_length=1)
    ch_database: str = "fitconnect"

    cdc_poll_seconds: float = 5.0
    cdc_heartbeat_file: str = "/tmp/fitconnect-cdc-heartbeat"

    def pg_url(self, drivername: str = "postgresql+psycopg") -> str:
        """Returns the PostgreSQL URL; `postgresql` gives a URL for psycopg2."""
        return URL.create(
            drivername,
            username=self.pg_user,
            password=self.pg_password,
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_db,
        ).render_as_string(hide_password=False)

    @property
    def ch_credentials(self) -> dict:
        """Returns the ClickHouse credentials in the form that dlt expects."""
        return {
            "host": self.ch_host,
            "port": self.ch_port,
            "http_port": self.ch_http_port,
            "username": self.ch_user,
            "password": self.ch_password,
            "database": self.ch_database,
            "secure": 0,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
