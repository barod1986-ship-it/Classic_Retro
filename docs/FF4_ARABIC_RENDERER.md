# Final Fantasy II Arabic Renderer v1

Target: *Final Fantasy II* (USA, Rev 1, SNS-F4-USA), the third Super NES target. The
[everything8215/ff4](https://github.com/everything8215/ff4) disassembly rebuilds this
revision (its "Final Fantasy II 1.1 (U)", CRC32 `23084FCD`) and names its code, but it
takes the ROM's data from the user's ROM, so this is a binary ROM overlay: it patches the
user's ROM and ships as a BPS patch of it. The text engine was read from the ROM's own
65C816 code, checked against the disassembly and run in snes9x with the
[research tools](RESEARCH_TOOLS.md). Names in brackets are the disassembly's
(`field/window.asm`).

| Item | Value |
|------|-------|
| No-Intro | *Final Fantasy II (USA) (Rev 1)*: one ROM, no copier header (a dump of 1049088 bytes carries a 512-byte one, to be removed first) |
| ROM | 1048576 bytes, LoROM: CRC32 `23084FCD`, SHA-256 `414bacc05a18a6137c0de060b4094ab6d1b75105342b0bb36a42e45d945a0e4d` |
| Header | at `$7FC0`: its size byte at `$7FD7` (`0A`), its checksum and complement at `$7FDC`; `classic-retro detect` names the platform and the game (`final-fantasy-ii-usa`) |
| Output | The ROM with a second MiB (banks `$20`-`$3F`, `FF` where nothing is written), its header's size (`0B`) and checksum set again. Shipped as BPS |

## Engine facts the overlay relies on

- **Mapping.** LoROM: bank `$00` is the ROM's first 32 KiB, at `$8000`-`$FFFF`, and so on,
  so `$11:8000` is offset `0x88000`. Banks `$00`-`$3F` show work RAM's first 8 KiB at
  `$0000`-`$1FFF`; the rest of it is in bank `$7E`.
- **Messages.** Three banks of dialogue, each a table of 16-bit offsets from the bank's
  text, then the text: the map dialogue [`MapDlg`] (bank 0: its table at `$11:8000`, 384
  entries, its text from `$11:8300` to `$11:FFFB`, a map's messages one after another from
  its entry) and two banks of event dialogue, the story's (bank 1: `$10:8000`, 512 entries,
  text from `$10:8400` to `$10:FE21`; bank 2: `$13:A500`, 256 entries, text from `$13:A700`
  to `$13:CD90`), a table entry a message. The engine keeps the bank's number in `$DD` and
  the next byte's offset from the bank's text in `$0772`, and reads a byte with [`GetByte`]
  (`lda f:MapDlg,x`). A message is named by its bank and its offset
  ([`engines/ff4.py`](../src/classic_retro/engines/ff4.py)).
- **Codes.** `00`: the end (the window waits for the button and closes); `06`: the end,
  the window closing at once. `01`: the end of a row (the rest of it spaces), `09`: an
  empty row, `02` and a byte: that many spaces. `03` and a byte: a song; `04` and a byte: a
  character's name (six letters at most, from the names the player gave at `$1500`); `05`
  and a byte: a pause; `07`: the item's name (9 tiles); `08`: the gil amount (6 tiles).
  `42`-`5B` the capitals, `5C`-`75` the small letters, `80`-`89` the digits, `C0`-`C9` the
  signs (`'`, `.`, `-`, `…`, `!`, `?`, `%`, `/`, `:`, `,`), `FF` the space; `21`-`41` and
  `79`-`7F` icons, `15` a blank tile. `8A`-`BF` and `CA`-`FE`: a pair of letters
  [`DTETbl`, `$13:9700`: two bytes a code from `80`].
- **The decode** [`DecodeDlgText`, `$00:B21F`]. A message is decoded into a buffer at
  `$0774` of four rows of 26 codes, `$3D` the next code's place: a letter is stored at
  `$00:B280` (`STA $0774,y`), a pair through [`DecodeDTE`, `$00:B2DC`] as its two letters,
  and the name command (`$00:B31C`, `LDA $1500,x; CMP #$FF`) copies the name's letters. When
  the four rows are full (`$3D` at `$68`) the page is marked (`$00:B2A4`: `LDA #1; STA $ED`),
  the blank row at `$0844` is filled with `FF` and the decode returns; the message goes on
  from `$0772` when the player presses the button.
