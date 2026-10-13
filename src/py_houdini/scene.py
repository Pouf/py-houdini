"""Scene model over a `.hip` container: nodes, parameters, channels, variables, libraries.

A node is a group of sections named after its path without the leading slash
(`obj/geo1.def`, `obj/geo1.parm`...); every node has a `.def`, all but the
top-level managers (`/obj`, `/out`...) an `.init` with their type. Sections are
parsed when first needed; edits splice single tokens into their section.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from . import hda, replace, sections
from .container import Container, FormatError, Section
from .data.node_types import CHILD_CATEGORIES as CHILD_CATEGORIES_BY_KEY
from .data.node_types import FILE_PARMS, MANAGERS
from .hscript import encode, encode_variable

if TYPE_CHECKING:
    from typing import Callable

    from .sections import Channel, ParmTuple, Variable

# By (category, type name as .init sections write it)
BUILTIN_FILE_PARMS = {
    hda.split_type_key(key): parms for key, parms in FILE_PARMS.items()
}
CHILD_CATEGORIES = {
    hda.split_type_key(key): category
    for key, category in CHILD_CATEGORIES_BY_KEY.items()
}
# $NAME or ${NAME}
VARIABLE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


class Node:
    def __init__(self, scene: Scene, prefix: str) -> None:
        self.scene = scene
        # Path without the leading slash: the sections' name stem
        self.prefix = prefix

    def __repr__(self) -> str:
        return f"Node({self.path!r})"

    @property
    def path(self) -> str:
        return "/" + self.prefix

    @property
    def name(self) -> str:
        return self.prefix.rpartition("/")[2]

    @property
    def parent(self) -> Node | None:
        """None for the top-level managers, and for nodes inside a locked asset
        whose network the file does not hold (editable nodes of an asset)."""
        stem = self.prefix.rpartition("/")[0]
        return self.scene._nodes.get("/" + stem) if stem else None

    @property
    def type(self) -> str | None:
        """The node type as `.init` names it; None for the top-level managers."""
        section = self.section("init")
        return sections.parse_node_type(section.data) if section else None

    @property
    def children(self) -> list[Node]:
        children = self.scene._children.get(self.prefix, [])
        order = self.section("order")
        if order is None:
            return list(children)
        by_name = {child.name: child for child in children}
        names = [
            token.raw.decode("ascii") for token in sections.parse_order(order.data)
        ]
        if sorted(names) != sorted(by_name):
            raise FormatError(f"{self.path}.order does not list the node's children")
        return [by_name[name] for name in names]

    def section(self, suffix: str) -> Section | None:
        return self.scene._sections.get(self.prefix + "." + suffix)

    @property
    def parms(self) -> list[ParmTuple]:
        section = self.section("parm")
        return sections.parse_parms(section.data) if section else []

    def parm(self, name: str) -> ParmTuple:
        for parm in self.parms:
            if parm.name == name:
                return parm
        raise KeyError(f"{self.path} has no parameter {name!r}")

    def set_parm(self, name: str, value: str, index: int = 0) -> None:
        """Set a component's value; an animated one keeps its channel."""
        component = self.parm(name).components[index]
        section = self.section("parm")
        assert section is not None
        token = component.token
        new = encode(value, like=token.raw)
        section.data = sections.splice(section.data, [(token.start, token.end, new)])

    @property
    def channels(self) -> list[Channel]:
        section = self.section("chn")
        return sections.parse_channels(section.data) if section else []

    @property
    def inputs(self) -> list[tuple[int, str | None, int]]:
        """Wired inputs: (input index, source node path, source output), as Houdini
        reports them: through network dots, and through the subnet inputs to what
        is wired outside (no path when nothing is)."""
        section = self.section("def")
        network = self.prefix.rpartition("/")[0]
        if section is None or not network:
            return []
        return [
            (
                wire.number,
                *self._source(network, wire.source.raw.decode("ascii"), wire.output),
            )
            for wire in sections.parse_inputs(section.data)
        ]

    def _source(self, network: str, source: str, output: int) -> tuple[str | None, int]:
        # "(name)" is a network dot, "(<digits>)" the network's own input
        while source.startswith("("):
            name = source[1:-1]
            if name.isdigit():
                subnet = self.scene._nodes.get("/" + network)
                for number, path, subnet_output in subnet.inputs if subnet else []:
                    if number == int(name):
                        return path, subnet_output
                return None, output
            dot = self.scene._sections.get(f"{network}/{name}.networkdotinit")
            if dot is None:
                # Part of a locked asset's contents, which the file does not hold
                return None, output
            fields = json.loads(dot.data)["input"].split()
            if not fields:
                return None, output
            source, output = fields[0], int(fields[1])
        return f"/{network}/{source}", output

    @property
    def category(self) -> str | None:
        """The category of the node's type (Sop, Object...), as its network's type
        sets it; None when the file does not tell (a network of an unknown asset type)."""
        stem = self.prefix.rpartition("/")[0]
        if not stem:
            return "Manager"
        if "/" not in stem:
            return MANAGERS.get(stem)
        parent = self.parent
        if parent is None or parent.type is None or parent.category is None:
            return None
        return CHILD_CATEGORIES.get((parent.category, parent.type))

    @property
    def file_parms(self) -> dict[str, tuple[str, str]]:
        """The node's parameter tuples that name a file, as Houdini types them:
        name > (file type, file chooser mode: "read", "write", "read_and_write" or "")."""
        category = self.category
        # The top-level networks' sections have no type: they go by name
        type_name = self.name if category == "Manager" else self.type
        templates = self.scene._type_file_parms(category, type_name)
        spare = self.section("spareparmdef")
        if spare is not None:
            templates = {**templates, **hda.file_parms(spare.data)}
        if not templates:
            return {}
        instances = [
            (re.compile(re.escape(name).replace(r"\#", r"\d+")), info)
            for name, info in templates.items()
            if "#" in name
        ]
        found = {}
        for parm in self.parms:
            info = templates.get(parm.name)
            if info is None:
                # A multiparm instance: "layer2" of "layer#"
                info = next((i for p, i in instances if p.fullmatch(parm.name)), None)
            if info is not None:
                found[parm.name] = info
        return found


