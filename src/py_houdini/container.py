"""`.hip` containers: MIME multipart (Houdini's Text save mode) and odc cpio (Binary).

Both hold an ordered list of named sections. `read_hip` splits a file into
`Section`s, keeping what is needed to write it back byte for byte;
`Container.to_bytes` rebuilds it, re-encoding only the sections that were
edited. Files that do not follow the layout Houdini writes are refused with
`FormatError` (layouts in docs/file_format.md).
"""

from __future__ import annotations

import base64
import binascii
import re

MIME_HEADER = re.compile(
    rb"MIME-Version: 1\.0\n"
    rb'Content-Type: multipart/mixed; boundary="('
    rb"HOUDINIMIMEBOUNDARY0x[0-9A-F]{8}-0x[0-9A-F]{8}-0x[0-9A-F]{8}-0x[0-9A-F]{8}HOUDINIMIMEBOUNDARY"
    rb')"\n\n'
)
# The only two part headers Houdini writes; group 2 is set for binary sections
PART_HEADER = re.compile(
    rb'Content-Disposition: attachment; filename="([^"\n]*)"\n'
    rb"Content-Type: (?:text/plain|application/octet-stream\n"
    rb"Content-Transfer-Encoding: (base64))"
)
TEXT_PART_HEADER = (
    b'Content-Disposition: attachment; filename="%s"\nContent-Type: text/plain'
)
BINARY_PART_HEADER = (
    b'Content-Disposition: attachment; filename="%s"\n'
    b"Content-Type: application/octet-stream\nContent-Transfer-Encoding: base64"
)
# Houdini encodes each 128-byte chunk on its own line
BASE64_CHUNK = 128
CPIO_MAGIC = b"070707"
CPIO_HEADER_SIZE = 76
# Magic, dev, ino, mode, uid, gid, nlink, rdev, mtime: kept as read
CPIO_PREFIX_SIZE = 59
CPIO_TRAILER = b"TRAILER!!!"
# Formats found in production files named .hip, for a clearer refusal
OTHER_FORMATS = (
    (b"HouNC", "a Houdini Apprentice scene (encrypted)"),
    (b"Ogawa", "an Alembic archive"),
    (b"FOR4", "a Maya Binary file"),
    (b"FOR8", "a Maya Binary file"),
    (b"//Maya ASCII", "a Maya ASCII file"),
    (b"docformatrev", "a Guerilla file"),
    (b"#!", "a script"),
)


class FormatError(ValueError):
    """A file that is not a Houdini scene, or one py_houdini cannot write back as is."""


class Section:
    """A named section of a `.hip` file.

    `data` is the section's content: base64-decoded for the binary parts of a
    MIME file. Untouched sections are written back from the bytes read.
    """

    __slots__ = ("_name", "_data", "_encoded", "binary", "cpio_prefix")

    def __init__(
        self,
        name: str,
        data: bytes | None,
        binary: bool = False,
        encoded: bytes | None = None,
        cpio_prefix: bytes | None = None,
    ) -> None:
        self._name = name
        self._data = data
        self._encoded = encoded
        self.binary = binary
        self.cpio_prefix = cpio_prefix

    def __repr__(self) -> str:
        return f"Section({self._name!r})"

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        # Would break the MIME part header or the cpio name
        if re.search(r'["\n\x00]', value) or not value:
            raise ValueError(f"invalid section name: {value!r}")
        self._name = value

    @property
    def data(self) -> bytes:
        if self._data is None:
            assert self._encoded is not None
            self._data = b"".join(map(binascii.a2b_base64, self._encoded.split(b"\n")))
        return self._data

    @data.setter
    def data(self, value: bytes) -> None:
        self._data = value
        self._encoded = None

    def encoded(self) -> bytes:
        """The base64 body of a binary MIME part: as read, or encoded the way Houdini does."""
        if self._encoded is None:
            data = self.data
            self._encoded = b"".join(
                base64.b64encode(data[i : i + BASE64_CHUNK]) + b"\n"
                for i in range(0, len(data), BASE64_CHUNK)
            )
        return self._encoded


