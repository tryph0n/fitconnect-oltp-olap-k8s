import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _values(key, folder="k8s"):
    for path in sorted((ROOT / folder).rglob("*.yaml")):
        for value in re.findall(
            rf"^\s*{key}:\s*(\S.*)$", path.read_text(), re.MULTILINE
        ):
            yield path.relative_to(ROOT), value.strip()


def test_images_are_pinned():
    images = list(_values("image"))
    assert images
    for path, image in images:
        name, _, tag = image.rpartition(":")
        assert name and "/" not in tag and tag != "latest", f"{path}: {image}"


def test_pipeline_image_matches_the_project_version():
    expected = f"ghcr.io/tryph0n/fitconnect-pipeline:{PROJECT['version']}"
    pipeline = [
        image for _, image in _values("image") if "fitconnect-pipeline" in image
    ]
    assert len(pipeline) == 4
    assert set(pipeline) == {expected}


def test_pipeline_commands_are_entry_points():
    containers = [
        json.loads(c)
        for _, c in _values("command", "k8s/pipeline")
        if c.startswith("[")
    ]
    assert {command[0] for command in containers} == set(PROJECT["scripts"])
