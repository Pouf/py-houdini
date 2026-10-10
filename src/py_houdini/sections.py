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
# name<TAB>[ flags ]<TAB>(<TAB>component<TAB>...)\n
PARM_START = re.compile(rb"([^\t\n]+)\t\[ ([^\]\n]*) \]\t\(\t")
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
# Both blocks name the sources: "<input> \t<source> ..." lines. The newline
# after "}" is left unmatched: it starts the next block's line.
INPUT_BLOCKS = re.compile(
    rb"\n(?:inputs|inputsNamed3)\n\{\n((?:\d+ \t[^\n]*\n)*)\}(?=\n)"
)
INPUT_SOURCE = re.compile(rb"\d+ \t(\S+) ")
# A network dot's input: "<node> <output> <?>"
DOT_INPUT = re.compile(rb'"input":"([^" ]+) ')
TAKES_HEADER = b"HoudiniTakeFile 1.0\n"
TAKE_LINE = re.compile(rb"take name (\S+) kids (\d+)\n")


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
        line = PARM_START.match(data, position)
        if not line:
            raise FormatError(
                f"unexpected .parm line: {data[position : position + 200]!r}"
            )
        position = line.end()
        components = []
        while not data.startswith(b")\n", position):
            component = COMPONENT.match(data, position)
            if not component:
                raise FormatError(
                    f"unexpected .parm value: {data[position : position + 200]!r}"
                )
            if component.group(1) is not None:
                token = Token(component.group(2), component.start(2), component.end(2))
                components.append(Component(token, component.group(1).decode("ascii")))
            else:
                token = Token(component.group(3), component.start(3), component.end(3))
                components.append(Component(token, None))
            position = component.end()
        tuples.append(
            ParmTuple(
                line.group(1).decode("utf-8", "surrogateescape"),
                line.group(2),
                components,
            )
        )
        position += 2
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


def parse_input_sources(data: bytes) -> list[Token]:
    """Every source a `.def` section names, in its `inputs` and `inputsNamed3`
    blocks: a sibling node, a network dot "(name)" or the network's input "(0)"."""
    sources = []
    for block in INPUT_BLOCKS.finditer(data):
        position = block.start(1)
        while position < block.end(1):
            match = INPUT_SOURCE.match(data, position)
            if not match:
                raise FormatError(
                    f"unexpected .def input: {data[position : position + 200]!r}"
                )
            sources.append(Token(match.group(1), match.start(1), match.end(1)))
            position = data.index(b"\n", position) + 1
    return sources


def parse_dot_input(data: bytes) -> Token | None:
    """The node a network dot (`.networkdotinit` JSON) is wired from, if any."""
    match = DOT_INPUT.search(data)
    return Token(match.group(1), match.start(1), match.end(1)) if match else None


class TakeItem(NamedTuple):
    """A `.takes` line or record. kind "take": `text` is the take's name and
    `extra` its child count; "node": `text` is a node path; "parms": `text` is
    a `.parm` block and `extra` the record's first line; "other": the record."""

    kind: str
    text: bytes
    extra: bytes = b""


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def parse_takes(data: bytes) -> list[TakeItem]:
    """`HoudiniTakeFile 1.0`, then per take its "take name" line and records,
    each a big-endian u32 length then text (docs/file_format.md)."""
    if not data.startswith(TAKES_HEADER):
        raise FormatError(f"unexpected .takes header: {data[:40]!r}")
    items = []
    position = len(TAKES_HEADER)
    while position < len(data):
        take = TAKE_LINE.match(data, position)
        if take:
            items.append(TakeItem("take", take.group(1), take.group(2)))
            position = take.end()
            continue
        size = int.from_bytes(data[position : position + 4], "big")
        record = data[position + 4 : position + 4 + size]
        if len(record) != size:
            raise FormatError(".takes record cut short")
        position += 4 + size
        if record.startswith(b"s 0 ") and record.endswith(b"\n"):
            items.append(TakeItem("node", record[4:-1]))
        elif record.startswith(b"d "):
            head = record[: record.index(b"\n") + 1]
            block = record[len(head) + 4 :]
            if int.from_bytes(record[len(head) : len(head) + 4], "big") != len(block):
                raise FormatError("unexpected .takes data record")
            items.append(TakeItem("parms", block, head))
        else:
            items.append(TakeItem("other", record))
    return items


def encode_takes(items: list[TakeItem]) -> bytes:
    chunks = [TAKES_HEADER]
    for item in items:
        if item.kind == "take":
            chunks.append(b"take name %s kids %s\n" % (item.text, item.extra))
        elif item.kind == "node":
            chunks += [_u32(len(item.text) + 5), b"s 0 ", item.text, b"\n"]
        elif item.kind == "parms":
            record = item.extra + _u32(len(item.text)) + item.text
            chunks += [_u32(len(record)), record]
        else:
            chunks += [_u32(len(item.text)), item.text]
    return b"".join(chunks)
