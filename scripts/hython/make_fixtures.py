"""Build the Houdini-made fixtures in samples/models/houdini<version>/.

    mklink /J C:\\py-houdini <this repository>
    "C:/Program Files/Side Effects Software/Houdini 20.5.370/bin/hython.exe" C:/py-houdini/scripts/hython/make_fixtures.py [scene ...]

Fixtures must not say who made them or where: run the script through a
neutral path, which ends up in `$HIP` and `.OPlibraries`. Each saved file then
gets neutral author stamps and home folder in `$JOB` and `$POSE`, and the run
stops if the login, host or home folder is still in it.

Builds the scenes named on the command line, all of them by default. Each
scene is saved in both containers: `mime/<name>.hip` (`hou.saveMode.Text`)
and `cpio/<name>.hip` (`hou.saveMode.Binary`). The test asset library is
`otls/py_houdini_fixture.hda`; scenes store its absolute path (Houdini expands
variables in `.OPlibraries` when saving), like `$HIP` in `.variables`. Paths in
values are fictional (`//server/proj/...`, `C:/data/...`): fixtures must never
hold production paths.
Node, take and note names carry a fabrication name (`e101_s010_p020`) so that
replace tests have something to rename.
"""

import os
import re
import socket
import sys

import hou

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from py_houdini import parse  # noqa: E402

HOME = os.path.expanduser("~").replace("\\", "/")
AUTHOR = re.compile(rb"\n  author \S+\n")
IDENTITY = [os.getlogin(), socket.gethostname(), socket.getfqdn(), HOME]
OUT = os.path.join(
    ROOT, "samples", "models", "houdini" + hou.applicationVersionString()
)
OUT = OUT.replace("\\", "/")
ASSET = "py_houdini::fixture_asset::1.0"
HDA_FILE = OUT + "/otls/py_houdini_fixture.hda"
# One spare parameter (and expression) per character Houdini may quote or
# escape. Left out, as Houdini 20.5 cannot read them back from its own file:
# CR and other control characters, values made of one escape ("\\", '"'),
# and ")" alone (read as the end of the tuple).
QUOTING_VALUES = [
    "plain", "", "a b", "a\tb", "a\nb", 'a"b', "a\\b", "a'b", "a`b", "a$b",
    "a(b", "a)b", "a[b", "a]b", "a{b", "a}b", "a;b", "a#b", "a,b", "a=b", "a<b",
    " lead", "trail ", "(", "[", "]", "{", "}", "'", "\u00e9", "a\\nb",
    'a\\"b', "-1", "1.5", "on", "*", "a&b", "a|b", "\\\\server\\share",
]  # fmt: skip
# Variables are written without escaping backslashes but read with escapes,
# and a newline ends them: only values Houdini reads back
QUOTING_VARIABLES = [v for v in QUOTING_VALUES if "\\" not in v and "\n" not in v]


def new_scene():
    hou.hipFile.clear(suppress_save_prompt=True)


def save(name):
    for folder, mode in (("mime", hou.saveMode.Text), ("cpio", hou.saveMode.Binary)):
        hou.hipFile.setSaveMode(mode)
        path = f"{OUT}/{folder}/{name}.hip"
        # hython 20.5 fails with "Error creating file" in a missing folder
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        hou.hipFile.save(path, save_to_recent_files=False)
        scrub(path)
        print("saved", path)


def scrub(path):
    """Take the author stamps and home folder out of a saved fixture."""
    scene = parse(path)
    for section in scene.container.sections:
        if section.name.endswith((".def", ".netboxinit", ".postitdef")):
            section.data = AUTHOR.sub(b"\n  author fixtures@houdini\n", section.data)
    for variable in scene.variables:
        # $HIP and $HIPFILE come from the path the script runs from
        if variable.name not in ("HIP", "HIPFILE") and variable.value.startswith(HOME):
            scene.set_variable(
                variable.name, "C:/Users/fixtures" + variable.value[len(HOME) :]
            )
    scene.save_in_place()
    with open(path, "rb") as f:
        data = f.read().lower()
    for text in IDENTITY:
        if text.lower().encode() in data:
            raise RuntimeError(f"{path} names {text}, run from a neutral path")


def hscript(command):
    output, errors = hou.hscript(command)
    if errors:
        raise RuntimeError(f"{command}: {errors}")
    return output


def string_parm(name, default="", file_reference=False):
    string_type = (
        hou.stringParmType.FileReference
        if file_reference
        else hou.stringParmType.Regular
    )
    return hou.StringParmTemplate(
        name, name, 1, default_value=(default,), string_type=string_type
    )


def add_spare_parms(node, *templates):
    group = node.parmTemplateGroup()
    for template in templates:
        group.append(template)
    node.setParmTemplateGroup(group)


def file_sop(network, name, path):
    node = network.createNode("file", name)
    node.parm("file").set(path)
    return node


def empty():
    """What a new scene holds."""
    new_scene()
    save("empty")


