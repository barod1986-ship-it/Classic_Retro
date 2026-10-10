# Pokémon Polished Crystal 3.2.3: the Arabic renderer

Version: 1

Target id: `polished-crystal`, a source overlay on
[Rangi42/polishedcrystal](https://github.com/Rangi42/polishedcrystal) at tag `v3.2.3`
(commit `3fa43192379df5c3e7b09a08e4d5d79af4f02f42`). It is the first Game Boy Color target,
and the first that translates a whole game rather than a scene: every text the game shows is
an entry of the overlay's manifest, and the translation fills them in batches. The guide for
players and testers, in Arabic, is [POLISHED_CRYSTAL_ARABIC_TEST_AR.md](POLISHED_CRYSTAL_ARABIC_TEST_AR.md).

## Identity

| | |
|---|---|
| Image | `polishedcrystal-3.2.3.gbc`, 2,097,152 bytes (MBC3 with the real-time clock, 32 KiB SRAM) |
| SHA-1 | `6930b48af5844d373e3c9130f26d6dd1084cf4ed` |
| SHA-256 | `f06dbebe3fd20db54e7804605f7a55ad05b8ca203c62209705290d8880864803` |
| Build | `make` with rgbds 1.0.0 builds this image byte for byte from the pinned commit |
| Game adapter | `pokemon-polished-crystal-3.2.3` (`classic-retro detect` knows it), engine `gbc.pokemon-gen2` |

## How the overlay works

`classic-retro targets prepare polished-crystal CHECKOUT --font FONT` patches a pristine
checkout; `make` then builds the Arabic ROM, and `classic-retro polished-crystal make-bps`
makes the BPS patch from the user's ROM and the built one. Three files ship with the overlay
(`src/classic_retro/source/polished_crystal/data/`), none of them holding text of the game:

- `pins.json`: the git blob of every file the overlay reads or writes (765 files). `prepare`
  refuses a checkout where any differs, before it writes anything.
- `engine_patch.json`: the engine changes, as hunks. Each hunk keeps its start line, how many
  lines it removes and the SHA-256 of those lines (never the lines), and the lines it adds,
  which are the overlay's own code. The one added line that repeats a string of the game (the
  battle text's word for the foe moves after the name) refers to the removed line's string
  instead of holding it (`[k, j]`: string `j` of removed line `k`). 54 files, 271 hunks, 4 new
  files.
- `manifest.json`: the 13,486 texts of the engine-patched tree, by stable id
  (`<path>:<label>`, `+n` for inline text, `[k]` for the k-th string of a label, `#k` for the
  k-th item of a list). Each has its kind, the lines it owns, a pin of those lines (16
  hexadecimal digits of their SHA-256), its placeholders, its limits and the structure the
  encoder rebuilds it from. It is compacted (entries by file, tables of limits and formats) and
  has no contexts: those are in the translation file.

`prepare` then:

1. applies the engine patch, checking every hunk's removed lines;
2. encodes every translated entry (`source/polished_crystal/encode.py`) and puts it in place of
   the lines it owns, checked by their pin. A translation that leaves an entry out is refused:
   the Arabic glyphs take the Latin letters' codes, so English left in would show as wrong
   letters (an entry whose limits allow it may be translated by an empty text);
3. lengthens the short jumps over text that grows (below);
4. writes the generated files from the pinned originals: the fonts, the VWF font, the
   Pokédex's tilemaps, the charmap, the n-grams, the keyboards, the shaping tables and the key
   phrase;
5. records what it wrote and the pins of what it read in `.classic-retro-arabic.json`. The
   same command on the same tree with the same translation does nothing; any other prepared
   tree, or one where a written or a pinned file changed since, is refused.

Everything is computed before the first file is written.

## Glyphs and codes

The game draws text a byte a tile: code `$7f` to `$ff` is an 8x8 glyph of a 1bpp font. The
reference font (Noto Kufi Arabic) is not legible at 8 pixels, so the overlay's glyphs are pixel
art drawn by hand (`engines/pokemon_gen2_arabic/glyphs.py`), and the `--font` argument every
target takes is not read. Row 5 is the joining baseline: a form that joins the next letter
reaches column 0 on it, one joined by the letter before reaches column 7.

An 8x8 cell cannot tell every contextual form apart, so forms share glyphs: beh, teh, theh,
noon and yeh have one glyph for the isolated and final forms and one for the initial and
medial ones; ain, ghain and heh keep three or four. 70 glyphs cover the 36 letters (28, the
hamza and alef variants, teh marbuta and alef maksura) and the four lam-alef ligatures. They
take the 70 codes the English font gave to the Latin letters (`$80-$99`, `$a0-$b9`), the
contractions and the accented letters (`$c0-$d1`), in the order of `GLYPHS`. Everything else
keeps its code: the digits `$e0-$e9`, `. ! - : / × % + ¥ …`, `♂ ♀ & ♪ ♥`, the special tiles
and the space. Three are redrawn: `$9d` (the comma) as `،`, `$9e` as `؟`, and `$ba` as a
neutral quotation mark, which every quotation mark of the translation becomes. Latin letters
stay in the charmap as aliases of the same codes, so untranslated English still assembles.

The typefaces option keeps Normal (the Arabic glyphs), Bold (the same glyphs emboldened a
pixel to the left) and Unown (the Ruins of Alph's own glyphs).

## Shaping

The translation is written in logical Arabic. The build shapes it
(`engines/pokemon_gen2_arabic/forms.py`): each letter takes its form by its neighbours'
joining types (dual, right, or none for the hamza), and lam before an alef becomes one
lam-alef glyph. The source holds the presentation forms (U+FE70 to U+FEFC), which the charmap
maps to the glyph codes. Names have no lam-alef: the naming screen's runtime shaper has none.

## Right to left

The engine (`home/rtl.asm`, `engine/gfx/rtl_reverse.asm`, `engine/gfx/rtl_box.asm` and the
changes to `home/text.asm`) has two modes:

- **The speech box, a reversed pen.** A text that starts at the box's origin is drawn leftward
  from the box's right inner edge (column 18), so the typewriter reveals it from the right;
  `<LINE>`, `<CONT>` and `<PARA>` restart at the right edge, and the button arrow sits at the
  bottom left. A run of digits (with `. , : /` between two digits, and `¥ ′ ″`) is drawn
  leftward like the rest and put back left to right when it ends, so "20,000" and "10:30"
  read as numbers. `text_decimal` prints its number as such a block.
- **Every other string, reversed lines.** Strings placed at explicit coordinates (menus,
  labels, the summary, the Pokégear...) are drawn left to right as the English was, by the
  outermost `PlaceString`, which owns the line; when the line ends its tiles are reversed in
  place, so it reads right to left in the same footprint. Text between runs of two or more
  spaces is reversed on its own, so a line's columns keep their places, and digit runs stay
  left to right. Only lines in a tilemap are reversed: a `PlaceString` into a RAM buffer is a
  plain copy.

Where a paragraph must end at a box's right edge (descriptions of items, moves and abilities,
the Pokédex's text, the mail, the diploma, the egg hints), `PlaceStringRight` places each line
ending at the edge. The map's name sign reverses the name before it centres it. The
Pokédex's labels are drawn into its tilemaps in visual order by the overlay
(`source/polished_crystal/dex.py`; each label is an entry of the translation, `gfx/pokedex/*`).
Clocks, the main menu's time, the battle menus, the bag's submenus and the start menu were
widened or mirrored for the Arabic labels (the comments of the engine patch say where).

## The player's gender

`<GM>masculine<GF>feminine<GE>` (codes `$4a-$4c`, in the notation `{masculine|feminine}`)
shows the side that fits the player and skips the other. The three codes take the place of
three English n-grams and are Huffman leaves (the shifted leaves start at `$4a`). An
alternative holds letters, spaces and signs only; the encoder refuses one whose sides would
give a neighbouring letter different forms, so words go whole into the braces.
`text_plural` (the English plural) does nothing; the word for the foe's Pokémon follows the
nickname.

## The variable-width font

Item names in Bill's PC, ability names in battle and the Pokédex's area labels use the VWF.
Each Arabic glyph is cropped to its ink (`engines/pokemon_gen2_arabic/fonts.py`): a joining
side keeps one pixel of its joining stroke, so joined letters touch while the font stays
narrow, and a side that does not join gets one blank column, the gap between letters. The VWF
draws right to left (`VWF_RTL`): each glyph moves the pen left by its width. Budgets: item
and ability names 80 pixels, the area labels 53.

## The naming screen

The keyboards (names: 9x5 cells, mail: 10x5) type isolated letters, alef in the top right
corner; page 2 holds digits and symbols. `ShapeArabicName` gives each letter the form its
neighbours call for, in place, every frame and when the name is stored, from two tables
(`data/text/arabic_shaping.asm`): the letter of each glyph and the four forms of each letter.
`naming.self_test` models the routine and checks it against the build-time shaper over every
string of up to three characters and 20,000 random ones, so a typed name is stored byte for
byte as the build writes names. The trendy phrase the game checks for
(`data/text/lucky_key_phrase.asm`) is the translation's entry
`engine/events/specials:CheckIfTrendyPhraseIsLucky.KeyPhrase`, shaped the same way.

## Text codes: Huffman and n-grams

Polished Crystal Huffman-codes its speech-box text with the codes of the charmap's `ctxtmap`
lines (at most 128 leaves and 127 parents, codes up to 24 bits here), and gives 64 strings
of the other texts one-byte n-gram codes (`$0a-$49`, expanded from `data/text/ngrams.asm` in
ROM0). `prepare` trains both on the tree it writes (`source/polished_crystal/textcodes.py`):
the Huffman codes from the symbols of every compressed text, translated or not; the n-grams
greedily from the uncompressed strings, within the bytes the English n-gram strings took in
ROM0. An n-gram is a sequence of glyph codes, written in the charmap as every spelling of it
the tree uses (several presentation forms and Latin letters share a code), so the assembler
applies it wherever it fits. `, ` stays an n-gram, as the encoder counts it as one byte.
`#mon` stays a Huffman leaf: once its entry (`data/text/ngrams:NgramStrings.Pokemon`) is
translated, the encoder writes `#mon` wherever the Arabic word occurs.

## Short jumps over text

`jr` (a signed byte) and the scripts' `sjumpfwd`, `iftruefwd`, `iffalsefwd` and `ifequalfwd`
(an unsigned byte, forward) store their distance in one byte; the assembler only warns when
it overflows. Where text lies between such a jump and its target, `prepare` estimates every
text's size before and after (`sizes.SizeModel`, the text macros' own rules) and writes the
long form (`jp`, `sjump`, `iftrue`, `iffalse`, `ifequal`) of each jump whose texts grow, or
shrink by less than a margin of 3 bytes: about 80 jumps at 73% translated. The build then
warns that some long jumps "can be" short (`-Wassert`), which is harmless.

## Space

| | Pristine | Arabic (73% translated) |
|---|---|---|
| Free space (`tools/bankends`) | 33,648 bytes | 37,866 bytes |
| ROM0 free | 351 bytes | 254 bytes |

The ROM is 2 MiB; banks `$7e` and `$7f` are empty in the pristine build. `rgblink` places
sections past bank `$7f` without an error, so `tools/bankends`, which `make` runs, is the guard:
it fails on a bank `$80`. Arabic is shorter than English in glyphs (about 0.8 tiles per
English tile) but its symbols are more even, so a Huffman code costs about 10% more per
glyph; the translators keep each batch at or below 0.95 of the English length.

## What a translation must respect

`targets check-translations polished-crystal` checks every entry without a checkout:

- **dialog** (the speech box): 18 cells a line, wrapped by the encoder; `\p` starts a page;
  placeholders count at their widest (`{PLAYER}` 7, `{USER}` 16, `{ENEMY}` a line);
- **box** (descriptions, the Pokédex): the entry's width, lines and pages (`\f`);
- **string** (menus, labels, names): the entry's width and lines (`\n`), columns separated by
  two or more spaces where the English had columns, bytes where a table limits them, the room
  of a one-byte `dr` table shared by its strings (`limits.dr_groups`). A string's width is the
  English's unless `source/polished_crystal/screen.py` gives the room read from the patched
  screen (its coordinates, frame, neighbours and byte copies); a variable-width field is
  measured in pixels with the Arabic VWF glyphs (`limits.vwf_px`);
- **field** (fixed-size names): its cells and bytes, padded with `@`; no gender alternatives in
  a raw field.

A translation keeps the original's placeholders (their count; the order may change). The
coverage (entries translated, by category) is in the report.

## Regenerating the data

```text
classic-retro polished-crystal make-engine-patch ENGINE_CLONE --ref main   # engine_patch.json
classic-retro polished-crystal make-manifest PRISTINE_CHECKOUT --contexts contexts.json
python tools/polished_crystal_translations.py --fill FILL.json --batches 'batch-*.ar.json' \
  --glossary-dir GLOSSARY --contexts contexts.json
classic-retro targets check-translations polished-crystal --font FONT --preview-dir DIR --update-digests
```

The manifest follows the engine patch (its `engine_patch` field is the patch's SHA-256, which
a test checks), and the digests follow the translation.

## Known issues

- An untranslated text would be drawn with the Arabic glyphs at the Latin letters' codes, so
  `prepare` refuses a translation that leaves any entry out; `check-translations` reports the
  coverage of a translation still in progress.
- Some engine strings that had no translation entry before the engine patch hold placeholder
  Arabic in the engine's code (the naming screen's titles and keys, the typeface names, the
  link battle's "against"); they are manifest entries of the patched tree and can be
  translated like any other.
- The Unown dex words and the Ruins of Alph's puzzles stay in Latin letters (the Unown font).
- The five removed typefaces' PNGs are still written (with the Arabic glyphs), so no font
  file keeps Latin glyphs at the Arabic codes; they are not in the ROM.
- Weekday names are written whole in the stems (`PrintDayOfWeek`), and the suffix entry is
  translated by an empty text.
- `targets extract` reads the originals from the engine-patched copy of the user's checkout
  with the extractor (about 20 seconds); the workspace holds only the entries of the
  translation file.
