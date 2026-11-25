import re
import secrets
from pathlib import Path

import pytest
from testcontainers.community.clickhouse import ClickHouseContainer
from testcontainers.community.postgres import PostgresContainer

from fitconnect.config import Settings
from fitconnect.seed import get_engine
from fitconnect.warehouse import get_client

K8S = Path(__file__).resolve().parents[2] / "k8s"


def k8s_image(manifest: str) -> str:
    """Uses the image tag of the Kubernetes manifest, so tests and cluster run the same version."""
    return re.search(r"^\s*image:\s*(\S+)", (K8S / manifest).read_text(), re.MULTILINE)[
        1
    ]


@pytest.fixture(scope="session")
def pg():
    container = PostgresContainer(
        k8s_image("postgres/statefulset.yaml"),
        password=secrets.token_hex(16),
        driver=None,
    ).with_command("postgres -c wal_level=logical -c max_slot_wal_keep_size=256MB")
    with container:
        yield container


@pytest.fixture(scope="session")
def ch():
    container = ClickHouseContainer(
        k8s_image("clickhouse/statefulset.yaml"),
        username="fitconnect",
        password=secrets.token_hex(16),
        dbname="fitconnect",
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def settings(pg, ch, tmp_path_factory):
    return Settings(
        _env_file=None,
        pg_user=pg.username,
        pg_password=pg.password,
        pg_host=pg.get_container_host_ip(),
        pg_port=int(pg.get_exposed_port(5432)),
        pg_db=pg.dbname,
        ch_host=ch.get_container_host_ip(),
        ch_port=int(ch.get_exposed_port(9000)),
        ch_http_port=int(ch.get_exposed_port(8123)),
        ch_user=ch.username,
        ch_password=ch.password,
        cdc_poll_seconds=0.5,
        cdc_heartbeat_file=str(tmp_path_factory.mktemp("cdc") / "heartbeat"),
    )


@pytest.fixture(scope="session")
def engine(settings):
    engine = get_engine(settings)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def ch_client(settings):
    client = get_client(settings)
    yield client
    client.close()
