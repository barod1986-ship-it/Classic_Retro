@ Right-to-left text hook for Mario & Luigi: Superstar Saga (USA, A88E).
@
@ Assembled at 0x08D00000, in the zero padding before the Mario Bros. image
@ at 0x08F50000. The glyph printer (0x08199624) is out of BL range from
@ there: its site (0x0819975C) calls a four-instruction veneer written in
@ the code it replaces, which loads this address.
@
@ The printer draws one character per call. At 0x0819975C it sets r9, the x
@ where the glyph is drawn (the pen x, plus half the free space of the cell
@ for fixed-width text), and r4, the printer's flags; the code after it only
@ needs those two. hook_draw_x computes the same values, then, for a glyph of
@ the right-to-left font, mirrors x inside the text area:
@
@     draw_x = box_width * 8 + left_margin - right_margin - x - drawn_width
@
@ The pen itself still advances left to right, so the game's measuring,
@ line ends and centring are unchanged; a left-aligned line now starts at
@ the right margin.
@
@ Printer (r5): +12 pen x, +14 left margin, +15 right margin, +18 flags
@ (bit 1 double width, bit 4 proportional), +19 box width in tiles << 2.
@ In: r1 = glyph width, r2 = fixed advance, [sp, #32] = the glyph's font.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ ARABIC_FONT, 0x08D00100
    .equ PEN_X, 12
    .equ LEFT_MARGIN, 14
    .equ RIGHT_MARGIN, 15
    .equ FLAGS, 18
    .equ BOX_TILES, 19
    .equ GLYPH_FONT, 32

    .global hook_draw_x
    .thumb_func
hook_draw_x:
    ldrb r4, [r5, #PEN_X]
    ldrb r3, [r5, #FLAGS]
    lsls r0, r3, #27                    @ bit 4: proportional
    bmi 1f
    subs r0, r2, r1                     @ fixed width: centre the glyph in its cell
    lsrs r3, r0, #31
    adds r0, r0, r3
    asrs r0, r0, #1
    adds r4, r4, r0
    lsls r4, r4, #24
    lsrs r4, r4, #24
1:
    ldr r0, [sp, #GLYPH_FONT]
    ldr r3, =ARABIC_FONT
    cmp r0, r3
    bne 2f
    ldrb r0, [r5, #BOX_TILES]
    lsrs r0, r0, #2
    lsls r0, r0, #3
    ldrb r3, [r5, #LEFT_MARGIN]
    adds r0, r0, r3
    ldrb r3, [r5, #RIGHT_MARGIN]
    subs r0, r0, r3
    subs r0, r0, r4
    ldrb r3, [r5, #FLAGS]
    lsls r3, r3, #30                    @ bit 1: double width
    lsrs r3, r3, #31
    lsls r1, r1, r3
    subs r4, r0, r1
    lsls r4, r4, #24
    lsrs r4, r4, #24
2:
    mov r9, r4
    ldrb r4, [r5, #FLAGS]
    bx lr
    .pool
