"""Asset definitions: `INDX` libraries (the `.hda`/`.otl` layout) and their dialog scripts.

A scene's `.OPdummydefs` section is such a library: it holds the definition of
every asset type the scene uses, so the scene loads without their libraries
(docs/file_format.md). A definition is itself an `INDX` whose `DialogScript`
section declares the type's parameters, in the syntax `.spareparmdef`
sections use for spare parameters.
"""

from __future__ import annotations

import re

from .container import FormatError
from .hscript import TOKEN, decode

# Dialog script parameter types that name a file, and the file type Houdini
# gives them
FILE_TYPES = {
    "file": "Any",
    "geometry": "Geometry",
    "image": "Image",
    "directory": "Directory",
}
# "[namespace::]Category/name[::version]", as library entries name types
TYPE_KEY = re.compile(r"(?:(.+)::)?([A-Za-z0-9]+)/(.+)")


def split_type_key(key: str) -> tuple[str, str]:
    """(category, type name as `.init` sections write it) of a "Sop/name" style key."""
    match = TYPE_KEY.fullmatch(key)
    if not match:
        raise ValueError(f"not a node type key: {key!r}")
    namespace, category, name = match.groups()
    return category, f"{namespace}::{name}" if namespace else name


def read_indx(data: bytes) -> list[tuple[str, bytes]]:
    """The (name, content) entries of an `INDX` library."""

    def u32(position: int) -> int:
        if position + 4 > len(data):
            raise FormatError("INDX index cut short")
        return int.from_bytes(data[position : position + 4], "big")

    if not data.startswith(b"INDX"):
        raise FormatError(f"not an INDX library: {data[:16]!r}")
    count = u32(12)
    position = 16
    entries = []
    for _ in range(count):
        size = u32(position)
        name = data[position + 4 : position + 4 + size].decode(
            "utf-8", "surrogateescape"
        )
        position += 4 + size
        # Offset and size of the content, then a modification time
        entries.append((name, u32(position), u32(position + 4)))
        position += 12
    contents = []
    for name, offset, size in entries:
        if position + offset + size > len(data):
            raise FormatError(f"INDX entry {name!r} beyond the library")
        contents.append((name, data[position + offset : position + offset + size]))
    return contents


def definitions(data: bytes) -> dict[tuple[str, str], bytes]:
    """The dialog script of each asset type in an `INDX` library, by (category, type)."""
    scripts = {}
    for name, content in read_indx(data):
        if not TYPE_KEY.fullmatch(name) or not content.startswith(b"INDX"):
            continue  # the library's own index and description sections
        for section, script in read_indx(content):
            if section == "DialogScript":
                scripts[split_type_key(name)] = script
    return scripts


def file_parms(script: bytes) -> dict[str, tuple[str, str]]:
    """The file parameters a dialog script declares: name > (file type, chooser mode).

    Multiparm instances keep their `#` (`layer#`).
    """
    found = {}
    # The keyword each open brace belongs to, and the parameter being read
    blocks: list[bytes] = []
    name = kind = mode = None
    tokens = [match.group() for match in TOKEN.finditer(script)]
    for index, token in enumerate(tokens):
        if token == b"{":
            blocks.append(tokens[index - 1] if index else b"")
            if blocks[-1] == b"parm":
                name = kind = mode = None
        elif token == b"}":
            if blocks and blocks.pop() == b"parm" and name and kind in FILE_TYPES:
                found[name] = (FILE_TYPES[kind], mode or "")
        elif blocks and blocks[-1] == b"parm" and index + 1 < len(tokens):
            if token == b"name" and name is None:
                name = decode(tokens[index + 1])
            elif token == b"type":
                kind = decode(tokens[index + 1])
        elif blocks[-2:] == [b"parm", b"parmtag"] and token == b'"filechooser_mode"':
            mode = decode(tokens[index + 1])
    return found