class Container:
    """The sections of a `.hip` file and what its container needs to write them back."""

    def __init__(
        self, kind: str, sections: list[Section], header: bytes, boundary: bytes = b""
    ) -> None:
        # "mime" or "cpio"
        self.kind = kind
        self.sections = sections
        # MIME: the message header; cpio: the trailer's header prefix
        self.header = header
        self.boundary = boundary

    def to_bytes(self) -> bytes:
        if self.kind == "mime":
            return self._mime_bytes()
        return self._cpio_bytes()

    def _mime_bytes(self) -> bytes:
        delimiter = b"--" + self.boundary + b"\n"
        chunks = [self.header]
        for section in self.sections:
            name = section.name.encode("latin-1")
            if section.binary:
                chunks += [
                    delimiter,
                    BINARY_PART_HEADER % name,
                    b"\n\n",
                    section.encoded(),
                ]
            else:
                chunks += [delimiter, TEXT_PART_HEADER % name, b"\n\n", section.data]
            chunks.append(b"\n")
        chunks.append(b"--" + self.boundary + b"--\n")
        return b"".join(chunks)

    def _cpio_bytes(self) -> bytes:
        chunks = []
        for prefix, name, data in [
            (s.cpio_prefix, s.name.encode("latin-1"), s.data) for s in self.sections
        ] + [(self.header, CPIO_TRAILER, b"")]:
            assert prefix is not None
            chunks += [
                prefix,
                b"%06o%011o" % (len(name) + 1, len(data)),
                name,
                b"\x00",
                data,
            ]
        return b"".join(chunks)


def read_hip(data: bytes) -> Container:
    """Split `.hip` file content into sections; `FormatError` if it cannot be written back as is."""
    if data.startswith(b"MIME-Version"):
        return _read_mime(data)
    if data.startswith(CPIO_MAGIC):
        return _read_cpio(data)
    if not data:
        raise FormatError("empty file")
    for signature, description in OTHER_FORMATS:
        if data.startswith(signature):
            raise FormatError("not a Houdini scene: " + description)
    raise FormatError(f"not a Houdini scene: starts with {data[:16]!r}")


def _read_mime(data: bytes) -> Container:
    match = MIME_HEADER.match(data)
    if not match:
        if data.startswith(b"MIME-Version: 1.0\r\n"):
            raise FormatError(
                "MIME scene with CRLF line endings: not as Houdini writes it"
            )
        raise FormatError(f"unexpected MIME header: {data[:200]!r}")
    boundary = match.group(1)
    pieces = data[match.end() :].split(b"--" + boundary)
    if pieces[0] or pieces[-1] != b"--\n":
        raise FormatError("unexpected text around the MIME parts")
    sections = []
    for piece in pieces[1:-1]:
        # "\n<part header>\n\n<body>\n" between two delimiters
        split = piece.find(b"\n\n")
        part = PART_HEADER.fullmatch(piece, 1, split) if split > 0 else None
        if not piece.startswith(b"\n") or len(piece) < split + 3 or part is None:
            raise FormatError(f"unexpected MIME part: {piece[:200]!r}")
        if not piece.endswith(b"\n"):
            raise FormatError(f"MIME part without a final newline: {piece[:200]!r}")
        name = part.group(1).decode("latin-1")
        body = piece[split + 2 : -1]
        if part.group(2):
            sections.append(Section(name, None, binary=True, encoded=body))
        else:
            sections.append(Section(name, body))
    return Container("mime", sections, data[: match.end()], boundary)


def _read_cpio(data: bytes) -> Container:
    sections = []
    position = 0
    while True:
        header = data[position : position + CPIO_HEADER_SIZE]
        if not header.startswith(CPIO_MAGIC) or len(header) < CPIO_HEADER_SIZE:
            if position == len(data):
                raise FormatError("cpio scene without a trailer: truncated")
            raise FormatError(f"unexpected cpio entry at byte {position}")
        try:
            name_size, data_size = int(header[59:65], 8), int(header[65:76], 8)
        except ValueError:
            raise FormatError(f"unexpected cpio sizes at byte {position}") from None
        if header[59:76] != b"%06o%011o" % (name_size, data_size):
            raise FormatError(f"unexpected cpio sizes at byte {position}")
        start = position + CPIO_HEADER_SIZE
        name = data[start : start + name_size]
        end = start + name_size + data_size
        if name[-1:] != b"\x00" or b"\x00" in name[:-1] or end > len(data):
            raise FormatError(f"unexpected cpio entry at byte {position}")
        prefix = header[:CPIO_PREFIX_SIZE]
        position = end
        if name[:-1] == CPIO_TRAILER and data_size == 0:
            break
        sections.append(
            Section(
                name[:-1].decode("latin-1"),
                data[start + name_size : end],
                cpio_prefix=prefix,
            )
        )
    if position != len(data):
        raise FormatError("unexpected bytes after the cpio trailer")
    return Container("cpio", sections, prefix)
