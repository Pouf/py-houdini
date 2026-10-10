"""The scene model against Houdini's own view of the fixtures (`<file>.json` from dump_scene.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import py_houdini
from py_houdini.hscript import encode, encode_variable

MODELS = Path(__file__).parent.parent / "samples" / "models"
SCENES = sorted(MODELS.glob("houdini*/*/*.hip"))


def scene_id(path: Path) -> str:
    return "/".join(path.parts[-3:])


def load(path: Path) -> tuple[py_houdini.Scene, dict[str, Any]]:
    dump = json.loads(path.with_name(path.name + ".json").read_text(encoding="ascii"))
    return py_houdini.parse(path), dump


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_nodes_and_types(path: Path) -> None:
    scene, dump = load(path)
    assert sorted(n.path for n in scene.nodes) == sorted(
        n["path"] for n in dump["nodes"]
    )
    for entry in dump["nodes"]:
        node = scene.node(entry["path"])
        if node.parent is not None:
            # "Sop/file", "py_houdini::Sop/fixture_asset::1.0": the file has no category
            assert node.type == re.sub(r"[A-Za-z0-9]+/", "", entry["type"])
        if "children" in entry:
            assert [child.name for child in node.children] == entry["children"]


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_parms(path: Path) -> None:
    scene, dump = load(path)
    for entry in dump["nodes"]:
        node = scene.node(entry["path"])
        parms = {parm.name: parm for parm in node.parms}
        assert sorted(parms) == sorted(entry["parms"]), node.path
        for name, expected in entry["parms"].items():
            components = parms[name].components
            kind = entry["parm_types"][name]
            if kind == "FolderSet":
                # The file stores one value per folder, Houdini shows one parameter
                continue
            assert len(components) == len(expected), (node.path, name)
            for component, value in zip(components, expected):
                if isinstance(value, dict):
                    assert component.channel == value["name"], (node.path, name)
                    continue
                assert component.channel is None, (node.path, name)
                # Menus store their index, Houdini shows the item: compare strings only
                if kind == "String":
                    assert component.value == value, (node.path, name)


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_expressions(path: Path) -> None:
    scene, dump = load(path)
    for entry in dump["nodes"]:
        node = scene.node(entry["path"])
        channels = {channel.name: channel for channel in node.channels}
        animated = [
            value
            for values in entry["parms"].values()
            for value in values
            if isinstance(value, dict)
        ]
        assert sorted(channels) == sorted(value["name"] for value in animated), (
            node.path
        )
        for value in animated:
            expected = [
                (key["expression"], key["language"].lower())
                for key in value["keyframes"]
                if "expression" in key
            ]
            channel = channels[value["name"]]
            got = [(e.value, e.language) for e in channel.expressions]
            if scene.kind == "mime":
                # Houdini's MIME reader drops CR (docs/file_format.md)
                got = [(e.replace("\r\n", "\n"), language) for e, language in got]
            assert got == expected, (node.path, value["name"])


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_tokens_encode_back(path: Path) -> None:
    # Every token Houdini wrote is what encode() gives for its value
    scene = py_houdini.parse(path)
    for node in scene.nodes:
        for parm in node.parms:
            for component in parm.components:
                assert (
                    encode(component.value, like=component.token.raw)
                    == component.token.raw
                )
        for channel in node.channels:
            for expression in channel.expressions:
                assert (
                    encode(expression.value, like=expression.token.raw)
                    == expression.token.raw
                )
    for variable in scene.variables:
        assert encode_variable(variable.value) == variable.token.raw


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_inputs(path: Path) -> None:
    scene, dump = load(path)
    for entry in dump["nodes"]:
        node = scene.node(entry["path"])
        assert [list(i) for i in node.inputs] == entry["inputs"], node.path


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_variables_and_libraries(path: Path) -> None:
    scene, dump = load(path)
    variables = {variable.name: variable.value for variable in scene.variables}
    # ACTIVETAKE is set when loading, saved only by scenes with takes
    assert variables == {
        k: v
        for k, v in dump["variables"].items()
        if k in variables or k != "ACTIVETAKE"
    }
    assert scene.libraries == dump["libraries"]


def test_set_parm_rewrites_one_token(tmp_path: Path) -> None:
    path = MODELS / "houdini20.5.370" / "mime" / "deps.hip"
    data = path.read_bytes()
    scene = py_houdini.parse(path)
    scene.node("/obj/deps/file_unc").set_parm("file", "//elsewhere/geo/rock.bgeo.sc")
    # Menu values stay quoted, plain ones get quotes only when needed
    scene.node("/obj/deps/file_unc").set_parm("filemode", "write")
    scene.node("/obj/deps/file_drive").set_parm("file", "C:/with space/tree.bgeo.sc")
    out = tmp_path / "deps.hip"
    scene.save(out)
    assert out.read_bytes() == data.replace(
        b"\t//server/proj/geo/rock.bgeo.sc\t)", b"\t//elsewhere/geo/rock.bgeo.sc\t)", 1
    ).replace(
        b'filemode\t[ 0\tlocks=0 ]\t(\t"read"\t)',
        b'filemode\t[ 0\tlocks=0 ]\t(\t"write"\t)',
        1,
    ).replace(b"\tC:/data/geo/tree.bgeo.sc\t)", b'\t"C:/with space/tree.bgeo.sc"\t)', 1)
    again = py_houdini.parse(out)
    assert (
        again.node("/obj/deps/file_drive").parm("file").components[0].value
        == "C:/with space/tree.bgeo.sc"
    )
    with pytest.raises(FileExistsError):
        scene.save(out)


def test_set_variable(tmp_path: Path) -> None:
    path = MODELS / "houdini20.5.370" / "cpio" / "deps.hip"
    scene = py_houdini.parse(path)
    scene.set_variable("JOB", "//elsewhere/it's")
    out = tmp_path / "deps.hip"
    scene.save(out)
    assert {v.name: v.value for v in py_houdini.parse(out).variables}[
        "JOB"
    ] == "//elsewhere/it's"


def test_save_in_place(tmp_path: Path) -> None:
    out = tmp_path / "names.hip"
    out.write_bytes((MODELS / "houdini20.5.370" / "mime" / "names.hip").read_bytes())
    scene = py_houdini.parse(out)
    scene.set_variable("JOB", "//elsewhere")
    scene.save_in_place()
    assert {v.name: v.value for v in py_houdini.parse(out).variables}[
        "JOB"
    ] == "//elsewhere"
    assert [p.name for p in tmp_path.iterdir()] == ["names.hip"]
