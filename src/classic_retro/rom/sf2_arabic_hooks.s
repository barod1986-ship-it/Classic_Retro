| Shining Force II (USA): the Arabic hooks of the dialogue's text engine.
|
| This file is assembled with m68k-linux-gnu-as -m68000 (registers without %)
| and linked at HOOK_ADDRESS ($042600), in free bytes at the end of the
| section that holds the text (ROOM_START to ROOM_END), where the overlay's
| data follows it. DisplayText finds a string in its text bank and reads it a
| symbol at a time (GetNextTextSymbol: Huffman-decoded, or the ASCII of a
| name the engine writes); SymbolsToGraphics draws a symbol's glyph from the
| variable-width font at the pen (PEN_X) and moves the pen on by its width:
|
| - redirect_hook (JMP from $006272, where DisplayText looks the string up): a
|   string whose number is in the REDIRECTS list is read from its Arabic text
|   instead, in the room, stored as the game stores a string (a length byte,
|   then its symbols) but not compressed;
| - symbol_hook (JMP from $00634E, the start of GetNextTextSymbol): while the
|   text's pointer (CODE_POINTER) is in the room, the next symbol is the next
|   byte, and a name or number the engine has written in ASCII is drawn whole,
|   in the English font, left to right, as a block that ends at the mirror of
|   the pen; the pointer is cleared at the string's end;
| - draw_hook (JMP from $006B70, the start of SymbolsToGraphics): while the
|   pointer is in the room, a symbol is a glyph of the Arabic font, drawn at
|   the mirror of the pen (RIGHT - pen - width) while the pen moves on as the
|   engine's does, so a line starts at the window's right;
| - cursor_hook (JSR from $0064DA, where the arrow that waits for the button
|   is placed at the window's right corner): while the pointer is in the room,
|   the arrow goes to the left corner, where an Arabic line ends.
|
| A name drawn whole is drawn as the English's letters would be: its first
| letter, as a string's first character, starts a new line when the pen is not
| at the line's start, and a new line when the name would pass the line's end;
| then its line goes to VRAM, as the engine sends a line after each character.
|
| A glyph writes only its ink's pixels, as the engine's routine does, so the
| glyphs drawn right to left keep their neighbours'. Every English string, and
| every symbol read or drawn outside an Arabic string, goes on through the
| engine's code as it was.
|
| The engine's routines and variables are named as in the
| ShiningForceCentral/SF2DISASM disassembly.

        .text
        .globl  redirect_hook
        .globl  symbol_hook
        .globl  draw_hook
        .globl  cursor_hook

| The engine.
        .set    FIND_ENGLISH, 0x006278          | DisplayText after movem.w d0,-(sp); lsr.w #6,d0
        .set    FOUND_STRING, 0x00629C          | DisplayText after the bank's strings: a0 = the length byte
        .set    HUFFMAN_BRANCH, 0x006356        | GetNextTextSymbol's decoding
        .set    ASCII_BRANCH, 0x006366          | GetNextTextSymbol's reading of a name's ASCII
        .set    DRAW_ENGLISH, 0x006B78          | SymbolsToGraphics after movem.w d0-d2,-(sp); andi.w #$FF,d0
        .set    GLYPH_PLACE, 0x006BDE           | the pen's place in the pixels: a2, its row in the tile d5, the ink << 4 d2
        .set    NEW_LINE_CHECK, 0x006308        | ApplyAutomaticNewline: a new line when the pen is past 204
        .set    SEND_LINE, 0x00697A             | HandleBlinkingDialogueCursor: the pen's line to VRAM
        .set    FONT_POINTER, 0x02800C          | p_font_VariableWidth
        .set    ASCII_TO_SYMBOL, 0x00666E       | table_AsciiToTextSymbolMap
| Work RAM.
        .set    PEN_X, 0xFFB6D4                 | DIALOGUE_TYPEWRITING_CURRENT_X
        .set    INK, 0xFFB6D6                   | USE_REGULAR_DIALOGUE_FONT: the ink's colour
        .set    FIRST_DRAWN, 0xFFB6D8           | DIALOGUE_REGULAR_TILE_TOGGLE: bit 0 once a character is drawn
        .set    ASCII, 0xFFB77A                 | CURRENT_DIALOGUE_ASCII_BYTE_ADDRESS
        .set    CODE_POINTER, 0xFFB77E          | COMPRESSED_STRING_POINTER
| The overlay's room and data.
        .set    ROOM_START, 0x042600
        .set    ROOM_END, 0x044000
        .set    REDIRECTS, 0x042A00             | 6 bytes each: a string's number, its Arabic's length byte; $FFFF ends it
        .set    ARABIC_FONT, 0x042B00           | 32 bytes a code, as the game's font: its width - 1, 15 rows of 16 pixels
        .set    RIGHT, 216                      | the window's inside: 27 tiles
        .set    LINE_START, 2
        .set    LINE_END, 214
        .set    CURSOR_ENGLISH, 0x168           | the arrow's X at the window's right corner
        .set    CURSOR_ARABIC, 0x98             | and at its left: 128 + 24
        .set    END, 0xFE

| -------------------------------------------------------------------------
| redirect_hook: d0.w = the string's number.

redirect_hook:
        movem.l d1/a1,-(sp)
        lea     REDIRECTS,a1
1:      move.w  (a1)+,d1
        cmpi.w  #0xFFFF,d1
        beq.s   2f
        cmp.w   d0,d1
        beq.s   3f
        addq.l  #4,a1
        bra.s   1b
2:      movem.l (sp)+,d1/a1                     | English: the instructions replaced, then on
        movem.w d0,-(sp)
        lsr.w   #6,d0
        jmp     FIND_ENGLISH
3:      movea.l (a1),a0                         | Arabic: its length byte
        movem.l (sp)+,d1/a1
        jmp     FOUND_STRING

| -------------------------------------------------------------------------
| symbol_hook: the next symbol in d0.

symbol_hook:
        move.l  a0,-(sp)
        movea.l CODE_POINTER,a0
        cmpa.l  #ROOM_START,a0
        blo.s   2f
        cmpa.l  #ROOM_END,a0
        bhs.s   2f
        addq.l  #4,sp
        tst.l   ASCII
        beq.s   1f
        bsr.w   draw_island
        clr.l   ASCII
1:      clr.w   d0
        move.b  (a0)+,d0
        move.l  a0,CODE_POINTER
        cmpi.b  #END,d0
        bne.s   9f
        clr.l   CODE_POINTER                    | the string's end: nothing is Arabic now
9:      rts
2:      movea.l (sp)+,a0                        | English: GetNextTextSymbol as it was
        tst.l   ASCII
        bne.w   3f
        jmp     HUFFMAN_BRANCH
3:      jmp     ASCII_BRANCH

| -------------------------------------------------------------------------
| draw_hook: d0 = a symbol to draw.

draw_hook:
        move.l  a0,-(sp)
        movea.l CODE_POINTER,a0
        cmpa.l  #ROOM_START,a0
        blo.s   1f
        cmpa.l  #ROOM_END,a0
        bhs.s   1f
        movea.l (sp)+,a0
        movem.l d0-d7/a0-a3,-(sp)
        andi.w  #0xFF,d0
        lea     ARABIC_FONT,a3
        bsr.w   glyph
        moveq   #0,d4
        move.b  PEN_X,d4
        move.w  #RIGHT,d0
        sub.w   d4,d0
        sub.w   d1,d0                           | its left side: RIGHT - pen - width
        bsr.w   plot
        add.b   d1,PEN_X
        movem.l (sp)+,d0-d7/a0-a3
        rts
1:      movea.l (sp)+,a0                        | English: SymbolsToGraphics as it was
        movem.w d0-d2,-(sp)
        andi.w  #0xFF,d0
        jmp     DRAW_ENGLISH

| -------------------------------------------------------------------------
| draw_island: the ASCII at ASCII (a name, an item, a number) drawn whole in
| the English font, left to right, as a block that ends at the mirror of the
| pen; the pen moves on by the block's width.

draw_island:
        movem.l d0-d7/a0-a6,-(sp)                | the engine's routines it calls keep none
        lea     ASCII_TO_SYMBOL,a2
        movea.l FONT_POINTER,a3
        movea.l ASCII,a1
        moveq   #0,d3                           | the block's width
1:      moveq   #0,d0
        move.b  (a1)+,d0
        beq.s   2f
        move.b  (a2,d0.w),d0
        subq.w  #1,d0                           | the English font starts at symbol 1
        bsr.w   glyph
        add.w   d1,d3
        bra.s   1b
2:      bset    #0,FIRST_DRAWN                  | a string's first character, as the English's
        bne.s   5f
        cmpi.b  #LINE_START,PEN_X
        beq.s   5f
        move.b  #0xFF,PEN_X                     | the string goes on in the window: a new line
5:      moveq   #0,d4
        move.b  PEN_X,d4
        add.w   d3,d4
        cmpi.w  #LINE_END,d4
        bls.s   6f
        move.b  #0xFF,PEN_X                     | the name would pass the line's end: a new line
6:      movem.l d3/a2-a3,-(sp)
        jsr     NEW_LINE_CHECK
        movem.l (sp)+,d3/a2-a3
        moveq   #0,d4
        move.b  PEN_X,d4
        move.w  #RIGHT,d5
        sub.w   d4,d5
        sub.w   d3,d5                           | its left side: RIGHT - pen - width
        movea.l ASCII,a1
3:      moveq   #0,d0
        move.b  (a1)+,d0
        beq.s   4f
        move.b  (a2,d0.w),d0
        subq.w  #1,d0
        bsr.w   glyph
        move.w  d5,d0
        bsr.w   plot
        add.w   d1,d5
        bra.s   3b
4:      add.b   d3,PEN_X
        jsr     SEND_LINE
        movem.l (sp)+,d0-d7/a0-a6
        rts

| -------------------------------------------------------------------------
| cursor_hook: the arrow's X (a0 = its sprite), at the left in an Arabic string.

cursor_hook:
        cmpi.l  #ROOM_START,CODE_POINTER
        blo.s   1f
        cmpi.l  #ROOM_END,CODE_POINTER
        bhs.s   1f
        move.w  #CURSOR_ARABIC,6(a0)
        rts
1:      move.w  #CURSOR_ENGLISH,6(a0)
        rts

| -------------------------------------------------------------------------
| glyph: d0.w = a glyph's number in the font at a3. a0 = its rows, d1 = its
| width (the first word's low nibble plus one, or 0).

glyph:
        move.w  d0,d1
        lsl.w   #5,d1
        lea     (a3,d1.w),a0
        move.w  (a0)+,d1
        andi.w  #0xF,d1
        beq.s   1f
        addq.w  #1,d1
1:      rts

| -------------------------------------------------------------------------
| plot: the glyph whose 15 rows are at a0 (a word each, its first pixel in the
| top bit) drawn with its left side at x = d0 on the pen's line, in the ink's
| colour; only the ink's pixels are written.

plot:
        movem.l d0-d7/a0-a2,-(sp)
        move.b  PEN_X,-(sp)
        move.b  d0,PEN_X
        move.w  d0,d4
        moveq   #0,d1
        move.b  INK,d1
        jsr     GLYPH_PLACE
        move.b  (sp)+,PEN_X
        andi.w  #7,d4                           | the first pixel's column in its tile
        moveq   #14,d6
1:      move.w  (a0)+,d7
        move.w  d4,d3
2:      lsl.w   #1,d7
        bcc.s   4f
        move.w  d3,d0                           | its byte: tile * 32, then two pixels a byte
        lsr.w   #3,d0
        lsl.w   #5,d0
        movea.l a2,a1
        adda.w  d0,a1
        move.w  d3,d0
        andi.w  #7,d0
        lsr.w   #1,d0
        adda.w  d0,a1
        btst    #0,d3
        bne.s   3f
        andi.b  #0x0F,(a1)                      | an even pixel: the high nibble
        or.b    d2,(a1)
        bra.s   4f
3:      andi.b  #0xF0,(a1)                      | an odd pixel: the low nibble
        or.b    d1,(a1)
4:      addq.w  #1,d3
        tst.w   d7
        bne.s   2b
        addq.l  #4,a2                           | the next row, in the tile under after its 8th
        addq.w  #1,d5
        cmpi.w  #8,d5
        blo.s   5f
        clr.w   d5
        adda.w  #0x3E0,a2
5:      dbf     d6,1b
        movem.l (sp)+,d0-d7/a0-a2
        rts
