"""MIME and cpio containers: byte-identical round-trip, edits, refusals."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable

import pytest

from py_houdini.container import FormatError, read_hip

MODELS = Path(__file__).parent.parent / "samples" / "models"
SCENES = sorted(MODELS.glob("houdini*/*/*.hip"))
MIME_SCENES = [p for p in SCENES if p.parent.name == "mime"]


def scene_id(path: Path) -> str:
    return "/".join(path.parts[-3:])


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_round_trip(path: Path) -> None:
    data = path.read_bytes()
    container = read_hip(data)
    assert container.kind == path.parent.name
    assert container.to_bytes() == data
    # Decoding binary sections does not change what is written
    for section in container.sections:
        assert section.data is not None
    assert container.to_bytes() == data


@pytest.mark.parametrize("path", MIME_SCENES, ids=scene_id)
def test_twins_hold_the_same_sections(path: Path) -> None:
    mime = read_hip(path.read_bytes())
    cpio = read_hip((path.parent.parent / "cpio" / path.name).read_bytes())
    assert [s.name for s in mime.sections] == [s.name for s in cpio.sections]
    differing = {
        s.name for s, t in zip(mime.sections, cpio.sections) if s.data != t.data
    }
    # Save paths and times, and user data (JSON in MIME, binary in cpio)
    assert all(
        name == ".variables" or name.endswith((".def", ".userdata"))
        for name in differing
    )


@pytest.mark.parametrize("path", SCENES, ids=scene_id)
def test_edit_rewrites_only_the_edited_section(path: Path) -> None:
    data = path.read_bytes()
    original = read_hip(data)
    container = read_hip(data)
    section = next(s for s in container.sections if s.name == ".variables")
    section.data = section.data.replace(b"HIPNAME = '", b"HIPNAME = 'renamed_")
    edited = container.to_bytes()
    again = read_hip(edited)
    assert [s.name for s in again.sections] == [s.name for s in original.sections]
    for before, after in zip(original.sections, again.sections):
        expected = section.data if before.name == ".variables" else before.data
        assert after.data == expected
        assert after.cpio_prefix == before.cpio_prefix
    if container.kind == "mime":
        assert edited.replace(b"HIPNAME = 'renamed_", b"HIPNAME = '") == data


def test_binary_section_reencoded_like_houdini() -> None:
    container = read_hip((MODELS / "houdini20.5.370" / "mime" / "hda.hip").read_bytes())
    section = next(s for s in container.sections if s.name == ".OPdummydefs")
    encoded = section.encoded()
    section.data = section.data
    # 128 bytes per line, as in every production file
    assert section.encoded() == encoded
    lines = encoded.split(b"\n")
    assert {len(line) for line in lines[:-2]} == {172}
    section.data = b"x" * 300
    assert section.encoded() == b"".join(
        base64.b64encode(chunk) + b"\n" for chunk in (b"x" * 128, b"x" * 128, b"x" * 44)
    )
    assert (
        read_hip(container.to_bytes()).sections[container.sections.index(section)].data
        == b"x" * 300
    )


def test_renamed_cpio_section_gets_its_new_size() -> None:
    container = read_hip(
        (MODELS / "houdini20.5.370" / "cpio" / "names.hip").read_bytes()
    )
    section = next(s for s in container.sections if s.name.endswith("/ctrl.parm"))
    section.name = "obj/a_much_longer_control_name.parm"
    again = read_hip(container.to_bytes())
    assert "obj/a_much_longer_control_name.parm" in [s.name for s in again.sections]


@pytest.mark.parametrize("name", ["", 'a"b', "a\nb", "a\x00b"])
def test_invalid_section_names(name: str) -> None:
    container = read_hip(
        (MODELS / "houdini20.5.370" / "mime" / "empty.hip").read_bytes()
    )
    with pytest.raises(ValueError):
        container.sections[0].name = name


def test_mime_without_parts() -> None:
    data = (MODELS / "houdini20.5.370" / "mime" / "empty.hip").read_bytes()
    header, _, _ = data.partition(b"\n\n")
    boundary = header.split(b'boundary="')[1].rstrip(b'"')
    empty = header + b"\n\n--" + boundary + b"--\n"
    container = read_hip(empty)
    assert container.sections == []
    assert container.to_bytes() == empty


def test_base64_kept_as_read() -> None:
    # A layout Houdini does not write still round-trips while untouched
    data = (MODELS / "houdini20.5.370" / "mime" / "empty.hip").read_bytes()
    container = read_hip(data)
    section = next(s for s in container.sections if s.binary)
    payload = section.data
    odd = base64.encodebytes(payload)
    rewritten = data.replace(section.encoded(), odd)
    assert rewritten != data
    again = read_hip(rewritten)
    assert again.to_bytes() == rewritten
    assert next(s for s in again.sections if s.binary).data == payload


def cut_cpio_after_last_entry(data: bytes) -> bytes:
    return data[: data.rindex(b"070707")]


@pytest.mark.parametrize(
    "make, message",
    [
        (lambda d: d.replace(b"\n", b"\r\n"), "CRLF"),
        (lambda d: d[: d.rindex(b"--HOUDINI")], "around the MIME parts"),
        (lambda d: d + b"\n", "around the MIME parts"),
        (
            lambda d: d.replace(
                b"Content-Type: text/plain", b"Content-Type: text/html", 1
            ),
            "MIME part",
        ),
    ],
    ids=["crlf", "no end", "trailing newline", "part header"],
)
def test_refused_mime(make: Callable[[bytes], bytes], message: str) -> None:
    data = (MODELS / "houdini20.5.370" / "mime" / "empty.hip").read_bytes()
    with pytest.raises(FormatError, match=message):
        read_hip(make(data))


@pytest.mark.parametrize(
    "make, message",
    [
        (cut_cpio_after_last_entry, "truncated"),
        (lambda d: d + b"\x00", "after the cpio trailer"),
        (lambda d: d[:-30], "unexpected cpio entry"),
        (lambda d: d[:59] + b" 00011" + d[65:], "sizes"),
    ],
    ids=["no trailer", "trailing byte", "cut", "padded size"],
)
def test_refused_cpio(make: Callable[[bytes], bytes], message: str) -> None:
    data = (MODELS / "houdini20.5.370" / "cpio" / "empty.hip").read_bytes()
    with pytest.raises(FormatError, match=message):
        read_hip(make(data))


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "empty file"),
        (b"HouNC\x1a103360rest", "Apprentice"),
        (b"Ogawa\xff\x00\x01", "Alembic"),
        (b"FOR8\x00\x00\x00\x00", "Maya Binary"),
        (b"//Maya ASCII 2022 scene", "Maya ASCII"),
        (b"docformatrev 1", "Guerilla"),
        (b"#! C:/Program Files/hscript", "script"),
        (b"PK\x03\x04", "starts with"),
    ],
)
def test_not_houdini_scenes(data: bytes, message: str) -> None:
    with pytest.raises(FormatError, match=message):
        read_hip(data)
