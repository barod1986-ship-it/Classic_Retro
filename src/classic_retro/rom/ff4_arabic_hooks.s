; Final Fantasy II (USA): the Arabic hooks of the field dialogue's text engine.
;
; This file is assembled with ca65 --cpu 65816 and linked by ld65 at
; HOOK_ADDRESS ($20:8000), the first bytes of the half the overlay adds to the
; ROM; the engine's code is in bank $00, so every site jumps here with JML and
; the hooks jump back with JML. The engine decodes a message into BUFFER, four
; rows of ROW codes, a code a tile of the dialogue font, and sends the rows to
; the tilemap in the vertical blank with a blank row of tiles above each. An
; Arabic message keeps the engine's commands, and its glyphs are the letters'
; codes and the pair codes: a pair code from TOP_FIRST on names the top half of
; the next glyph, any other code a glyph's bottom half, the tile the message
; writes. The Arabic tiles of the letters' codes are in the tiles' memory only
; while an Arabic page shows (LETTER_TILES over the font's own, LATIN_TILES,
; from the ROM). The hooks:
;
; - parse_hook (JML from $00:B21F, the start of DecodeDlgText): clears the
;   tops of the page (TOP_BUFFER); a message whose bank and offset are in the
;   REDIRECTS list is read from its Arabic (ARABIC_TEXT) instead: BANK is set
;   to ARABIC_BANK and SOURCE to the Arabic's offset. A later page of an
;   Arabic message finds BANK already set;
; - byte_hook (JML from $00:B2BE, the start of GetByte): in an Arabic message
;   the next byte comes from ARABIC_TEXT;
; - dte_hook (JML from $00:B2DC, the start of DecodeDTE): in an Arabic message
;   a pair code is a glyph's half: a top is kept for the bottom that follows,
;   a bottom is stored as a letter is;
; - store_hook (JML from $00:B280, where a letter is stored): in an Arabic
;   message the top kept goes to TOP_BUFFER with the code;
; - name_hook (JML from $00:B31C, in the name command): in an Arabic message
;   a character's name comes from NAMES, in the message's own codes, in
;   place of the name the player gave;
; - page_hook (JML from $00:B2A4, where DecodeDlgText marks a page decoded):
;   an Arabic page's rows are laid out for the tilemap while the game runs on:
;   each row mirrored (MIRROR_ROW: the first code at the right), each run of
;   the game's own codes (the icons and the digits: ISLAND_FIRST to
;   ISLAND_LAST, DIGIT_FIRST to DIGIT_LAST) turned back to read left to right,
;   with the tops (TOP_ROW) of the same codes, into MIRROR_PAGE and TOP_PAGE;
; - transfer_hook (JML from $00:B55F, the start of TfrDlgText, whose RTS stays
;   for the frames with nothing to send): before an Arabic page the letters'
;   tiles are replaced by LETTER_TILES and before an English one put back from
;   LATIN_TILES; an Arabic page's rows are sent from MIRROR_PAGE, with their
;   tops from TOP_PAGE in the row above.
;
; The engine runs these with its data bank $00 and its direct page at $0600,
; its accumulator 8 bits and its index registers 16; the transfer runs in the
; vertical blank with the engine's own scratch bytes $11-$15, and does no more
; work there than the engine's own transfer: the rows were laid out when the
; page was decoded. The engine's routines and labels are named as in the
; everything8215/ff4 disassembly (field/window.asm).

    .p816
    .smart -

    .export parse_hook, byte_hook, dte_hook, store_hook, name_hook, page_hook, transfer_hook

