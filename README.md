# py_houdini
`py_houdini` is a Python package for reading and editing SideFX Houdini scene files (`.hip`) without Houdini.

Sibling project of [py-maya](https://github.com/Pouf/py-maya).

## About

A `.hip` file is a list of named sections (scene settings, then a few sections per node) stored either as a MIME multipart message (Houdini's "Text" save mode) or as a cpio archive ("Binary"). This package will read and edit both, keeping every byte it does not change, so that tools can list and replace a scene's file dependencies on machines and farms without a Houdini licence.

## Status

Pre-alpha: nothing usable yet. The plan, in order:

* Byte-identical round-trip of both containers, refusing files that cannot be reproduced
* Section codecs and a scene model (nodes, parameters, expressions, variables, asset libraries)
* Listing file dependencies
* Replacing strings across the scene (paths, variables, libraries, parameters, expressions, node names)

Apprentice files (`.hipnc`) are encrypted and out of scope.

## Installation

```sh
uv sync --extra dev
```

## Documentation

See [docs/file_format.md](docs/file_format.md) for what is known of the `.hip` format.
