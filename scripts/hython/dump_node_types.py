"""Export what py_houdini needs to know of every node type Houdini knows.

    "C:/Program Files/Side Effects Software/Houdini 20.5.370/bin/hython.exe" scripts/hython/dump_node_types.py build/schema

Writes `<folder>/houdini<version>.json`:
- "types": {"<Category>/<type>": {"file_parms": {"<parm tuple>": {"file_type":
  ..., "mode": "read"/"write"/"read_and_write"/""}}, "child_category": the
  category of the nodes it contains or null, "hda": whether it is an asset}}.
  File parameters are string parameters typed `FileReference`, including those
  inside folders and multiparm blocks (names keep their `#`); `mode` is the
  file chooser's mode tag when the type sets one.
- "managers": {"<top-level network>": "<category of its children>"}; the
  top-level networks are also in "types", as "Manager/<name>".
"""

import json
import os
import sys

import hou


def file_parms(templates, found):
    for template in templates:
        if template.type() == hou.parmTemplateType.Folder:
            file_parms(template.parmTemplates(), found)
        elif (
            template.type() == hou.parmTemplateType.String
            and template.stringType() == hou.stringParmType.FileReference
        ):
            found[template.name()] = {
                "file_type": template.fileType().name(),
                "mode": template.tags().get("filechooser_mode", ""),
            }
    return found


out = sys.argv[1]
if not os.path.isdir(out):
    os.makedirs(out)
types = {}
for category in hou.nodeTypeCategories().values():
    for node_type in category.nodeTypes().values():
        try:
            group = node_type.parmTemplateGroup()
        except hou.Error:  # some types cannot build their parameters outside a scene
            group = None
        child = node_type.childTypeCategory()
        types[node_type.nameWithCategory()] = {
            "file_parms": file_parms(group.entries(), {}) if group else {},
            "child_category": child.name() if child else None,
            "hda": node_type.definition() is not None,
        }
managers = {}
for node in hou.node("/").children():
    managers[node.name()] = node.childTypeCategory().name()
    # Their sections have no type: keyed by their name
    types["Manager/" + node.name()] = {
        "file_parms": file_parms(node.parmTemplateGroup().entries(), {}),
        "child_category": node.childTypeCategory().name(),
        "hda": False,
    }
path = os.path.join(out, "houdini" + hou.applicationVersionString() + ".json")
with open(path, "wb") as f:
    data = {"types": types, "managers": managers}
    f.write(json.dumps(data, indent=1, sort_keys=True).encode("ascii"))
print("wrote", path, len(types), "types")
