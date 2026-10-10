"""hscript tokens as Houdini writes them in `.parm`, `.chn` and `.variables` sections.

Rules measured on Houdini 20.5.370 (docs/file_format.md): a token is quoted
only when empty or holding whitespace, `\\` and `"` are always escaped, nothing
else is. Menu and toggle values are quoted even when they need not be: an edit
keeps such quotes. Variable values are in single quotes, only `'` escaped.
Text is UTF-8; `surrogateescape` keeps any other byte as it was.
"""

from __future__ import annotations

import re

# One token: a quoted string, or a run of characters other than space, tab
# and newline (CR and other control characters are written raw); `\` escapes
# the next character in both
QUOTED = rb'"[^"\\]*(?:\\.[^"\\]*)*"'
UNQUOTED = rb'(?:[^ \t\n"\\]|\\.)+'
TOKEN = re.compile(QUOTED + rb"|" + UNQUOTED, re.DOTALL)
ESCAPE = re.compile(r"\\(.)", re.DOTALL)
NEEDS_QUOTES = re.compile(r"[ \t\n]|\A\Z")


def decode(raw: bytes) -> str:
    """The value of a token: quotes removed, escapes resolved."""
    text = raw.decode("utf-8", "surrogateescape")
    if text.startswith('"'):
        text = text[1:-1]
    return ESCAPE.sub(r"\1", text)


def encode(value: str, like: bytes | None = None) -> bytes:
    """A token for `value`; given the token it replaces, keep quotes Houdini forced."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    quoted = bool(NEEDS_QUOTES.search(value))
    if not quoted and like is not None and like.startswith(b'"'):
        # A quoted token that did not need it: a menu or toggle value
        quoted = not NEEDS_QUOTES.search(decode(like))
    if quoted:
        escaped = '"' + escaped + '"'
    return escaped.encode("utf-8", "surrogateescape")


def decode_variable(raw: bytes) -> str:
    """The value of a `set -g` variable from its single-quoted token."""
    return raw[1:-1].replace(b"\\'", b"'").decode("utf-8", "surrogateescape")


def encode_variable(value: str) -> bytes:
    return b"'" + value.encode("utf-8", "surrogateescape").replace(b"'", b"\\'") + b"'"
