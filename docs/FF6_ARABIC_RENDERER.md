# Final Fantasy III Arabic Renderer v1

Target: *Final Fantasy III* (USA, SNS-F6-USA; the Super NES release of Final Fantasy VI),
the fourth Super NES target. The [everything8215/ff6](https://github.com/everything8215/ff6)
disassembly rebuilds this revision (its "Final Fantasy III 1.0 (U)", CRC32 `A27F1C7A`) and
names its code, but it takes the ROM's data from the user's ROM, so this is a binary ROM
overlay: it patches the user's ROM and ships as a BPS patch of it. The text engine was read
from the disassembly (`field/text.asm`), its addresses derived from the disassembly's own
numbered labels, checked byte by byte against the ROM and run in snes9x with the
[research tools](RESEARCH_TOOLS.md). Names in brackets are the disassembly's.

| Item | Value |
|------|-------|
| No-Intro | *Final Fantasy III (USA)*: one ROM, version 1.0, no copier header (a dump of 3146240 bytes carries a 512-byte one, to be removed first) |
| ROM | 3145728 bytes, HiROM: CRC32 `A27F1C7A`, SHA-256 `0f51b4fca41b7fd509e4b8f9d543151f68efa5e97b08493e4b2a0c06f5d8d5e2` |
| Header | at `$FFC0`: its map byte at `$FFD5` (`31`: HiROM, fast), its size byte at `$FFD7` (`0C`: 4 MiB, already, for a 3 MiB ROM), its checksum and complement at `$FFDC`; `classic-retro detect` names the platform and the game (`final-fantasy-iii-usa`) |
| Output | The ROM with a fourth MiB (banks `$F0`-`$FF`, `FF` where nothing is written) and its header's checksum set again; the size byte stays `0C`. Shipped as BPS |

## Engine facts the overlay relies on

- **Mapping.** HiROM: bank `$C0` is the ROM's first 64 KiB, and so on, so `$CD:0000` is
  offset `0xD0000`; banks `$40`-`$7D` mirror them. Banks `$00`-`$3F` show work RAM's first
  8 KiB at `$0000`-`$1FFF`; the rest of it is in bank `$7E`.
- **Messages.** One table of 16-bit offsets [`DlgPtrs`, `$CC:E602`, 3084 entries] from the
  text [`Dlg`, `$CD:0000`, a block of `$1F100` bytes over banks `$CD` and `$CE`]; a message
  whose number is the word at `$CC:E600` [`DlgBankInc`, 1574] or more counts from `$CE:0000`.
  The event script gives the number (`$D0`), [`GetDlgPtr`, `$C0:7FBF`] sets the pointer
  (`$C9`-`$CB`) and enables the display (`$0568` = 1), and the engine reads the bytes with
  `lda [$c9],y` ([`engines/ff6.py`](../src/classic_retro/engines/ff6.py)).
- **Codes.** `00`: the end (the window waits for the button and closes). `01`: the end of a
  line; `13`: the end of a page (the window waits for the button and clears); `14` and a
  byte: that many spaces. `02`-`0F`: a character's name (Terra to Umaro, from the names the
  player gave at `$1602`, 37 bytes a character); `10`: a pause of a second; `11` and a byte:
  a pause of that many quarter seconds; `12`: waiting for the button; `16` and a byte: the
  pause then the button; `15`: a choice's mark; `19`: the gil amount; `1A`: the item's name;
  `1B`: the spell's name; `1C`-`1F` and a byte: the Japanese game's letters beyond the first
  256, unused. `20`-`7F`: a letter (the capitals from `20`, the small letters from `3A`, the
  digits from `54`, the signs, icons from `76`, `7F` the space). `80`-`FF`: a pair of letters
  [`DTETbl`, `$C0:DFA0`: two bytes a code from `80`].
