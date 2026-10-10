"""Codecs for the text sections a scene model needs (layouts in docs/file_format.md).

Parsers work on a section's bytes and return what they found with the byte
offsets of each value, so that an edit replaces single tokens (`splice`) and
leaves every other byte as it was. A section that does not follow the layout
raises `FormatError`.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .container import FormatError
from .hscript import QUOTED, TOKEN, UNQUOTED, decode, decode_variable

PARM_TOKEN = QUOTED + rb"|" + UNQUOTED
# name<TAB>[ flags ]<TAB>(<TAB>component<TAB>...)
PARM_LINE = re.compile(
    rb"([^\t\n]+)\t\[ ([^\]\n]*) \]\t\(\t((?:(?:\[ [^\t\n]+\t(?:"
    + PARM_TOKEN
    + rb") \] |(?:"
    + PARM_TOKEN
    + rb"))\t)*)\)\n",
    re.DOTALL,
)
# An animated component is "[ <channel><TAB><value> ] "
COMPONENT = re.compile(
    rb"(?:\[ ([^\t\n]+)\t(" + PARM_TOKEN + rb") \] |(" + PARM_TOKEN + rb"))\t",
    re.DOTALL,
)
PARM_HEADER = b"{\nversion 0.8\n"
# Houdini escapes only `'` in values, so `'\'` is a backslash: a value ends at
# the quote that ends its line before the next variable
VARIABLE = re.compile(rb"set -g (\S+) = ('.*?')\n(?=set -g |\Z)", re.DOTALL)
NODE_TYPE = re.compile(rb"type = (\S+)\n")
INPUTS = re.compile(rb"\ninputs\n\{\n((?:\d+ \t[^\n]*\n)*)\}\n")
INPUT = re.compile(rb"(\d+) \t(\S+) (\d+) (\d+)\n")


class Token(NamedTuple):
    """A value in a section: its raw bytes and where they are."""

    raw: bytes
    start: int
    end: int


class Component(NamedTuple):
    token: Token
    # Set when the component is animated: its channel in the `.chn` section
    channel: str | None

    @property
    def value(self) -> str:
        return decode(self.token.raw)


class ParmTuple(NamedTuple):
    name: str
    flags: bytes
    components: list[Component]


class Expression(NamedTuple):
    token: Token
    language: str

    @property
    def value(self) -> str:
        return decode(self.token.raw)


class Channel(NamedTuple):
    name: str
    expressions: list[Expression]
    default_string: Token | None


class Variable(NamedTuple):
    name: str
    token: Token

    @property
    def value(self) -> str:
        return decode_variable(self.token.raw)


class Input(NamedTuple):
    number: int
    # A sibling node's name, or a network dot's as "(name)"
    source: Token
    output: int


def splice(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """`data` with each (start, end) span replaced; spans must not overlap."""
    chunks = []
    position = 0
    for start, end, new in sorted(edits):
        chunks += [data[position:start], new]
        position = end
    chunks.append(data[position:])
    return b"".join(chunks)


def parse_parms(data: bytes) -> list[ParmTuple]:
    if not data.startswith(PARM_HEADER):
        raise FormatError(f"unexpected .parm header: {data[:40]!r}")
    tuples = []
    position = len(PARM_HEADER)
    while not data.startswith(b"}\n", position):
        line = PARM_LINE.match(data, position)
        if not line:
            raise FormatError(
                f"unexpected .parm line: {data[position : position + 200]!r}"
            )
        components = []
        for component in COMPONENT.finditer(data, line.start(3), line.end(3)):
            if component.group(1) is not None:
                token = Token(component.group(2), component.start(2), component.end(2))
                components.append(Component(token, component.group(1).decode("ascii")))
            else:
                token = Token(component.group(3), component.start(3), component.end(3))
                components.append(Component(token, None))
        tuples.append(
            ParmTuple(
                line.group(1).decode("utf-8", "surrogateescape"),
                line.group(2),
                components,
            )
        )
        position = line.end()
    if position + 2 != len(data):
        raise FormatError("unexpected bytes after the .parm block")
    return tuples


def parse_channels(data: bytes) -> list[Channel]:
    """Channels with their segments' expressions and their default string."""
    tokens = list(TOKEN.finditer(data))
    channels: list[Channel] = []
    index = 0
    while index < len(tokens):
        word = tokens[index].group()
        if word == b"channel" and index + 1 < len(tokens):
            name = tokens[index + 1].group().decode("ascii")
            channels.append(Channel(name, [], None))
            index += 2
            continue
        is_assignment = index + 2 < len(tokens) and tokens[index + 1].group() == b"="
        if is_assignment and word in (b"expr", b"defaultString", b"language"):
            if not channels:
                raise FormatError("expression outside a channel in .chn")
            value = tokens[index + 2]
            token = Token(value.group(), value.start(), value.end())
            channel = channels[-1]
            if word == b"expr":
                channel.expressions.append(Expression(token, "hscript"))
            elif word == b"defaultString":
                channels[-1] = channel._replace(default_string=token)
            elif channel.expressions:
                last = channel.expressions[-1]
                channel.expressions[-1] = last._replace(language=decode(token.raw))
            index += 3
            continue
        index += 1
    return channels


def parse_variables(data: bytes) -> list[Variable]:
    variables = []
    position = 0
    while position < len(data):
        line = VARIABLE.match(data, position)
        if not line:
            raise FormatError(
                f"unexpected .variables line: {data[position : position + 200]!r}"
            )
        name = line.group(1).decode("utf-8", "surrogateescape")
        variables.append(
            Variable(name, Token(line.group(2), line.start(2), line.end(2)))
        )
        position = line.end()
    return variables


def parse_lines(data: bytes) -> list[Token]:
    """One value per line (`.OPlibraries`, `.order` after its count line)."""
    tokens = []
    position = 0
    for line in data.split(b"\n")[:-1]:
        tokens.append(Token(line, position, position + len(line)))
        position += len(line) + 1
    return tokens


def parse_order(data: bytes) -> list[Token]:
    """The children names in `.order`: a count line, then one name per line."""
    lines = parse_lines(data)
    if not lines or not lines[0].raw.isdigit() or int(lines[0].raw) != len(lines) - 1:
        raise FormatError(f"unexpected .order section: {data[:200]!r}")
    return lines[1:]


def parse_node_type(data: bytes) -> str:
    match = NODE_TYPE.match(data)
    if not match:
        raise FormatError(f"unexpected .init section: {data[:200]!r}")
    return match.group(1).decode("utf-8", "surrogateescape")


def parse_inputs(data: bytes) -> list[Input]:
    """The wired inputs listed in a `.def` section's `inputs` block."""
    block = INPUTS.search(data)
    if not block:
        raise FormatError("no inputs block in .def section")
    inputs = []
    position = block.start(1)
    while position < block.end(1):
        line = INPUT.match(data, position)
        if not line:
            raise FormatError(
                f"unexpected .def input: {data[position : position + 200]!r}"
            )
        source = Token(line.group(2), line.start(2), line.end(2))
        inputs.append(Input(int(line.group(1)), source, int(line.group(3))))
        position = line.end()
    return inputs
