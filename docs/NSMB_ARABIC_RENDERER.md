# New Super Mario Bros. Arabic Renderer v1

Target: *New Super Mario Bros.* (USA), the first Nintendo DS target. The
[NSMB-Decomp/nsmb](https://github.com/NSMB-Decomp/nsmb) decompilation names the text
classes (`BMGReader`, `FontRenderer`, `FontCache`...) but cannot build a ROM yet, so this
is a binary ROM overlay built from the user's image. The facts below come from the image
itself, read with the toolkit's DS formats, and from DeSmuME runs
([research tools](RESEARCH_TOOLS.md), `--core desmume_libretro.so`).

| Item | Value |
|------|-------|
| ROM size | 33554432 bytes (32 MiB) |
| SHA-1 | `a22713711b5cd58dfbafc9688dadea66c59888ce` |
| SHA-256 | `9f67fef1b4c73e966767f6153431ada3751dc1b0da2c70f386c14a5e3017f354` |
| Game code | `A2DE` (`NEW MARIO`), maker `01`, header revision 0 |
| Output | 32 MiB image (same size), shipped as BPS |

## Engine facts the overlay relies on

- **Header.** The ARM9 binary is at `0x4000`, `0x5EFA4` bytes packed, loaded at
  `0x02000000`; the 12 bytes after it (the words `0xDEC00621`, `0xB48` and `0x4293C`)
  are the SDK's footer, and the ARM9 overlay table follows at `0x62FB0`. The file
  system's name and allocation tables are at `0x226EA0` and `0x2310F4` (1957 named
  files). The used area ends at
  `0x13A5720`, followed by the 0x88-byte signature DS Download Play checks.
- **ARM9.** Packed with the SDK's backward LZ (`rebuild/blz.py`): the first `0x4000`
  bytes (the secure area and the start-up code) are stored as they are, and the start-up
  code unpacks the rest in place to `0x8E090` bytes. The module parameters at `0xB48`
  hold, at `+0x14`, where the packed data ends in RAM (`0x0205EFA4`), and at `+0x1C` the
  SDK's two magic words.