- **The draw.** A letter a frame: [`UpdateDlgText`, `$C0:814C`] in the main loop reads the
  next byte, [`CalcTextWidth`, `$C0:8067`] measures the next word and [`NewLine`,
  `$C0:851A`] starts a line where the word would pass the pen's end (`$C8` = 224).
  [`DrawDlgText`, `$C0:84D0`] shifts the letter's glyph to the pen (`$BF`, from 4) into a
  cell of 16x16 pixels ([`LoadLetterGfx`], [`DrawLetter`]: `$7E:9003` and `$7E:9103`,
  the letter's 16 pixels in a word, ORed in), copies the cell to `$7E:9083`
  ([`CopyDlgTextToBuf`]) and moves the pen on by the letter's width [`FontWidth`,
  `$C4:8FC0`, a byte a code]. In the vertical blank [`TfrDlgTextGfx`, `$C0:8603`] sends the
  cell (64 bytes: four tiles of two planes, the second plane the glyph a pixel right, the
  shadow) by DMA to the word address `$3800` + `$C3`: the text's tiles are four lines of
  `$200` words, 16 cells of 16 pixels a line, of which the box shows 14 (224 pixels).
  `NewLine` moves the line pointer `$C1` a line on and, after the fourth line, has the box
  wait for the button (`$CC` = 9, `$D3` = 2); [`NewPage`, `$C0:8554`] moves it to the top the
  same way; then [`ClearDlgTextRegion`] clears the text's tiles over eight frames and the
  message goes on. A choice's mark takes the pen's cell for its cursor (`$C1` into `$0570`,
  a word a choice) and draws a wide space.
- **The font.** [`LargeFontGfx`, `$C4:90C0`]: 22 bytes a letter from `20`, eleven rows of a
  16-bit word, the leftmost pixel in bit 15; the letters are white (palette entries 1 and 3)
  with a black shadow (2) on the window's blue.

## Right-to-left text

The overlay's hooks (`rom/ff6_arabic_hooks.s`, 1785 bytes) live at `$F0:0000`, the first
bytes of the MiB the overlay adds; the engine's code is in bank `$C0`, so eight sites call
them with `JSL` and they go back with `RTL` to the site's end, or with `JML` to the engine
where the site's own code branched. They run with the engine's data bank `$00` and direct
page `$0000`, the accumulator 8 bits and the index registers 16.

- **Arabic messages.** At `GetDlgPtr`'s end (`redirect_hook`) a message whose entry in the
  overlay's table (an address of three bytes a message number, `FFFFFF` where there is no
  Arabic) has Arabic is read from it instead: `$C9`-`$CB` becomes that address and a flag
  in work RAM (`$7E:9D00`) says the message is Arabic; any other message clears it. The
  English stays where it was, as it was.
- **Glyphs.** In an Arabic message every byte from `20` is a glyph of the overlay's own font
  (`dte_hook`: a byte from `80` is a glyph, not a pair); the commands keep their meaning.
- **A line laid out whole.** Where `UpdateDlgTextOneLine` adds the next word's width to the
  pen (`width_hook`), in an Arabic message the line the engine is on is laid out whole the
  first time (`lay_out_line`, outside the vertical blank): from the right edge (224)
  leftwards, each glyph's variant of its pixel is ORed into a buffer of the line's tile
  columns at `$7E:9800` (32 columns of 32 bytes: 16 rows of two planes), the next variant as
  its shadow in the second plane; a name's glyphs come from the names' table; `14` and a
  byte moves the pen that many pixels (the narration's centring); `15` moves the pen to a
  cell's edge and leaves the next cell (16 pixels) for the choice's cursor, keeping that cell
  for `choice_hook` (four marks a line at most); the pauses and the button waits are
  skipped; the line ends at `00`,
  `01` or `13`. The word's width is then nothing, so the engine never breaks a line itself,
  and `DrawDlgText` draws nothing (`draw_hook`): the engine still walks the line a byte a
  frame, so its pauses, button waits, pages and choices work as before.
- **The transfer.** In the vertical blank (`transfer_hook`, at `TfrDlgTextGfx`'s start), a
  line laid out is sent by DMA, 896 bytes (14 cells), to its tiles at `$3800` + `$C1`; then
  the engine's own cell as before. `NewLine` and `NewPage` (`line_hook`, `page_hook`) keep
  the engine's line and page logic (the pen back to 4, the line pointer on or to the top,
  the wait for the button) without its blank cell, and mark the next line as not laid out;
  at the message's end (`00`) the message is over, so what the engine draws next (a map's
  name) is English.