class FileReference(NamedTuple):
    """A file parameter component, its value as stored (unexpanded)."""

    node: Node
    parm: str
    # Index of the component in the tuple
    component: int
    value: str
    file_type: str
    # The file chooser's mode: "read", "write", "read_and_write" or ""
    mode: str
    # The value comes from an expression in the node's channels
    animated: bool


class Scene:
    def __init__(self, container: Container, path: Path | None = None) -> None:
        self.container = container
        self.path = path
        self._index()
        self._file_parms: dict[tuple[str | None, str], dict[str, tuple[str, str]]] = {}
        self._definitions: dict[tuple[str, str], bytes] | None = None

    def _index(self) -> None:
        """Sections by name and nodes by path, again after renames."""
        self._sections = {section.name: section for section in self.container.sections}
        self._nodes: dict[str, Node] = {}
        self._children: dict[str, list[Node]] = {}
        for section in self.container.sections:
            prefix, _, suffix = section.name.rpartition(".")
            if suffix == "def" and prefix and not prefix.startswith("."):
                node = Node(self, prefix)
                self._nodes[node.path] = node
                self._children.setdefault(prefix.rpartition("/")[0], []).append(node)

    def _type_file_parms(
        self, category: str | None, type_name: str | None
    ) -> dict[str, tuple[str, str]]:
        """A node type's file parameters: Houdini's own types', and the scene's
        asset definitions (they win: the scene's version of the asset); any
        category when it is unknown. A definition does not type the parameters
        its asset inherits (an object's `pickscript`): only Houdini's types do."""
        if type_name is None:
            return {}
        key = (category, type_name)
        if key not in self._file_parms:
            if self._definitions is None:
                section = self._sections.get(".OPdummydefs")
                self._definitions = hda.definitions(section.data) if section else {}
            found: dict[str, tuple[str, str]] = {}
            for (cat, name), parms in BUILTIN_FILE_PARMS.items():
                if name == type_name and category in (None, cat):
                    found.update(parms)
            for (cat, name), script in self._definitions.items():
                if name == type_name and category in (None, cat):
                    found.update(hda.file_parms(script))
            self._file_parms[key] = found
        return self._file_parms[key]

    def file_references(self) -> list[FileReference]:
        """Every component of every file parameter, empty or not, inputs and outputs."""
        references = []
        for node in self.nodes:
            file_parms = node.file_parms
            if not file_parms:
                continue
            for parm in node.parms:
                if parm.name not in file_parms:
                    continue
                file_type, mode = file_parms[parm.name]
                references += [
                    FileReference(
                        node,
                        parm.name,
                        index,
                        component.value,
                        file_type,
                        mode,
                        component.channel is not None,
                    )
                    for index, component in enumerate(parm.components)
                ]
        return references

    def expand(
        self, value: str, path: str | Path | None = None, node: Node | None = None
    ) -> str:
        """`value` with the scene's variables replaced ($JOB, $HIP...), others kept ($F4).

        `$HIP`, `$HIPFILE` and `$HIPNAME` come from `path` (default: the parsed
        file's), as Houdini sets them when loading a file, not from the values
        saved in it. Given the node the value belongs to, `$OS` is its name.
        """
        variables = {variable.name: variable.value for variable in self.variables}
        if node is not None:
            variables["OS"] = node.name
        path = Path(path) if path is not None else self.path
        if path is not None:
            absolute = Path(os.path.abspath(str(path)))
            variables["HIP"] = absolute.parent.as_posix()
            variables["HIPFILE"] = absolute.as_posix()
            variables["HIPNAME"] = absolute.stem
        return VARIABLE.sub(
            lambda match: variables.get(
                match.group(1) or match.group(2), match.group()
            ),
            value,
        )

    @property
    def kind(self) -> str:
        """The container: "mime" (Houdini's Text save mode) or "cpio" (Binary)."""
        return self.container.kind

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def node(self, path: str) -> Node:
        try:
            return self._nodes[path]
        except KeyError:
            raise KeyError(f"no node {path!r}") from None

    @property
    def variables(self) -> list[Variable]:
        """The `set -g` variables saved with the scene."""
        # Near-empty production scenes have no .variables section
        section = self._sections.get(".variables")
        return sections.parse_variables(section.data) if section else []

    def set_variable(self, name: str, value: str) -> None:
        for variable in self.variables:
            if variable.name == name:
                section = self._sections[".variables"]
                token = variable.token
                new = encode_variable(value)
                section.data = sections.splice(
                    section.data, [(token.start, token.end, new)]
                )
                return
        raise KeyError(f"no variable {name!r}")

    @property
    def libraries(self) -> list[str]:
        """The asset libraries the scene installs (`.OPlibraries`)."""
        section = self._sections.get(".OPlibraries")
        if section is None:
            return []
        return [
            token.raw.decode("utf-8", "surrogateescape")
            for token in sections.parse_lines(section.data)
        ]

    @property
    def fallback_libraries(self) -> list[tuple[str, str]]:
        """(type, library) of the asset types the scene uses from libraries it does
        not install (`.OPfallbacks`: each with the path it was loaded from, then a
        relative `otls/...` form)."""
        return self._type_libraries(".OPfallbacks")

    @property
    def preferred_libraries(self) -> list[tuple[str, str]]:
        """(type, library) the scene prefers a type's definition from (`.OPpreferences`)."""
        return self._type_libraries(".OPpreferences")

    def _type_libraries(self, name: str) -> list[tuple[str, str]]:
        section = self._sections.get(name)
        pairs = []
        for token in sections.parse_lines(section.data) if section else []:
            # "<Category>/<type> <path>": a path may hold spaces, a type cannot
            type_key, _, library = token.raw.decode(
                "utf-8", "surrogateescape"
            ).partition(" ")
            if not library:
                raise FormatError(f"unexpected {name} line: {token.raw!r}")
            pairs.append((type_key, library))
        return pairs

    def replace_strings(self, fn: Callable[[str], str]) -> bool:
        """Put every name and string through `fn`, node names included, keeping
        the scene consistent (what is reached: `py_houdini.replace`); return
        whether anything changed. Nothing changes if a new node name is invalid
        or clashes."""
        return replace.replace_strings(self, fn)

    def remap_paths(self, fn: Callable[[str], str | None]) -> bool:
        """Put every file parameter value and asset library path through `fn`
        (None keeps a path); return whether anything changed."""
        return replace.remap_paths(self, fn)

    def to_bytes(self) -> bytes:
        return self.container.to_bytes()

    def save(self, path: str | Path) -> None:
        """Write the scene to a new file, atomically: a failed write leaves no
        file. Refuses to overwrite one (`FileExistsError`)."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")
        self._write(path)

    def save_in_place(self) -> None:
        """Overwrite the parsed file, atomically: a failed write leaves it as it was."""
        if self.path is None:
            raise ValueError("this scene was not parsed from a file")
        self._write(self.path)

    def _write(self, target: Path) -> None:
        data = self.to_bytes()
        # Opened like any new file (not `mkstemp`, which makes it private to
        # its owner on POSIX), under a unique name no user file carries.
        temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as f:
                f.write(data)
            os.replace(temporary, target)
        finally:
            if temporary.exists():  # missing_ok needs Python 3.8
                temporary.unlink()
