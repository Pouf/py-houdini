# The `.hip` file format

What is known of Houdini scene files, from production files and Houdini-made
fixtures. Every claim says how it was established; "observed" means seen on
files but not probed with Houdini.

## Containers

A `.hip` file is an ordered list of named sections stored in one of two
containers. Houdini calls them save modes (`hou.hipFile.saveMode()`,
`hou.hipFile.setSaveMode()`):

- `hou.saveMode.Text`: a MIME multipart message ("an ASCII format that is
  friendly to version control", commercial licence only, Houdini 16 and later);
- `hou.saveMode.Binary`: an old portable ASCII cpio archive ("odc").

Production census (31,925 files named `.hip*`, 2026-10-10): 31,002 MIME
(Houdini 18.5 to 20.5), 830 cpio (18.5 to 20.5), 62 Apprentice files
(`HouNC\x1a` header, encrypted, out of scope), and a few files of other
formats named `.hip` (Alembic, Guerilla, Maya, hscript scripts, empty files).

### MIME (Text)
Observed on production files:

- Header: `MIME-Version: 1.0`, then
  `Content-Type: multipart/mixed; boundary="HOUDINIMIMEBOUNDARY0x<hex>-0x<hex>-0x<hex>-0x<hex>HOUDINIMIMEBOUNDARY"`,
  a blank line, then the parts separated by `--<boundary>`, ending with
  `--<boundary>--` and a newline. LF line endings.
- No content lengths: parts are delimited by the boundary only.
- Each part: `Content-Disposition: attachment; filename="<section name>"`, then
  `Content-Type: text/plain`, or `application/octet-stream` with
  `Content-Transfer-Encoding: base64` for binary sections (`.OPdummydefs`,
  `.datablocks`, `.takes`, `.outputinfos`).

### cpio (Binary)
Observed on production files:

- Each entry: a 76-byte header `070707` + octal fields dev(6) ino(6) mode(6)
  uid(6) gid(6) nlink(6) rdev(6) mtime(11) namesize(6) filesize(11), then the
  NUL-terminated name, then the data. The last entry is `TRAILER!!!`.
- The archive ends exactly at the end of the file (no block padding).
- Header fields are constant (dev 1, ino 0, mode 0666, uid and gid 0, nlink 1,
  rdev 0) except mtime and the two sizes.
- Same section names as MIME; binary sections are stored raw. `.userdata` is
  binary in cpio but text (JSON) in MIME. `.OPdummydefs` holds an asset
  library index (`INDX`, the `.hda` format).

## Sections
Observed on production files, in file order:

- Scene: `.start` (hscript: `fplayback`, `tcur`, `fps`, `tset`, `frange`),
  `.variables` (`set -g NAME = 'value'`: `HIP`, `HIPFILE`, `HIPNAME`, `JOB`,
  `_HIP_SAVEVERSION`, `_HIP_SAVETIME`...), `.aliases`, `.takeconfig`,
  `.hou.session` (Python source), `.OPlibraries` (asset libraries the scene
  installs), `.OPpreferences`, `.OPfallbacks` (`<optype> <path>` pairs: each
  definition with its absolute path, then a relative `otls/...` form),
  `.OPdummydefs`, `expression.func`, then the node sections, then
  `.scenefilevisualizers`, `.application`, `.takes`, `.styles`,
  `.contextoptions`, `.cwd`.
- One group of sections per node, named by node path without the leading
  slash (`obj/fx/retime1.init`): `.init` (`type = retime`, `matchesdef = 1`),
  `.def` (flags, inputs, position, colour, `exprlanguage`), `.parm`, `.chn`,
  `.userdata`, `.spareparmdef`, `.multiparm`, `.inp`, `.net`, `.order`
  (children order), `.netbox`/`.netboxinit`, `.postit*` (sticky notes),
  `.networkdotinit`, `.gdelta`.
- `.parm`: `{`, `version 0.8`, one line per parameter
  `name<TAB>[ N<TAB>locks=0 ]<TAB>(<TAB>value...<TAB>)`, `}`. Values are
  hscript tokens, quoted only when needed. `N` > 0 when the parameter is
  animated; the value then names a channel.
- `.chn`: `channel <name> { ... segment { length = 0 expr = <expression> } }`;
  expressions are quoted when needed, with `\"` escapes, and may be multi-line
  Python (`language = python`).
