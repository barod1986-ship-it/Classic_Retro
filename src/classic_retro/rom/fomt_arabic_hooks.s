@ Right-to-left text hooks for Harvest Moon: Friends of Mineral Town (USA, A4NE).
@
@ Assembled at 0x08760000, in the 0xFF padding at the end of the 8 MiB image.
@ The bank header at 0x08760400 gives the cells: +0 the 8x16 cells (64 bytes
@ each: top tile, bottom tile), +4 their count, +8 the 16x16 name tag cells
@ (128 bytes each: top left, top right, bottom left, bottom right), +12 theirs.
@
@ Codes (lead byte, trail byte); the game draws neither lead on its own, so
@ it pairs it with the next byte like a Shift-JIS lead:
@   F0 40..FA FC  cell (lead - F0) * 189 + trail - 0x40, one 8-pixel cell
@   FB xx         the game's own glyph xx, drawn right to left
@   FC 40..FC FC  a 16-pixel name tag cell
@   FD xx         placeholder FF xx (FF in the story scenes), right to left
@
@ The game's glyph routine (0x080D0D28, called for every character drawn in
@ a text box, a name tag or a menu) starts with a jump to hook_glyph. The
@ text box's draw-character method (0x0804EFAC) calls hook_mirror through a
@ veneer written in the code it replaces (0x0804EFD0). The character
@ expanders of the event scripts and of the story scenes have their method
@ slot (vtables 0x080E76E8 and 0x080E79E8, +12) pointed to hook_expand_script
@ and hook_expand_story.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ BANK, 0x08760400
    .equ BANK_CELLS, 0
    .equ BANK_CELL_COUNT, 4
    .equ BANK_TAG_CELLS, 8
    .equ BANK_TAG_CELL_COUNT, 12
    .equ CELL_LEAD, 0xF0
    .equ ISLAND_LEAD, 0xFB
    .equ TAG_LEAD, 0xFC
    .equ PLACEHOLDER_LEAD, 0xFD
    .equ TRAIL_FIRST, 0x40
    .equ TRAIL_LAST, 0xFC
    .equ TRAILS, 189
    .equ LAST_COLUMN, 27
    .equ GLYPH_RESUME, 0x080D0D31
    .equ SCRIPT_EXPAND, 0x0803B4DD
    .equ STORY_EXPAND, 0x080E19A5

@ int draw_glyph(u8 *buffer, int character): the glyph's tiles go to the
@ buffer line by line (top left, top right, bottom left, bottom right, 32
@ bytes each; a null buffer only asks the width), the result is its width in
@ tiles, 0 for a lead byte or a character without a glyph. Codes of this
@ overlay get their cell (the name's FB xx the game's glyph xx); any other
@ character runs the four instructions the jump replaced, then the routine.
    .global hook_glyph
    .thumb_func
