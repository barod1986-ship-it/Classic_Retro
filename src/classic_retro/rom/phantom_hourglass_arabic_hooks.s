@ Right-to-left hook for The Legend of Zelda: Phantom Hourglass (USA), ARM946E-S ARM.
@
@ Linked at 0x0204F314, over func_0204f358 (zeldaret/ph's name), a routine of
@ the C++ runtime that nothing calls: no branch of the ARM9 or of any overlay
@ reaches it and no word of them points to it. The message printer's glyph
@ call reaches the hook with BL (addresses from zeldaret/ph's symbols).
@
@ A glyph code from RTL_FIRST up to RTL_LAST is a right-to-left glyph: the
@ overlay draws the Arabic forms over the font's kana, which the game's texts
@ never use. The printer still lays a line out from the left, moving its pen
@ by each glyph's advance and the letter spacing; the hook draws a
@ right-to-left glyph at the mirror of its place on the canvas:
@
@     x' = canvas width - x - glyph width
@
@ An Arabic glyph's width is its advance and one pixel, the spacing the
@ printer adds, so the glyphs of a line meet and the line grows leftwards from
@ the canvas's right edge. A translated line holds right-to-left glyphs only,
@ its spaces and punctuation included, so all of it is mirrored; every other
@ glyph is drawn where the game draws it.

    .syntax unified
    .cpu arm946e-s
    .arm

    @ NitroSystem's character canvas and font (zeldaret/ph: func_020296e0,
    @ func_02023ea4, func_02023eec)
    .equ DrawChar,          0x020296E0  @ (canvas, font, x, y, colour, code)
    .equ GetGlyphIndex,     0x02023EA4  @ (font, code): 0xFFFF when the font lacks it
    .equ GetCharWidths,     0x02023EEC  @ (font, index): left, width, advance

    .equ RTL_FIRST,         0x3041
    .equ RTL_COUNT,         0x30FC - 0x3041 + 1
    .equ NO_GLYPH,          0xFFFF
    .equ CANVAS_WIDTH,      0x04        @ in characters of 8 pixels
    .equ FONT_INFO,         0x00        @ the font's FINF: its glyph for a missing code at +2
    .equ INFO_ALTERNATE,    0x02
    .equ WIDTHS_WIDTH,      0x01

    .text

@ In func_020334b4 (0x02033564), the message printer's glyph, for
@ DrawChar(canvas, font, x, y, colour, code); the colour and the code are on
@ the stack.
    .global hook_glyph
hook_glyph:
    push {r0-r4, lr}
    ldr r4, [sp, #28]               @ the code
    ldr r3, =RTL_FIRST
    sub r3, r4, r3
    cmp r3, #RTL_COUNT
    bhs 1f
    mov r0, r1
    mov r1, r4
    bl GetGlyphIndex
    ldr r1, =NO_GLYPH
    cmp r0, r1
    ldreq r0, [sp, #4]              @ the font
    ldreq r0, [r0, #FONT_INFO]
    ldrheq r0, [r0, #INFO_ALTERNATE]
    mov r1, r0
    ldr r0, [sp, #4]
    bl GetCharWidths
    ldrb r0, [r0, #WIDTHS_WIDTH]
    ldr r1, [sp]                    @ the canvas
    ldr r1, [r1, #CANVAS_WIDTH]
    ldr r2, [sp, #8]                @ x
    rsb r2, r2, r1, lsl #3
    sub r2, r2, r0
    str r2, [sp, #8]
1:  pop {r0-r4, lr}
    b DrawChar

    .ltorg
