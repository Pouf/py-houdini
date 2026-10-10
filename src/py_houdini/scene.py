"""Scene model over a `.hip` container: nodes, parameters, channels, variables, libraries.

A node is a group of sections named after its path without the leading slash
(`obj/geo1.def`, `obj/geo1.parm`...); every node has a `.def`, all but the
top-level managers (`/obj`, `/out`...) an `.init` with their type. Sections are
parsed when first needed; edits splice single tokens into their section.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from . import sections
from .container import Container, FormatError, Section
from .hscript import encode, encode_variable

if TYPE_CHECKING:
    from .sections import Channel, ParmTuple, Variable


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
            dot = self.scene._sections[f"{network}/{name}.networkdotinit"]
            fields = json.loads(dot.data)["input"].split()
            if not fields:
                return None, output
            source, output = fields[0], int(fields[1])
        return f"/{network}/{source}", output


class Scene:
    def __init__(self, container: Container, path: Path | None = None) -> None:
        self.container = container
        self.path = path
        self._sections = {section.name: section for section in container.sections}
        self._nodes: dict[str, Node] = {}
        self._children: dict[str, list[Node]] = {}
        for section in container.sections:
            prefix, _, suffix = section.name.rpartition(".")
            if suffix == "def" and prefix and not prefix.startswith("."):
                node = Node(self, prefix)
                self._nodes[node.path] = node
                self._children.setdefault(prefix.rpartition("/")[0], []).append(node)

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
        return sections.parse_variables(self._sections[".variables"].data)

    def set_variable(self, name: str, value: str) -> None:
        section = self._sections[".variables"]
        for variable in sections.parse_variables(section.data):
            if variable.name == name:
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

    def to_bytes(self) -> bytes:
        return self.container.to_bytes()

    def save(self, path: str | Path) -> None:
        """Write the scene to a new file; refuses to overwrite one."""
        path = Path(path)
        with path.open("xb") as f:
            f.write(self.to_bytes())

    def save_in_place(self) -> None:
        """Overwrite the parsed file, atomically: a failed write leaves it as it was."""
        if self.path is None:
            raise ValueError("this scene was not parsed from a file")
        handle, temporary = tempfile.mkstemp(dir=str(self.path.parent), suffix=".hip")
        try:
            with os.fdopen(handle, "wb") as f:
                f.write(self.to_bytes())
            os.replace(temporary, str(self.path))
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
