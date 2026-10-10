"""Replacing strings across a scene, and remapping its file paths.

`replace_strings` puts every name and string a remap must reach through one
function, like a text replace over the file that keeps its structure (the
reach of a hython remap, see docs/file_format.md):
- parameter values, animated ones' stored values included;
- channel expressions and default strings;
- `set -g` variables, but `HIP`, `HIPFILE` and `HIPNAME`: Houdini sets them
  from the file's path when loading it;
- asset library paths (`.OPlibraries`, `.OPfallbacks`, `.OPpreferences`);
- take names and the values they override;
- node names, and every place that names a node: section names, the parent's
  `.order`, the inputs of its siblings and network dots, take overrides.
Parameter and channel names, node types, variable names, parameter
definitions (spare parameters' defaults), and what Houdini rebuilds or only
shows (asset definitions, user data, comments, sticky notes, network boxes and
dots names, the UI state in `.application`) are kept.

Every edit is computed and checked first: on a bad name or a clash between
renamed nodes nothing is changed.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Callable

from . import sections
from .container import FormatError
from .hscript import decode, encode, encode_variable

if TYPE_CHECKING:
    from .container import Section
    from .scene import Scene

# Measured: Houdini refuses any other character in a node name
NODE_NAME = re.compile(r"[A-Za-z0-9_.\-]+")
SCENE_PATH_VARIABLES = {"HIP", "HIPFILE", "HIPNAME"}
TYPE_LIBRARIES = (".OPfallbacks", ".OPpreferences")
TAKE_NAME = re.compile(rb"\S+")


def replace_strings(scene: Scene, fn: Callable[[str], str]) -> bool:
    """Put every name and string through `fn`; return whether anything changed."""
    renames = _renames(scene, fn)
    renamed = _Renamer(renames)
    edits: dict[Section, list[tuple[int, int, bytes]]] = defaultdict(list)
    new_data: dict[Section, bytes] = {}
    for section in scene.container.sections:
        name = section.name
        item, _, suffix = name.rpartition(".")
        network = item.rpartition("/")[0]
        if name == ".variables":
            edits[section] += _variable_edits(section.data, fn)
        elif name == ".OPlibraries":
            edits[section] += _line_edits(section.data, fn, typed=False)
        elif name in TYPE_LIBRARIES:
            edits[section] += _line_edits(section.data, fn, typed=True)
        elif name == ".takes":
            data = _replaced_takes(section.data, fn, renamed)
            if data != section.data:
                new_data[section] = data
        elif suffix == "parm":
            edits[section] += _parm_edits(section.data, fn)
        elif suffix == "chn":
            edits[section] += _channel_edits(section.data, fn)
        elif not renames:
            continue
        elif suffix == "order":
            edits[section] += [
                (token.start, token.end, renames[child].encode("ascii"))
                for token in sections.parse_order(section.data)
                for child in [f"{item}/{token.raw.decode('ascii')}"]
                if child in renames
            ]
        elif suffix == "def" and network:
            edits[section] += _source_edits(
                sections.parse_input_sources(section.data), network, renames
            )
        elif suffix == "networkdotinit":
            source = sections.parse_dot_input(section.data)
            edits[section] += _source_edits(
                [source] if source else [], network, renames
            )
    edits = {section: spans for section, spans in edits.items() if spans}
    if not (renames or edits or new_data):
        return False
    for section, spans in edits.items():
        section.data = sections.splice(section.data, spans)
    for section, data in new_data.items():
        section.data = data
    for section in scene.container.sections:
        item, dot, suffix = section.name.rpartition(".")
        if item and not item.startswith("."):
            new_item = renamed(item)
            if new_item != item:
                section.name = new_item + dot + suffix
    scene._index()
    return True


def remap_paths(scene: Scene, fn: Callable[[str], str | None]) -> bool:
    """Put every file parameter value and asset library path through `fn`
    (None keeps a path); return whether anything changed."""

    def keep_none(value: str) -> str:
        new = fn(value)
        return value if new is None else new

    edits: dict[Section, list[tuple[int, int, bytes]]] = defaultdict(list)
    for node in scene.nodes:
        file_parms = node.file_parms
        section = node.section("parm")
        if not file_parms or section is None:
            continue
        for parm in node.parms:
            if parm.name in file_parms:
                edits[section] += _component_edits(parm.components, keep_none)
    for name, typed in [(".OPlibraries", False), *((n, True) for n in TYPE_LIBRARIES)]:
        library_section = scene._sections.get(name)
        if library_section is not None:
            edits[library_section] += _line_edits(
                library_section.data, keep_none, typed
            )
    edits = {section: spans for section, spans in edits.items() if spans}
    for section, spans in edits.items():
        section.data = sections.splice(section.data, spans)
    return bool(edits)


class _Renamer:
    """The new path stem of a node or network item once its networks are renamed."""

    def __init__(self, renames: dict[str, str]) -> None:
        self.renames = renames
        self.cache: dict[str, str] = {}

    def __call__(self, item: str) -> str:
        if not self.renames:
            return item
        if item not in self.cache:
            network, _, name = item.rpartition("/")
            name = self.renames.get(item, name)
            self.cache[item] = f"{self(network)}/{name}" if network else name
        return self.cache[item]


def _renames(scene: Scene, fn: Callable[[str], str]) -> dict[str, str]:
    """The new name of each node `fn` renames, by path stem; checks the result."""
    renames = {}
    for node in scene.nodes:
        # The top-level managers (/obj, /out...) are not the scene's to name
        if "/" not in node.prefix:
            continue
        new = fn(node.name)
        if new != node.name:
            if not NODE_NAME.fullmatch(new):
                raise ValueError(
                    f"cannot rename {node.path} to {new!r}: not a node name"
                )
            renames[node.prefix] = new
    if renames:
        items = defaultdict(set)
        for section in scene.container.sections:
            item = section.name.rpartition(".")[0]
            network, _, _ = item.rpartition("/")
            if network:
                items[network].add(item)
        for network, prefixes in items.items():
            names = Counter(renames.get(p, p.rpartition("/")[2]) for p in prefixes)
            clashes = sorted(name for name, count in names.items() if count > 1)
            if clashes:
                raise ValueError(
                    f"renaming nodes would give /{network} several {clashes}"
                )
    return renames


def _component_edits(
    components: list[sections.Component], fn: Callable[[str], str]
) -> list[tuple[int, int, bytes]]:
    edits = []
    for component in components:
        value = component.value
        new = fn(value)
        if new != value:
            token = component.token
            edits.append((token.start, token.end, encode(new, like=token.raw)))
    return edits


def _parm_edits(data: bytes, fn: Callable[[str], str]) -> list[tuple[int, int, bytes]]:
    return [
        edit
        for parm in sections.parse_parms(data)
        for edit in _component_edits(parm.components, fn)
    ]


def _channel_edits(
    data: bytes, fn: Callable[[str], str]
) -> list[tuple[int, int, bytes]]:
    edits = []
    for channel in sections.parse_channels(data):
        tokens = [expression.token for expression in channel.expressions]
        if channel.default_string is not None:
            tokens.append(channel.default_string)
        for token in tokens:
            value = decode(token.raw)
            new = fn(value)
            if new != value:
                edits.append((token.start, token.end, encode(new, like=token.raw)))
    return edits


def _variable_edits(
    data: bytes, fn: Callable[[str], str]
) -> list[tuple[int, int, bytes]]:
    edits = []
    for variable in sections.parse_variables(data):
        if variable.name in SCENE_PATH_VARIABLES:
            continue
        value = variable.value
        new = fn(value)
        if new != value:
            token = variable.token
            edits.append((token.start, token.end, encode_variable(new)))
    return edits


def _line_edits(
    data: bytes, fn: Callable[[str], str], typed: bool
) -> list[tuple[int, int, bytes]]:
    """A path per line, after "<Category>/<type> " when `typed`."""
    edits = []
    for token in sections.parse_lines(data):
        space = token.raw.find(b" ")
        if typed and space < 0:
            raise FormatError(f"unexpected library line: {token.raw[:200]!r}")
        start = token.start + (space + 1 if typed else 0)
        value = data[start : token.end].decode("utf-8", "surrogateescape")
        new = fn(value)
        if new != value:
            if "\n" in new:
                raise ValueError(f"a library path cannot hold a newline: {new!r}")
            edits.append((start, token.end, new.encode("utf-8", "surrogateescape")))
    return edits


def _source_edits(
    sources: list[sections.Token], network: str, renames: dict[str, str]
) -> list[tuple[int, int, bytes]]:
    # "(name)" sources are dots or the network's inputs: never renamed
    return [
        (token.start, token.end, renames[sibling].encode("ascii"))
        for token in sources
        for sibling in [f"{network}/{token.raw.decode('ascii')}"]
        if sibling in renames
    ]


def _replaced_takes(data: bytes, fn: Callable[[str], str], renamed: _Renamer) -> bytes:
    items = []
    for item in sections.parse_takes(data):
        if item.kind == "take":
            name = item.text.decode("utf-8", "surrogateescape")
            new = fn(name).encode("utf-8", "surrogateescape")
            if not TAKE_NAME.fullmatch(new):
                raise ValueError(f"cannot rename take {name!r} to {new!r}")
            item = item._replace(text=new)
        elif item.kind == "node" and item.text.startswith(b"/"):
            path = item.text.decode("ascii")
            item = item._replace(text=("/" + renamed(path[1:])).encode("ascii"))
        elif item.kind == "parms":
            item = item._replace(
                text=sections.splice(item.text, _parm_edits(item.text, fn))
            )
        items.append(item)
    return sections.encode_takes(items)
