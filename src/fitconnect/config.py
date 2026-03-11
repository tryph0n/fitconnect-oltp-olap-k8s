"""Centralized configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # PostgreSQL
    pg_user: str = "postgres"
    pg_password: str = "changeme"
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_db: str = "postgres"

    # ClickHouse
    ch_host: str = "localhost"
    ch_port: int = 9000
    ch_http_port: int = 8123
    ch_user: str = "default"
    ch_password: str = "changeme"
    ch_database: str = "fitconnect"

    # S3 (optional)
    s3_endpoint: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    @property
    def pg_url(self) -> str:
        """Build the PostgreSQL connection URL (psycopg v3 driver)."""
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def ch_credentials(self) -> dict:
        """Return ClickHouse credentials as a dict suitable for dlt."""
        return {
            "host": self.ch_host,
            "port": self.ch_port,
            "http_port": self.ch_http_port,
            "username": self.ch_user,
            "password": self.ch_password,
            "database": self.ch_database,
            "secure": 0,
        }


settings = Settings()
