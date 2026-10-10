"""Export, for every node type Houdini knows, its file-reference parameters.

    "C:/Program Files/Side Effects Software/Houdini 20.5.370/bin/hython.exe" scripts/hython/dump_node_types.py build/schema

Writes `<folder>/houdini<version>.json`: {"<Category>/<type>": {"<parm>":
{"file_type": ..., "mode": "read"/"write"/""}}} for string parameters typed
`FileReference`, including those inside folders and multiparm blocks (names
keep their `#`). `mode` is the file chooser's mode tag when the type sets one.
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
            continue
        found = file_parms(group.entries(), {})
        if found:
            types[node_type.nameWithCategory()] = found
path = os.path.join(out, "houdini" + hou.applicationVersionString() + ".json")
with open(path, "wb") as f:
    f.write(json.dumps(types, indent=1, sort_keys=True).encode("ascii"))
print("wrote", path, len(types), "types")
