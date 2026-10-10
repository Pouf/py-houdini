"""hscript tokens: the bytes Houdini 20.5 writes for each kind of value (docs/file_format.md)."""

from __future__ import annotations

import pytest

from py_houdini.hscript import decode, decode_variable, encode, encode_variable

# Measured in the quoting fixture and a probe with the values Houdini cannot
# read back (CR, control characters, a lone escape)
PARM_TOKENS = [
    ("plain", b"plain"),
    ("", b'""'),
    ("a b", b'"a b"'),
    ("a\tb", b'"a\tb"'),
    ("a\nb", b'"a\nb"'),
    ("a\rb", b"a\rb"),
    ("a\x01b", b"a\x01b"),
    ('a"b', b'a\\"b'),
    ("a\\b", b"a\\\\b"),
    ("\\", b"\\\\"),
    ('"', b'\\"'),
    ("a'b", b"a'b"),
    ("a;b", b"a;b"),
    ("[", b"["),
    (" lead", b'" lead"'),
    ("é", "é".encode()),
    ('$HIP/`chs("../ctrl/version")`/x', b'$HIP/`chs(\\"../ctrl/version\\")`/x'),
]


@pytest.mark.parametrize("value, raw", PARM_TOKENS)
def test_parm_tokens(value: str, raw: bytes) -> None:
    assert encode(value) == raw
    assert decode(raw) == value


@pytest.mark.parametrize(
    "value, like, raw",
    [
        # Menu and toggle values are quoted even when they need not be
        ("write", b'"read"', b'"write"'),
        ("off", b'"on"', b'"off"'),
        # A plain string was quoted for its spaces only
        ("ab", b'"a b"', b"ab"),
        ("a b", b"ab", b'"a b"'),
        ("x", b'""', b"x"),
    ],
)
def test_quotes_kept_where_houdini_forces_them(
    value: str, like: bytes, raw: bytes
) -> None:
    assert encode(value, like=like) == raw


@pytest.mark.parametrize(
    "value, raw",
    [
        ("plain", b"'plain'"),
        ("", b"''"),
        ("a'b", b"'a\\'b'"),
        ("'", b"'\\''"),
        # Backslashes are not escaped: Houdini writes a lone one as '\'
        ("\\", b"'\\'"),
        ("a\\b", b"'a\\b'"),
        ("a\nb", b"'a\nb'"),
    ],
)
def test_variable_tokens(value: str, raw: bytes) -> None:
    assert encode_variable(value) == raw
    assert decode_variable(raw) == value