def deps():
    """One node per way a value can name a file."""
    new_scene()
    hscript("set -g JOB = //server/proj")
    hscript("set -g ASSET_ROOT = C:/data/assets")
    hou.setSessionModuleSource('CACHE_ROOT = "//server/proj/cache"\n')
    obj = hou.node("/obj")
    geo = obj.createNode("geo", "deps")
    file_sop(geo, "file_unc", "//server/proj/geo/rock.bgeo.sc")
    file_sop(geo, "file_drive", "C:/data/geo/tree.bgeo.sc")
    file_sop(geo, "file_hip_sequence", "$HIP/geo/box.$F4.bgeo.sc")
    file_sop(geo, "file_variable", "$ASSET_ROOT/props/crate.bgeo.sc")
    file_sop(geo, "file_job", "$JOB/geo/job.bgeo.sc")
    file_sop(geo, "file_backtick", '$HIP/`chs("../../ctrl/version")`/cache.$F4.bgeo.sc')
    file_sop(geo, "file_search_path", "defgeo.bgeo")
    file_sop(geo, "file_backslashes", "C:\\data\\geo\\windows.bgeo.sc")
    file_sop(geo, "file_spaces", "C:/my data/geo/a b.bgeo.sc")
    file_sop(geo, "file_quotes", 'C:/data/geo/say "hi".bgeo.sc')
    file_sop(geo, "file_unicode", "C:/donn\u00e9es/g\u00e9o/\u00e9toile.bgeo.sc")
    file_sop(geo, "file_empty", "")
    file_sop(geo, "file_hscript_expr", "").parm("file").setExpression(
        'chs("../file_unc/file")', hou.exprLanguage.Hscript
    )
    file_sop(geo, "file_python_expr", "").parm("file").setExpression(
        '"//server/proj/geo/py_%04d.bgeo.sc" % hou.frame()', hou.exprLanguage.Python
    )
    file_sop(geo, "file_python_multiline", "").parm("file").setExpression(
        'import os\nreturn os.path.join("//server/proj", "geo", "multi.bgeo.sc")',
        hou.exprLanguage.Python,
    )
    geo.createNode("alembic", "abc_sop").parm("fileName").set(
        "//server/proj/cache/anim.abc"
    )
    obj.createNode("alembicarchive", "abc_archive").parm("fileName").set(
        "C:/data/cache/archive.abc"
    )
    geo.createNode("attribwrangle", "wrangle").parm("snippet").set(
        'string path = "//server/proj/tex/noise.rat";\n'
        's@quoted = "a \\"b\\" c\\\\d";\n'
        "i@id = 1;\n"
    )
    geo.createNode("python", "python_sop").parm("python").set(
        "node = hou.pwd()\n"
        'path = "//server/proj/geo/from_python.bgeo.sc"\n'
        'other = hou.node("../file_unc")\n'
    )
    spare = geo.createNode("null", "spare")
    add_spare_parms(
        spare,
        string_parm(
            "cache_path", "//server/proj/cache/default.bgeo.sc", file_reference=True
        ),
        string_parm("note"),
    )
    spare.parm("cache_path").set("//server/proj/cache/spare.$F4.bgeo.sc")
    spare.parm("note").set("plain text, not a path")
    ctrl = obj.createNode("null", "ctrl")
    add_spare_parms(ctrl, string_parm("version", "v001"))
    ctrl.parm("version").set("v003")
    comp = hou.node("/img").createNode("img", "comp")
    comp.createNode("file", "cop_file").parm("filename1").set(
        "//server/proj/plates/plate.$F4.exr"
    )
    rop = hou.node("/out").createNode("geometry", "rop_geo")
    rop.parm("soppath").set("/obj/deps/file_unc")
    rop.parm("sopoutput").set("$HIP/geo/$OS.$F4.bgeo.sc")
    save("deps")


def build_asset_library():
    """Built in a scratch scene then uninstalled, so that the scene using it installs it itself."""
    new_scene()
    if os.path.exists(HDA_FILE):
        os.remove(HDA_FILE)
    source = hou.node("/obj").createNode("geo", "source").createNode("subnet", "asset")
    file_sop(source, "inner_file", '`chs("../asset_file")`').setDisplayFlag(True)
    file_sop(source, "inner_fixed", "//server/proj/geo/inside_asset.bgeo.sc")
    asset = source.createDigitalAsset(
        name=ASSET,
        hda_file_name=HDA_FILE,
        description="py-houdini fixture asset",
        min_num_inputs=0,
        max_num_inputs=1,
        create_backup=False,
    )
    definition = asset.type().definition()
    group = definition.parmTemplateGroup()
    group.append(
        string_parm(
            "asset_file",
            "//server/proj/geo/asset_default.bgeo.sc",
            file_reference=True,
        )
    )
    definition.setParmTemplateGroup(group, create_backup=False)
    hou.hda.uninstallFile(HDA_FILE)
    print("saved", HDA_FILE)


