# Quick Start

## Parse a scene

```python
import py_houdini

scene = py_houdini.parse("shot.hip")

print(f"Container: {scene.kind}")  # "mime" (Text save mode) or "cpio" (Binary)
for variable in scene.variables:
    print(f"{variable.name} = {variable.value}")
```

A file that is not a Houdini scene, or that cannot be written back byte for
byte, raises `py_houdini.FormatError`.

## Iterate over nodes

```python
for node in scene.nodes:
    print(f"{node.path} ({node.category}/{node.type})")

geo = scene.node("/obj/geo1")
for child in geo.children:  # in Houdini's order
    print(f"  {child.name}")
    for number, source, output in child.inputs:
        print(f"    input {number} <- {source} (output {output})")
```

## Read parameters and expressions

Values are the ones Houdini stores: unexpanded (`$HIP/geo/box.$F4.bgeo.sc`).

```python
node = scene.node("/obj/geo1/file1")
for parm in node.parms:
    print(parm.name, [component.value for component in parm.components])

# An animated component names a channel holding its expressions
for channel in node.channels:
    for expression in channel.expressions:
        print(f"{channel.name}: {expression.value} ({expression.language})")
```

## List file references

`file_references()` lists every file parameter as Houdini types it: built-in
node types, asset types from their definitions saved in the scene, and spare
parameters. Each has the file chooser mode of its parameter (`read`, `write`)
and tells whether an expression drives it.

```python
for ref in scene.file_references():
    if ref.value and ref.mode != "write" and not ref.animated:
        print(ref.node.path, ref.parm, scene.expand(ref.value, node=ref.node))
```

`expand()` replaces the scene's variables (`$JOB`...), with `$HIP` taken from
where the file is. Frame variables (`$F4`) are kept.

The asset libraries the scene names are listed too:

```python
print(scene.libraries)  # installed by the scene
print(scene.fallback_libraries)  # (type, library) of the other asset types it uses
print(scene.preferred_libraries)  # (type, library) it prefers a definition from
```

## Edit parameters and variables

An edit rewrites that token only, quoted and escaped the way Houdini does.

```python
scene.node("/obj/geo1/file1").set_parm("file", "$HIP/geo/rock.bgeo.sc")
scene.set_variable("JOB", "//server/project")
```

## Remap file paths

`remap_paths()` puts every file parameter value and asset library path
through a function, which returns the new path or `None` to keep it.

```python
def remap(path):
    if path.startswith("//server/old_project/"):
        return path.replace("//server/old_project/", "//server/new_project/", 1)
    return None


scene.remap_paths(remap)
```

## Replace strings everywhere

`replace_strings()` puts every name and string through one function, like a
text replace that keeps the scene consistent: parameter values, expressions,
variables, library paths, takes, and node names with everything that names a
node (paths, children order, inputs).

```python
scene.replace_strings(lambda text: text.replace("shot_010", "shot_020"))
```

Nothing changes if a new node name is invalid or clashes with another node
(`ValueError`).

## Save

```python
scene.save("shot_edited.hip")  # refuses to overwrite an existing file
scene.save_in_place()  # overwrites the parsed file, atomically
```

The container stays the one the scene was parsed from.
