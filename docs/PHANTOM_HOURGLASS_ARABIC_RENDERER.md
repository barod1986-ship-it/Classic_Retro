# Phantom Hourglass Arabic Renderer v1

Target: *The Legend of Zelda: Phantom Hourglass* (USA, En/Fr/Es), the third Nintendo DS
target. The [zeldaret/ph](https://github.com/zeldaret/ph) decompilation (commit
`29e3578e388b2ff350388e2cdfe45497c4ebdae2`) targets this image (`ph_usa.sha1`) and gave the
names and addresses below; it rebuilds the game from the user's own copy and is not finished.
The translation patches the user's own image, so this is a binary ROM overlay shipped as a
BPS patch. The facts were checked in the image and in DeSmuME with the
[research tools](RESEARCH_TOOLS.md): `research run` with touches, and `peek`, `dump` and
`poke` on a DeSmuME core built from libretro/desmume's current source.

| Item | Value |
|------|-------|
| ROM size | 67108864 bytes (64 MiB) |
| No-Intro | *Legend of Zelda, The - Phantom Hourglass (USA) (En,Fr,Es)*: SHA-1 `4c8f52dd719918bbcd46e73a8bae8628139c1b85`, SHA-256 `2dd43288c1b7b428cbd09d9a74464b9a46fe0239eaed82849369f261678011f7`, CRC32 `8B431C41` |
| Game code | `AZEE` (`ZELDA_DS:PH`), maker `01`, header revision 0 |
| Output | 64 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Messages.** Every text is a message of a BMG file, one set per language
  (`English/Message/*.bmg`; the game picks English, French or Spanish from the DS's
  language). The prologue is messages 0 to 6 of `English/Message/demo.bmg` (341 messages,
  rebuilt byte for byte by `text.bmg`). Texts are UTF-16 with line ends and escapes (unit
  `001A`, a size byte, a kind byte, an argument); an escape's kind and the first two bytes
  of its argument are the game's code for it. The prologue uses `{01:0A00nnnn}` and
  `{01:0E00nnnn}` (the typewriter waits `nnnn` frames; `0E` holds most pages' ends),
  `{01:1400nnnn}` (the typewriter's pace) and `{FF:0000cc00}` (the colour of what follows:
  0 white, 3 blue). No text of the game, in any language, uses a code from `3041` to
  `30FC`: only `3000`, the ideographic space, is found near them.
- **Font.** `Font/zeldaDS_15.nftr` (24044 bytes, not packed): NitroSystem's NFTR, 396
  glyphs of 14x16 pixels, 2 bits a pixel, a line feed of 16. The game's letters use three
  ink levels (1 to 3, 3 the full colour), smoothing their edges, and no shadow; capitals
  are 11 rows tall on row 14. The font maps the kana, `3041..3093`, `30A1..30F6` and
  `30FC`, 170 codes each with a glyph of its own, which the English game never shows.
- **The printer.** A message box is `UnkStruct_02032f0c` (zeldaret/ph's name; its cursor
  is `UnkStruct_02032e7c`). It draws into a NitroSystem character canvas at `+0x10` with
  the font at `+0x2C`, the letter spacing at `+0x30`, the line spacing at `+0x34` and the
  box's width at `+0x4A`. The cursor holds the message at `+0x04`, the pen at `+0x08` and
  `+0x0A`, the line's start at `+0x0C`, the colour at `+0x0E`. The typewriter draws a
  glyph at a time: `func_020334b4` calls `func_020296e0` (NitroSystem's
  `NNS_G2dCharCanvasDrawChar(canvas, font, x, y, colour, code)`, `bl` at `0x02033564`),
  then moves the pen by the glyph's advance (`func_02023ea4` finds the glyph,
  `func_02023eec` its widths) and the spacing. A line end takes the pen back to the line's
  start and down a line.
- **The prologue's box** (read in DeSmuME at the first page): a canvas of 28x8 characters
  of 4 bits, 224 pixels wide, the box's width 224; the pen starts at 9, letters are 1
  pixel apart, lines 18 (16 and 2). The box shows three lines; the line end after a
  page's third line clears it and starts the next page at the top (message 5's first page
  holds its three lines across a `0E` wait). It is centred on the top screen.