- **Choices.** `choice_hook`: a choice's cursor takes the cell the line's layout kept for
  its mark, the marks in their order (the first at the line's right, cell 13, pixels
  208-223; the raft's prompts put two on a line), at the right of the choice's text; the
  game's own cursor graphic and its moves are untouched.
- **Names.** `{Terra}` to `{Umaro}` in an Arabic message write the translation's own name of
  the character (from `$F0:1400`, 32 bytes a name, its glyph codes then `FF`), in place of
  the name the player gave.
- **Two lessons.** The engine keeps the accumulator's high byte zero in its 8-bit code (its
  `shorta0` is `TDC` then `SEP #$20`) and moves the whole accumulator into a 16-bit index
  with `TAX` (`LDA $CF; TAX; LDA $7E9183,x`), and the event interpreter does the same after
  `GetDlgPtr`; a hook that used 16 bits clears the high byte before going back (`clear_b`:
  `XBA; LDA #0; XBA`), or the event script and the text buffer's index go astray, as they
  did in snes9x until they did. And the hooks' flags count only the value 1 as set: the
  emulator fills work RAM with `55` at power-on, which would otherwise read as Arabic mode
  before the first message.

## Glyphs

The reference font is Noto Kufi Arabic SemiBold. A glyph is 16 pixels wide and 15 rows
tall (the cell's rows 0 to 14, the letters on row 10, four rows left below for the tails),
drawn at 12 pixels: the largest size, from 15 down to 9, at which every form of the
repertoire and every digit fits. Coverage from 128 of 255 is ink, and a dot between 60 and
128 keeps its strongest pixel. The merged dots of two- and three-dot letters are drawn apart
(`separated_dots`), the deep dots under a letter are raised to the last row
(`raised_marks`), hamza above alef is drawn by hand over the font's alef
(`alef_with_mark`), and final and isolated yeh are raised a row when their tail would leave
the cell. The signs `.`, `,`, `:`, `!`, `-`, `…`, `،`, `؛` and `؟` are drawn by hand; the
space is a blank glyph 4 pixels wide. Each glyph has a width, the pen's advance: a form that
joins the glyph on its right (the letter before it in reading order) has its stroke run on
to its edge, and any other form keeps its advance with a pixel free after its ink, as
Chrono Trigger's do; the glyphs are ORed together, so a stroke meets its neighbour's.

The hook draws at any pixel without shifting: the overlay writes each glyph in nine
variants, shifted right by 0 to 8 pixels into three bytes a row (45 bytes a variant, 405 a
glyph), and the shadow of a glyph at pixel `s` of its tile is the variant `s + 1`. The
glyphs take codes `20` to `FF` in the font's order (the space, the punctuation, the digits,
then the repertoire by code point), 224 at most, and their variants take two banks, no glyph
across one (161 a bank); the whole dialogue uses 139. The quotes `«` `»` and the brackets
`(` `)` are drawn by hand as their mirror images, since a right-to-left run shows them
mirrored and the painter does not mirror; the opera's note `♪`, which the English writes
with the font's note icon, is drawn by hand too.

## Layout

