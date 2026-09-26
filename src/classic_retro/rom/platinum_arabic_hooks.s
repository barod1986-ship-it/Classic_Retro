@ Right-to-left hooks for Pokemon Platinum (USA, Rev 0), ARM946E-S Thumb.
@
@ Linked at 0x01FF8680 in the ARM9's instruction TCM: the overlay grows the
@ ITCM autoload block, so this code is copied there at boot and stays whatever
@ the game loads. The game's code reaches it with BL (addresses from
@ pret/pokeplatinum's symbols).
@
@ A glyph code from RTL_FIRST up to RTL_END is a right-to-left glyph: the
@ glyphs the overlay adds after the fonts' own 509. A line that holds one, or
@ any line of a menu whose first entry holds one, is drawn right to left: the
@ printer still lays it out from the left, and hook_glyph draws each glyph at
@ the mirror of its pen on the window's width. A run of the game's own glyphs
@ in such a line (a name) is drawn left to right as a block at the mirror of
@ the run: the text around it stores its runs in reading order.
@
@ The printer's substruct bytes 3 to 5, zeroed for every printer and unused
@ by the game, hold a line's state: bit 0 of byte 3 is set when the line is
@ right to left, bit 1 inside a left-to-right run, and bytes 4 and 5 hold
@ where the run's pen maps (x' = base + x).

    .syntax unified
    .cpu arm946e-s
    .thumb

    .equ Window_CopyGlyph,              0x0201AED0
    .equ Window_FillRectWithColor,      0x0201AE78
    .equ Window_BlitBitmapRect,         0x0201ADDC
    .equ ColoredArrow_Print,            0x02014A58
    .equ PrintEntry,                    0x020015D0
    .equ Text_RenderScreenIndicator,    0x0201DB8C
    .equ Text_LoadScreenIndicatorGfx,   0x0201DB50
    .equ sFontWork,                     0x02101D48

    .equ RTL_FIRST,     0x01FE
    .equ RTL_COUNT,     0x0202          @ up to 0x0400, where the Korean codes start
    .equ LEFT_ARROW,    0x01FE          @ the menus' cursor, drawn from the right
    .equ FORMAT,        0xFFFE
    .equ NEWLINE,       0xE000
    .equ CLEAR,         0x25BC

    @ TextPrinter
    .equ P_RAW,         0x00            @ the string, after the current character
    .equ P_WINDOW,      0x04
    .equ P_X,           0x0A            @ where a line starts (u8)
    .equ P_SPACING,     0x10            @ letter spacing (u16)
    .equ P_FONT,        0x20            @ font id, bits 0-3
    .equ P_STATE,       0x23
    .equ P_BASE,        0x24
    .equ P_ICON,        0x30            @ the touch-screen icon's graphics
    @ FontWork and FontManager
    .equ FW_MANAGERS,   0x94
    .equ FM_WIDTH_FUNC, 0x70
    @ Window
    .equ W_WIDTH,       0x07            @ in tiles
    @ ListMenu, ColoredArrow and String
    .equ LM_WINDOW,     0x0C
    .equ ARROW_STRING,  0x04
    .equ STRING_DATA,   0x08

    .text

@ In RenderText (0x02002692), for Window_CopyGlyph(window, gfx, width, height,
@ x, y, table). r4 is the printer.
    .global hook_glyph
    .thumb_func