- **The proof.** Turning the call at `0x02033564` into a `NOP` (`poke system_ram:0x33564
  0000a0e1` after loading a state in the prologue) stops the prologue's typewriter where
  it is; a few instructions recording the call's arguments gave the canvas, the font
  (the loaded `zeldaDS_15.nftr`), `x` = pen, the colour 4 and the code.
- **The ARM9.** At `0x4000`, `0x41A18` bytes packed (BLZ) with its NitroSDK footer (module
  parameters at `0xB64`), `0x60F78` bytes unpacked at `0x02000000`. Its ITCM autoload
  block fills all but 96 bytes of the ITCM, and its BSS runs up to the first overlay: it
  cannot grow. 476 bytes of `0xFF` separate its footer from the overlay table
  (`0x45C00`).

## Right-to-left text

The printer keeps its pen and lays a line out from the left. The hook draws each
right-to-left glyph at the mirror of its place on the canvas:

    x' = canvas width - x - glyph width

where the canvas width is its width in characters times 8 (224 in the prologue) and the
glyph width is the width of its bitmap (the font's `CWDH` width). The Arabic glyphs make
the mirror exact: each is as wide as its advance and the letter spacing (its `CWDH`
advance is its width less 1), so the glyphs the printer lays out a pixel apart meet once
mirrored, and a line starts 9 pixels from the canvas's right edge, as far in as the pen
starts on the left, and grows leftwards; the typewriter reveals it from the right. Pages,
waits, the typewriter's pace and the colours keep working unchanged.

- **Direction by glyph.** A code from `3041` to `30FC` is a right-to-left glyph. A
  translated line holds only right-to-left glyphs, its spaces and punctuation included,
  so all of it is mirrored; every other glyph is drawn where the game draws it, and every
  English, French and Spanish text is unchanged.
- **No state.** The hook reads only the call's own arguments (the canvas, the font, `x`
  and the code), so it needs no memory of its own and is the same for every printer that
  draws through this call.

## Glyph codes

The Arabic glyphs take the place of the font's 170 kana, in code order: the space, `.`,
`!`, `:`, then the forms by code point. Only the characters the script uses get codes;
seen and sheen alone and at a word's end, wider than a cell, take two codes (the right
half first). A kana code the script does not use becomes a blank glyph with no width. The
prologue uses 94 codes (`3041..30AB`) for 92 characters.

## Hook