- **The transfer** [`TfrDlgText`, `$00:B55F`]. In the vertical blank, when `$ED` is set, the
  four rows go to the tilemap by DMA, a byte at a time to `VMDATAL` (its `InitDMA`), each row
  of 26 tiles a row below a copy of the blank row: from the word address `$2C03 + ($BA & 3)
  * $100`, `$20` words a tilemap row, back from `$30xx` to `$2Cxx`; it ends with `INC $BA`
  (`$00:B5E7`). The engine writes each code straight into the tilemap as its tile: a line of
  text is 16 pixels, its row of tiles under a blank row (the Japanese version's dakuten row).
- **The font.** 256 tiles of two bits a pixel, 16 bytes each, at `$0A:F000`, copied whole
  to the third background's tiles; a code's tile is at `$0A:F000` + code x 16, so the
  letters' (`42`-`75`) start at `$0A:F420`. The pair codes' tiles are zeros in the ROM (they
  never reach the tilemap in English), but `F1`-`F5` and `F7`-`FF`, the window's own pieces.
- **The font's look.** The letters are white (value 3) on the window's blue (value 1).

## Right-to-left text

The overlay's hooks (`rom/ff4_arabic_hooks.s`, 721 bytes) live at `$20:8000`, the first
bytes of the MiB the overlay adds; the engine's code is in bank `$00`, so seven sites jump
to them with `JML` and they jump back with `JML`. They run with the engine's data bank `$00`
and direct page `$0600`, the accumulator 8 bits and the index registers 16.

- **Arabic messages.** At the decode's start (`parse_hook`), a message whose bank and
  offset are in the overlay's list is read from its Arabic text instead: `$DD` becomes 3
  (the Arabic bank, no English bank's number) and `$0772` the Arabic's offset, and every
  byte then comes from `$21:8000` + `$0772` (`byte_hook`). A later page of the message
  finds `$DD` already 3. The English stays where it was, as it was.
- **Glyphs.** In an Arabic message the glyphs are the letters' codes (`42`-`75`) and the
  pair codes (`8A`-`BF`, `CA`-`F0`, `F6`): 146 codes; the commands, the space (`FF`), the
  digits and the signs keep their meaning. A pair code from the first top code (a byte at
  `$20:8400`) on names the top half of the next glyph: `dte_hook` keeps it (`$7E:D0D0`) and
  `store_hook` writes it beside the code, into `$7E:D000` (a top a code of the buffer, `FF`
  where the row above is blank); any other code is a bottom half, stored as a letter is.
- **Mirrored rows.** When a page is decoded (`page_hook`, outside the vertical blank), each
  row of the buffer is copied backwards with its tops, so its first code lands at the
  right, and each run of the game's own codes (`21`-`41`, `79`-`89`: the icons and the
  digits) is turned back to read left to right (`turn_islands`), into `$7E:D100` (the rows)
  and `$7E:D180` (their tops). The transfer (`transfer_hook`) sends them from there, a row's
  tops into the blank row above it. So a row is written in reading order and shown
  mirrored; the encoder writes a run of the game's own codes reversed
  (`compensate_islands`), so the hook's turn lays it out left to right.
- **The letters' tiles.** Before an Arabic page the transfer copies the Arabic tiles of the
  letters' codes (`$20:8800`, 832 bytes) over the font's own in the tiles' memory (word
  address `$2210`), and before an English page the font's own from `$0A:F420` again, by a
  DMA of two registers (`VMDATAL`, `VMDATAH`) in the vertical blank (`load_letter_tiles`).
- **Names.** `{Name xx}` in an Arabic message writes the translation's own name of the
  character (`name_hook`: from `$20:8C00`, 48 bytes a name, its codes then `FF`), in the
  message's codes with their tops, six cells at most, in place of the name the player gave.
- **Numbers.** The gil amount's digits are the game's (`80`-`89`) and their run is turned
  back, so a number reads left to right in the Arabic row. `{Item}` is refused in an Arabic
  message: the item's name would be written in the letters' codes and shown in the Arabic
  tiles.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. A form is drawn into a cell of 8x16 pixels,
