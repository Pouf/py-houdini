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

The mode belongs to the scene (measured): a new scene in hython is `Binary`,
loading a file sets the mode of its container, so re-saving a loaded scene
keeps its container. `hou.hipFile.saveAndBackup()` copies the previous file
as it is (a MIME file stays MIME in `backup/` even after switching the scene
to `Binary`), `saveAsBackup()` writes in the current mode.

The same scene saved both ways has the same sections in the same order, with
the same bytes except: `.variables` (`HIP`, `HIPFILE`), `.def` (modification
time), `.userdata` (text in MIME, binary in cpio) and base64 encoding in MIME
(measured).

Production census (`research/hip_sweep.py`, every file read in full,
2026-10-10): 18,214 files named `.hip*` (352 GB): 17,577 MIME (328 GB,
Houdini 18.5.759 to 20.5.487, 99.7% 20.5.370), 577 cpio (19 GB, 18.5.759 to
20.5.370), and 60 others: Apprentice files (`HouNC\x1a` header, encrypted,
out of scope) and files of other formats named `.hip` (Alembic, Guerilla,
Maya, hscript scripts, empty files). Backups (`backup/*_bakN.hip`) are 72% of
MIME and 79% of cpio files. Which saves produce cpio is not established
(neither version, share, nor backup paths separate them).

### MIME (Text)
Observed on all 17,577 production MIME files but one (a file whose every line
ends with CRLF, converted outside Houdini), and measured:

- Layout, exactly:
  ```
  MIME-Version: 1.0\n
  Content-Type: multipart/mixed; boundary="<B>"\n
  \n
  then per part:  --<B>\n<part header lines>\n\n<body>\n
  end:            --<B>--\n
  ```
  with `<B>` = `HOUDINIMIMEBOUNDARY0x<8 hex>-0x<8 hex>-0x<8 hex>-0x<8 hex>HOUDINIMIMEBOUNDARY`
  (upper-case hex). Parsing on that layout rebuilds every one of these files
  byte for byte. A body is everything between the part header's blank line and
  the `\n` before the next `--<B>`. A scene may have no parts at all.
- No content lengths: parts are delimited by the boundary only.
- Part headers have exactly two forms:
  `Content-Disposition: attachment; filename="<section name>"\nContent-Type: text/plain`,
  or the same with `Content-Type: application/octet-stream\nContent-Transfer-Encoding: base64`
  (`.OPdummydefs`, `.datablocks`, `.takes`, `.outputinfos`, `.data`; a few
  `.outputinfos` are text).
- base64 sections: each line encodes 128 bytes on its own (172 characters,
  padding included), the last line the remainder, every line ending with
  `\n`. Re-encoding the decoded bytes that way gives back every production
  section; decoded, the bytes equal the cpio twin's section (measured).
- Text is stored as written, CR bytes included (a multi-line expression with
  CRLF line ends keeps them in both containers), but Houdini's MIME reader
  drops the CRs: hython reads that expression with LF from the MIME file and
  with CRLF from the cpio twin (measured).

### cpio (Binary)
- Each entry: a 76-byte header `070707` + octal fields dev(6) ino(6) mode(6)
  uid(6) gid(6) nlink(6) rdev(6) mtime(11) namesize(6) filesize(11), then the
  NUL-terminated name, then the data. The last entry is `TRAILER!!!`.
- The archive ends exactly at the end of the file, no block padding; sizes are
  always zero-padded octal of the field width (all 577 production files).
- Header fields are constant (dev 1, ino 0, mode 0666, uid and gid 0, nlink 1,
  rdev 0) except mtime and the two sizes (all production entries). mtime
  varies between entries of a file (up to dozens of values): it is per entry.
- One production file is truncated: it stops at an entry boundary, without
  `TRAILER!!!`.
- Binary sections are stored raw. `.userdata` is binary where MIME has JSON
  text (measured on single string entries: a big-endian u32 count, then a
  u16-length-prefixed key, a u32 (3), a u16-length-prefixed value).

## Text encoding
Text is UTF-8 (measured: `C:/données/...` is written `C:/donn\xc3\xa9es/...`;
every non-ASCII text section of the production files decodes as UTF-8:
`.parm`, `.spareparmdef`, `.postitdef`, `.netboxinit`, `.application`). CR
bytes appear only in `.chn` (multi-line expressions with CRLF line ends).
Section names are printable ASCII without spaces (all production files).

## Binary sections
First bytes (all production files): `.OPdummydefs` `INDX` (asset library),
`.takes` `HoudiniT...`, `.outputinfos` `NumInfos...`, `.datablocks` a
big-endian u64 (1 to 3), `.data` `\x7fNSJb` (probably Houdini binary JSON), `.userdata`
(cpio only) a big-endian u32 entry count.

- `.OPdummydefs`: an asset library (`INDX` index, then per definition its
  sections: `DialogScript` text with parameter defaults, `Contents` as a nested
  cpio archive...) holding the definitions the scene uses, so it loads without
  their libraries. It names types and `oplib:` paths, not library files; paths
  in it come from the definitions (parameter defaults) (measured).
- `.takes`: `HoudiniTakeFile 1.0\n`, then per take a `take name <name> kids <n>\n`
  line followed by records, each a big-endian u32 length then text: `s 0 <node
  path>\n`, `s 1 <parm name>\n`, `d 0 1\n`, a `.parm`-style block with the
  overridden values, `e\n` to close the take (measured on a take overriding one
  parameter). Production files hold only the empty `Main` take (every `.takes`
  is 48 bytes or less).

## Where paths and node names appear
Census of a replace of each file's item name and share root over 360
production files (`research/replace_census.py`): in `.variables` (`HIP`,
`HIPFILE`, `HIPNAME` in every file, other variables), `.parm` values (plain and
animated `[ channel value ]`), `.chn` expressions (including multi-line Python)
and `defaultString`, section names (nodes named after the item), `.order`,
`.def` input blocks (`inputsNamed3`, `inputs`), `.spareparmdef` defaults,
`.OPlibraries`, `.OPfallbacks`, `.OPpreferences`, `.userdata` (JSON in MIME,
binary in cpio), `.application` (pane paths, flipbook and audio files), and
binary `.OPdummydefs` (definition contents).

## Sizes
Sections can be large: a `.parm` of 164 MB, a `.gdelta` of 36 MB, an
`.OPdummydefs` of 3 MB (production maxima).

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