- **Messages.** The menus and prompts are three BMG files ("MESGbmg1", UTF-16, entries
  of 4 bytes: the text's offset): `script/data.bmg` (the file select, 10 messages),
  `script/course.bmg` (the world map, 16) and `script/game.bmg` (a level, 16). A text is
  UTF-16 with `\n` for a line end and escapes: `001A`, the escape's size in bytes, its
  kind, then its argument. Kind `FF` with the argument `0000cc00` sets colour `cc` for
  what follows (0 the text colour, 1 a number, 2 a choice that cannot be taken); kind
  `01` (`0100`) writes in a number the game supplies, the Star Coins a gate asks for.
- **Font.** `font_a.NFTR`, in the NARC `message/common/USA` inside the unpacked ARM9
  (the NARC at `0x3267C`, the font as "LZ77" and BIOS LZ77 data at `0x341C4..0x3589B`,
  the next file at `0x3589C`). 387 glyphs of 11x15 pixels at two bits a pixel, of which
  the letters use one value (1); line feed 15, baseline 13. Its character map covers
  ASCII, Latin-1, symbols, the DS buttons (private use, `U+E000..`) and 166 kana
  (`U+3041..U+30FC`, glyphs 186 to 351, each drawn by no other code), which the English
  game never shows.
- **Renderer.** A message is laid out line by line, each line centred on its own and
  drawn at once from its left; nothing types it out or wraps it. The game draws a grey
  shadow one pixel right, below and on the diagonal of every glyph pixel. Menus take a
  line per choice and put the cursor's arrows on either side of the chosen line, from
  its width. Yes and No are messages of their own, at fixed places.
- **Other text.** The embedded `error.bmg` (save errors) and `msg_data.bin` (the
  minigames, in the 3D font) are separate; the level's HUD, the Options screen, the
  title and the file select's buttons are pictures.

## Right-to-left text

No routine changes. The game centres each line and draws it at once, so a line stored in
visual order, its glyphs from the leftmost to the rightmost, shows exactly as a
right-to-left line would. The build does the bidi work (`engines/nsmb_arabic.py`):

1. each line of the logical text is shaped (contextual forms, no ligatures) and put in
   display order by the shared pipeline, which for a line of Arabic, spaces and
   punctuation is the line reversed; a line the algorithm would order otherwise (Latin
   letters or digits, which keep their own direction) is refused;
2. every glyph keeps the colour it has in the logical text; colour escapes go where the
   colour changes along the stored line, and the line ends in the colour its logical
   text ends in, so the next line starts right;
3. the number the game writes in is one unit of its line: it moves with the reversal,
   and its digits (the game's own) read left to right, as numbers do in Arabic.

A line's first glyph in reading order is its rightmost, with the blank of its advance on
its right; the cursor's arrows end up a pixel further on that side than on the other.

## How right-to-left text is marked

It is not: every message of the three files is translated, and each is stored in the
order it is drawn.

## Glyph codes

The Arabic glyphs replace the kana: the code points `U+3041..U+30FC`, in order, are the
Arabic glyph codes (`ARABIC_CODES`). Codes go only to what the script uses, in a fixed
order (the space, `.`, `!`, `:`, then the forms by code point), so the same characters
always get the same codes; the kana left over are blank, 0 pixels wide. A form wider than
11 pixels takes two codes, its left half's then its right half's. The script uses 84
codes of 166.

## ROM layout

Nothing is added to the ARM9 or its RAM; its packed size shrinks.

| Place | Contents |
|-------|----------|
| `0x4000..0x62FA4` | The ARM9, packed again: `0x5EA9C` bytes, then the SDK's 12-byte footer, then `FF` up to the overlay table |
| NARC `message/common/USA`, `0x341C4..0x3589C` (unpacked ARM9) | `font_a.NFTR` with the Arabic glyphs: "LZ77" and 4964 bytes, then `FF`; the NARC's table gets the new end |
| `script/course.bmg`, `script/game.bmg` | In place (they got shorter) |
| `script/data.bmg` | Moved to `0x13A5800`, past the used area (it grew); the signature follows it and the header's used size too |
| Header | ARM9 size, used size, secure-area CRC, header CRC |

**Packing the ARM9 again.** `rebuild.blz.repack_blz` packs the changed binary like the
original: it reads the original's items, keeps every item that still produces the same
bytes, gives a match that now copies changed bytes another distance where the same bytes
lie, and packs only the groups of eight items around the changes again, in whole groups,
so every group after them keeps its flag byte. The patch therefore carries the new font
and a few dozen bytes around it, not the game's code (a full repack would put 350 KB of
the ARM9 into the patch). The result must decompress in place: the data decoded first
must never save more than the whole does, or the start-up code would overwrite bytes it
has not read; the build checks it by decompressing in one buffer, as the console does.

**The font.** `compress_lz77_optimal` packs the new font: the original is packed tighter
than a greedy compressor can manage (the repository's greedy LZ77 needs 5920 bytes for the
original font's 5843), and the NARC leaves 5848 bytes before the next file. Like the
original, no match copies the byte just before it, which the SDK's 16-bit unpacker
cannot do. The "LZ77" of the next file must stay: a first prototype that ran over it
never got past a white screen.

**The secure area's CRC** (header `0x6C`) covers the ARM9's first `0x4000` bytes as a
cartridge stores them, the first 2 KiB encrypted. The packed end changes at `0x4B5C`,
outside the encrypted part, and a CRC is linear, so the new value is the old one with the
CRC of the difference (and of zeros) added (`patching.nitro.secure_area_crc`).

## Font

The reference font is Noto Kufi Arabic SemiBold, drawn at 12 pixels, the largest size at
which every form of the repertoire fits the 15-row cell with the baseline on row 11,
two rows above the Latin letters': Arabic descends further than Latin, and the game's
cell is short. Hamza over alef is drawn by hand above a shortened alef, final and
isolated yeh are raised a row, and a dot that stays under the ink level keeps its
strongest pixel. Coverage from 96 of 255 is ink (1); the game adds the shadow. Seen and
sheen in every form and the final and isolated sad, dad and feh are wider than 11 pixels
and are split into halves. The space is 4 pixels, and `.`, `!` and `:` are drawn by hand
on the Arabic baseline; the Arabic comma and question mark come from the font. Lam and
alef stay two glyphs.

## Translations

`rom/nsmb_arabic_script.py` pins the 42 messages of the three files by file and index,
the SHA-256 of the UTF-16 text and its escapes and line ends. The Arabic is in
`translations/nsmb.json`. A translation keeps every escape and line end in order; lines
are measured against the room their place leaves: 48 pixels for an answer, 128 for a
menu's choice, 200 for a prompt's line (the file select's band is 256 wide, the
windows about 230). The number is counted as two of the game's digits (14 pixels).
START is written as the button's name in Arabic (زر البدء), since a line holds no Latin
letters.

## Verification

With the reference font the build matches `reference_patch_sha256` (a 7615-byte
patch). In DeSmuME, from power-on with the patched image:

- the file select's message in its band;
- the world map's menu (three choices, the cursor's arrows on the chosen one), and its
  quit prompt with the two answers;
- level 1-1's pause menu, with the choice that cannot be taken greyed out, and the
  cursor passing over it;
- a local probe build that puts the widest file prompt (191 pixels) in the file select's
  band and a Star Coin gate's two lines in the quit prompt's window: both fit and read
  right to left (the number stays empty there, since only the gate's code fills it);
- starting a game and playing into level 1-1: the repacked ARM9 runs.

A script for `classic-retro research run` that reaches the world map's menu (inputs
only):

```text
run 1200
tap A
run 180
shot file-select.png
tap A
run 1410
tap START
run 120
tap START
run 120
```

then eighteen times `run 200` and `tap A` (the opening scene, up to the world map),
`tap START`, `run 60` and `shot map-menu.png`. From the map, `tap RIGHT`, `run 90`,
`tap A`, `run 600`, `tap START` and `run 40` open level 1-1's pause menu.

## Limits

- The menus and prompts only: the Options screen, the HUD, the title, the file select's
  buttons and the level names are pictures and stay in English, like the minigames and
  the save-error messages kept inside the ARM9.
- No Latin letters or digits inside Arabic lines (the number the game writes in is
  fine), no vowel marks, no ligatures, one size.
- A line holds 200 pixels at most, and a translation keeps the original's line ends.
- The Star Coin gates and the Challenge mode's greeting were checked in previews and a
  probe build, not reached in play.
- The patched image's signature no longer matches its ARM9, so DS Download Play from
  one cartridge may be refused by the other console; single-player is what was tested.