or two cells side by side when it is wider, the letters on row 11 (four rows left below for
the tails), at 12 pixels: the largest size, from 12 down to 8, at which every form of the
repertoire fits its cells and the translation's tiles fit the 146 codes; a translation whose
tiles would not fit is drawn a size smaller. Coverage from 110 of 255 is ink, and a dot
between 60 and 110 keeps its strongest pixel. The merged dots of two- and three-dot letters
are drawn apart (`separated_dots`), and hamza above alef is drawn by hand over the font's
alef (`alef_with_mark`). The signs `'`, `.`, `-`, `…`, `!`, `?`, `%`, `/`, `:` and `,` keep
the game's own tiles; `،`, `؛` and `؟` are drawn by hand. A form that joins on either side
sits against its cell's right edge, where the letter before it in reading order stands, and
on each joining side the rows of its stroke at the ink's edge (those of rows 7 to 12) are
carried on to the cell's edge, where the neighbour's go on; a form that joins neither side
is centred. Every form is white (3) on the window's blue (1). The space is the game's tile,
a cell.

Each cell's bottom half is a tile, and its top half a tile when it is not blank; identical
halves share a tile, so the free codes go a long way. The bottom halves take their codes
from the low end of the 146 (`42` up), the top halves from the high end of the pair codes
(`F6` down); the lowest top code is the first top code. A character's codes are its cells
from the right, each cell its top's code (when its top is not blank) then its bottom's.

## Layout

The encoder lays each page out itself, a word at a time: a row holds 26 cells, a page four
rows. A line of the notation is a page, `{line}` ends a row where it stands, `{blank}` is
an empty row. Each row is written with `01` at its end, as the English ends a row; a page
short of four rows is filled with `09` when another page follows; the message ends with
`00`, or `06` after `{Close}`. The other commands pass through as the English has them:
`{Song xx}`, `{Name xx}`, `{Wait xx}`, `{Gil}`. A name counts six cells, the gil amount six.
The glyphs of a row are stored in reading order: the first is shown at the right.

## The overlay's room

