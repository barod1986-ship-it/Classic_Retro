; Chrono Trigger (USA): the Arabic hooks of the dialogue text engine.
;
; This file is assembled with ca65 --cpu 65816 and linked by ld65 at
; HOOK_ADDRESS ($DB:8000), in the zeros at the end of bank $DB, where the
; overlay's data follows it (ARABIC_BANK). The text engine is in bank $C2 and
; has no room, so the hooks are reached with long jumps and leave the same
; way: to the engine's code, or to one of its RTS (ENGINE_RTS, GLYPH_RTS)
; where the engine called the routine a hook replaces. The engine runs with
; an 8-bit accumulator, 16-bit index registers and its direct page at $0200,
; and so does every hook:
;
; - setup_hook (JSL from $C2:57F7, in place of LDA $0F; STA $33): a string
;   whose address is in the REDIRECTS list is read from its Arabic text
;   instead, in ARABIC_BANK;
; - reader_hook (JML from $C2:58B2, the engine's reading loop): in a string of
;   ARABIC_BANK, a byte from $21 is a glyph of the Arabic font, drawn at the
;   mirror of the pen (MIRROR - pen - width) while the pen moves on as the
;   engine's does; a byte below $21 is a control code, left to the engine
;   (line and page breaks, delays, names, numbers); any other string goes on
;   through the engine's code;
; - glyph_hook (JML from $C2:5DC4, the engine's glyph routine): in an Arabic
;   string, a name or number the engine expands (its states 1 to 3) is drawn
;   whole, left to right, at the mirror of its place, and the engine is told
;   that its last character is done.
;
; Glyphs are ORed into the engine's tile buffer: the pixels of a glyph drawn
; right to left share their tile bytes with the glyph on their right, which
; the engine's own routine would overwrite.
;
; The engine's routines as the dscotton/ct_disassembly disassembly names
; them: the message's start Text_RenderString ($C2:57DF), the reading loop
; Text_DecodeLoop ($C2:58B2), the control codes' table TextCtrlCodeTable
; ($C2:5903), the glyph routine Text_EmitGlyph ($C2:5DC4), its two layouts
; Text_DrawGlyph2bpp (COLUMNS_A) and Text_DrawGlyph4bpp (COLUMNS_B), and
; the widths CharacterWidthStandardTable1 (WIDTHS).

    .p816
    .smart -

    .export setup_hook, reader_hook, glyph_hook

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

; The overlay's data (ARABIC_BANK).
ARABIC_BANK     = $DB
REDIRECTS       = $DB8400           ; 6 bytes each: English address, Arabic address
ARABIC_WIDTHS   = $DB8800           ; a byte a code from FIRST_GLYPH
ARABIC_FONT     = $DB8900           ; 48 bytes a code: 24 left, 24 right (high nibble)
FIRST_GLYPH     = $21
GLYPH_BYTES     = 48
MIRROR          = 256
STEP_A          = $00F0             ; to the tile row under, after a glyph's 4th row
STEP_B          = $01F0

; The engine's direct page ($0200).
BUFFER          = $10               ; 3 bytes: the tile buffer
STYLE           = $14               ; window style
DRAWN           = $17               ; characters drawn in the line
STATE           = $30               ; 0 text, 1 to 3 an expansion
TEXT            = $31               ; 3 bytes: the text pointer
PEN             = $34
CODE            = $35               ; 2 bytes
SOURCE          = $37               ; 3 bytes: an expansion's next character
LEFTOVER        = $3A               ; an expansion's characters left
; The engine's glyph temporaries ($60-$7B), the hooks' own between glyphs.
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

    .a8
    .i16

; -------------------------------------------------------------------------
; setup_hook: the string's address is $31-$32 and its bank $0F.

setup_hook:
    lda $0F
    sta TEXT+2
    ldx #$0000
@next:
    lda f:REDIRECTS+2,x             ; the English string's bank; 0 ends the list
    beq @done
    cmp TEXT+2
    bne @skip
    rep #$20
    .a16
    lda f:REDIRECTS,x
    cmp TEXT
    bne @skip16
    lda f:REDIRECTS+3,x
    sta TEXT
    sep #$20
    .a8
    lda f:REDIRECTS+5,x
    sta TEXT+2
    bra @done
@skip16:
    sep #$20
    .a8
@skip:
    inx
    inx
    inx
    inx
    inx
    inx
    bra @next
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
    cmp #ARABIC_BANK
    beq @arabic
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
    cmp #ARABIC_BANK
    bne @english
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
; number's digits (state 2) are the font's digit codes.
    .a8
next_char:
    rep #$20
    .a16
    lda [SOURCE],y
    and #$00FF
    iny
    sep #$20
    .a8
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
    xba
    lda STATE
    cmp #$02
    bne @plain
    xba
    clc
    adc #$D4
    xba
@plain:
    xba
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
