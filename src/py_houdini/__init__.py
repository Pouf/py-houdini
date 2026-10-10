"""py_houdini - SideFX Houdini scene file (.hip) reader and writer."""

from __future__ import annotations

from pathlib import Path

from .container import FormatError, read_hip
from .scene import Node, Scene

try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore[import,no-redef]  # Python 3.7

try:
    __version__ = importlib_metadata.version("py-houdini")
except importlib_metadata.PackageNotFoundError:
    # Running from a source tree without an installed distribution.
    __version__ = "0.0.0"

__all__ = ["FormatError", "Node", "Scene", "parse"]


def parse(path: str | Path) -> Scene:
    """Parse a `.hip` file, MIME or cpio; `FormatError` if it is not one py_houdini can write back."""
    path = Path(path)
    return Scene(read_hip(path.read_bytes()), path)
