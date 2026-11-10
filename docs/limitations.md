# Known Limitations

This page documents limitations of py_houdini that arise from reading a
scene file rather than querying a running Houdini.

## The file, not the loaded scene

py_houdini sees what the file stores:

- Values are unexpanded (`$HIP/geo/box.$F4.bgeo.sc`) and expressions are not
  evaluated. `Scene.expand()` replaces the scene's own variables, `$HIP`,
  `$HIPFILE`, `$HIPNAME` and `$OS` only.
- The contents of a locked asset come from its definition and are not in the
  file, except the nodes the asset declares editable. A node inside a locked
  asset can have no `parent` in the model.

## File references

- Built-in node types come from a table generated from Houdini 20.5; asset
  types come from their definitions saved in the scene, spare parameters from
  the node itself. A node of an asset type whose definition the scene does
  not hold has no known file parameters.
- A value driven by an expression is flagged `animated`; its stored value is
  not what Houdini would evaluate.
- Bare names looked up on Houdini's search path (`defgeo.bgeo`) are reported
  as stored, not resolved.

## Editing

- `set_parm` and `set_variable` edit existing values. Creating or deleting
  nodes, parameters and keyframes is not supported.
- Node names accept letters, digits, `_`, `.` and `-`, as in Houdini.

## replace_strings

Left as they are: parameter and channel names, node types, variable names,
`$HIP`, `$HIPFILE` and `$HIPNAME` (Houdini sets them when loading), spare
parameters' defaults, asset definitions, user data, comments, sticky notes,
network box and dot names, and the interface state saved with the scene.

## Files that are refused

A file py_houdini cannot write back byte for byte is refused at parse time
(`FormatError`): one converted to CRLF line endings outside Houdini, a
truncated file, or another format named `.hip`. Apprentice files (`.hipnc`)
are encrypted and out of scope.

## Houdini versions

Checked on scenes saved by Houdini 18.5 to 20.5, in both containers.
