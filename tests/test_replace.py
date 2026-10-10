"""replace_strings and remap_paths: what they reach, consistency, refusals."""

from __future__ import annotations

from pathlib import Path

import pytest

import py_houdini
from py_houdini import sections

MODELS = Path(__file__).parent.parent / "samples" / "models" / "houdini20.5.370"
SCENES = sorted(MODELS.glob("*/*.hip"))
OLD, NEW = "e101_s010_p020", "e999_s999_p999"


def scene_id(path: Path) -> str:
    return "/".join(path.parts[-2:])


def rename(value: str) -> str:
    return value.replace(OLD, NEW)


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_identity_changes_nothing(path: Path) -> None:
    data = path.read_bytes()
    scene = py_houdini.parse(path)
    assert not scene.replace_strings(lambda value: value)
    assert not scene.remap_paths(lambda value: None)
    assert scene.to_bytes() == data


@pytest.mark.parametrize("container", ["mime", "cpio"])
def test_rename_keeps_the_scene_consistent(container: str, tmp_path: Path) -> None:
    path = MODELS / container / "names.hip"
    before = py_houdini.parse(path)
    scene = py_houdini.parse(path)
    assert scene.replace_strings(rename)
    out = tmp_path / "names.hip"
    scene.save(out)
    after = py_houdini.parse(out)

    # Every node, at its renamed path
    assert sorted(n.path for n in after.nodes) == sorted(
        rename(n.path) for n in before.nodes
    )
    for node in before.nodes:
        new = after.node(rename(node.path))
        assert new.type == node.type
        assert [c.name for c in new.children] == [rename(c.name) for c in node.children]
        # Inputs, through dots and subnet inputs, name the renamed nodes
        assert new.inputs == [
            (number, rename(source) if source else None, output)
            for number, source, output in node.inputs
        ]
        # Values and expressions went through the function
        assert [[c.value for c in p.components] for p in new.parms] == [
            [rename(c.value) for c in p.components] for p in node.parms
        ]
        assert [[e.value for e in c.expressions] for c in new.channels] == [
            [rename(e.value) for e in c.expressions] for c in node.channels
        ]
    takes = sections.parse_takes(
        next(s for s in after.container.sections if s.name == ".takes").data
    )
    assert [t.text for t in takes if t.kind == "take"] == [
        b"Main",
        b"take_" + NEW.encode(),
    ]
    assert b"/obj/" + NEW.encode() + b"_cache/outer/inner/file1" in [
        t.text for t in takes if t.kind == "node"
    ]
    # Left as they were: sticky notes, network boxes, comments, user data,
    # spare parameter definitions (their defaults)
    kept = {"postitinit", "postitdef", "netboxinit", "netbox", "def", "userdata",
            "networkdotinit", "spareparmdef"}  # fmt: skip
    for section in after.container.sections:
        if OLD.encode() in section.name.encode() + section.data:
            assert section.name.rpartition(".")[2] in kept, section.name


def test_rename_clash_changes_nothing() -> None:
    path = MODELS / "mime" / "names.hip"
    data = path.read_bytes()
    scene = py_houdini.parse(path)
    # e101_s010_p020_cache would become its sibling e101_s010_p030_cache
    with pytest.raises(ValueError, match="several"):
        scene.replace_strings(lambda value: value.replace("p020", "p030"))
    assert scene.to_bytes() == data


def test_invalid_node_name_changes_nothing() -> None:
    path = MODELS / "cpio" / "names.hip"
    data = path.read_bytes()
    scene = py_houdini.parse(path)
    with pytest.raises(ValueError, match="not a node name"):
        scene.replace_strings(lambda value: value.replace("xform_", "x form "))
    assert scene.to_bytes() == data


def test_replace_reaches_variables_libraries_expressions(tmp_path: Path) -> None:
    scene = py_houdini.parse(MODELS / "mime" / "deps.hip")
    assert scene.replace_strings(
        lambda value: value.replace("//server/proj", "//other/job")
    )
    after = {v.name: v.value for v in scene.variables}
    assert after["JOB"] == "//other/job"
    channels = {c.name: c for c in scene.node("/obj/deps/file_python_expr").channels}
    expression = channels["file"].expressions[0]
    assert expression.value == '"//other/job/geo/py_%04d.bgeo.sc" % hou.frame()'
    # Code is a string like any other
    snippet = scene.node("/obj/deps/wrangle").parm("snippet").components[0].value
    assert snippet.startswith('string path = "//other/job/tex/noise.rat";')
    # $HIP is the scene's own folder: Houdini sets it when loading
    hip = py_houdini.parse(MODELS / "mime" / "deps.hip")
    assert {v.name: v.value for v in hip.variables}["HIP"] == after["HIP"]

    hda = py_houdini.parse(MODELS / "cpio" / "hda.hip")
    assert hda.replace_strings(lambda value: value.replace("py-houdini", "elsewhere"))
    assert hda.libraries[0].endswith(
        "/git/elsewhere/samples/models/houdini20.5.370/otls/py_houdini_fixture.hda"
    )


def test_remap_paths_reaches_file_parameters_only() -> None:
    path = MODELS / "cpio" / "deps.hip"
    scene = py_houdini.parse(path)
    assert scene.remap_paths(
        lambda value: (
            value.replace("//server/proj", "//other/job")
            if value.startswith("//server/proj")
            else None
        )
    )
    refs = {
        (r.node.path, r.parm): r.value
        for r in scene.file_references()
        if r.component == 0
    }
    assert refs["/obj/deps/file_unc", "file"] == "//other/job/geo/rock.bgeo.sc"
    assert refs["/img/comp/cop_file", "filename"] == "//other/job/plates/plate.$F4.exr"
    # Not file parameters: kept
    snippet = scene.node("/obj/deps/wrangle").parm("snippet").components[0].value
    assert "//server/proj/tex/noise.rat" in snippet
    assert {v.name: v.value for v in scene.variables}["JOB"] == "//server/proj"