The encoder lays each page out itself, a word at a time: a line holds 220 pixels (from the
right edge, 224, to 4), a page four lines. A line of the notation is a page and `{line}` ends
a line where it stands; `{center}` at a page's start centres its lines, each written with
`14` and its indent in pixels. Lines are written with `01` between them; a page short of
four lines ends with `13` when another page follows, and a full page with `01` alone, since
the game turns the page itself after a fourth line; the message ends with `00`. The other
commands pass through as the English has them: `{Wait}`, `{Pause xx}`, `{Key}`,
`{KeyAfter xx}`, and `{Choice}`, which moves the pen to a cell's edge and counts the cell of
its cursor (16 pixels at a line's start, up to 31 after text), so two choices may share a
line; a centred page holds no choice. A name counts its translation's width. The glyphs of a line are stored in the order they are
painted from the right (a run of digits reads left to right by the shaper's own order).

## The overlay's room

| Address | Content |
|---------|---------|
| `$F0:0000` | the hooks: `redirect_hook` at `+0`, `width_hook` at `+$44`, `dte_hook` at `+$63`, `draw_hook` at `+$79`, `line_hook` at `+$8F`, `page_hook` at `+$D1`, `choice_hook` at `+$108`, `transfer_hook` at `+$143` |
| `$F0:1000` | a width a code from `20` (0 where there is no glyph), 224 bytes |
| `$F0:1100` | 3 bytes a code from `20`: the glyph's address, its bank the third byte, 672 bytes |
| `$F0:1400` | the fourteen names: 32 bytes each, the codes then `FF` |
| `$F0:2000` | the table: 3 bytes a message number, 3084 entries (9252 bytes): the Arabic's address, or `FFFFFF` for an English message |
| `$F1:0000` | the glyphs, 405 bytes each, over banks `$F1` and `$F2`; none across a bank |
| `$F3:0000` | the Arabic messages, to the ROM's end; none across a bank, and none at a bank's last byte, so no address has `FFFF` for its low word |

In work RAM the hooks use `$7E:9D00` (the Arabic flag), `$7E:9D01` (the line laid out),
`$7E:9D02` (a line waiting to be sent), `$7E:9D04`-`$7E:9D0F` (the line's tiles, the pen and
scratch), `$7E:9D10`-`$7E:9D1B` (the choices' cells: the marks taken, the marks kept, a word
a cell) and `$7E:9800`-`$7E:9BFF` (the line's tile columns): the tail of the engine's own
text buffer (`$7E:9183`-`$7E:9DFF`), of which it writes the first 256 bytes at most. The
added MiB is `FF` where the overlay writes nothing.

| Site | Original | Arabic |
|------|----------|--------|
| `$C0:7FDF`, `GetDlgPtr`'s end | `LDA #1`; `STA $0568` | `JSL redirect_hook` |
| `$C0:8250`, `UpdateDlgTextOneLine`, the word's width | `LDA $BF`; `CLC`; `ADC $C0` | `JSL width_hook` |
| `$C0:828F`, where a byte from `80` is a pair | `LDA $BD`; `BMI` | `JSL dte_hook` |
| `$C0:84D0`, `DrawDlgText` | `LDX $CD`; `LDA f:FontWidth,x` | `JSL draw_hook` |
| `$C0:851A`, `NewLine` | `LDA #$FF`; `STA $CD` | `JSL line_hook` |
| `$C0:8554`, `NewPage` | `LDA #$FF`; `STA $CD` | `JSL page_hook` |
| `$C0:8603`, `TfrDlgTextGfx` | `LDA $C5`; `BEQ`; `STZ $C5` | `JSL transfer_hook` |
| `$C0:836D`, a choice's mark | `LDA $C1`; `STA $0570,y` | `JSL choice_hook` |

A `JSL` is 4 bytes; a longer site is filled with `NOP`.

Anchors checked before any change: the ROM (SHA-256, size, its header's map and size
bytes); `GetDlgPtr`'s `RTS` after its site; `UpdateDlgTextOneLine` after the width (the
overflow check, `NewLine`, the buffer); after the pair check (the command check, a letter,
the pair's letters at `$C0:8466`); `DrawDlgText` after its site and its `RTS` at `$C0:8519`;
`NewLine` and `NewPage` after their sites and their `RTS`s at `$C0:8553` and `$C0:857D`;
the choice's mark after its site; `TfrDlgTextGfx` after its site (the engine's cell sent)
and its `RTS` at `$C0:8641`; each translated message (its number, the SHA-256 of its bytes
and, where pinned, its commands). The build then sets the header's checksum, reads
everything back from the image (the hooks, the sites, the tables, the list, the glyphs, and
each Arabic message through the list as the hooks find it, with the translation's commands)
and checks that nothing but the sites, the header's checksum and the added MiB changed. The
table is read back whole (a message's entry, or `FFFFFF`), and each Arabic message from its
address to its end within its bank.

## Translations

`rom/ff6_arabic_script.py` pins the whole dialogue, 3077 messages, by their numbers, with
the SHA-256 of each and its command skeleton, in eleven chapters that follow the game; each
entry's id is a scene prefix and the message number.

| Chapter | Messages | Scenes (prefix, messages) |
|---|---|---|
| 1. Narshe | 0-63 (0 shares 1's text and pointer) | the cliffs, the narration, the save point, the town and the mines, Arvis's house, Kefka's and the Empire's scenes, Locke and the Moogles, the escape (`narshe`) |
| 2. Figaro to the raft | 64-368 but the empty 364 and 365 | Figaro Castle, Kefka's visit, the dive and the clock key's cave (`figaro`, 64-178); South Figaro and Duncan's cabin (`south-figaro`, 179-236); Mt. Kolts, Vargas and Sabin (`kolts`, 237-266); the Returners' hideout, Banon's choice, the meeting and the raft (`returners`, 267-368) |
| 3. The scenarios and the battle for Narshe | 369-932 but the empty 484 | Locke and Celes (`locke`, 369-416); Banon's party (`banon`, 417-428); Gau's father's house and the merchants (`veldt`, 429-451); the Imperial camp and Shadow's dream (`sabin`, 452-479); Doma, Leo, Kefka's poison and Cyan (`doma`, 480-598); the classroom (`classroom`, 599-637); the ship and the dining car (`ship`, 638-660); the Phantom Train (`train`, 661-735); Baren Falls, the Veldt, Gau, Mobliz and the Serpent Trench (`veldt`, 736-802); Nikeah (`nikeah`, 803-836); the Elder, the battle and Terra's flight (`narshe-battle`, 837-932) |
| 4. The search for Terra | 933-1329 | Figaro Castle and the brothers' memory (`castle`, 933-985); Kohlingen and Rachel (`kohlingen`, 986-1028); Jidoor (`jidoor`, 1029-1042); Zozo, its clocks, Ramuh and the plan (`zozo`, 1043-1151); the Opera House (`opera`, 1152-1269); Setzer's coin and airship (`airship`, 1270-1329) |
| 5. Vector and the Esper world | 1330-1497 | Vector (`vector`, 1330-1346); Banon's return (`narshe-return`, 1347-1354); the Magitek Research Facility (`facility`, 1355-1409); the escape (`escape`, 1410-1421); Terra's memory of the Esper world (`maduin`, 1422-1497) |
| 6. The sealed gate and the banquet | 1498-1887 but the empty 1536 | the world of ruin's dragons, Duncan and Narshe's stone (`ruin`, 1498-1535); Maranda, Tzen and Albrook (`maranda`, 1537-1549; `tzen`, 1550-1572; `albrook`, 1573-1612); Narshe and Banon's plan (`narshe-plan`, 1613-1637); the sealed gate (`gate`, 1638-1690); Vector after the Espers (`vector`, 1691-1733); Lone Wolf and Mog (`narshe-wolf`, 1734-1766; 1749 is two commands and no text); the banquet, the soldiers and the rewards (`banquet`, 1767-1874); Cid and Setzer's memory of Daryl (`setzer`, 1875-1887) |
| 7. Thamasa and the Floating Continent | 1888-2167 | Albrook, the voyage and Crescent Island (`voyage`, 1888-1929); Thamasa, Strago, Relm and the fire (`thamasa`, 1930-2026); Ultros, the goddesses' story and Yura (`espers`, 2027-2062); Kefka's betrayal, Leo's death and the return (`leo`, 2063-2117); the Floating Continent and the day the world changed (`continent`, 2118-2167) |
| 8. The world of ruin's first towns | 2168-2418 | Celes and Cid on the island (`island`, 2168-2200); Albrook and Tzen after the fall (`albrook-ruin`, 2201-2208; `tzen-ruin`, 2209-2240); the cult's tower (`cult`, 2241-2254); Mobliz (`mobliz-ruin`, 2255-2323); Nikeah and Gerad (`nikeah-ruin`, 2324-2348); South Figaro (`south-figaro-ruin`, 2349-2373); the cave to Figaro and the castle (`figaro-ruin`, 2374-2403); the Ancient Castle (`ancient-castle`, 2404-2418) |
| 9. The gathering of the friends | 2419-2613 | the Colosseum (`colosseum`, 2419-2435); Kohlingen and Setzer (`kohlingen-ruin`, 2436-2458); Daryl's tomb (`tomb`, 2459-2531); Maranda's letters and Cyan (`maranda-ruin`, 2532-2572); Gogo (`gogo`, 2573-2577); the Veldt cave (`veldt-cave`, 2578-2591); Locke, the Phoenix and Rachel (`phoenix`, 2592-2613) |
| 10. Tritoch, the auction and Cyan's dream | 2614-2799 | Narshe with Tritoch, Mog and Umaro (`narshe-ruin`, 2614-2622); Jidoor's auction house (`auction`, 2623-2699); the Emperor's letter, Owzer, Relm and Chadarnook (`owzer`, 2700-2757); Cyan's dream (`dream`, 2758-2799) |
| 11. Kefka's tower and the ending | 2800-3083 but 2949, 2950 and 2951 | Gau's father (`gau-father`, 2800-2841); Thamasa, Gungho and Hidon (`thamasa-ruin`, 2842-2913); the scattered lines of the first chapters' places (`scattered`, 2914-2947); the system messages (`system`, 2948-2963); Kefka's tower (`tower`, 2964-2984); Kefka's speech (`kefka`, 2985-3019); the escape and the ending (`ending`, 3020-3083) |

The four empty messages stay as they are, and so do 2949, 2950 and 2951, which write an item,
a spell or a sum with `{Item}`, `{Spell}` and `{Gil}`: the game draws those in its own
letters, which the Arabic draw cannot show. The text of the first four chapters fits bank
`$F3`; the fifth chapter's is the first past it (151 of its messages sit in bank `$F4`) and
the tenth's the first past bank `$F4` (73 in `$F5`), read through the table's three-byte
addresses.

What the notation carries, by example: the cliffs' `{KeyAfter 18}{Key}` pacing and the
narration's `{Pause FF}{Key}` are kept; the narration, the item and Magicite lines, the
dragon counts, the banquet's count of soldiers, the tombstone's hint, Cyan's poem and the
ending's timed lines are centred with `{center}`; the raft's prompts (362, 363, 366) and
Zozo's clocks put two choices on a line; the arias keep the English's pauses and button
waits between their words, the note written with `♪`; the classroom's status names are in
guillemets and the buttons written out. The tombstone puzzle (2483-2530) is the one place
the English writes Latin letters the Arabic cannot draw: its four reversed groups, which
spell «THE WORLD IS SQUARE» backwards in the right order, become the four words of «إن هذا
العالم مربع», so the player orders words instead of letters and the game's own check of
the order (the choice indices) is untouched.

The Arabic is in `translations/final-fantasy-iii.json`, a line a page, `{line}` where a
line must end; its `glossary` fixes how every place, character, Esper and term is written,
and `check-translations` on a workspace reports each message whose original names a term
that its Arabic does not use (a reminder, not an error: a stem such as `إمبراطوري` covers
the inflections, and a message may say «هو» instead of the name). The names are
`name.terra` to `name.umaro`, the fourteen characters the name commands write, in the
game's order, one word each, 64 pixels at most. A translation keeps its original's
commands but the layout (`{line}`, `{page}`, the spaces): its skeleton must equal the
original's, which the build takes from the ROM and the script pins too. The messages and
the names use 139 distinct forms, digits and signs.

## Verification

With the reference font the build matches the reference patch (its SHA-256 is pinned with
the target, and the build report's `matches_reference` says so). In snes9x
(`snes9x_libretro`) through `classic-retro research run`, from power-on with the patched
ROM, a new game: the narration's four pages centred, the cliff dialogues right-aligned in
the box a page at a time, the first Narshe dialogue in Arabic; a message with a name draws
«تيرا» and «لوك» from the translation, and a two-way choice draws its lines with the cursor
at their right, moves with Down and confirms with A. The second chapter's messages were
shown the same way with the first message's entry pointed at each (the table makes that a
three-byte change): the raft's three-way prompt with its cursor moving from the first
choice to the two on one line and back, with Down, Up, Left and Right; the password's three
choices in guillemets; the clock key's bracketed choices; a centred item line. The third
chapter the same way: the chest's three choices, the ghosts' centred lines drawn one at a
time with their pauses, Lola's letter over its pages and the Esper lesson. The fourth: the
aria with its note and its pauses, Zozo's clock with its six choices over three lines and
the cursor moving among them with Right and Down, the centred Magicite lines and Setzer's
answer. The fifth, from bank `$F4`: the oath's choices, Ifrit's Magicite line, Maduin's
two pages with their bracketed choices, Kefka's boast with its pauses, the centred title,
the drunk's pauses inside a line and Madonna's plea over its pages. The sixth: the
smith's three pages ending in two bracketed choices with guillemets, the dragons' two
centred pages, the three toasts and the three questions with the cursor moving among
them, Gestahl's four pages with their wait, the centred count, Lone Wolf's centred
lines, the hairpin over its pages and Setzer's five pages. The seventh: the airship's
prompt after its page with the cursor moving with Down, Kefka's hate over its three
pages, the closing line centred with its wait, Strago's waits inside a line, the goddesses'
story over four pages, the jump's choices with a name in one, the inn's bracketed
choices after their page and Strago's warning over four pages. The eighth: Cid's four
pages with their waits, the treasure's bracketed choices, the cult's centred lines,
Fenrir's Magicite after its page, Terra's «love» with its waits, the children's centred
cries, the thieves' centred cry with its button wait, Edgar's six pages, Odin's centred
level-up over two pages and his attack's centred name. The ninth: the tombstone's four
words as choices with the cursor moving among them, the carved sentence, the carving
prompt, the egg's centred hint, Cyan's centred poem, his letter over its pages, Kohlingen's
centred title, Rachel's farewell over five pages, the cave's six centred treasures, the
Colosseum's three bracketed choices and the traveller's four. The tenth, the last
messages from bank `$F5`: Tritoch's three pages, the auction's bracketed choices, a lot
centred over its bid, the bid's choices, the Emperor's letter over three pages, Owzer's
story over its pages, Starlet's centred Magicite, Owzer's farewell, Cyan's timed family
lines with their waits, Wrexsoul's boast and Alexandr's centred Magicite. The eleventh: Gau's
recognition over three pages, his happiness with its waits, the chest's hunger, its
bracketed choices, Strago's tale with its centred sound effects, the merchant's choices,
the scenario prompt and the chest's monster centred, Kefka's welcome and his speech over
its pages, the ending's centred timed lines, Sabin's three timed pages and Maduin's
farewell with its pauses. The three messages left English show the game's own text as
before. The RetroPad's A is the Super NES's A.

Any message can be shown the same way after an edit. The intro's narration is message 6,
the first the game shows; pointing its table entry at another message's Arabic makes that
message the first shown, three bytes in the patched ROM:

```python
from pathlib import Path
from classic_retro.engines.ff6 import hirom_offset
from classic_retro.rom import ff6_arabic as overlay

rom = bytearray(Path("Final Fantasy III (USA) (Arabic).sfc").read_bytes())
table = overlay.read_message_table(rom)          # message number -> Arabic address
entry = hirom_offset(overlay.MESSAGES + 6 * overlay.MESSAGE_ENTRY)
rom[entry : entry + 3] = table[2483].to_bytes(3, "little")   # show 2483 first
overlay.set_checksum(rom)
Path("variant.sfc").write_bytes(rom)
```

Then `classic-retro research run --core snes9x_libretro.so --out-dir DIR variant.sfc SCRIPT`
with a script that starts a new game and takes shots: `run 600`, `tap START 4 8`, `run
120`, `tap START 4 8`, `run 120`, `tap A 4 8`, `run 180`, `tap A 4 8`, then `shot v1.png`
and `tap A 4 8` or `tap DOWN 4 8` for the next page or choice. The intro fades out about
700 frames after the message opens, so take a long message's pages a few dozen frames
apart; a message whose page ends in `{KeyAfter n}` or `{Pause n}{Key}` closes itself
after n quarter-seconds, so shoot it early; a centred page draws its blank lines first,
about a hundred frames each. The original of any message, in the notation, is
`engines.ff6.message_notation(engines.ff6.message_at(rom, number).data, engines.ff6.dte_pairs(rom))`
on the unpatched ROM; `targets extract` writes them all into a workspace.

## Limits

- The whole dialogue's 3077 messages and the characters' names are in Arabic; the three
  messages that write an item, a spell or a sum with `{Item}`, `{Spell}` and `{Gil}` stay
  English, as do the four empty ones, and the menus and the battles are other text engines,
  untouched, so the classroom's lessons name menu entries and statuses in Arabic that the
  menus still show in English.
- A message holds no Latin letters; `{Gil}`, `{Item}` and `{Spell}` are refused: the game
  writes them in its own letters, which the Arabic draw leaves out.
- A line is laid out whole when the engine reaches it, so a `{Key}` or a `{Pause}` in the
  middle of a line shows the rest of the line at once: the opera's arias, timed word by word
  in English, show a line at a time and keep their pauses between lines.
- A choice's cursor is the game's right-pointing arrow, at the right of the choice's text;
  a line keeps cells for four marks at most, and a centred page holds none. The raft's
  prompts keep the English's order of choices, so the choice the game takes as "left"
  reads «يسار» at the line's right.
- A name in an Arabic message is the translation's, not the one the player gave.
- A page holds four lines of 220 pixels; the encoder refuses more, and a word wider than a
  line. The font is 12 pixels; no vowel marks, lam and alef stay two glyphs.
- The ROM grows to 4 MiB; the added banks hold only the overlay's hooks and data: two
  banks of glyphs (224 codes at most) and thirteen of Arabic text, room for the whole
  game's dialogue.
