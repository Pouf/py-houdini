"""Export Houdini's own view of .hip files as JSON ground truth (`<file>.json`).

    "C:/Program Files/Side Effects Software/Houdini 20.5.370/bin/hython.exe" scripts/hython/dump_scene.py "samples/models/houdini20.5.370/*/*.hip"

Records what a hython remap reads and writes: global variables listed by
`set -s`, asset libraries, every parameter (raw value, keyframes and their
expressions) of every node outside locked assets, node names; plus
`hou.fileReferences()`, the load warnings, takes, sticky notes and network
boxes. `libraries` holds only those the scene adds to what an empty scene loads
(Houdini's, packages', user preferences'); nodes still name theirs.
"""

import glob
import json
import os
import re
import sys

import hou

hou.hipFile.clear(suppress_save_prompt=True)
BASELINE_LIBRARIES = set(hou.hda.loadedFiles())


def keyframes(parm):
    entries = []
    for key in parm.keyframes():
        entry = {"frame": key.frame()}
        if key.isExpressionSet():
            entry["expression"] = key.expression()
            entry["language"] = key.expressionLanguage().name()
        if isinstance(key, hou.Keyframe) and key.isValueSet():
            entry["value"] = key.value()
        entries.append(entry)
    return entries


def parm_entry(parm):
    keys = keyframes(parm)
    if keys:
        return {"name": parm.name(), "raw": parm.rawValue(), "keyframes": keys}
    return parm.rawValue()


def is_file_parm(parm):
    template = parm.parmTemplate()
    return (
        template.type() == hou.parmTemplateType.String
        and template.stringType() == hou.stringParmType.FileReference
    )


def node_entry(node):
    entry = {
        "path": node.path(),
        "type": node.type().nameWithCategory(),
        # By tuple, as .parm sections store them
        "parms": {
            parm_tuple.name(): [parm_entry(parm) for parm in parm_tuple]
            for parm_tuple in node.parmTuples()
        },
        "parm_types": {
            parm_tuple.name(): parm_tuple.parmTemplate().type().name()
            for parm_tuple in node.parmTuples()
        },
        # By tuple, as .parm sections store them
        "file_parms": sorted(
            {parm.tuple().name() for parm in node.parms() if is_file_parm(parm)}
        ),
        # A subnet input wired to nothing outside has no input node
        "inputs": [
            [
                c.inputIndex(),
                c.inputNode().path() if c.inputNode() else None,
                c.outputIndex(),
                type(c.inputItem()).__name__,
            ]
            for c in node.inputConnections()
        ],
    }
    definition = node.type().definition()
    if definition is not None:
        entry["library"] = definition.libraryFilePath()
        entry["matches_definition"] = node.matchesCurrentDefinition()
    if node.comment():
        entry["comment"] = node.comment()
    if node.userDataDict():
        entry["user_data"] = node.userDataDict()
    # A locked asset's contents come from its definition, not from the file
    if node.isNetwork() and not node.isLockedHDA():
        entry["children"] = [child.name() for child in node.children()]
        notes = {n.name(): n.text() for n in node.stickyNotes()}
        boxes = {
            b.name(): {
                "comment": b.comment(),
                "items": sorted(i.name() for i in b.items()),
            }
            for b in node.networkBoxes()
        }
        dots = {d.name(): d.input().path() for d in node.networkDots() if d.input()}
        if notes:
            entry["sticky_notes"] = notes
        if boxes:
            entry["network_boxes"] = boxes
        if dots:
            entry["dots"] = dots
    return entry


def take_entries():
    entries = []
    current = hou.takes.currentTake()
    for take in hou.takes.takes():
        hou.takes.setCurrentTake(take)
        entries.append(
            {
                "name": take.name(),
                "parent": take.parent().name() if take.parent() else None,
                "parms": {
                    parm.path(): parm_entry(parm)
                    for parm_tuple in take.parmTuples()
                    for parm in parm_tuple
                },
            }
        )
    hou.takes.setCurrentTake(current)
    return entries


def dump(path):
    try:
        hou.hipFile.load(path, suppress_save_prompt=True)
        warnings = []
    except hou.LoadWarning as warning:
        warnings = str(warning).splitlines()
    listing, errors = hou.hscript("set -s")
    if errors:
        raise RuntimeError(errors)
    names = re.findall(r"^set -g (\S+) = ", listing, re.MULTILINE)
    # hscript-only variables (E, PI, status...) are not in hou.getenv: read the listing
    listed = dict(re.findall(r"^set -g (\S+) = '([^'\n]*)'$", listing, re.MULTILINE))
    data = {
        "houdini": hou.applicationVersionString(),
        "save_mode": hou.hipFile.saveMode().name(),
        "load_warnings": warnings,
        "variables": {
            name: listed.get(name) if hou.getenv(name) is None else hou.getenv(name)
            for name in names
        },
        "libraries": sorted(set(hou.hda.loadedFiles()) - BASELINE_LIBRARIES),
        "session_module": hou.sessionModuleSource(),
        "nodes": [
            node_entry(node)
            for node in hou.node("/").allSubChildren(recurse_in_locked_nodes=False)
        ],
        "takes": take_entries(),
        "file_references": sorted(
            [parm.path() if parm else "", value] for parm, value in hou.fileReferences()
        ),
    }
    # ASCII JSON in binary mode: stable bytes whatever the console encoding
    with open(path + ".json", "wb") as f:
        f.write(json.dumps(data, indent=1, sort_keys=True).encode("ascii"))
    print("wrote", path + ".json")


for pattern in sys.argv[1:]:
    for path in sorted(glob.glob(pattern)):
        dump(os.path.abspath(path).replace("\\", "/"))
