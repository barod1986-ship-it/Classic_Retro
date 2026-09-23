@ Golden Sun (USA/Europe, AGSE01) Arabic right-to-left dialogue hooks.
@
@ Assembled once for ARMv4T Thumb at HOOK_CODE and stored as bytes in
@ golden_sun_arabic.py; CI re-assembles this file and compares the bytes.
@ HOOK_CODE lies in the zero padding before the 0x08077000 code section, so
@ the game reaches every hook with a plain BL.
@
@ The game's text bank stays untouched: translated strings live in
@ ARABIC_STORE with their own Huffman trees (codes up to 0x1FF), and the
@ dialogue decoder is pointed at them when such a string is opened.
@
@ A message is right-to-left when its first code is RTL_MARKER (0x0B, a
@ command the game never uses and skips). While such a message is decoded
@ into the 512-entry text ring, every name inserted at runtime is reversed;
@ at the end every glyph gets the RTL_TAG bit. Text is stored in paint order:
@ the first glyph of a line is its rightmost one. The typewriter still
@ advances left to right; each glyph pair is drawn at the mirrored position
@
@     draw_x = window_width * 8 - RTL_MARGIN - cursor_x - pair_width
@
@ from RTL_FONT: 512 advances, then 512 glyphs of 16 rows x 16 two-bit
@ pixels (1 ink, 2 shadow), indexed by code & 0x1FF (Arabic 0x100 + slot,
@ Latin copies 0x21..0x8F, space 0x20).

    .syntax unified
    .cpu arm7tdmi
    .thumb

    .equ HOOK_CODE,          0x08074000
    .equ ARABIC_STORE,       0x08810000
    .equ ARABIC_INDEX,       ARABIC_STORE + 16
    .equ STORE_INDEX_END,    0xFFFF
    .equ RTL_FONT,           0x08800000
    .equ RTL_WIDTHS,         RTL_FONT
    .equ RTL_BITMAPS,        RTL_FONT + 0x200
    .equ RTL_MARKER,         0x0B
    .equ RTL_TAG,            0x200
    .equ CODE_MASK,          0x1FF
    .equ RING_MASK,          0x1FF
    .equ PAIR_WIDTH,         15
    .equ RTL_MARGIN,         12

    .equ TEXT_STATE_PTR,     0x03001E8C
    .equ STATE_NO_SHADOW,    0xEA4
    .equ STATE_TEXT_COLOUR,  0xEAE
    .equ LATIN_FONT,         0x08032224

    .equ STRING_INIT,        0x08019BAC
    .equ DECODER_TREES,      0x13C
    .equ DECODE_CONTINUE,    0x08018614
    .equ FREE_DECODER,       0x08002DD8
    .equ NAME_COPY,          0x08017E88
    .equ PAIR_CONTINUE,      0x08016E3E
    .equ LATIN_RENDER,       0x080178B0
    .equ MEASURE_CONTINUE,   0x080188B0
    .equ MEASURE_ALT_RETURN, 0x08018ACC
    .equ MEASURE_ALT_STATE,  0xEAC

    .global hook_init, hook_expand, hook_tag, hook_pair, hook_render
    .global hook_measure, hook_measure_alt, rtl_font_pointer

    .text
    .align 2

@ Decoder start (replaces "bl Func_19bac" at 0x080180BE). In: r0 = decoder
@ state {previous code, data, bit buffer}, r1 = string index, r9 = the RAM
@ copy of the ARM decoder (DECODER_TREES: its tree table literal). The game
@ treats r4 as scratch, so the state and index are kept in r5 and r6.
    .thumb_func
hook_init:
    push  {r5, r6, lr}
    movs  r5, r0
    movs  r6, r1
    bl    .Linit_game
    ldr   r0, =ARABIC_INDEX
    ldr   r3, =STORE_INDEX_END
.Linit_search:
    ldrh  r1, [r0]
    cmp   r1, r6
    beq   .Linit_found
    cmp   r1, r3
    beq   .Linit_done
    adds  r0, #8
    b     .Linit_search
