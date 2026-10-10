# The `.hip` file format

What is known of Houdini scene files, from production files and Houdini-made
fixtures (`samples/models/houdini20.5.370`, made by
`scripts/hython/make_fixtures.py`). Every claim says how it was established:
"measured" means probed with Houdini 20.5.370 on the fixtures, "observed" means
seen on production files but not probed.

## Containers

A `.hip` file is an ordered list of named sections stored in one of two
containers, which Houdini calls save modes (`hou.hipFile.saveMode()`,
`hou.hipFile.setSaveMode()`); measured: a scene saved in `Text` mode is MIME,
in `Binary` mode cpio, and loading either sets the mode back.

- `hou.saveMode.Text`: a MIME multipart message ("an ASCII format that is
  friendly to version control", commercial licence only, Houdini 16 and later);
- `hou.saveMode.Binary`: an old portable ASCII cpio archive ("odc").

The same scene saved both ways has the same sections in the same order, with
the same bytes except: `.variables` (`HIP`, `HIPFILE`), `.def` (modification
time), `.userdata` (text in MIME, binary in cpio) and base64 encoding in MIME
(measured).

Production census (31,925 files named `.hip*`, 2026-10-10): 31,002 MIME
(Houdini 18.5 to 20.5), 830 cpio (18.5 to 20.5), 62 Apprentice files
(`HouNC\x1a` header, encrypted, out of scope), and a few files of other
formats named `.hip` (Alembic, Guerilla, Maya, hscript scripts, empty files).

### MIME (Text)
- Header: `MIME-Version: 1.0`, then
  `Content-Type: multipart/mixed; boundary="HOUDINIMIMEBOUNDARY0x<hex>-0x<hex>-0x<hex>-0x<hex>HOUDINIMIMEBOUNDARY"`,
  a blank line, then the parts separated by `--<boundary>`, ending with
  `--<boundary>--` and a newline. LF line endings (observed, measured).
- No content lengths: parts are delimited by the boundary only (observed).
- Each part: `Content-Disposition: attachment; filename="<section name>"`, then
  `Content-Type: text/plain`, or `application/octet-stream` with
  `Content-Transfer-Encoding: base64` for binary sections (`.OPdummydefs`,
  `.datablocks`, `.takes`, `.outputinfos`) (observed).
- base64 sections: each line encodes 128 bytes on its own (172 characters,
  padding included), the last line the remainder; decoded, the bytes equal
  the cpio twin's section (measured).
- Text is stored as written, CR bytes included (a multi-line expression with
  CRLF line ends keeps them in both containers), but Houdini's MIME reader
  drops the CRs: hython reads that expression with LF from the MIME file and
  with CRLF from the cpio twin (measured).

### cpio (Binary)
- Each entry: a 76-byte header `070707` + octal fields dev(6) ino(6) mode(6)
  uid(6) gid(6) nlink(6) rdev(6) mtime(11) namesize(6) filesize(11), then the
  NUL-terminated name, then the data. The last entry is `TRAILER!!!`.
- The archive ends exactly at the end of the file, no block padding (observed).
- Header fields are constant (dev 1, ino 0, mode 0666, uid and gid 0, nlink 1,
  rdev 0) except mtime and the two sizes (observed, measured).
- Binary sections are stored raw. `.userdata` is binary where MIME has JSON
  text (measured on single string entries: a big-endian u32 count, then a
  u16-length-prefixed key, a u32 (3), a u16-length-prefixed value).

## Text encoding
Values are UTF-8 (measured: `C:/données/...` is written `C:/donn\xc3\xa9es/...`).

## Sections
Observed on production files, in file order:

- Scene: `.start` (hscript: `fplayback`, `tcur`, `fps`, `tset`, `frange`),
  `.variables`, `.aliases`, `.takeconfig`, `.hou.session` (Python source),
  `.OPlibraries`, `.OPpreferences`, `.OPfallbacks`, `.OPdummydefs`,
  `expression.func`, then the node sections, then `.scenefilevisualizers`,
  `.application`, `.takes`, `.styles`, `.contextoptions`, `.cwd`.
- One group of sections per node, named by node path without the leading
  slash (`obj/fx/retime1.init`): `.init` (`type = retime`, `matchesdef = 1`),
  `.def` (flags, inputs, position, colour, `exprlanguage`, creation and
  modification times, `author <user>@<host>`), `.parm`, `.chn`, `.userdata`,
  `.spareparmdef`, `.multiparm`, `.inp`, `.net`, `.order` (children order),
  `.netbox`/`.netboxinit`, `.postit*` (sticky notes), `.networkdotinit`,
  `.gdelta`.

### `.variables`
`set -g NAME = 'value'` lines, sorted: `E`, `EYE`, `HIP`, `HIPFILE`,
`HIPNAME`, `JOB`, `PI`, `POSE`, `_HIP_SAVEPLATFORM`, `_HIP_SAVETIME`,
`_HIP_SAVEVERSION`, `_HIP_SHELFTOOLCOUNT`, `status`, plus the scene's own
(measured). `ACTIVETAKE` is set when loading but not saved (measured).

### Asset libraries
- `.OPlibraries`: one path per line, the libraries the scene installs.
  Variables in the installed path are expanded when saving: a library
  installed as `$VAR/otls/x.hda` is saved with its absolute path (measured).
- `.OPfallbacks`: `<category>/<type> <path>` pairs for the types the scene uses
  from libraries it does not install: each with the path Houdini loaded it from
  (`$HFS` as an 8.3 short path under hython), then a relative `otls/...` form.
  A type from a library in `.OPlibraries` is not listed (measured).
- `.OPdummydefs`: an asset library (`INDX`, the `.hda` layout) holding the
  definitions of the non-built-in types the scene uses, from both kinds of
  library (measured).

### `.parm`
`{`, `version 0.8`, one line per parameter, `}`:
`name<TAB>[ 0<TAB>locks=0 ]<TAB>(<TAB>value<TAB>...<TAB>)`, one value per
component of the tuple. The bracket may hold more flags (`autoscope=1`,
`autosel=4294967295`). Measured value forms:

| Value | Written |
|---|---|
| plain path, `$HIP/geo/box.$F4.bgeo.sc` | unquoted |
| empty | `""` |
| spaces | `"C:/my data/geo/a b.bgeo.sc"` |
| `"` inside | `"C:/data/geo/say \"hi\".bgeo.sc"` |
| backslashes | `C:\\data\\geo\\windows.bgeo.sc` (doubled, unquoted) |
| backticks with quotes | ``$HIP/`chs(\"../../ctrl/version\")`/cache.$F4.bgeo.sc`` (escaped, unquoted) |
| several lines | quoted, newlines kept literally |
| animated | `[ <channel><TAB><value> ]`, e.g. `( [ file default.bgeo ] )`, `( [ tx 0 ] 0 0 )` |

The leading `0` in the bracket is not an animation count: animated parameters
also have `0` (measured).

### `.chn`
`channel <name> { ... segment { ... expr = <expression> ... } }`. Expressions
are unquoted when they have no spaces, `"` escaped as `\"` either way
(`expr = chs(\"../file_unc/file\")`), quoted when they have spaces, newlines
kept literally; Python ones add `language = python` (measured).
