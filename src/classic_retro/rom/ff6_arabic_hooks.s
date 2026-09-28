; Final Fantasy III (USA): the Arabic hooks of the field dialogue's text engine.
;
; This file is assembled with ca65 --cpu 65816 and linked by ld65 at
; HOOK_ADDRESS ($F0:0000), the first bytes of the MiB the overlay adds to the
; ROM; the engine's code is in bank $C0, so every site jumps here with JSL and
; a hook goes back with RTL to the site's end, or with JML to the engine where
; the site's own code branched. The engine draws a letter a frame: DrawDlgText
; shifts the letter's glyph to the pen (PEN), ORs it into a cell of 16x16
; pixels and has the cell sent to the tiles' memory in the vertical blank
; (TfrDlgTextGfx), the pen moving on by the letter's width; NewLine moves the
; tiles' line pointer (VRAM_LINE) to the next line and, after the fourth, has
; the box wait for the button; NewPage moves it to the top. An Arabic message
; keeps the engine's commands, and its bytes from FIRST_CODE are glyphs of the
; overlay's font: WIDTHS holds a width a code, OFFSETS a glyph's rows in
; GLYPHS, nine variants shifted right by 0 to 8 pixels, three bytes a row,
; GLYPH_ROWS rows each. The hooks:
;
; - redirect_hook (JSL from $C0:7FDF, the end of GetDlgPtr): a message whose
;   number is in the REDIRECTS list is read from its Arabic (ARABIC_TEXT)
;   instead: TEXT_POINTER is set to it and ARABIC to 1, else to 0;
; - width_hook (JSL from $C0:8250, where UpdateDlgTextOneLine adds the next
;   word's width to the pen): in an Arabic message the line the engine is on
;   is laid out whole the first time (lay_out_line: from the right edge
;   leftwards into LINE_BUFFER, each glyph's variant of its pixel ORed in,
;   the next variant as its shadow in the second plane, a name's glyphs from
;   NAMES) and the word's width is nothing, so the engine never breaks the
;   line itself;
; - dte_hook (JSL from $C0:828F, where a letter from $80 is a pair): in an
;   Arabic message it is a glyph, drawn as a letter is;
; - draw_hook (JSL from $C0:84D0, the start of DrawDlgText): in an Arabic
;   message nothing is drawn: the line was laid out whole;
; - line_hook (JSL from $C0:851A, the start of NewLine): in an Arabic message
;   the pen goes back and the line pointer on, the box waiting for the button
;   after the fourth line, without the engine's blank cell, and the next line
;   waits to be laid out;
; - page_hook (JSL from $C0:8554, the start of NewPage): the same, the line
;   pointer to the top; at the message's end ($00) the message is over, so
;   what the engine draws next (the map's name) is English;
; - choice_hook (JSL from $C0:836D, where a choice's mark takes the cell the
;   pen is on for its cursor): in an Arabic message the cursor's cell is the
;   line's last shown (CHOICE_CELL), at the right of the choice's text, which
;   the line leaves CHOICE_WIDTH pixels for;
; - transfer_hook (JSL from $C0:8603, the start of TfrDlgTextGfx): in the
;   vertical blank, a line laid out (LINE_READY) is sent from LINE_BUFFER to
;   its tiles (LINE_CELLS cells of 64 bytes from $3800 + LINE_VRAM), then the
;   engine's own cell as before.
;
; The engine runs these with its data bank $00 and its direct page at $0000,
; its accumulator 8 bits and its index registers 16; the transfer runs in the
; vertical blank and does one DMA there. The engine's routines and labels are
; named as in the everything8215/ff6 disassembly (field/text.asm).

    .p816
    .smart -

    .export redirect_hook, width_hook, dte_hook, draw_hook, line_hook, page_hook, transfer_hook
    .export choice_hook

; The engine (bank $C0).
DTE_PAIR        = $C08466           ; UpdateDlgText: a pair's letters (AND #$7F; ASL; TAY)
DRAW_RETURN     = $C08519           ; DrawDlgText's RTS
LINE_RETURN     = $C08553           ; NewLine's RTS
PAGE_RETURN     = $C0857D           ; NewPage's RTS
TRANSFER_NONE   = $C08641           ; TfrDlgTextGfx's RTS when there is no cell to send
FONT_WIDTHS     = $C48FC0           ; the English font's widths
; Work RAM (direct page $0000).
CURRENT_CODE    = $BD               ; the byte of the message being read
PEN             = $BF               ; the pen: the next letter's left pixel
WORD_WIDTH      = $C0               ; the next word's width
VRAM_LINE       = $C1               ; 2 bytes: the line's tiles, a word address from $3800
VRAM_CELL       = $C3               ; 2 bytes: the cell to send
NEED_CELL       = $C5               ; 1: the engine's cell waits to be sent
TEXT_POINTER    = $C9               ; 3 bytes: the next byte of the message
REGION          = $CC               ; 9: the text shown whole, then the regions to clear
LETTER          = $CD               ; 2 bytes: the letter to draw
MESSAGE         = $D0               ; 2 bytes: the message's number
KEY_STATE       = $D3               ; 2: waiting for the button to be let go
CHOICES         = $0570             ; a word a choice: the cell of its cursor
DIALOG_FLAGS    = $0568
ARABIC          = $7E9D00           ; 1: the message is Arabic (any other value, as at power-on, English)
LINE_LAID       = $7E9D01           ; 1: the line the engine is on is in LINE_BUFFER
LINE_READY      = $7E9D02           ; 1: LINE_BUFFER waits to be sent (any other value: nothing)
LINE_VRAM       = $7E9D04           ; 2 bytes: the line's tiles, as VRAM_LINE
LINE_PEN        = $7E9D06           ; 2 bytes: the glyph's left pixel, from the right edge down
CODE_SCRATCH    = $7E9D08           ; 2 bytes: the glyph's code from FIRST_CODE
WIDTH_SCRATCH   = $7E9D0A           ; 2 bytes: the glyph's width
ROW_SCRATCH     = $7E9D0C           ; 2 bytes: the variant's first byte in GLYPHS
LINE_BUFFER     = $7E9800           ; 32 tile columns of 32 bytes: the line's 16 cells
; Hardware.
VMAIN           = $2115
VMADDL          = $2116
DMAP0           = $4300
BBAD0           = $4301
A1T0L           = $4302
A1B0            = $4304
DAS0L           = $4305
MDMAEN          = $420B
; This overlay's data.
WIDTHS          = $F01000           ; a width a code from FIRST_CODE; 0 where there is no glyph
OFFSETS         = $F01100           ; a word a code from FIRST_CODE: the glyph's first byte in GLYPHS
NAMES           = $F01300           ; a character's name: NAME_STRIDE bytes, its codes then $FF
REDIRECTS       = $F01500           ; entries of 2 words: the message's number, the Arabic's offset; $FFFF ends
GLYPHS          = $F10000           ; the glyphs: GLYPH_BYTES each
ARABIC_TEXT     = $F20000           ; the Arabic messages, an offset a message
; Constants.
FIRST_CODE      = $20
NAME_FIRST      = $02
NAME_LAST       = $0F
END             = $00
LINE            = $01
PAGE            = $13
NAME_END        = $FF
NAME_STRIDE     = 32
RIGHT_EDGE      = 224
LEFT_EDGE       = 4
GLYPH_ROWS      = 15
ROW_BYTES       = 3
VARIANT_BYTES   = GLYPH_ROWS * ROW_BYTES
COLUMN_BYTES    = 32                ; a tile column: 16 rows of two planes
LINE_CELLS      = 14                ; the cells the box shows
CHOICE_CELL     = 13                ; the cell of a choice's cursor: the line's last shown
CHOICE_WIDTH    = 16                ; the pixels a choice's mark takes
CELL_WORDS      = $20               ; a cell's tiles: 4 tiles of 8 words
SPACES          = $14               ; the command with a byte: that many pixels in an Arabic line
CHOICE          = $15
LINE_BYTES      = LINE_CELLS * 2 * COLUMN_BYTES
BUFFER_BYTES    = 32 * COLUMN_BYTES
VRAM_TEXT       = $3800             ; the text's tiles: four lines of $200 words

; The engine keeps the accumulator's high byte 0 in its 8-bit code (its
; ``shorta0`` is TDC then SEP #$20) and moves the whole accumulator into a
; 16-bit index with TAX; a hook that used 16 bits clears the high byte before
; going back.
.macro clear_b
    xba
    lda #0
    xba
.endmacro

    .a8
    .i16

; ---------------------------------------------------------------------------
; GetDlgPtr's end: LDA #1; STA DIALOG_FLAGS, the message read from its Arabic
; when its number is in REDIRECTS.

redirect_hook:
    lda #0
    sta f:ARABIC
    sta f:LINE_LAID
    sta f:LINE_READY
    rep #$20
    .a16
    ldx #0
@entry:
    lda f:REDIRECTS,x
    cmp #$FFFF
    beq @english                    ; the list's end
    cmp MESSAGE
    beq @found
    inx
    inx
    inx
    inx
    bra @entry
@found:
    lda f:REDIRECTS+2,x             ; the Arabic's offset
    sta TEXT_POINTER
    sep #$20
    .a8
    lda #^ARABIC_TEXT
    sta TEXT_POINTER+2
    lda #1
    sta f:ARABIC
    bra @on
@english:
    sep #$20
    .a8
@on:
    clear_b
    lda #1
    sta DIALOG_FLAGS
    rtl

; ---------------------------------------------------------------------------
; UpdateDlgTextOneLine: LDA PEN; CLC; ADC WORD_WIDTH, with the line laid out
; and no width in an Arabic message.

width_hook:
    lda f:ARABIC
    cmp #1
    bne @english
    lda f:LINE_LAID
    bne @laid
    jsr lay_out_line
    clear_b
@laid:
    lda PEN
    clc
    rtl
@english:
    lda PEN
    clc
    adc WORD_WIDTH
    rtl

; ---------------------------------------------------------------------------
; A byte read: LDA CURRENT_CODE; BMI the pair's letters, or a glyph.

dte_hook:
    lda f:ARABIC
    bne @glyph
    lda CURRENT_CODE
    bpl @letter
    pla                             ; the site's return
    pla
    pla
    lda CURRENT_CODE
    jml DTE_PAIR
@glyph:
@letter:
    lda CURRENT_CODE
    rtl

; ---------------------------------------------------------------------------
; DrawDlgText: LDX LETTER; LDA f:FONT_WIDTHS,x, or nothing in an Arabic message.

draw_hook:
    lda f:ARABIC
    cmp #1
    bne @english
    pla
    pla
    pla
    jml DRAW_RETURN
@english:
    ldx LETTER
    lda f:FONT_WIDTHS,x
    rtl

; ---------------------------------------------------------------------------
; NewLine: LDA #$FF; STA LETTER, or the Arabic line's end: the pen back, the
; line pointer on (the box waits for the button after the fourth line).

line_hook:
    lda f:ARABIC
    cmp #1
    bne @english
    pla
    pla
    pla
    lda #LEFT_EDGE
    sta PEN
    lda #0
    sta f:LINE_LAID
    rep #$20
    .a16
    lda VRAM_LINE
    sta VRAM_CELL
    and #$0600
    clc
    adc #$0200
    and #$07FF
    sta VRAM_LINE
    sep #$20
    .a8
    clear_b
    ldx VRAM_LINE
    bne @on
    lda #9
    sta REGION
    lda #2
    sta KEY_STATE
@on:
    jml LINE_RETURN
@english:
    lda #$FF
    sta LETTER
    rtl

; ---------------------------------------------------------------------------
; NewPage: LDA #$FF; STA LETTER, or the Arabic page's end: the pen back, the
; line pointer to the top, the box waiting for the button; at the message's
; end the message is over.

page_hook:
    lda f:ARABIC
    cmp #1
    bne @english
    pla
    pla
    pla
    lda #LEFT_EDGE
    sta PEN
    lda #0
    sta f:LINE_LAID
    ldx VRAM_LINE
    stx VRAM_CELL
    ldx #0
    stx VRAM_LINE
    lda #9
    sta REGION
    lda #2
    sta KEY_STATE
    lda CURRENT_CODE
    bne @on                         ; a page's end: the message goes on
    sta f:ARABIC                    ; the message's end: English from here
@on:
    jml PAGE_RETURN
@english:
    lda #$FF
    sta LETTER
    rtl

; ---------------------------------------------------------------------------
; A choice's mark: LDA VRAM_LINE; STA CHOICES,y with the accumulator 16 bits, or
; the line's last shown cell in an Arabic message.

choice_hook:
    .a16
    lda f:ARABIC
    and #$00FF
    cmp #1
    bne @english
    lda VRAM_LINE
    clc
    adc #CHOICE_CELL * CELL_WORDS
    sta CHOICES,y
    rtl
@english:
    lda VRAM_LINE
    sta CHOICES,y
    rtl
    .a8

; ---------------------------------------------------------------------------
; TfrDlgTextGfx: LDA NEED_CELL; BEQ its RTS; STZ NEED_CELL, with a line laid
; out sent first.

transfer_hook:
    lda f:LINE_READY
    cmp #1
    bne @engine
    lda #0
    sta f:LINE_READY
    stz MDMAEN
    lda #$80                        ; a word on, after the high byte
    sta VMAIN
    rep #$20
    .a16
    lda f:LINE_VRAM
    clc
    adc #VRAM_TEXT
    sta VMADDL
    sep #$20
    .a8
    clear_b
    lda #$01                        ; two registers: VMDATAL, VMDATAH
    sta DMAP0
    lda #$18
    sta BBAD0
    ldx #.loword(LINE_BUFFER)
    stx A1T0L
    lda #^LINE_BUFFER
    sta A1B0
    ldx #LINE_BYTES
    stx DAS0L
    lda #1
    sta MDMAEN
@engine:
    lda NEED_CELL
    bne @cell
    pla
    pla
    pla
    jml TRANSFER_NONE
@cell:
    stz NEED_CELL
    rtl

; ---------------------------------------------------------------------------
; The line from TEXT_POINTER laid out into LINE_BUFFER: each glyph at the pen
; from the right edge, a name's glyphs from NAMES, to the line's end (END,
; LINE or PAGE); the pen moves left by a SPACES command's byte and by
; CHOICE_WIDTH for a choice's mark; the pauses and the button waits are
; skipped. Runs with the data bank at GLYPHS' for draw_glyph.

lay_out_line:
    phb
    lda #^GLYPHS
    pha
    plb
    rep #$20
    .a16
    lda #0
    ldx #0
@clear:
    sta f:LINE_BUFFER,x
    inx
    inx
    cpx #BUFFER_BYTES
    bne @clear
    lda #RIGHT_EDGE
    sta f:LINE_PEN
    sep #$20
    .a8
    ldy #0
@code:
    lda [TEXT_POINTER],y
    beq @to_end                     ; END
    cmp #LINE
    beq @to_end
    cmp #PAGE
    beq @to_end
    bra @kind
@to_end:
    jmp @end
@kind:
    cmp #FIRST_CODE
    bcs @glyph
    cmp #NAME_FIRST
    bcc @one
    cmp #NAME_LAST+1
    bcc @name
    cmp #SPACES
    beq @spaces
    cmp #CHOICE
    beq @choice
    cmp #$11                        ; the commands with a byte: $11, $16, $1C-$1F
    beq @two
    cmp #$16
    beq @two
    cmp #$1C
    bcs @two
@one:
    iny
    jmp @code
@two:
    iny
    iny
    jmp @code
@spaces:
    iny
    lda [TEXT_POINTER],y            ; the byte: pixels
    rep #$20
    .a16
    and #$00FF
    sta f:WIDTH_SCRATCH
    lda f:LINE_PEN
    sec
    sbc f:WIDTH_SCRATCH
    sta f:LINE_PEN
    sep #$20
    .a8
    iny
    jmp @code
@choice:
    rep #$20
    .a16
    lda f:LINE_PEN
    sec
    sbc #CHOICE_WIDTH
    sta f:LINE_PEN
    sep #$20
    .a8
    iny
    jmp @code
@glyph:
    phy
    jsr draw_glyph
    ply
    iny
    jmp @code
@name:
    sec
    sbc #NAME_FIRST
    rep #$20
    .a16
    and #$00FF
    asl
    asl
    asl
    asl
    asl                             ; the number times NAME_STRIDE
    tax
    sep #$20
    .a8
    phy
@letter:
    lda f:NAMES,x
    cmp #NAME_END
    beq @named
    phx
    jsr draw_glyph
    plx
    inx
    bra @letter
@named:
    ply
    iny
    jmp @code
@end:
    rep #$20
    .a16
    lda VRAM_LINE
    sta f:LINE_VRAM
    sep #$20
    .a8
    lda #1
    sta f:LINE_LAID
    sta f:LINE_READY
    plb
    rts

; ---------------------------------------------------------------------------
; The glyph of code A drawn at the pen, which moves left by its width: its
; variant of the pen's pixel in its tile ORed into the first plane of three
; tile columns, the next variant into the second as its shadow. A glyph the
; font lacks, or one that would pass the left edge, draws nothing. The data
; bank is GLYPHS'.

draw_glyph:
    rep #$20
    .a16
    and #$00FF
    sec
    sbc #FIRST_CODE
    sta f:CODE_SCRATCH
    tax
    sep #$20
    .a8
    lda f:WIDTHS,x
    beq @none
    rep #$20
    .a16
    and #$00FF
    sta f:WIDTH_SCRATCH
    lda f:LINE_PEN
    sec
    sbc f:WIDTH_SCRATCH
    bcc @none
    cmp #LEFT_EDGE
    bcc @none
    sta f:LINE_PEN
    and #$0007
    asl
    tax
    lda f:SHIFT_OFFSETS,x           ; the variant: the pixel in its tile times VARIANT_BYTES
    sta f:ROW_SCRATCH
    lda f:CODE_SCRATCH
    asl
    tax
    lda f:OFFSETS,x
    clc
    adc f:ROW_SCRATCH
    tay                             ; the variant's rows in GLYPHS
    lda f:LINE_PEN
    and #$FFF8
    asl
    asl
    tax                             ; the tile column's first byte: the pixel's tile times COLUMN_BYTES
    sep #$20
    .a8
    bra @rows
@none:
    sep #$20
    .a8
    rts
@rows:
    .repeat GLYPH_ROWS, row
    lda a:row*ROW_BYTES,y
    ora f:LINE_BUFFER+row*2,x
    sta f:LINE_BUFFER+row*2,x
    lda a:row*ROW_BYTES+1,y
    ora f:LINE_BUFFER+COLUMN_BYTES+row*2,x
    sta f:LINE_BUFFER+COLUMN_BYTES+row*2,x
    lda a:row*ROW_BYTES+2,y
    ora f:LINE_BUFFER+2*COLUMN_BYTES+row*2,x
    sta f:LINE_BUFFER+2*COLUMN_BYTES+row*2,x
    lda a:VARIANT_BYTES+row*ROW_BYTES,y
    ora f:LINE_BUFFER+1+row*2,x
    sta f:LINE_BUFFER+1+row*2,x
    lda a:VARIANT_BYTES+row*ROW_BYTES+1,y
    ora f:LINE_BUFFER+COLUMN_BYTES+1+row*2,x
    sta f:LINE_BUFFER+COLUMN_BYTES+1+row*2,x
    lda a:VARIANT_BYTES+row*ROW_BYTES+2,y
    ora f:LINE_BUFFER+2*COLUMN_BYTES+1+row*2,x
    sta f:LINE_BUFFER+2*COLUMN_BYTES+1+row*2,x
    .endrep
    rts

; A variant's first byte in its glyph, by the pixel in its tile (0-7).
SHIFT_OFFSETS:
    .word 0, VARIANT_BYTES, 2*VARIANT_BYTES, 3*VARIANT_BYTES, 4*VARIANT_BYTES
    .word 5*VARIANT_BYTES, 6*VARIANT_BYTES, 7*VARIANT_BYTES