; The engine (bank $00).
DECODE_LOOP     = $00B224           ; DecodeDlgText: the next byte
STORE_CONTINUE  = $00B288           ; after a code is stored: the source on, the row check
DTE_LETTERS     = $00B2E1           ; DecodeDTE after SEC; SBC #$80; ASL; TAX
BYTE_MAP        = $00B2C5           ; GetByte: LDA f:MapDlg,x
BYTE_EVENT      = $00B2CC           ; GetByte: the event banks
BYTE_RETURN     = $00B2DB           ; GetByte's RTS
NAME_CHECK      = $00B321           ; the name command after LDA $1500,x; CMP #$FF
PAGE_CONTINUE   = $00B2A8           ; DecodeDlgText after LDA #1; STA $ED: the blank row filled
TRANSFER_NONE   = $00B563           ; TfrDlgText's RTS when there is nothing to send
TRANSFER_ENGLISH = $00B564          ; TfrDlgText after LDA $ED; BNE
TRANSFER_DONE   = $00B5E7           ; TfrDlgText's end: INC $BA; RTS
; Work RAM.
BUFFER          = $0774             ; the message decoded: four rows of ROW codes
TOP_ROW         = $0844             ; the engine's blank row: a row's tops, mirrored
MIRROR_ROW      = $085E             ; a row mirrored
SOURCE          = $0772             ; 2 bytes: the next byte of the text, an offset in its bank
NAMES_RAM       = $1500             ; the names the player gave, 6 letters each
BANK            = $DD               ; the text's bank: 0-2 the English, ARABIC_BANK the Arabic
POSITION        = $3D               ; 2 bytes: the next code of BUFFER
PAGE            = $BA               ; which rows of the tilemap the page goes to
NEED_TRANSFER   = $ED               ; 1: BUFFER waits to be sent
VRAM_ADDRESS    = $12               ; 2 bytes: the tilemap row (the transfer's scratch)
TEXT_POINTER    = $14               ; 2 bytes: the row of BUFFER
ROWS_LEFT       = $11
TOP_BUFFER      = $7ED000           ; a top a code of BUFFER, $FF where the row above is blank
PENDING_TOP     = $7ED0D0           ; the top kept for the next bottom
ISLAND_SCRATCH  = $7ED0D1           ; turn_islands: the run's end
SOURCE_END      = $7ED0D2           ; 2 bytes: page_hook: the row's last code
DEST            = $7ED0D4           ; 2 bytes: page_hook: the row's first byte in the page buffers
ROW_COUNT       = $7ED0D6           ; page_hook: rows left
MIRROR_PAGE     = $7ED100           ; the page's rows mirrored, ROW bytes each
TOP_PAGE        = $7ED180           ; their tops
TOP_OF_CODE     = TOP_BUFFER - BUFFER ; TOP_BUFFER indexed as BUFFER is
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
TOP_FIRST       = $208400           ; a byte: the first code that is a top half
REDIRECTS       = $208500           ; entries of 5 bytes: bank, offset, the Arabic's offset; $FF ends
LETTER_TILES    = $208800           ; the Arabic tiles of the letters' codes ($42-$75)
NAMES           = $208C00           ; a character's name: NAME_STRIDE bytes, its codes then $FF
ARABIC_TEXT     = $218000           ; the Arabic messages, an offset a message
LATIN_TILES     = $0AF420           ; the font's own tiles of the letters' codes
; Constants.
ARABIC_BANK     = 3
ROW             = 26
ROWS            = 4
PAGE_CODES      = ROW * ROWS
ISLAND_FIRST    = $21               ; the icons
ISLAND_LAST     = $41
DIGIT_FIRST     = $79               ; the icons of items, then the digits
DIGIT_LAST      = $89
BLANK           = $FF
REDIRECT_ENTRY  = 5
NAME_STRIDE     = 48                ; 8 bytes for each of the 6 letters the engine copies
LETTER_FIRST    = $42
LETTER_COUNT    = $34
LETTER_TILE_BYTES = LETTER_COUNT * 16
LETTERS_VRAM    = $2000 + LETTER_FIRST * 8 ; the word address of the letters' tiles

    .a8
    .i16

; ---------------------------------------------------------------------------
; DecodeDlgText: LDY #0; STY POSITION, then the tops cleared and the message
; redirected when it is translated.

parse_hook:
    ldy #0
    sty POSITION
    lda #BLANK
    sta f:PENDING_TOP
    ldx #0
@clear:
    sta f:TOP_BUFFER,x
    inx
    cpx #PAGE_CODES
    bne @clear
    lda BANK
    cmp #ARABIC_BANK
    beq @done                       ; a later page of an Arabic message
    ldx #0
@entry:
    lda f:REDIRECTS,x
    cmp #$FF
    beq @done                       ; the list's end: an English message
    cmp BANK
    bne @next
    rep #$20
    .a16
    lda f:REDIRECTS+1,x
    cmp SOURCE
    bne @other
    lda f:REDIRECTS+3,x             ; the Arabic's offset
    sta SOURCE
    sep #$20
    .a8
    lda #ARABIC_BANK
    sta BANK
    bra @done
@other:
    sep #$20
    .a8
@next:
    inx
    inx
    inx
    inx
    inx
    bra @entry
@done:
    jml DECODE_LOOP

; ---------------------------------------------------------------------------
; GetByte: LDX SOURCE; LDA BANK; BNE the event banks, with the Arabic bank.

byte_hook:
    ldx SOURCE
    lda BANK
    cmp #ARABIC_BANK
    bne @english
    lda f:ARABIC_TEXT,x
    jml BYTE_RETURN
@english:
    lda BANK
    bne @event
    jml BYTE_MAP
@event:
    jml BYTE_EVENT

; ---------------------------------------------------------------------------
; DecodeDTE: SEC; SBC #$80; ASL; TAX, with A the pair code and Y the position,
; or an Arabic glyph's half.

dte_hook:
    pha
    lda BANK
    cmp #ARABIC_BANK
    beq @glyph
    pla
    sec
    sbc #$80
    asl
    tax
    jml DTE_LETTERS
@glyph:
    pla
    cmp f:TOP_FIRST
    bcc store_hook                  ; a bottom half: stored as a letter is
    sta f:PENDING_TOP               ; a top half: kept for the bottom that follows
    jml STORE_CONTINUE

; ---------------------------------------------------------------------------
; A letter stored: STA BUFFER,y; LDY POSITION; INY; STY POSITION, with the top
; kept for it in an Arabic message.

store_hook:
    sta BUFFER,y
    lda BANK
    cmp #ARABIC_BANK
    bne @on
    tyx
    lda f:PENDING_TOP
    sta f:TOP_BUFFER,x
    lda #BLANK
    sta f:PENDING_TOP
@on:
    ldy POSITION
    iny
    sty POSITION
    jml STORE_CONTINUE

; ---------------------------------------------------------------------------
; The name command: LDA NAMES_RAM,x; CMP #$FF, with X the name's number times
; 6 and Y the position; in an Arabic message the name comes from NAMES (its
; entry at the number times NAME_STRIDE), its tops kept as the message's are,
; and the command goes on to its end (STY POSITION; JMP STORE_CONTINUE).

name_hook:
    lda BANK
    cmp #ARABIC_BANK
    beq @arabic
    lda NAMES_RAM,x
    cmp #BLANK
    jml NAME_CHECK
@arabic:
    rep #$20
    .a16
    txa
    asl
    asl
    asl                             ; the number times 48
    tax
    sep #$20
    .a8
@copy:
    lda f:NAMES,x
    cmp #BLANK
    beq @end
    cmp f:TOP_FIRST
    bcc @cell
    sta f:PENDING_TOP
    inx
    bra @copy
@cell:
    sta BUFFER,y
    phx
    tyx
    lda f:PENDING_TOP
    sta f:TOP_BUFFER,x
    lda #BLANK
    sta f:PENDING_TOP
    plx
    iny
    inx
    bra @copy
@end:
    sty POSITION
    jml STORE_CONTINUE

; ---------------------------------------------------------------------------
; DecodeDlgText, a page decoded: LDA #1; STA NEED_TRANSFER, then an Arabic
; page's rows laid out for the tilemap.

page_hook:
    lda #1
    sta NEED_TRANSFER
    lda BANK
    cmp #ARABIC_BANK
    beq @arabic
    jml PAGE_CONTINUE
@arabic:
    rep #$20
    .a16
    lda #BUFFER + ROW - 1
    sta f:SOURCE_END
    lda #0
    sta f:DEST
    sep #$20
    .a8
    lda #ROWS
    sta f:ROW_COUNT
@row:
    rep #$20
    .a16
    lda f:SOURCE_END
    tax                             ; the row's last code
    sep #$20
    .a8
    ldy #0
@mirror:
    lda a:0,x
    sta MIRROR_ROW,y
    lda f:TOP_OF_CODE,x             ; the top of the same code
    sta TOP_ROW,y
    dex
    iny
    cpy #ROW
    bne @mirror
    jsr turn_islands
    rep #$20
    .a16
    lda f:DEST
    tax
    sep #$20
    .a8
    ldy #0
@copy:
    lda MIRROR_ROW,y
    sta f:MIRROR_PAGE,x
    lda TOP_ROW,y
    sta f:TOP_PAGE,x
    inx
    iny
    cpy #ROW
    bne @copy
    rep #$20
    .a16
    lda f:DEST
    clc
    adc #ROW
    sta f:DEST
    lda f:SOURCE_END
    clc
    adc #ROW
    sta f:SOURCE_END
    sep #$20
    .a8
    lda f:ROW_COUNT
    dec
    sta f:ROW_COUNT
    bne @row
    jml PAGE_CONTINUE

; ---------------------------------------------------------------------------
; TfrDlgText: LDA NEED_TRANSFER; BNE send; RTS, the letters' tiles set for the
; page and the Arabic rows sent from the page buffers.

transfer_hook:
    lda NEED_TRANSFER
    bne @send
    jml TRANSFER_NONE
@send:
    lda BANK
    cmp #ARABIC_BANK
    beq @arabic
    ldx #.loword(LATIN_TILES)
    lda #^LATIN_TILES
    jsr load_letter_tiles
    jml TRANSFER_ENGLISH
@arabic:
    ldx #.loword(LETTER_TILES)
    lda #^LETTER_TILES
    jsr load_letter_tiles
    stz NEED_TRANSFER
    lda PAGE                        ; the tilemap row: $2C03 + (PAGE & 3) * $100
    and #$03
    clc
    adc #$2C
    sta VRAM_ADDRESS+1
    lda #$03
    sta VRAM_ADDRESS
    ldx #0
    stx TEXT_POINTER                ; the row's first byte in the page buffers
    stz VMAIN                       ; a word on, after the low byte
    stz MDMAEN                      ; the engine's InitDMA: a byte at a time to VMDATAL
    lda #$18
    sta BBAD0
    lda #^TOP_PAGE
    sta A1B0
    stz DMAP0
    lda #ROWS
    sta ROWS_LEFT
@row:
    rep #$20
    .a16
    lda TEXT_POINTER
    clc
    adc #.loword(TOP_PAGE)
    sta A1T0L
    sep #$20
    .a8
    ldx VRAM_ADDRESS
    stx VMADDL
    ldx #ROW
    stx DAS0L
    lda #1
    sta MDMAEN
    jsr next_tilemap_row
    stz MDMAEN
    rep #$20
    .a16
    lda TEXT_POINTER
    clc
    adc #.loword(MIRROR_PAGE)
    sta A1T0L
    sep #$20
    .a8
    ldx VRAM_ADDRESS
    stx VMADDL
    ldx #ROW
    stx DAS0L
    lda #1
    sta MDMAEN
    jsr next_tilemap_row
    lda VRAM_ADDRESS+1
    cmp #$30
    bne @keep
    lda #$2C
    sta VRAM_ADDRESS+1
@keep:
    rep #$20
    .a16
    lda TEXT_POINTER
    clc
    adc #ROW
    sta TEXT_POINTER
    sep #$20
    .a8
    dec ROWS_LEFT
    bne @row
    jml TRANSFER_DONE

; The letters' tiles from the source in X (its low word) and A (its bank), a
; word at a time into the tiles' memory.
load_letter_tiles:
    stz MDMAEN
    stx A1T0L
    sta A1B0
    lda #$80
    sta VMAIN
    ldx #LETTERS_VRAM
    stx VMADDL
    lda #$01
    sta DMAP0                       ; two registers: VMDATAL, VMDATAH
    lda #$18
    sta BBAD0
    ldx #LETTER_TILE_BYTES
    stx DAS0L
    lda #1
    sta MDMAEN
    rts

; The tilemap row after this one: $20 words on.
next_tilemap_row:
    rep #$20
    .a16
    lda VRAM_ADDRESS
    clc
    adc #$0020
    sta VRAM_ADDRESS
    sep #$20
    .a8
    rts

; Each run of the game's own codes in MIRROR_ROW reversed, so the icons and
; the digits read left to right in the mirrored row. Their tops are blank, so
; TOP_ROW stays as it is. Runs in the engine's context with X and Y free.
turn_islands:
    ldx #0
@scan:
    cpx #ROW
    bcs @done
    lda MIRROR_ROW,x
    jsr is_island
    bcc @next
    txy
@extend:
    iny
    cpy #ROW
    bcs @run
    lda MIRROR_ROW,y
    jsr is_island
    bcs @extend
@run:
    phy                             ; the code after the run
    dey
@swap:
    tya
    sta f:ISLAND_SCRATCH            ; is X before Y?
    txa
    cmp f:ISLAND_SCRATCH
    bcs @turned
    lda MIRROR_ROW,x
    pha
    lda MIRROR_ROW,y
    sta MIRROR_ROW,x
    pla
    sta MIRROR_ROW,y
    inx
    dey
    bra @swap
@turned:
    plx
    bra @scan
@next:
    inx
    bra @scan
@done:
    rts

; Carry set when A is a code the game shows left to right.
is_island:
    cmp #ISLAND_FIRST
    bcc @no
    cmp #ISLAND_LAST+1
    bcc @yes
    cmp #DIGIT_FIRST
    bcc @no
    cmp #DIGIT_LAST+1
    bcs @no
@yes:
    sec
    rts
@no:
    clc
    rts
