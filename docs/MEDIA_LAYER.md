# Media / Container Layer

Version: 1

## Purpose

A classic game is not always one ROM file. Cartridge systems often use one binary image, while optical systems may use a descriptor plus one or more track files.

Classic Retro therefore resolves user input into a deterministic MediaSet before platform or game detection.

## Supported media inputs in this phase

### Single file

Any non-CUE file is represented as one payload member. Platform identification still uses content signatures, not the filename extension.

### CUE + referenced files

CUE input is parsed into FILE, TRACK, INDEX, PREGAP, and POSTGAP layout data.

Common metadata-only commands are accepted but ignored by the layout model.

Every referenced file must exist. Missing files are fatal.

The CUE format is widely implemented but does not have one universally enforced syntax specification, so Classic Retro intentionally implements a conservative subset and rejects unknown layout-affecting commands.

Reference:
- https://www.gnu.org/software/ccd2cue/manual/html_node/CUE-sheet-format.html

## Deterministic media identity

A MediaSet identity is SHA-256 over canonical structured data containing:

- media kind,
- semantic CUE layout digest when present,
- ordered member roles,
- member sizes,
- member SHA-256 values.

Absolute paths and filenames are not part of the identity. Moving or renaming a correctly updated set should not change content identity.

## Optical sector view

Classic Retro exposes supported CD data tracks as a logical stream of 2048-byte data sectors.

Initial layouts:

- MODE1/2048
- MODE1/2352
- MODE2/2352

For raw 2352-byte sectors, only the user-data window is exposed to the ISO9660 layer.

PlayStation CDRWIN BIN/CUE commonly stores raw 0x930-byte sectors and uses MODE2/2352 for the first data track.

Reference:
- https://psx-spx.consoledev.net/psx-spx.pdf

## ISO9660

Classic Retro uses PyCdlib for ISO9660 parsing rather than implementing the filesystem from scratch.

Reasons:

- pure Python,
- actively maintained,
- supports current Python releases,
- parses and writes ISO9660,
- works with arbitrary file-like objects through open_fp,
- also supports Joliet, Rock Ridge, UDF, and related standards for future platforms.

References:
- https://clalancette.github.io/pycdlib/
- https://clalancette.github.io/pycdlib/python-compatibility.html
- https://clalancette.github.io/pycdlib/pycdlib-api.html

PyCdlib is LGPL-2.1-only.

A disc overlay that repoints a file reads the directory records itself
(`patching.cdrom.iso_file`), because it needs each record's sector and offset to
rewrite it in place.

## PlayStation identification

For a CUE/BIN input, the built-in PS1 probe currently requires all of the following:

1. a supported binary data track,
2. a readable ISO9660 filesystem,
3. SYSTEM.CNF at the disc root,
4. a BOOT target from SYSTEM.CNF,
5. the target file beginning with PS-X EXE.

SYSTEM.CNF and PS-X EXE are documented PS1 boot structures.

Reference:
- https://psx-spx.consoledev.net/cdromfileformats/

This identifies the platform only. It does not mark a game revision as translation-supported.

## Writing a data track

`patching.cdrom` writes sectors of a CD data track in place, for a disc overlay
(Castlevania: Symphony of the Night). A Mode 2 Form 1 sector is written whole: sync,
header (its address in BCD minutes, seconds and frames), subheader, data, EDC (CRC-32
with the polynomial `0x8001801B`, reflected) and the ECMA-130 P and Q parity, computed
with the header counted as zero. The tests check the EDC against the CRC's check value
and every P and Q codeword's syndromes; every sector of the files the overlay reads is
checked on the user's disc. A file that grows moves to the empty sectors at the end of
the data track and its ISO 9660 record is repointed; the track keeps its size, and the
CUE sheet and the other tracks do not change.

## Deliberate limitations

This phase does not rebuild a whole BIN/CUE image or change its layout: sectors are
replaced in place, and Form 2 sectors, CDDA tracks and pregaps are not written.

Correct rebuilding must account for details such as:

- sector mode,
- EDC/ECC,
- XA Form 1/Form 2,
- CDDA tracks,
- pregaps,
- mixed-mode track boundaries,
- games using hidden sectors or non-filesystem archives.

Some PS1 titles place important resources outside the ordinary ISO9660 directory tree, so ISO file listing can never be assumed to expose the complete game.

Reference:
- https://psx-spx.consoledev.net/cdromfileformats/

Rebuild support will be introduced separately with fixture-backed round-trip tests.
