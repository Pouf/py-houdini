"""The Houdini-made fixtures: each scene in both containers, each with its dump."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MODELS = Path(__file__).parent.parent / "samples" / "models"
CONTAINERS = {"mime": (b"MIME-Version: 1.0\n", "Text"), "cpio": (b"070707", "Binary")}
SCENES = sorted(MODELS.glob("houdini*/*/*.hip"))


def test_fixtures_exist() -> None:
    assert SCENES


@pytest.mark.parametrize("path", SCENES, ids=lambda p: "/".join(p.parts[-3:]))
def test_container_and_dump(path: Path) -> None:
    magic, save_mode = CONTAINERS[path.parent.name]
    assert path.read_bytes().startswith(magic)
    dump = json.loads(path.with_name(path.name + ".json").read_text(encoding="ascii"))
    assert dump["save_mode"] == save_mode
    assert dump["load_warnings"] == []
    twin = path.parent.parent / ("cpio" if path.parent.name == "mime" else "mime")
    assert (twin / path.name).is_file()