.Linit_found:
    ldr   r1, [r0, #4]
    movs  r2, #0
    str   r2, [r5]
    str   r1, [r5, #4]
    movs  r2, #1
    str   r2, [r5, #8]
    ldr   r1, =ARABIC_STORE
    mov   r2, r9
    ldr   r3, =DECODER_TREES
    str   r1, [r2, r3]
.Linit_done:
    pop   {r5, r6}
    pop   {r0}
    bx    r0
.Linit_game:
    ldr   r2, =STRING_INIT + 1
    bx    r2

@ Z set when the message being decoded (ring index [sp + 0x20 + depth] of
@ the decoder frame) starts with the right-to-left marker. r8 = ring.
    .macro MESSAGE_IS_RTL rs, rt, depth
    ldr   \rs, [sp, #(0x20 + \depth)]
    lsls  \rs, \rs, #1
    add   \rs, r8
    ldrh  \rs, [\rs]
    cmp   \rs, #RTL_MARKER
    .endm

@ Decoder, after a name/item was copied into the ring (replaces
@ "adds r6, r0, #0; b 0x08018614" at 0x0801851A with a BL).
@ In: r0 = ring index after the name, r6 = index of its first code.
    .thumb_func
hook_expand:
    MESSAGE_IS_RTL r5, r5, 0
    bne   .Lexpand_done
    push  {r0, r6, r7}
    ldr   r2, =RING_MASK
    subs  r4, r0, r6
    ands  r4, r2
    lsrs  r4, r4, #1
    beq   .Lexpand_pop
    subs  r1, r0, #1
    ands  r1, r2
    movs  r3, r6
.Lexpand_swap:
    lsls  r5, r3, #1
    add   r5, r8
    lsls  r0, r1, #1
    add   r0, r8
    ldrh  r6, [r5]
    ldrh  r7, [r0]
    strh  r7, [r5]
    strh  r6, [r0]
    adds  r3, #1
    ands  r3, r2
    subs  r1, #1
    ands  r1, r2
    subs  r4, #1
    bne   .Lexpand_swap
.Lexpand_pop:
    pop   {r0, r6, r7}
.Lexpand_done:
    adds  r6, r0, #0
    ldr   r0, =DECODE_CONTINUE + 1
    bx    r0

@ Decoder end (replaces "bl Func_2dd8" at 0x0801864A). In: r6 = ring index
@ of the final 0, r8 = ring, r0 = 0x32 (argument of the replaced call).
    .thumb_func
hook_tag:
    push  {r0, r4-r7, lr}
    MESSAGE_IS_RTL r1, r1, 24
    bne   .Ltag_done
    ldr   r1, [sp, #(0x20 + 24)]
    ldr   r3, =RING_MASK
    ldr   r5, =RTL_TAG
.Ltag_next:
    adds  r1, #1
    ands  r1, r3
    cmp   r1, r6
    beq   .Ltag_done
    lsls  r2, r1, #1
    add   r2, r8
    ldrh  r4, [r2]
    cmp   r4, #0x20
    blo   .Ltag_control
    orrs  r4, r5
    strh  r4, [r2]
    b     .Ltag_next
.Ltag_control:
    @ Commands whose argument follows in the ring: 08 09 0A 0F 1D.
    cmp   r4, #0x08
    blo   .Ltag_next
    cmp   r4, #0x0A
    bls   .Ltag_skip
    cmp   r4, #0x0F
    beq   .Ltag_skip
    cmp   r4, #0x1D
    bne   .Ltag_next
.Ltag_skip:
    adds  r1, #1
    ands  r1, r3
    cmp   r1, r6
    bne   .Ltag_next
.Ltag_done:
    pop   {r0}
    bl    .Lfree_decoder
    pop   {r4-r7}
    pop   {r0}
    bx    r0
.Lfree_decoder:
    ldr   r1, =FREE_DECODER + 1
    bx    r1

@ Typewriter, before a glyph is paired (replaces "ldr r0, [r6]; ldrh r2,
@ [r0, #22]" at 0x08016DFE with a BL). In: r7 = code, r4 = next ring entry,
@ r5 = cursor x, ip = cursor y, r6 = printer. Left-to-right glyphs return to
@ the game's pairing (which packs code | next << 8); right-to-left glyphs go
@ straight to the draw call with r7 = code | next << 16 | bit 31 and r5 =
@ mirrored x.
    .thumb_func
hook_pair:
    ldr   r0, [r6]
    ldr   r3, =RTL_TAG
    tst   r7, r3
    bne   .Lpair_rtl
    ldrh  r2, [r0, #22]
    bx    lr
.Lpair_rtl:
    ldr   r3, =CODE_MASK
    ands  r7, r3
    cmp   r7, #0x20
    beq   .Lpair_draw
    ldr   r1, =RTL_WIDTHS
    ldrb  r2, [r1, r7]
    ldr   r3, =RTL_TAG
    tst   r4, r3
    beq   .Lpair_place
    ldr   r3, =CODE_MASK
    ands  r4, r3
    cmp   r4, #0x20
    beq   .Lpair_place
    ldrb  r3, [r1, r4]
    adds  r3, r2
    cmp   r3, #PAIR_WIDTH
    bhi   .Lpair_place
    movs  r2, r3
    lsls  r4, r4, #16
    orrs  r7, r4
    ldrh  r3, [r6, #18]
    adds  r3, #1
    ldr   r1, =RING_MASK
    ands  r3, r1
    strh  r3, [r6, #18]
.Lpair_place:
    ldrh  r3, [r0, #8]
    lsls  r3, r3, #3
    subs  r3, #RTL_MARGIN
    subs  r3, r5
    subs  r3, r2
    bpl   .Lpair_x
    movs  r3, #0
.Lpair_x:
    movs  r5, r3
    movs  r3, #1
    lsls  r3, r3, #31
    orrs  r7, r3
.Lpair_draw:
    ldr   r3, =PAIR_CONTINUE + 1
    bx    r3

@ Sprite glyph renderer (replaces "bl Func_178b0" at 0x08018DCA).
@ In: r0 = code or pair (bit 31: right-to-left pair from hook_pair),
@ r1 = 16x16 4bpp tile buffer. Out: r0 = width.
    .thumb_func
hook_render:
    cmp   r0, #0
    blt   .Lrender_rtl
    ldr   r2, =LATIN_RENDER + 1
    bx    r2
.Lrender_rtl:
    push  {r4-r7, lr}
    mov   r4, r8
    mov   r5, r9
    mov   r6, r10
    mov   r7, r11
    push  {r4-r7}
    mov   r8, r1
    lsls  r4, r0, #23
    lsrs  r4, r4, #23
    mov   r11, r4
    lsrs  r0, r0, #16
    ldr   r3, =CODE_MASK
    ands  r0, r3
    mov   ip, r0
    @ Clear the four tiles.
    movs  r2, #0
    movs  r3, #32
.Lrender_clear:
    stmia r1!, {r2}
    subs  r3, #1
    bne   .Lrender_clear
    @ Colours: ink [state + 0xEAE] with shadow 1, or ink 8 without shadow.
    ldr   r3, =TEXT_STATE_PTR
    ldr   r3, [r3]
    ldr   r2, =STATE_NO_SHADOW
    ldrb  r2, [r3, r2]
    cmp   r2, #0
    beq   .Lrender_shadow
    movs  r2, #8
    mov   r9, r2
    movs  r2, #0
    mov   r10, r2
    b     .Lrender_glyphs
.Lrender_shadow:
    ldr   r2, =STATE_TEXT_COLOUR
    ldrh  r2, [r3, r2]
    mov   r9, r2
    movs  r2, #1
    mov   r10, r2
.Lrender_glyphs:
    @ The second (left) glyph at x 0, then the first at x = its width.
    ldr   r5, =RTL_WIDTHS
    mov   r0, ip
    movs  r1, #0
    cmp   r0, #0
    beq   .Lrender_first
    ldrb  r1, [r5, r0]
    push  {r1}
    movs  r1, #0
    bl    .Ldraw_glyph
    pop   {r1}
.Lrender_first:
    mov   r0, r11
    push  {r1}
    bl    .Ldraw_glyph
    pop   {r1}
    ldr   r5, =RTL_WIDTHS
    mov   r0, r11
    ldrb  r0, [r5, r0]
    adds  r0, r1
    pop   {r4-r7}
    mov   r8, r4
    mov   r9, r5
    mov   r10, r6
    mov   r11, r7
    pop   {r4-r7}
    pop   {r1}
    bx    r1

@ Draw glyph r0 at x r1 into the tile buffer r8 (ink r9, shadow r10).
.Ldraw_glyph:
    ldr   r2, =RTL_BITMAPS
    lsls  r0, r0, #6
    adds  r2, r0
    movs  r4, #0
.Ldraw_row:
    ldmia r2!, {r5}
    movs  r6, r1
.Ldraw_pixel:
    cmp   r5, #0
    beq   .Ldraw_next_row
    movs  r7, #3
    ands  r7, r5
    lsrs  r5, r5, #2
    cmp   r7, #0
    beq   .Ldraw_next_pixel
    cmp   r6, #16
    bhs   .Ldraw_next_row
    cmp   r7, #1
    bne   .Ldraw_shadow_pixel
    mov   r7, r9
    b     .Ldraw_put
.Ldraw_shadow_pixel:
    mov   r7, r10
    cmp   r7, #0
    beq   .Ldraw_next_pixel
.Ldraw_put:
    @ byte = ((y >> 3) * 2 + (x >> 3)) * 32 + (y & 7) * 4 + (x & 7) / 2
    lsrs  r0, r4, #3
    lsls  r0, r0, #1
    lsrs  r3, r6, #3
    adds  r0, r3
    lsls  r0, r0, #5
    lsls  r3, r4, #29
    lsrs  r3, r3, #27
    adds  r0, r3
    lsls  r3, r6, #29
    lsrs  r3, r3, #30
    adds  r0, r3
    add   r0, r8
    ldrb  r3, [r0]
    push  {r1}
    lsrs  r1, r6, #1
    bcs   .Ldraw_high
    movs  r1, #0xF0
    ands  r3, r1
    orrs  r3, r7
    b     .Ldraw_store
.Ldraw_high:
    movs  r1, #0x0F
    ands  r3, r1
    lsls  r7, r7, #4
    orrs  r3, r7
.Ldraw_store:
    pop   {r1}
    strb  r3, [r0]
.Ldraw_next_pixel:
    adds  r6, #1
    b     .Ldraw_pixel
.Ldraw_next_row:
    adds  r4, #1
    cmp   r4, #16
    blo   .Ldraw_row
    bx    lr

@ Page measure, glyph width (replaces "ldr r3, =font; subs r2, #32; lsls r2,
@ #5; ldrh r2, [r3, r2]" at 0x080188A8 with "ldr r3, [pc]; bx r3; .word").
@ lr holds the caller's jump table, so this hook is entered without BL.
    .align 2
    .thumb_func
hook_measure:
    ldr   r3, =RTL_TAG
    tst   r2, r3
    bne   .Lmeasure_rtl
    subs  r2, #32
    lsls  r2, r2, #5
    ldr   r3, =LATIN_FONT
    ldrh  r2, [r3, r2]
    b     .Lmeasure_done
.Lmeasure_rtl:
    ldr   r3, =CODE_MASK
    ands  r2, r3
    ldr   r3, =RTL_WIDTHS
    ldrb  r2, [r3, r2]
.Lmeasure_done:
    ldr   r3, =MEASURE_CONTINUE + 1
    bx    r3

@ Alternative page measure (replaces 0x08018AC4..0x08018ACB: the width lookup
@ and "ldr r3, =0xEAC"); lr holds a pointer argument, r3 must return 0xEAC.
    .align 2
    .thumb_func
hook_measure_alt:
    ldr   r3, =RTL_TAG
    tst   r2, r3
    bne   .Lmeasure_alt_rtl
    subs  r2, #32
    lsls  r2, r2, #5
    ldr   r3, =LATIN_FONT
    ldrh  r2, [r3, r2]
    b     .Lmeasure_alt_done
.Lmeasure_alt_rtl:
    ldr   r3, =CODE_MASK
    ands  r2, r3
    ldr   r3, =RTL_WIDTHS
    ldrb  r2, [r3, r2]
.Lmeasure_alt_done:
    ldr   r3, =MEASURE_ALT_RETURN + 1
    push  {r3}
    ldr   r3, =MEASURE_ALT_STATE
    pop   {pc}

    .pool
    .align 2
rtl_font_pointer:
    .word RTL_FONT