hook_glyph:
    push {r3-r7, lr}
    sub sp, #24
    str r0, [sp, #12]
    str r1, [sp, #16]
    str r3, [sp, #20]
    movs r5, r0                      @ window
    movs r7, r2                      @ width
    ldr r6, [sp, #48]               @ x
    ldrb r0, [r4, #P_X]
    cmp r0, r6
    bne 1f
    @ The first glyph of a line: its direction.
    ldr r0, [r4, #P_RAW]
    subs r0, #2
    bl scan_line
    ldr r1, =forced
    ldrb r1, [r1]
    orrs r0, r1
    movs r1, r4
    adds r1, #P_STATE
    strb r0, [r1]
1:
    movs r3, r4
    adds r3, #P_STATE
    ldrb r0, [r3]
    lsls r1, r0, #31
    beq 4f                          @ left to right: x as it is
    ldrb r2, [r5, #W_WIDTH]
    lsls r2, r2, #3                 @ the window's width
    ldr r1, [r4, #P_RAW]
    subs r1, #2
    ldrh r1, [r1]
    push {r0-r3}
    movs r0, r1
    bl rtl_code
    movs r1, r0
    pop {r0}
    cmp r1, #0
    pop {r1-r3}
    beq 2f
    @ A right-to-left glyph: x' = width - x - glyph's width.
    movs r1, #2
    bics r0, r1
    strb r0, [r3]
    subs r6, r2, r6
    subs r6, r6, r7
    b 4f
2:
    @ A glyph of a left-to-right run: the run is drawn at its mirror.
    lsls r1, r0, #30
    bmi 3f
    movs r1, #2
    orrs r0, r1
    strb r0, [r3]
    push {r2, r3}
    movs r0, r4
    bl run_width
    pop {r2, r3}
    subs r2, r2, r0
    subs r2, r2, r6
    subs r2, r2, r6                 @ base = width - run - 2 x
    movs r1, r4
    adds r1, #P_BASE
    strh r2, [r1]
3:
    movs r1, r4
    adds r1, #P_BASE
    ldrh r0, [r1]
    adds r6, r6, r0
4:
    lsls r6, r6, #16                @ a u16, as the printer passes it
    lsrs r6, r6, #16
    str r6, [sp, #0]
    ldr r0, [sp, #52]
    str r0, [sp, #4]
    ldr r0, [sp, #56]
    str r0, [sp, #8]
    ldr r0, [sp, #12]
    ldr r1, [sp, #16]
    movs r2, r7
    ldr r3, [sp, #20]
    bl Window_CopyGlyph
    add sp, #24
    pop {r3-r7, pc}

@ r0: a character code. r0 = 1 when it is a right-to-left glyph. Clobbers r1.
    .thumb_func
rtl_code:
    ldr r1, =RTL_FIRST
    subs r0, r0, r1
    ldr r1, =RTL_COUNT
    cmp r0, r1
    movs r0, #0
    bcs 1f
    movs r0, #1
1:
    bx lr

@ r0: characters. r0 = 1 when they hold a right-to-left glyph before the end
@ of their line (a line end, a new page, a scroll or FFFF). Clobbers r1-r3.
    .thumb_func
scan_line:
    push {r4, lr}
    movs r4, r0
1:
    ldrh r0, [r4]
    ldr r1, =FORMAT
    cmp r0, r1
    beq 3f
    bhi 2f                          @ FFFF
    ldr r1, =NEWLINE
    cmp r0, r1
    beq 2f
    ldr r1, =CLEAR
    subs r1, r0, r1
    cmp r1, #1
    bls 2f                          @ 25BC or 25BD
    bl rtl_code
    cmp r0, #0
    bne 4f
    adds r4, #2
    b 1b
3:
    ldrh r0, [r4, #4]               @ a command: skip it and its arguments
    adds r0, #3
    lsls r0, r0, #1
    adds r4, r4, r0
    b 1b
2:
    movs r0, #0
4:
    pop {r4, pc}

@ r0: the printer. r0 = the width of the run of the game's glyphs from the
@ current character, as the printer will advance over it.
    .thumb_func
run_width:
    push {r3-r7, lr}
    movs r4, r0
    ldr r5, =sFontWork
    ldr r5, [r5]
    movs r0, r4
    adds r0, #P_FONT
    ldrb r0, [r0]
    lsls r0, r0, #28
    lsrs r0, r0, #26
    adds r5, r5, r0
    adds r5, #FW_MANAGERS
    ldr r5, [r5]                    @ the printer's FontManager
    ldr r6, [r4, #P_RAW]
    subs r6, #2
    movs r7, #0
1:
    ldrh r0, [r6]
    ldr r1, =FORMAT
    cmp r0, r1
    beq 3f
    bhi 2f
    ldr r1, =NEWLINE
    cmp r0, r1
    beq 2f
    ldr r1, =CLEAR
    subs r1, r0, r1
    cmp r1, #1
    bls 2f
    push {r0}
    bl rtl_code
    movs r1, r0
    pop {r0}
    cmp r1, #0
    bne 2f
    subs r1, r0, #1
    movs r0, r5
    ldr r2, [r5, #FM_WIDTH_FUNC]
    blx r2
    adds r7, r7, r0
    ldrh r0, [r4, #P_SPACING]
    adds r7, r7, r0
    adds r6, #2
    b 1b
3:
    ldrh r0, [r6, #4]
    adds r0, #3
    lsls r0, r0, #1
    adds r6, r6, r0
    b 1b
2:
    ldrh r0, [r4, #P_SPACING]
    subs r0, r7, r0
    pop {r3-r7, pc}

@ In PrintEntries (0x02001702), for PrintEntry(menu, string, x, y): a menu
@ whose first entry is right to left prints every entry right to left, and
@ its window is remembered for the cursor.
    .global hook_entry
    .thumb_func
hook_entry:
    push {r0-r4, lr}
    ldr r0, [r0]                    @ the entries
    ldr r0, [r0]                    @ the first entry's string
    cmp r0, #0
    beq 3f
    adds r0, #STRING_DATA
    bl scan_line
3:
    ldr r1, =forced
    strb r0, [r1]
    ldr r2, [sp, #0]
    ldr r2, [r2, #LM_WINDOW]
    ldr r1, =rtl_window
    ldr r3, [r1]
    cmp r0, #0
    beq 1f
    str r2, [r1]
    b 2f
1:
    cmp r3, r2
    bne 2f
    str r0, [r1]
2:
    pop {r0-r3}
    bl PrintEntry
    ldr r1, =forced
    movs r0, #0
    strb r0, [r1]
    pop {r4, pc}

@ In PrintCursor (0x02001772), for ColoredArrow_Print(arrow, window, x, y):
@ the cursor of a right-to-left menu is the left arrow, a right-to-left glyph.
    .global hook_cursor
    .thumb_func
hook_cursor:
    push {r0-r4, lr}
    ldr r4, =rtl_window
    ldr r4, [r4]
    cmp r4, r1
    bne 1f
    ldr r0, [r0, #ARROW_STRING]
    ldr r4, =LEFT_ARROW
    strh r4, [r0, #STRING_DATA]
1:
    pop {r0-r3}
    bl ColoredArrow_Print
    pop {r4, pc}

@ In EraseCursor (0x020017D8), for Window_FillRectWithColor(window, colour,
@ x, y, width, height): a right-to-left menu erases its cursor at the mirror.
    .global hook_erase
    .thumb_func
hook_erase:
    push {r4, r5}
    ldr r4, =rtl_window
    ldr r4, [r4]
    cmp r4, r0
    bne 1f
    ldrb r4, [r0, #W_WIDTH]
    lsls r4, r4, #3
    subs r4, r4, r2
    ldr r5, [sp, #8]
    subs r2, r4, r5
1:
    pop {r4, r5}
    push {r0}
    ldr r0, =Window_FillRectWithColor + 1
    mov r12, r0
    pop {r0}
    bx r12

@ In RenderText (0x0200252E), for Text_RenderScreenIndicator(printer, x, y,
@ icon): on a right-to-left line the icon goes to the window's left edge.
    .global hook_icon
    .thumb_func
hook_icon:
    push {r3-r7, lr}
    sub sp, #24
    movs r4, r0
    movs r7, r3
    movs r5, r4
    adds r5, #P_STATE
    ldrb r5, [r5]
    lsls r5, r5, #31
    bne 1f
    bl Text_RenderScreenIndicator
    b 3f
1:
    ldr r0, [r4, #P_ICON]
    cmp r0, #0
    bne 2f
    bl Text_LoadScreenIndicatorGfx
    str r0, [r4, #P_ICON]
2:
    movs r1, #3
    lsls r1, r1, #7                 @ an icon is 24x32 pixels, 384 bytes
    muls r1, r7
    adds r1, r0, r1
    movs r2, #24
    str r2, [sp, #0]
    str r2, [sp, #16]
    movs r2, #32
    str r2, [sp, #4]
    str r2, [sp, #20]
    movs r2, #0
    str r2, [sp, #8]
    str r2, [sp, #12]
    movs r3, #0
    ldr r0, [r4, #P_WINDOW]
    bl Window_BlitBitmapRect
3:
    add sp, #24
    pop {r3-r7, pc}

    .pool

@ The hooks' variables, in the same writable block.
    .align 2
@ Set while a right-to-left menu prints its entries.
forced:
    .byte 0
    .align 2
@ The window of the last right-to-left menu, for its cursor.
rtl_window:
    .word 0
