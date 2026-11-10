# py_houdini
`py_houdini` is a Python package for reading and editing SideFX Houdini scene files (`.hip`) without Houdini.

Sibling project of [py-aep](https://github.com/forticheprod/py-aep), [py-premiere](https://github.com/Pouf/py-premiere) and [py-maya-scene](https://github.com/Pouf/py-maya-scene).

## About

A `.hip` file is a list of named sections (scene settings, then a few sections per node) stored either as a MIME multipart message (Houdini's "Text" save mode) or as a cpio archive ("Binary"). This package will read and edit both, keeping every byte it does not change, so that tools can list and replace a scene's file dependencies on machines and farms without a Houdini licence.

## Status

Pre-alpha.

### Supported
* Both containers, byte for byte: parse then save gives the same bytes (all 18,152 production MIME and cpio files; the two others, one truncated and one converted to CRLF outside Houdini, are refused at parse time). Files of other formats named `.hip` (Apprentice, Alembic, Maya...) are refused with an error naming the format
* Scene model: nodes (path, type, children in Houdini's order, wired inputs through network dots), parameter tuples (values decoded as Houdini reads them, animated components with their channel), channel expressions with their language, `set -g` variables, the asset libraries the scene installs; checked against Houdini's own view of every fixture
* Editing a parameter value or a variable rewrites that token only, quoted and escaped the way Houdini writes it
* File references (`scene.file_references()`): every file parameter as Houdini types it (built-in node types from a table generated from Houdini 20.5, asset types from their definitions saved in the scene, spare parameters), with its file chooser mode (read/write) and whether an expression drives it; the asset libraries the scene installs, uses and prefers; `scene.expand()` for the scene's variables, `$HIP` from where the file is
* Replacing every name and string through a function (`scene.replace_strings(fn)`), like a text replace that keeps the scene consistent: parameter values, expressions, variables (but `$HIP`, `$HIPFILE`, `$HIPNAME`), library paths, takes, and node names with everything that names a node (paths, children order, inputs, network dots). Houdini's view of the result matches a hython remap on every fixture, takes aside (hython leaves their overrides behind). Nothing changes when a new node name is invalid or clashes
* Remapping file paths only (`scene.remap_paths(fn)`)
* Saving atomically: `save(path)` refuses to overwrite, `save_in_place()` overwrites the parsed file

Apprentice files (`.hipnc`) are encrypted and out of scope.

## Installation

```sh
uv sync --extra dev
```

## Getting started

```python
import py_houdini

scene = py_houdini.parse("shot.hip")
for node in scene.nodes:
    for parm in node.parms:
        print(node.path, node.type, parm.name, [c.value for c in parm.components])

scene.node("/obj/geo1/file1").set_parm("file", "$HIP/geo/rock.bgeo.sc")
scene.save("shot_edited.hip")

# Inputs only, with variables expanded
for ref in scene.file_references():
    if ref.value and ref.mode != "write" and not ref.animated:
        print(ref.node.path, ref.parm, scene.expand(ref.value, node=ref.node))

# Rename an item everywhere: node names, values, expressions...
scene.replace_strings(lambda value: value.replace("e101_s010_p020", "e101_s010_p030"))
scene.save_in_place()
```

## Documentation

See [docs/file_format.md](docs/file_format.md) for what is known of the `.hip` format.