The hook (`rom/phantom_hourglass_arabic_hooks.s`, ARM946E-S ARM code, 112 bytes) is linked
at `0x0204F314`, over `func_0204f358`, a routine of the C++ runtime (236 bytes) that
nothing calls: no branch of the ARM9 or of any of the 62 overlays reaches it, and no word
of them points to it (checked in the unpacked binaries, as well as in zeldaret/ph's
relocations). A larger routine those relocations leave without a reference,
`func_02050a20` (SHA-1's block function), is reached through a table from the overlay
digest check that NitroSDK runs on a Download Play boot, and stays untouched.

| Site | Original | Hook |
|------|----------|------|
| `0x02033564` in `func_020334b4` | `bl func_020296e0` | `hook_glyph`: a right-to-left glyph at the mirror of its place, then `func_020296e0` |

Anchors checked before any change: the call (a `BL` to `func_020296e0`) and the code
before it that sets its arguments (the canvas at `+0x10`, the font at `+0x2C`, the colour
and the code on the stack); the first 16 bytes of `func_020296e0`, `func_02023ea4` and
`func_02023eec`; the replaced routine (SHA-256); the ARM9 (SHA-256 packed and unpacked,
its module parameters, its footer and the padding before the overlay table); the font
(SHA-256, its cell and its kana); `demo.bmg` (SHA-256) and every translated original
(SHA-256, escapes and line ends). The build also checks that the stored hook calls
exactly these three routines (`cpu.arm.branch_targets`).

## Image layout

The ARM9 is packed again like the original (`rebuild.blz.repack_blz`): its compressed
items stay wherever the code did not change, so the patch carries the hook and not the
game's code. The files go back through `patching.nitro`:

| Part | Original | Arabic image |
|------|----------|--------------|
| ARM9 | `0x4000`, `0x41A18` bytes | `0x4000`, `0x41A78` bytes, in the padding before the overlay table |
| `Font/zeldaDS_15.nftr` | 24044 bytes | In place, the same size |
| `English/Message/demo.bmg` | 48128 bytes | `0x3410E00`: it grew, so it moved past the used area |

The module parameters get the ARM9's new packed end, and the header's secure area CRC
follows them (`secure_area_crc`); the header CRC comes last. The build reads everything
back: the ARM9 unpacked in place (changed only at the hook, the call and the packed end),
the files, and every byte outside the parts it wrote.

## Font

The reference font is Noto Kufi Arabic SemiBold, drawn at 11 pixels (the largest size, up
to 11, at which every form of the repertoire fits a 14x16 glyph), with the baseline on row
11: Arabic reaches further below its baseline than the game's letters. Seen and sheen
alone and at a word's end are split into two glyphs. Coverage from 96 of 255 is the full
ink (3) and from 48 the lightest level (1), the way the game smooths its own letters; a
dot that falls between pixels keeps its strongest pixel as ink, and smoothing never goes
right of a glyph's width, where the glyph painted before it lies. The space is 5 pixels;
`.`, `!` and `:` are drawn by hand; the Arabic comma and question mark come from the font.
Lam and alef stay two glyphs.

## Translations

`rom/phantom_hourglass_arabic_script.py` pins the prologue's seven messages, each by its
index in `demo.bmg`, the SHA-256 of its UTF-16 text and its escapes and line ends. The
Arabic is in `translations/phantom-hourglass.json`, in the BMG notation. A translation
keeps every escape and line end in order, so every page keeps its lines; words may move
between the lines of a page. A line holds at most 206 pixels (the box less the pen's
start on each side); the prologue's widest is 167. The names in blue (Tetra, Princess
Zelda) stay blue.

## Verification

With the reference font the build matches the reference patch (7602 bytes). In DeSmuME
(libretro/desmume's current source, the pointer as the touch screen), from power-on with
the patched image: every page of the seven messages typed from the right, the pauses and
the pages' waits as in English, the names in blue, the three dots typed one at a time;
then Niko's question about the cutouts, in English and in its bubble, as in the original.

A script for `classic-retro research run` that reaches the prologue from power-on on a DS
with no save, inputs only (the frame holds both screens, 256x384; the touch screen is its
lower half). The game names the file after the DS's user, which the emulator sets:

```text
# Core: desmume_libretro with --option desmume_pointer_mouse=enabled
# (enable on 0.9.11) --option desmume_pointer_type=touch.
run 1800
tap START 4 120
touch 128 288 6 120
run 300
# "A file has been created."
run 900
touch 128 350 6 120
run 200
# File 1: New Game!, the name keyboard: OK; Yes; the right hand: Yes.
touch 128 260 6 120
run 200
touch 205 367 6 120
run 1400
touch 212 302 6 120
run 2100
touch 212 302 6 120
run 200
touch 212 302 6 120
run 1500
# File 1, Start, Adventure: the prologue.
touch 128 260 6 120
run 200
touch 128 260 6 60
run 1700
touch 128 271 6 120
run 500
shot prologue-1.png
run 12000
shot niko.png
```

The prologue takes about three and a half minutes; nothing needs to be pressed.

## Limits

- Only the prologue is in Arabic; the title, the menus and keyboards (pictures and other
  message files), Niko's question after it and the rest of the game stay English.
- The Arabic replaces the English prologue only: a DS set to French or Spanish shows the
  prologue in that language.
- Arabic lines hold no Latin letters or Latin digits: the hook mirrors every glyph of a
  line, and no hook draws a left-to-right run inside one.
- The kana become Arabic forms for every text of the game: a name typed in kana on
  another DS (the battle mode's players) would show them.
- 170 glyph codes for the whole script (the prologue uses 94).
- No vowel marks, no ligatures, one size.
- Escapes other than the typewriter's timing and the colours are refused in Arabic text.
