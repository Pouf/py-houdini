# API Reference

Welcome to the py_houdini API reference. This section provides detailed documentation for the classes and functions of the library.

## Main Entry Point

The primary function you'll use is [`parse()`](parsers.md).

## Core Modules

### [Scene](scene.md)

The `Scene` parsed from a `.hip` file: nodes, variables, asset libraries, file references, replacing and saving.


### [Node](node.md)

A `Node` of the scene: path, type, category, children, inputs, parameters and channels.


### [File Reference](file_reference.md)

A `FileReference`: a file parameter value with its file type and file chooser mode.


### Parameters

Values as the file stores them:

- [Parm Tuple](parameters/parm_tuple.md) - A parameter and its components
- [Channel](parameters/channel.md) - An animated parameter's channel and its expressions
- [Variable](parameters/variable.md) - A `set -g` variable saved with the scene

### Other

The file under the model:

- [Container](other/container.md) - The named sections of the file, in its MIME or cpio container
- [Token](other/token.md) - A value in a section, with its position
- [Errors](other/errors.md) - The error raised for files that cannot be read back

## Quick Start

See the [Quick Start guide](../quickstart.md) for usage examples (parsing, file references, editing, replacing, saving).