hook_glyph:
    lsrs r2, r1, #8
    cmp r2, #CELL_LEAD
    blo glyph_original
    cmp r2, #TAG_LEAD
    bhi glyph_original
    lsls r3, r1, #24
    lsrs r3, r3, #24
    cmp r2, #ISLAND_LEAD
    beq glyph_island
    subs r3, #TRAIL_FIRST
    blo glyph_original
    cmp r3, #(TRAIL_LAST - TRAIL_FIRST)
    bhi glyph_original
    cmp r2, #TAG_LEAD
    beq glyph_tag
    subs r2, #CELL_LEAD
    push {r4, r5}
    movs r4, #TRAILS
    muls r2, r4
    adds r2, r2, r3                     @ cell number
    ldr r3, =BANK
    ldr r4, [r3, #BANK_CELL_COUNT]
    cmp r2, r4
    bhs 2f
    cmp r0, #0
    beq 1f
    ldr r3, [r3, #BANK_CELLS]
    lsls r2, r2, #6
    adds r3, r3, r2
    ldmia r3!, {r1, r2, r4, r5}         @ top tile to the top left
    stmia r0!, {r1, r2, r4, r5}
    ldmia r3!, {r1, r2, r4, r5}
    stmia r0!, {r1, r2, r4, r5}
    adds r0, #32
    ldmia r3!, {r1, r2, r4, r5}         @ bottom tile to the bottom left
    stmia r0!, {r1, r2, r4, r5}
    ldmia r3!, {r1, r2, r4, r5}
    stmia r0!, {r1, r2, r4, r5}
1:  pop {r4, r5}
    movs r0, #1
    bx lr
2:  pop {r4, r5}
    b glyph_original

glyph_tag:
    ldr r2, =BANK
    push {r4}
    ldr r4, [r2, #BANK_TAG_CELL_COUNT]
    cmp r3, r4
    pop {r4}
    bhs glyph_original
    cmp r0, #0
    beq 2f
    ldr r2, [r2, #BANK_TAG_CELLS]
    lsls r3, r3, #7
    adds r2, r2, r3
    movs r3, #128
1:  subs r3, #4
    ldr r1, [r2, r3]
    str r1, [r0, r3]
    bne 1b
2:  movs r0, #2
    bx lr

glyph_island:
    movs r1, r3
glyph_original:
    push {r4, r5, r6, lr}
    adds r4, r0, #0
    adds r2, r1, #0
    movs r6, #0
    ldr r0, =GLYPH_RESUME
    bx r0

@ The text box's draw-character method picks the sprite of the current line
@ that holds column x and the column inside it. For this overlay's codes (a
@ cell or a character of the name) the column is 27 - x: the pen still
@ advances left to right, so the game's wrapping and line ends are unchanged,
@ and a line fills from the right edge of the box.
@ In: r1 = the line's sprites (16 bytes each), r8 = x, r9 = the character.
@ Out: r7 = the sprite, r2 = the column inside it, r0 = 3 (as the replaced code).
    .global hook_mirror
    .thumb_func
hook_mirror:
    mov r2, r8
    mov r0, r9
    lsrs r0, r0, #8
    cmp r0, #CELL_LEAD
    blo 1f
    cmp r0, #ISLAND_LEAD
    bhi 1f
    movs r0, #LAST_COLUMN
    subs r2, r0, r2
1:  lsrs r0, r2, #2
    lsls r0, r0, #4
    adds r7, r1, r0
    movs r0, #3
    ands r2, r0
    bx lr

@ result *expand(result *out, expander *this, int character): out gets a
@ flag byte (expanded or not) and, at +4, the text (up to 31 bytes). FD xx
@ asks for the expander's text for FF xx (a lone FF in the story scenes)
@ reversed, each character as FB xx; names are at most 15 characters here.
    .global hook_expand_script
    .thumb_func
hook_expand_script:
    lsrs r3, r2, #8
    cmp r3, #PLACEHOLDER_LEAD
    ldr r3, =SCRIPT_EXPAND
    bne call_r3
    movs r3, #2                         @ FD xx -> FF xx
    lsls r3, r3, #8
    adds r2, r2, r3
    ldr r3, =SCRIPT_EXPAND
    b expand_reversed

    .global hook_expand_story
    .thumb_func
hook_expand_story:
    lsrs r3, r2, #8
    cmp r3, #PLACEHOLDER_LEAD
    ldr r3, =STORY_EXPAND
    bne call_r3
    movs r2, #0xFF

expand_reversed:
    push {r0, lr}
    bl call_r3
    ldrb r1, [r0]
    cmp r1, #0
    beq 5f
    sub sp, #16
    adds r1, r0, #4
    movs r2, #0
1:  ldrb r3, [r1, r2]                   @ copy the text (15 characters at most)
    cmp r3, #0
    beq 2f
    mov r0, sp
    strb r3, [r0, r2]
    adds r2, #1
    cmp r2, #15
    blo 1b
2:  movs r0, #ISLAND_LEAD
3:  subs r2, #1                         @ write it back last character first
    blo 4f
    mov r3, sp
    ldrb r3, [r3, r2]
    strb r0, [r1]
    strb r3, [r1, #1]
    adds r1, #2
    b 3b
4:  movs r3, #0
    strb r3, [r1]
    add sp, #16
5:  pop {r0}
    pop {r1}
    bx r1

call_r3:
    bx r3
    .pool
