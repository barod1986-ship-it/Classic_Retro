; The Legend of Zelda: A Link to the Past (USA): the Arabic hooks of the
; dialogue's text engine.
;
; This file is assembled with ca65 --cpu 65816 and linked by ld65 at
; HOOK_ADDRESS ($0E:EE30), in free bytes of bank $0E, the text engine's own
; bank, so the engine's code and tables are reached with short calls. The
; overlay's data is in the half the overlay adds to the ROM (banks $20 on).
; The engine parses a message into BUFFER (its dictionary words and the
; player's name written out), then draws it a character at a time into the
; lines' tiles (VWF_BUFFER), each at the pen of its line (PENS), which moves
; on by the character's width:
;
; - parse_hook (JMP from $0E:C4E2, the start of RenderText_ParseMessage): a
;   message whose number is in the REDIRECTS list is parsed from its Arabic
;   text instead, where every byte below $67 or from $80 is a glyph of the
;   Arabic font and $67-$7F keep their meaning (line changes, waits, speed,
;   the player's name); the name and numbers are written between ISLAND and
;   ISLAND_END, one block for those that follow each other (a number's digits
;   are a command each), and FLAG tells the drawing the message is Arabic;
; - draw_hook (JSR from $0E:CAD5, in RenderText_DrawSingleCharacter, in place
;   of RenderText_PerformVWFing): in an Arabic message, each glyph is drawn at
;   the mirror of the pen (RIGHT - pen - width) while the pen moves on as the
;   engine's does, so a line starts at the right;
; - island_hook (the draw table's entry for ISLAND, $0E:CA09, which only an
;   Arabic message writes): the name or number is drawn whole in the English
;   font, left to right, at the mirror of its place;
; - tilemap_hook (JSR from $0E:D313, in RenderText_DrawACharacter): an Arabic
;   message's lines are shown a tile further right, against the window's
;   right side as the English's are against its left.
;
; Glyphs are ORed into the tiles: a glyph drawn right to left shares its tile
; bytes with the glyph on its right, which the engine's routine would write
; over. The engine runs these with its data bank $0E and its direct page at
; $0000; the hooks use the engine's scratch bytes $00-$0F.
;
; The engine's routines and tables are named as in the spannerisms/usdasm
; disassembly.

    .p816
    .smart -

    .export parse_hook, draw_hook, island_hook, tilemap_hook

; The engine (bank $0E).
PARSE_ENGLISH   = $C4E7             ; RenderText_ParseMessage after REP #$30; LDA $1CF0
EXECUTE         = $C547             ; RenderText_ExecuteCommand: A = a command
PERFORM_VWF     = $CB5E             ; RenderText_PerformVWFing
ENGLISH_WIDTHS  = $CADF             ; its widths, by the English code
RENDER_OFFSETS  = $CB4A             ; each line's first tile in VWF_BUFFER
LINE_OFFSETS    = $CB50             ; each line's first pen in PENS
ENGLISH_FONT    = $0E8000           ; TheFont: a code's top tile, its bottom 16 on
; Work RAM.
BUFFER          = $7F1200           ; the message, parsed
VWF_BUFFER      = $7F0000           ; the lines' tiles, two bits a pixel
PENS            = $7EC230           ; the pen of each character of a line
TILEMAP_ADDRESS = $1CD0
INDEX           = $1CD9             ; 2 bytes: the next byte of BUFFER
SOURCE          = $1CDD             ; 2 bytes: the next byte of the text, while parsing
FLAG            = $1CE4             ; 1: an Arabic message (0 from the engine's settings)
MESSAGE         = $1CF0             ; 2 bytes: the message's number
VWF_NEWROW      = $0720             ; 2 bytes: a line change is waiting
VWF_LINE        = $0722             ; 2 bytes: the line, times 2
VWF_PEN         = $0724             ; 2 bytes: the next character's place in PENS
VWF_RENDER      = $0726             ; 2 bytes: the line's first tile in VWF_BUFFER
HALF            = $0150             ; a line's lower tiles, after its upper
RIGHT           = 168               ; a line is 21 tiles

; The text's codes.
FIRST_COMMAND   = $67
NAME            = $6A
NUMBER          = $6C
END             = $7F
GLYPHS_ABOVE    = $80               ; from here the bytes are glyphs again
ISLAND          = $6A               ; in BUFFER: English text from here...
ISLAND_END      = $6B               ; ...to here

; The overlay's data (the added half, bank $20).
REDIRECTS       = $208000           ; 5 bytes each: a message's number, its Arabic's address
ARABIC_WIDTHS   = $208800           ; a byte a code
ARABIC_FONT     = $208900           ; 64 bytes a code: 16 rows of two planes, 16 bits each

; The engine's scratch bytes.
GLYPH           = $00               ; 3 bytes: the glyph's pixels
DEST            = $04               ; 2 bytes: the row's first tile in VWF_BUFFER
P0              = $06               ; 2 bytes: the row's plane 0, its leftmost pixel in bit 15
P1              = $08               ; 2 bytes: its plane 1
C0              = $0A               ; 2 bytes: bits shifted into a third tile
C1              = $0C
SHIFT           = $0E               ; 2 bytes: the glyph's first pixel in its tile

; -------------------------------------------------------------------------
; parse_hook: RenderText_ParseMessage.

    .a16
    .i16
parse_hook:
    rep #$30
    ldx #$0000
@find:
    lda f:REDIRECTS,x
    cmp #$FFFF
    beq @english
    cmp MESSAGE
    beq @arabic
    txa
    clc
    adc #5
    tax
    bra @find
@english:
    sep #$20
    .a8
    stz FLAG
    rep #$20
    .a16
    lda MESSAGE
    jmp PARSE_ENGLISH
@arabic:
    lda f:REDIRECTS+2,x
    sta $04
    lda f:REDIRECTS+3,x
    sta $05
    sep #$20
    .a8
    lda #1
    sta FLAG
    rep #$20
    .a16
    lda #$7F7F                      ; a terminator, as the engine writes
    sta f:BUFFER
    ldy #$0000
    tyx
    sty INDEX
    sty SOURCE
    sep #$20
    .a8
@next:
    lda [$04],y
    cmp #FIRST_COMMAND
    bcc @glyph
    cmp #GLYPHS_ABOVE
    bcs @glyph
    cmp #END
    beq @end
    cmp #NAME
    beq @island
    cmp #NUMBER
    beq @island
    jsr EXECUTE                     ; the engine's commands leave A 8 bits, X and Y 16
    ldx INDEX
    ldy SOURCE
    bra @next
@glyph:
    sta f:BUFFER,x
    iny
    sty SOURCE
    inx
    stx INDEX
    bra @next
@island:
    pha
    cpx #$0000
    beq @new_island
    lda f:BUFFER-1,x                ; right after another: the same block (a number's digits)
    cmp #ISLAND_END
    bne @new_island
    dex
    bra @in_island
@new_island:
    lda #ISLAND
    sta f:BUFFER,x
    inx
@in_island:
    stx INDEX
    pla
    jsr EXECUTE                     ; the name or the digits, at INDEX
    ldx INDEX
    lda #ISLAND_END
    sta f:BUFFER,x
    inx
    stx INDEX
    ldy SOURCE
    bra @next
@end:
    sta f:BUFFER,x
    sep #$30
    .i8
    rts

; -------------------------------------------------------------------------
; draw_hook: a character of RenderText_DrawSingleCharacter.

    .a8
    .i8
draw_hook:
    lda FLAG
    bne @arabic
    jmp PERFORM_VWF
@arabic:
    jsr new_row
    rep #$30
    .a16
    .i16
    ldx INDEX
    lda f:BUFFER,x
    and #$00FF
    pha                             ; the code
    tax
    lda f:ARABIC_WIDTHS,x
    and #$00FF
    jsr advance
    jsr setup_plot
    pla
    asl a                           ; the code * 64
    asl a
    asl a
    asl a
    asl a
    asl a
    clc
    adc #.loword(ARABIC_FONT)
    sta GLYPH
    sep #$20
    .a8
    lda #^ARABIC_FONT
    sta GLYPH+2
    rep #$20
    .a16
    jsr plot_arabic
    inc INDEX
    sep #$30
    .a8
    .i8
    rts

; -------------------------------------------------------------------------
; island_hook: BUFFER holds ISLAND, English codes, then ISLAND_END.

    .a8
    .i8
island_hook:
    jsr new_row
    rep #$30
    .a16
    .i16
    ldx INDEX
    inx
    stz P1                          ; the island's width
@measure:
    lda f:BUFFER,x
    and #$00FF
    cmp #ISLAND_END
    beq @measured
    tay
    lda ENGLISH_WIDTHS,y
    and #$00FF
    clc
    adc P1
    sta P1
    inx
    bra @measure
@measured:
    phx                             ; ISLAND_END's index
    lda P1
    jsr advance
    pha                             ; the island's left side: 1,s; the end: 3,s
    ldx INDEX
    inx
@character:
    lda f:BUFFER,x
    and #$00FF
    cmp #ISLAND_END
    beq @done
    phx                             ; its index: 1,s; the left side: 3,s
    pha                             ; the code: 1,s; the index: 3,s; the left side: 5,s
    lda 5,s
    jsr setup_plot
    lda 1,s                         ; the top tile: ((code & $F0) << 1) | (code & $0F)
    and #$00F0
    asl a
    sta GLYPH
    lda 1,s
    and #$000F
    ora GLYPH
    asl a                           ; 16 bytes a tile
    asl a
    asl a
    asl a
    clc
    adc #.loword(ENGLISH_FONT)
    sta GLYPH
    sep #$20
    .a8
    lda #^ENGLISH_FONT
    sta GLYPH+2
    rep #$20
    .a16
    jsr plot_english
    pla                             ; the code; the index: 1,s; the left side: 3,s
    tay
    lda ENGLISH_WIDTHS,y
    and #$00FF
    clc
    adc 3,s
    sta 3,s
    plx
    inx
    bra @character
@done:
    pla
    plx
    inx
    stx INDEX
    sep #$30
    .a8
    .i8
    rts

; -------------------------------------------------------------------------
; tilemap_hook: RenderText_DrawACharacter's first row, a tile further right in
; an Arabic message. It keeps X and Y.

    .a16
    .i16
tilemap_hook:
    lda FLAG
    and #$00FF
    clc
    adc #$0021                      ; a row down and a tile right, as the engine's
    clc
    adc TILEMAP_ADDRESS
    sta TILEMAP_ADDRESS
    rts

; -------------------------------------------------------------------------
; new_row: the line's places after a line change, as the engine's.

    .a8
    .i8
new_row:
    rep #$20
    .a16
    lda VWF_NEWROW
    beq @same
    ldy VWF_LINE
    lda RENDER_OFFSETS,y
    sta VWF_RENDER
    lda LINE_OFFSETS,y
    sta VWF_PEN
    stz VWF_NEWROW
@same:
    sep #$20
    .a8
    rts

; advance: A = a width. The pen moves on by it; A = RIGHT - the new pen, the
; left side of what is drawn.

    .a16
    .i16
advance:
    sta P0
    ldx VWF_PEN
    lda f:PENS,x
    and #$00FF
    clc
    adc P0
    sep #$20
    .a8
    sta f:PENS+1,x
    rep #$20
    .a16
    inx
    stx VWF_PEN
    and #$00FF
    sta P0
    lda #RIGHT
    sec
    sbc P0
    rts

; setup_plot: A = the left side. DEST and SHIFT for a glyph there.

setup_plot:
    pha
    and #$0007
    sta SHIFT
    pla
    lsr a
    lsr a
    lsr a
    asl a                           ; 16 bytes a tile
    asl a
    asl a
    asl a
    clc
    adc VWF_RENDER
    sta DEST
    rts

; plot_arabic: GLYPH = 16 rows of 4 bytes (plane 0, then plane 1).

plot_arabic:
    ldy #$0000
@row:
    lda [GLYPH],y
    sta P0
    iny
    iny
    lda [GLYPH],y
    sta P1
    iny
    iny
    jsr plot_row
    cpy #32
    bne @same_half
    lda DEST                        ; the lower tiles
    clc
    adc #HALF - 16
    sta DEST
@same_half:
    cpy #64
    bne @row
    rts

; plot_english: GLYPH = a code's top tile in the English font (a row: plane 0,
; then plane 1); its bottom tile is 16 tiles on.

plot_english:
    ldy #$0000
@row:
    lda [GLYPH],y
    pha
    and #$FF00
    sta P1
    pla
    xba
    and #$FF00
    sta P0
    iny
    iny
    jsr plot_row
    cpy #16
    bne @same_half
    tya                             ; the bottom tile
    clc
    adc #256 - 16
    tay
    lda DEST
    clc
    adc #HALF - 16
    sta DEST
@same_half:
    cpy #256 + 16
    bne @row
    rts

; plot_row: P0 and P1 shifted SHIFT pixels right, ORed into the tiles at DEST,
; DEST + 16 and DEST + 32; DEST moves to the next row. It keeps Y.

plot_row:
    stz C0
    stz C1
    ldx SHIFT
    beq @shifted
@shift:
    lsr P0
    ror C0
    lsr P1
    ror C1
    dex
    bne @shift
@shifted:
    ldx DEST
    sep #$20
    .a8
    lda P0+1
    ora f:VWF_BUFFER,x
    sta f:VWF_BUFFER,x
    lda P1+1
    ora f:VWF_BUFFER+1,x
    sta f:VWF_BUFFER+1,x
    lda P0
    ora f:VWF_BUFFER+16,x
    sta f:VWF_BUFFER+16,x
    lda P1
    ora f:VWF_BUFFER+17,x
    sta f:VWF_BUFFER+17,x
    lda C0+1
    ora f:VWF_BUFFER+32,x
    sta f:VWF_BUFFER+32,x
    lda C1+1
    ora f:VWF_BUFFER+33,x
    sta f:VWF_BUFFER+33,x
    rep #$20
    .a16
    inx
    inx
    stx DEST
    rts