| Address | Content |
|---------|---------|
| `$20:8000` | the hooks: `parse_hook` at `+0`, `byte_hook` at `+$54`, `dte_hook` at `+$71`, `store_hook` at `+$91`, `name_hook` at `+$B2`, `page_hook` at `+$FD`, `transfer_hook` at `+$192` |
| `$20:8400` | a byte: the first code that is a top half |
| `$20:8500` | the list: 5 bytes a message (its bank, its offset, its Arabic's offset); `FF` ends it |
| `$20:8800` | the Arabic tiles of the letters' codes `42`-`75`: 16 bytes a code, 832 |
| `$20:8C00` | the fourteen names: 48 bytes each, the codes then `FF` |
| `$21:8000` | the Arabic messages, an offset below `$8000` each |
| `$0A:F000` + code x 16 | the pair codes' tiles, in the font's blank tiles |

In work RAM the hooks use `$7E:D000` (a top a code of the buffer, 104 bytes), `$7E:D0D0`
(the top kept for the next bottom), `$7E:D0D1`-`$7E:D0D6` (the page hook's scratch),
`$7E:D100` (the page's rows mirrored) and `$7E:D180` (their tops). The added MiB is `FF`
where the overlay writes nothing, and the header's size byte (`$7FD7`) goes from `0A` to
`0B`.

| Site | Original | Arabic |
|------|----------|--------|
| `$00:B21F`, `DecodeDlgText` | `LDY #0`; `STY $3D` | `JML parse_hook` |
| `$00:B280`, where a letter is stored | `STA $0774,y`; `LDY $3D`; `INY`; `STY $3D` | `JML store_hook` |
| `$00:B2A4`, in `DecodeDlgText`, a page decoded | `LDA #1`; `STA $ED` | `JML page_hook` |
| `$00:B2BE`, `GetByte` | `LDX $0772`; `LDA $DD`; `BNE` | `JML byte_hook` |
| `$00:B2DC`, `DecodeDTE` | `SEC`; `SBC #$80`; `ASL`; `TAX` | `JML dte_hook` |
| `$00:B31C`, in the name command | `LDA $1500,x`; `CMP #$FF` | `JML name_hook` |
| `$00:B55F`, `TfrDlgText` | `LDA $ED`; `BNE` | `JML transfer_hook` |

A `JML` is 4 bytes; a longer site is filled with `NOP`.

Anchors checked before any change: the ROM (SHA-256, size and its header's size byte); the
decode's loop (`$00:B224`, `JSR GetByte`) and what follows a stored code (`$00:B288`: the
source on, the row check, back to the loop); the decode after a page (`$00:B2A8`: the blank
row filled, its `RTS`); `GetByte` after its site (`$00:B2C5`: the English banks, its `RTS` at
`$00:B2DB`); `DecodeDTE` after its site (`$00:B2E1`: the pair's letters from `$13:9700`); the
name command after its site (`$00:B321`, to its end); `TfrDlgText` after its site
(`$00:B563`: its `RTS`, its transfer, its end at `$00:B5E7`); the pair codes' tiles, zeros;
each translated message (its bank and offset, the SHA-256 of its bytes and, where pinned,
its commands). The build then sets the header's checksum, reads everything back from the
image (the hooks, the sites, the list, the tiles, the names, and each Arabic message through
the list as the hooks find it, with the translation's commands) and checks that nothing but
the sites, the font's blank tiles, the header and the added MiB changed.

## Translations

`rom/ff4_arabic_script.py` pins six messages of the opening on the deck of the Red Wings'
airship, all in bank 1 (the event dialogue at `$10:8400`), by their offsets. The Arabic is
in `translations/final-fantasy-ii.json`, a line a page, `{line}` where a row must end. The
six were chosen to be unlike:

| Entry | Message | What it tries |
|-------|---------|---------------|
| `deck.arrive` | `0x0290`: the crew tells the captain they are about to arrive, and Cecil answers | `{Name 00}` twice, inside a row and at a row's start |
| `deck.robbing` | `0x02B7`: the crew on robbing the crystals | two pages |
| `deck.captain` | `0x030C`: the crew protests, Cecil answers | four pages, rows the encoder wraps |
| `deck.monsters` | `0x03F9`: monsters attack | one short row |
| `deck.ouch` | `0x0405`: a crewman is hit | four rows, two names |
| `deck.baron` | `0x0490`: over Baron, the landing | the scene's last |

The names are `name.00` to `name.0D`: the fourteen characters the name command writes, in
the game's order (Cecil, Kain, Rydia, Tellah, Edward, Rosa, Yang, Palom, Porom, Cid, Edge,
FuSoYa, Golbez, Anna), one word each, six cells at most. A translation keeps its original's
commands but the layout (`{line}`, `{blank}`, the spaces): its skeleton must equal the
original's, which the build takes from the ROM; the script pins no skeleton yet (`None`),
and the build's report carries every original's, for pinning. The messages and the names
use 83 distinct forms and signs.

## Verification

With the reference font the build matches the reference patch (about 4 KiB; its SHA-256 is
pinned with the target, and the build report's `matches_reference` says so). In snes9x
(`snes9x_libretro`) through `classic-retro research run`, from power-on with the patched
ROM, a new game: the six messages of the deck in Arabic from the right, a page at a time,
«سيسل» in Arabic where the game writes the captain's name; the battles and the messages
that follow in English as before, their Latin letters put back. The RetroPad's A is the
Super NES's A.

## Limits

- Six messages and the characters' names are in Arabic; every other message stays English,
  and the menus and the battles are other text engines, untouched.
- 146 codes for all the Arabic at one size: the pair codes and the letters' codes. A message
  holds no Latin letters; `{Item}` is refused; a yes/no or gil sub-window opened during an
  Arabic message would show its Latin letters as Arabic tiles (no message of the scope opens
  one).
- A name in an Arabic message is the translation's, not the one the player gave.
- A page holds four rows of 26 cells; the encoder refuses more, and a word wider than a row.
- The font is 12 pixels, a step smaller when a translation's tiles would not fit; no vowel
  marks, lam and alef stay two glyphs.
- The ROM grows to 2 MiB; the added banks hold only the overlay's hooks and data.