def hda():
    """Instances of a local asset (default, edited, unlocked) and a SideFX one."""
    build_asset_library()
    new_scene()
    hou.hda.installFile(HDA_FILE)
    geo = hou.node("/obj").createNode("geo", "assets")
    geo.createNode(ASSET, "asset_default")
    geo.createNode(ASSET, "asset_custom").parm("asset_file").set(
        "C:/data/geo/custom.bgeo.sc"
    )
    unlocked = geo.createNode(ASSET, "asset_unlocked")
    unlocked.allowEditingOfContents()
    unlocked.node("inner_fixed").parm("file").set(
        "//server/proj/geo/edited_inside.bgeo.sc"
    )
    geo.createNode("filecache", "filecache")
    save("hda")


def names():
    """Node names, node paths in values and expressions, takes, notes."""
    new_scene()
    obj = hou.node("/obj")
    ctrl = obj.createNode("null", "ctrl")
    for frame, value in ((1, 0.0), (24, 10.0)):
        key = hou.Keyframe()
        key.setFrame(frame)
        key.setValue(value)
        ctrl.parm("tx").setKeyframe(key)
    add_spare_parms(
        ctrl, string_parm("path", "//server/proj/geo/e101_s010_p020.bgeo.sc")
    )
    # Created as geo1 then renamed, like an artist does
    geo = obj.createNode("geo")
    geo.setName("e101_s010_p020_cache")
    # A sibling that a p020 -> p030 replace would collide with
    obj.createNode("geo", "e101_s010_p030_cache")
    outer = geo.createNode("subnet", "outer")
    inner = outer.createNode("subnet", "inner")
    file_sop(inner, "file1", "//server/proj/geo/e101_s010_p020_inner.bgeo.sc")
    top = file_sop(geo, "file1", "//server/proj/geo/e101_s010_p020_top.bgeo.sc")
    top.parm("file").setExpression('chs("/obj/ctrl/path")', hou.exprLanguage.Hscript)
    # Subnet inputs seen from inside: one wired outside, one not
    outer.setInput(0, top)
    inside = outer.createNode("merge", "merge_inside")
    inside.setInput(0, outer.indirectInputs()[0])
    inside.setInput(1, outer.indirectInputs()[1])
    dot = geo.createNetworkDot()
    dot.setInput(top)
    xform = geo.createNode("xform", "xform_e101_s010_p020")
    xform.setInput(0, dot)
    xform.parm("tx").setExpression('ch("/obj/ctrl/tx") * 2', hou.exprLanguage.Hscript)
    xform.parm("ty").setExpression(
        'hou.node("../../ctrl").evalParm("tx")', hou.exprLanguage.Python
    )
    xform.setComment("from e101_s010_p020")
    xform.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    xform.setUserData(
        "source", "e101_s010_p020 //server/proj/geo/e101_s010_p020.bgeo.sc"
    )
    merge = geo.createNode("object_merge", "objmerge")
    merge.parm("numobj").set(2)
    merge.parm("objpath1").set("/obj/e101_s010_p020_cache/outer/inner/file1")
    merge.parm("objpath2").set("../xform_e101_s010_p020")
    both = geo.createNode("merge", "merge_all")
    both.setInput(0, xform)
    both.setInput(1, merge)
    both.setDisplayFlag(True)
    both.setRenderFlag(True)
    note = geo.createStickyNote("note_e101_s010_p020")
    note.setText(
        "cache of e101_s010_p020 from //server/proj/geo/e101_s010_p020.bgeo.sc"
    )
    box = geo.createNetworkBox("box_e101_s010_p020")
    box.setComment("e101_s010_p020 inputs")
    box.addItem(top)
    box.addItem(dot)
    rop = hou.node("/out").createNode("geometry", "rop_e101_s010_p020")
    rop.parm("soppath").set("/obj/e101_s010_p020_cache/merge_all")
    rop.parm("sopoutput").set("$HIP/geo/e101_s010_p020.$F4.bgeo.sc")
    take = hou.takes.rootTake().addChildTake("take_e101_s010_p020")
    hou.takes.setCurrentTake(take)
    take.addParmTuple(inner.node("file1").parmTuple("file"))
    inner.node("file1").parm("file").set(
        "//server/proj/geo/e101_s010_p020_take.bgeo.sc"
    )
    hou.takes.setCurrentTake(hou.takes.rootTake())
    save("names")


def quoting():
    """Values with every character Houdini may quote or escape: parms, expressions, variables."""
    new_scene()
    values = hou.node("/obj").createNode("null", "values")
    expressions = hou.node("/obj").createNode("null", "expressions")
    add_spare_parms(values, *(string_parm(f"v{i}") for i in range(len(QUOTING_VALUES))))
    add_spare_parms(
        expressions, *(string_parm(f"e{i}") for i in range(len(QUOTING_VALUES)))
    )
    for index, value in enumerate(QUOTING_VALUES):
        values.parm(f"v{index}").set(value)
        # An empty expression is not kept as one
        if value:
            expressions.parm(f"e{index}").setExpression(value, hou.exprLanguage.Python)
    for index, value in enumerate(QUOTING_VARIABLES):
        hscript(f"set -g QUOTING{index} = placeholder")
        hou.putenv(f"QUOTING{index}", value)
    save("quoting")


SCENES = {f.__name__: f for f in (empty, deps, hda, names, quoting)}
for scene in sys.argv[1:] or list(SCENES):
    SCENES[scene]()
