# py_houdini Documentation

Welcome to the py_houdini documentation! This library reads and edits SideFX Houdini scene files (`.hip`) without Houdini.

## About

A `.hip` file is a list of named sections (scene settings, then a few sections per node) stored either as a MIME multipart message (Houdini's "Text" save mode) or as a cpio archive ("Binary"). py_houdini parses both into one scene model and writes them back keeping every byte it does not change, so that tools can list and replace a scene's file dependencies on machines and farms without a Houdini licence.

## Installation

=== "uv"

    ```bash
    uv add py-houdini
    ```

=== "pip"

    ```bash
    pip install py-houdini
    ```

## Quick Start

```python
import py_houdini

scene = py_houdini.parse("shot.hip")

# List the files the scene reads
for ref in scene.file_references():
    if ref.value and ref.mode != "write":
        print(ref.node.path, ref.parm, ref.value)

# Edit a parameter
scene.node("/obj/geo1/file1").set_parm("file", "$HIP/geo/rock.bgeo.sc")

# Save to a new file
scene.save("shot_edited.hip")
```

See the [Quick Start guide](quickstart.md) for examples.

## Key Concepts

### Scene Structure

A parsed scene exposes what the file itself stores:

```
Scene
├── Variable
├── Libraries (installed, fallback, preferred)
├── Node
│   ├── Node (children)
│   ├── ParmTuple
│   │   └── Component
│   └── Channel
│       └── Expression
└── FileReference
```

### Data Model

- `Scene`: a `.hip` file: nodes, `set -g` variables, asset libraries, file references
- `Node`: a node of the scene (path, type, category, children, inputs, parameters, channels)
- `ParmTuple`, `Component`: a parameter and its values, as Houdini stores them (unexpanded)
- `Channel`, `Expression`: an animated parameter's channel and its expressions, with their language
- `Variable`: a `set -g` variable saved with the scene
- `FileReference`: a file parameter value, with its file type and file chooser mode (read or write)
- `Container`, `Section`: the named sections of the file, in its MIME or cpio container

### Guarantees

- **Byte-identical round-trip**: parsing then saving without edits gives the same bytes, in both containers. Files that cannot be reproduced are refused at parse time.
- **Minimal edits**: an edit rewrites only the tokens it changes, quoted and escaped the way Houdini writes them.
- **Checked against Houdini**: the model matches Houdini's own view of every test scene.

## API Reference

Browse the [API Reference](api/index.md) for detailed documentation of all classes and methods.

## Contributing

Contributions are welcome! See the [Contributing Guide](contributing.md) to get started, or visit the [GitHub repository](https://github.com/Pouf/py-houdini) for more information.

## License

This project is licensed under the MIT License.
