; Chrono Trigger (USA): the Arabic hooks of the dialogue text engine.
;
; This file is assembled with ca65 --cpu 65816 and linked by ld65 at
; HOOK_ADDRESS ($40:0000), the first bytes of the third and fourth MiB the
; overlay adds to the ROM (banks $40 to $5F, whose upper halves mirror the
; ROM's first banks as the game's HiROM mapping had them). The text engine is
; in bank $C2 and has no room, so the hooks are reached with long calls and
; jumps and leave the same way: to the engine's code, or to one of its RTS
; (ENGINE_RTS, GLYPH_RTS) where the engine called the routine a hook
; replaces. The engine runs with an 8-bit accumulator, 16-bit index registers
; and its direct page at $0200, and so do its hooks:
;
; - setup_hook (JSL from $C2:57F7, in place of LDA $0F; STA $33): a string
;   named by a table the TABLES list knows is read from its Arabic text
;   instead, when its entry in the table's ENTRIES (three bytes a string, the
;   Arabic's address; a zero bank leaves the English) has one. The list is
;   reached through BANK_INDEX by the table's bank, and a table is matched
;   by the address of the string's pointer in it (the table's start plus
;   twice the string's number), so an event that names a table from its
;   middle finds the same entries;
; - reader_hook (JML from $C2:58B2, the engine's reading loop): in a string
;   of the Arabic banks (FIRST_ARABIC_BANK to END_ARABIC_BANK), a byte from
;   $21 is a glyph of the Arabic font, drawn at the mirror of the pen
;   (MIRROR - pen - width) while the pen moves on as the engine's does; a
;   byte below $21 is a control code, left to the engine (line and box
;   breaks, pauses, names, numbers); any other string goes on through the
;   engine's code;
; - glyph_hook (JML from $C2:5DC4, the engine's glyph routine): in an Arabic
;   string, a name or number the engine expands (its states 1 to 3) is drawn
;   whole, left to right, at the mirror of its place, and the engine is told
;   that its last character is done;
; - choice_hook (JML from $C0:F05E, the dialogue driver's cursor routine, in
;   the vertical blank): the choice cursor's two by two tiles go to the box's
;   right side (CURSOR_MAP_RTL) after an Arabic message, to its left
;   (CURSOR_MAP) as before after an English one; the other choices' cells
;   show their text tiles again.
;
; Glyphs are ORed into the engine's tile buffer: the pixels of a glyph drawn
; right to left share their tile bytes with the glyph on their right, which
; the engine's own routine would overwrite.
;
; The engine's routines as the dscotton/ct_disassembly disassembly names
; them: the message's start Text_RenderString ($C2:57DF), the reading loop
; Text_DecodeLoop ($C2:58B2), the control codes' table TextCtrlCodeTable
; ($C2:5903), the glyph routine Text_EmitGlyph ($C2:5DC4), its two layouts
; Text_DrawGlyph2bpp (COLUMNS_A) and Text_DrawGlyph4bpp (COLUMNS_B), the
; widths CharacterWidthStandardTable1 (WIDTHS), and the cursor routine
; Dialog_DrawChoiceCursor ($C0:F05E) with its slots Dialog_DrawChoiceSlot0
; to 3.

    .p816
    .smart -

    .export setup_hook, reader_hook, glyph_hook, choice_hook

; The engine (bank $C2).
DRAW_CHAR       = $C258BE           ; A = a code from $A0: the engine draws it
DICTIONARY      = $C258D0           ; A = a code below $A0: dictionary or control
CONTROL         = $C258FD           ; A = a code below $21: the control codes' table
ENGINE_RTS      = $C258CB           ; LDA #$10; STA $15; RTS: the frame's characters done
GLYPH_BODY      = $C25DC8           ; the glyph routine after REP #$20; LDA $35
GLYPH_RTS       = $C25E32           ; LDA #$00; XBA; RTS: the glyph routine's end
COLUMNS_A       = $5FE6             ; tile buffer column offsets, window style 0
COLUMNS_B       = $6066             ; the other styles
WIDTHS          = $C260E6           ; the font's widths from code $A0
FONT_LEFT       = $FF2060           ; 24 bytes a code: its left 8 pixels, 2 bits each
FONT_RIGHT      = $FF3860           ; 24 bytes two codes: their right 4 pixels
FIRST_CHAR      = $A0

; The dialogue driver (bank $C0): the choice cursor, drawn in the vertical
; blank with the PPU's registers on the direct page.
CURSOR_DONE     = $C0F0CE           ; PLD; RTS: the cursor routine's end, a choice shown
CURSOR_IDLE     = $C0F085           ; PLD; LDA #$80; STA $63; RTS: the same, no choice
CHOICE_SLOT     = $7E0163           ; the choice the cursor is on: 0 to 3; 4 or $80 none
TEXT_BANK       = $7E0233           ; the bank of the last message's text
CURSOR_MAP      = $1C02             ; the box's tile map: the cursor's cell, line 0, column 2
CURSOR_MAP_RTL  = $1C1D             ; the same at column 29
CURSOR_TILE     = $28FC             ; the cursor's tiles: two, and two under them
TEXT_TILE       = $2902             ; the text's tiles under the cursor, column 2
TEXT_TILE_RTL   = $292D             ; the same at column 29 (the second half's 13th)
LINE_STEP       = $0040             ; a line of the box: two rows of 32 tiles
ROW_STEP        = $0020             ; the row of tiles under a row
TEXT_ROW_STEP   = $0010             ; the text's tiles of the row under
CURSOR_ROW_STEP = $0002             ; the cursor's tiles of the row under

; The overlay's data (banks $40 to $5F).
FIRST_ARABIC_BANK = $42             ; the Arabic messages' first bank...
END_ARABIC_BANK = $60               ; ...and the one past their last
DATA_BANK       = $400000           ; the bank of the index and the list
BANK_INDEX      = $400800           ; a word a bank from $C0: the offset in DATA_BANK of its first TABLES entry, 0 for none
TABLES          = $400900           ; 8 bytes: the English table's address (3), its strings times two (2), its ENTRIES' address (3); a zero bank ends
ARABIC_WIDTHS   = $402000           ; a byte a code from FIRST_GLYPH
ARABIC_FONT     = $402100           ; 48 bytes a code: 24 left, 24 right (high nibble)
FIRST_GLYPH     = $21
GLYPH_BYTES     = 48
MIRROR          = 256
STEP_A          = $00F0             ; to the tile row under, after a glyph's 4th row
STEP_B          = $01F0

; The engine's direct page ($0200).
BUFFER          = $10               ; 3 bytes: the tile buffer
STYLE           = $14               ; window style
DRAWN           = $17               ; characters drawn in the line
TABLE           = $0D               ; 3 bytes: the string table
STATE           = $30               ; 0 text, 1 to 3 an expansion
TEXT            = $31               ; 3 bytes: the text pointer
PEN             = $34
CODE            = $35               ; 2 bytes
SOURCE          = $37               ; 3 bytes: an expansion's next character
LEFTOVER        = $3A               ; an expansion's characters left
; The engine's glyph temporaries ($60-$7B), the hooks' own between glyphs, and
; the message's start's.
LEFT            = $60               ; 3 bytes: a glyph's left 8 pixels
RIGHT           = $63               ; 3 bytes: its right 4 pixels
NIBBLE          = $66               ; $80: the right pixels are in the low nibble
SHIFT           = $68               ; 2 bytes
COUNT           = $6A               ; 2 bytes: the glyph byte (row and plane)
CATCH           = $6C               ; 2 bytes: bits shifted into a third tile
ROW             = $6E               ; 2 bytes
COLUMN0         = $70               ; 2 bytes: tile offsets of the glyph's columns
DEST            = $73               ; 3 bytes: the glyph byte's place in the buffer
COLUMN1         = $76
COLUMN2         = $78
STEP            = $7A
ENTRY           = $60               ; 3 bytes: at a message's start, the string's entry

    .a8
    .i16

; -------------------------------------------------------------------------
; setup_hook: the string's address is $31-$32, its bank $0F, its table $0D-$0F
; and Y its number times two.

setup_hook:
    lda TABLE+2
    sta TEXT+2
    sec
    sbc #$C0                        ; the table's bank, from $C0
    bcc @done
    rep #$20
    .a16
    and #$00FF
    asl a
    tax
    lda f:BANK_INDEX,x              ; the bank's first entry, from DATA_BANK; 0: no table of this bank
    beq @done16
    tax
    tya
    clc
    adc TABLE                       ; the string's pointer in its table
    sta ENTRY
@next:
    sep #$20
    .a8
    lda f:DATA_BANK+2,x             ; the entry's table's bank: another bank, or 0, ends the bank's run
    cmp TABLE+2
    bne @done
    rep #$20
    .a16
    lda ENTRY
    sec
    sbc f:DATA_BANK,x               ; the pointer's offset in this table
    bcc @skip                       ; before it
    cmp f:DATA_BANK+3,x             ; past its strings times two
    bcs @skip
    lsr a
    sta ENTRY
    asl a
    clc
    adc ENTRY                       ; the number times three
    clc
    adc f:DATA_BANK+5,x
    sta ENTRY
    sep #$20
    .a8
    lda f:DATA_BANK+7,x
    sta ENTRY+2
    ldy #$0002
    lda [ENTRY],y                   ; the Arabic's bank; 0: the English stays
    beq @done
    tay
    rep #$20
    .a16
    lda [ENTRY]
    sta TEXT
    sep #$20
    .a8
    tya
    sta TEXT+2
    bra @done
    .a16                            ; from the tests above, A is 16 bits
@skip:
    txa
    clc
    adc #$0008
    tax
    bra @next
@done16:
    sep #$20
    .a8
@done:
    rep #$20
    .a16
    lda #$0000
    sep #$20
    .a8
    rtl

; -------------------------------------------------------------------------
; reader_hook: the engine's reading loop, state 0.

reader_hook:
    lda [TEXT]
    rep #$20
    .a16
    inc TEXT
    sep #$20
    .a8
    pha
    lda TEXT+2
    cmp #FIRST_ARABIC_BANK
    bcc @english
    cmp #END_ARABIC_BANK
    bcc @arabic
@english:
    pla
    cmp #FIRST_CHAR
    bcc @dictionary
    jml DRAW_CHAR
@dictionary:
    jml DICTIONARY
@arabic:
    pla
    cmp #FIRST_GLYPH
    bcs @glyph
    jml CONTROL
@glyph:
    jsr draw_arabic
    dec $13
    bne reader_hook
    jml ENGINE_RTS

; draw_arabic: A = an Arabic glyph's code. It goes at MIRROR - pen - width; the
; pen moves on by the width.
draw_arabic:
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #FIRST_GLYPH
    tax
    sta ROW                         ; the glyph's number
    lda f:ARABIC_WIDTHS,x
    and #$00FF
    pha                             ; its width, kept on the stack
    asl ROW                         ; number * 16
    asl ROW
    asl ROW
    asl ROW
    lda ROW
    asl a                           ; number * 32
    clc
    adc ROW                         ; number * 48
    clc
    adc #.loword(ARABIC_FONT)
    sta LEFT
    clc
    adc #24
    sta RIGHT
    sep #$20
    .a8
    lda #^ARABIC_FONT
    sta LEFT+2
    sta RIGHT+2
    stz NIBBLE
    rep #$20
    .a16
    lda PEN
    and #$00FF
    sta ROW
    lda #MIRROR
    sec
    sbc ROW
    sec
    sbc 1,s                         ; MIRROR - pen - width
    bmi @moved                      ; left of the buffer: not drawn
    sep #$20
    .a8
    jsr plot
@moved:
    sep #$20
    .a8
    pla                             ; the width's low byte
    clc
    adc PEN
    sta PEN
    pla
    inc DRAWN
    rep #$20
    .a16
    lda #$0000
    sep #$20
    .a8
    rts

; -------------------------------------------------------------------------
; glyph_hook: the engine's glyph routine, for an expansion's character.

glyph_hook:
    lda TEXT+2
    cmp #FIRST_ARABIC_BANK
    bcc @english
    cmp #END_ARABIC_BANK
    bcs @english
    lda STATE
    bne island
@english:
    rep #$20
    .a16
    lda CODE
    jml GLYPH_BODY

    .a8
; island: the expansion's characters from this one on, drawn left to right as a
; block that ends at the mirror of the pen. The engine then takes it for its
; last character: LEFTOVER is set to 1.
island:
    ; Its width: this character, then the ones left in SOURCE.
    rep #$20
    .a16
    lda #$0000
    pha                             ; the width, on the stack
    lda CODE
    jsr char_width
    clc
    adc 1,s
    sta 1,s
    ldy #$0000
    ldx #$0001
@measure:
    txa
    sep #$20
    .a8
    cmp LEFTOVER
    bcs @measured
    jsr next_char
    rep #$20
    .a16
    jsr char_width
    clc
    adc 1,s
    sta 1,s
    inx
    bra @measure
@measured:
    ; Its left edge: MIRROR - pen - width.
    rep #$20
    .a16
    lda PEN
    and #$00FF
    sta ROW
    lda #MIRROR
    sec
    sbc ROW
    sec
    sbc 1,s
    pha                             ; the next character's x, on the stack
    ; Draw: this character, then the rest.
    lda CODE
    jsr island_char
    ldy #$0000
    ldx #$0001
@draw:
    txa
    sep #$20
    .a8
    cmp LEFTOVER
    bcs @drawn
    jsr next_char
    rep #$20
    .a16
    jsr island_char
    inx
    bra @draw
@drawn:
    sep #$20
    .a8
    txa
    clc
    adc DRAWN
    sta DRAWN
    lda #$01
    sta LEFTOVER
    rep #$20
    .a16
    pla                             ; the x past the block
    pla                             ; the block's width
    sep #$20
    .a8
    clc
    adc PEN
    sta PEN
    jml GLYPH_RTS

; next_char: A (16-bit) = the character at SOURCE + Y, Y moved past it. A
; number's digits (state 2) are raw digits, 0 to 9, which become the font's
; digit codes; only in a name or an item do $01 and $02 lead a two-byte code.
    .a8
next_char:
    rep #$20
    .a16
    lda [SOURCE],y
    and #$00FF
    iny
    sep #$20
    .a8
    xba                             ; B = the byte
    lda STATE
    cmp #$02
    bne @text
    xba
    clc
    adc #$D4                        ; a digit: the font's code for it
    bra @one
@text:
    xba
    cmp #$03
    bcs @one
    cmp #$01                        ; $01 and $02: a two-byte code
    bcc @one
    rep #$20
    .a16
    lda #$0100                      ; not drawn
    iny
    rts
    .a8
@one:
    rep #$20
    .a16
    and #$00FF
    rts

; char_width: A (16-bit) = a code of the game's font; A = its width (0 for a
; code outside the font).
    .a16
char_width:
    cmp #FIRST_CHAR
    bcc @none
    cmp #$0100
    bcs @none
    phx
    sec
    sbc #FIRST_CHAR
    tax
    lda f:WIDTHS,x
    plx
    and #$00FF                      ; Z: no width
    rts
@none:
    lda #$0000
    rts

; island_char: A (16-bit) = a code of the game's font, drawn at the x on the
; stack (3,s, under the return address), which moves on by its width. X and Y
; are kept.
    .a16
island_char:
    phx
    phy
    pha                             ; the code; the x is at 9,s
    jsr char_width
    beq @skip                       ; not a glyph of the font
    lda 1,s
    ; left pixels: FONT_LEFT + code * 24
    asl a
    asl a
    asl a                           ; code * 8
    sta ROW
    asl a                           ; code * 16
    clc
    adc ROW                         ; code * 24
    clc
    adc #.loword(FONT_LEFT)
    sta LEFT
    ; right pixels: FONT_RIGHT + (code / 2) * 24, the low nibble for an odd code
    lda 1,s
    lsr a
    asl a
    asl a
    asl a
    sta ROW
    asl a
    clc
    adc ROW
    clc
    adc #.loword(FONT_RIGHT)
    sta RIGHT
    sep #$20
    .a8
    lda #^FONT_LEFT
    sta LEFT+2
    lda #^FONT_RIGHT
    sta RIGHT+2
    lda 1,s
    lsr a
    lda #$00
    ror a                           ; $80 for an odd code
    sta NIBBLE
    lda 9,s                         ; the x
    jsr plot
    rep #$20
    .a16
@skip:
    pla
    jsr char_width
    clc
    adc 7,s                         ; the x, under Y, X and the return address
    sta 7,s
    ply
    plx
    rts

; -------------------------------------------------------------------------
; plot: A (8-bit) = x. ORs the glyph at LEFT/RIGHT (NIBBLE) into the tile
; buffer, its 12 rows of 2 bits from the line's top, as the engine lays a
; glyph out: rows 0 to 3 in the lower half of a tile row, rows 4 to 11 in the
; tile row under it.

    .a8
plot:
    phb
    pha
    lda #$C2
    pha
    plb                             ; the column tables' bank
    lda 1,s
    and #$07
    sta SHIFT
    stz SHIFT+1
    pla
    and #$F8
    lsr a
    lsr a                           ; the column * 2
    rep #$30
    .a16
    and #$00FF
    tax
    lda STYLE
    and #$000F
    bne @style_b
    lda COLUMNS_A,x
    sta COLUMN0
    lda COLUMNS_A+2,x
    sta COLUMN1
    lda COLUMNS_A+4,x
    sta COLUMN2
    lda #STEP_A
    bra @laid_out
@style_b:
    lda COLUMNS_B,x
    sta COLUMN0
    lda COLUMNS_B+2,x
    sta COLUMN1
    lda COLUMNS_B+4,x
    sta COLUMN2
    lda #STEP_B
@laid_out:
    sta STEP
    lda BUFFER
    clc
    adc #$0008
    sta DEST
    sep #$20
    .a8
    lda BUFFER+2
    sta DEST+2
    rep #$20
    .a16
    stz COUNT
@row:
    ldy COUNT
    sep #$20
    .a8
    lda [LEFT],y
    xba
    lda [RIGHT],y
    bit NIBBLE
    bpl @high
    asl a
    asl a
    asl a
    asl a
    bra @joined
@high:
    and #$F0
@joined:
    rep #$20
    .a16
    stz CATCH
    ldx SHIFT
    beq @shifted
@shift:
    lsr a
    ror CATCH
    dex
    bne @shift
@shifted:
    sta ROW
    sep #$20
    .a8
    ldy COLUMN0
    lda ROW+1
    ora [DEST],y
    sta [DEST],y
    ldy COLUMN1
    lda ROW
    ora [DEST],y
    sta [DEST],y
    ldy COLUMN2
    lda CATCH+1
    ora [DEST],y
    sta [DEST],y
    rep #$20
    .a16
    inc DEST
    lda COUNT
    inc a
    sta COUNT
    cmp #$0008
    bne @same_row
    lda DEST
    clc
    adc STEP
    sta DEST
    lda COUNT
@same_row:
    cmp #$0018
    bne @row
    sep #$20
    .a8
    plb
    rts

; -------------------------------------------------------------------------
; choice_hook: the dialogue driver's cursor routine, from its start (PHD;
; REP #$20; LDA #$2100). The four choices' cells are written to the box's tile
; map: the cursor's tiles in the chosen one, the text's tiles in the others.
; After an Arabic message the cells are at the box's right side. The stack
; holds the loop's values: the choice (from CHOICE_SLOT), the cell's tile map
; address and the text's tile of each line, and the line.

    .a8
    .i16
choice_hook:
    phd
    rep #$20
    .a16
    lda #$2100
    tcd                             ; the PPU's registers
    sep #$20
    .a8
    lda #$80
    sta $15                         ; VMAIN: the address moves on after a word
    ldx #CURSOR_MAP
    ldy #TEXT_TILE
    lda f:TEXT_BANK
    cmp #FIRST_ARABIC_BANK
    bcc @placed
    cmp #END_ARABIC_BANK
    bcs @placed
    ldx #CURSOR_MAP_RTL
    ldy #TEXT_TILE_RTL
@placed:
    rep #$20
    .a16
    phx                             ; 7,s: the cell
    phy                             ; 5,s: the text's tile
    lda f:CHOICE_SLOT
    and #$00FF
    pha                             ; 3,s: the choice
    lda #$0000
    pha                             ; 1,s: the line
@line:
    lda 7,s
    tax
    stx $16                         ; VMADD
    lda 1,s
    cmp 3,s
    beq @cursor
    lda 5,s
    tay
    sty $18                         ; VMDATA: the text's tile...
    iny
    sty $18                         ; ...and the next
    txa
    clc
    adc #ROW_STEP
    tax
    stx $16
    tya
    clc
    adc #TEXT_ROW_STEP-1
    tay
    sty $18                         ; the row under: the text's tiles
    iny
    sty $18
    bra @next
@cursor:
    ldy #CURSOR_TILE
    sty $18
    iny
    sty $18
    txa
    clc
    adc #ROW_STEP
    tax
    stx $16
    iny
    sty $18                         ; the row under: the cursor's other tiles
    iny
    sty $18
@next:
    lda 7,s
    clc
    adc #LINE_STEP
    sta 7,s
    lda 5,s
    clc
    adc #LINE_STEP
    sta 5,s
    lda 1,s
    inc a
    sta 1,s
    cmp #$0004
    bne @line
    pla                             ; the line
    pla                             ; the choice
    plx
    plx
    cmp #$0004
    sep #$20
    .a8
    bcs @idle
    jml CURSOR_DONE
@idle:
    jml CURSOR_IDLE
