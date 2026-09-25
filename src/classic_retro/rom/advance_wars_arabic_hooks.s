@ Right-to-left text hooks for Advance Wars (USA, Rev 1, AWRE).
@
@ Assembled at 0x083F8000, in the 0xFF padding at the end of the image. Every
@ hook is reached by a BL written over the game's code (or over a BL it
@ replaces); none changes how the printer moves its pen.
@
@ A printer state prints Arabic when its text (or, while it inserts the
@ player's name, the text it goes back to) lies in the Arabic bank. For such
@ a state:
@
@ - hook_gap: no one-pixel gap before a glyph (the glyphs carry their spacing);
@ - hook_draw: glyphs from the right-to-left font, stored flipped; the name's
@   letters from the game's font, flipped here, each with a free column;
@ - hook_column: the tile column goes to its mirror in the text area, with
@   the horizontal flip: column' = 2 * left + 21 - column;
@ - hook_arrow: the key arrow takes the column left of the text, mirrored;
@ - hook_name / hook_name_end: the name is reversed in place while it is
@   drawn, so its letters, painted right to left, read left to right;
@ - hook_choice: a question's cursor stands at the mirror of its place, and
@   bit 0 of the place tells the other choice hooks that the answers are
@   Arabic (they are part of the message's last line);
@ - hook_labels: no English answers; hook_cursor: the cursor in its mirrored
@   places, flipped; hook_keys_*: Left and Right swap.
@
@ Printer state: +32 text, +36 the text after the name, +40 the tilemap,
@ +44 the tiles' palette bits, +48 the text area's left column, +51 the
@ current row, +52 the current tile. Choice task: +24 the cursor's place,
@ +30 the choice (0 Yes, 1 No), +44 the owner to refresh.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ ARABIC_TEXT, 0x083FC000
    .equ ARABIC_BANK, 0x4000
    .equ RTL_POINTERS, 0x083F8800
    .equ RTL_WIDTHS, 0x083F8C00
    .equ GAME_POINTERS, 0x083097F0
    .equ GAME_WIDTHS, 0x08309BF0
    .equ NAME_BUFFER, 0x0201226C
    .equ PEN_STEP, 0x08012C7D
    .equ DRAW_GLYPH, 0x08052231
    .equ PUT_COLUMN, 0x08012065
    .equ PRINT_TEXT, 0x08012A69
    .equ DRAW_CURSOR, 0x0801862D
    .equ REFRESH, 0x0807B44D
    .equ BLANK_TILE, 0x0174
    .equ ARROW_TILE, 0xA1C9
    .equ CURSOR_TILE, 0xA1CA
    .equ HFLIP, 0x0400
    .equ TEXT, 32
    .equ RETURN, 36
    .equ MAP, 40
    .equ PALETTE, 44
    .equ LEFT, 48
    .equ ROW, 51
    .equ TILE_INDEX, 52
    .equ PLACE, 24
    .equ CHOICE, 30
    .equ OWNER, 44
    .equ LAST_COLUMN, 21
    .equ YES_COLUMN, 20
    .equ NAME_LIMIT, 8

@ ---------------------------------------------------------------------------
@ At 0x080121AA, for `bl 0x08012C7C` (r0 = state, r1 = 1): the gap.
    .global hook_gap
    .thumb_func
hook_gap:
    push {lr}
    bl arabic_state
    pop {r3}
    mov lr, r3
    cmp r2, #0
    bne 1f
    ldr r2, =PEN_STEP
    bx r2
1:
    bx lr

@ ---------------------------------------------------------------------------
@ At 0x080121CC, for `bl 0x08052230` (r0 = character, r1 = its tiles in
@ VRAM, r2 = the pen's pixel in them, r3 = colour; r4 = state). Returns the
@ advance.
    .global hook_draw
    .thumb_func
hook_draw:
    push {r4-r7, lr}
    adds r5, r0, #0
    adds r6, r1, #0
    adds r7, r2, #0
    mov ip, r3
    adds r0, r4, #0
    bl arabic_state
    cmp r2, #0
    bne 1f
    adds r0, r5, #0
    adds r1, r6, #0
    adds r2, r7, #0
    mov r3, ip
    ldr r4, =DRAW_GLYPH
    bl call_r4
    b 9f
1:
    ldr r0, [r4, #TEXT]
    ldr r1, =ARABIC_TEXT
    subs r0, r0, r1
    ldr r1, =ARABIC_BANK
    cmp r0, r1
    bhs 2f
    ldr r3, =RTL_WIDTHS
    ldrb r3, [r3, r5]
    ldr r0, =RTL_POINTERS
    lsls r1, r5, #2
    ldr r0, [r0, r1]
    adds r1, r6, #0
    adds r2, r7, #0
    bl blit
    b 9f
2:
    @ A letter of the name: the game's glyph, flipped, after a free column.
    sub sp, #64
    ldr r2, =GAME_WIDTHS
    ldrb r2, [r2, r5]
    cmp r2, #7
    bls 3f
    movs r2, #7
3:
    ldr r0, =GAME_POINTERS
    lsls r1, r5, #2
    ldr r0, [r0, r1]
    mov r1, sp
    push {r2}
    bl flip_glyph
    pop {r3}
    adds r3, #1
    mov r0, sp
    adds r1, r6, #0
    adds r2, r7, #0
    bl blit
    add sp, #64
9:
    pop {r4-r7}
    pop {r1}
    bx r1

@ ---------------------------------------------------------------------------
@ At 0x080121E2 and 0x080121FE, for `bl 0x08012064` (r0 = state, r1 = the
@ tilemap entry of the pen's column): the column's two tiles.
    .global hook_column
    .thumb_func
hook_column:
    push {r0, r1, lr}
    bl arabic_state
    pop {r0, r1}
    pop {r3}
    mov lr, r3
    cmp r2, #0
    bne 1f
    ldr r2, =PUT_COLUMN
    bx r2
1:
    push {r4, lr}
    bl mirror_entry
    ldrh r2, [r0, #TILE_INDEX]
    ldrh r3, [r0, #PALETTE]
    ldr r4, =HFLIP
    orrs r3, r4
    adds r4, r2, #0
    orrs r4, r3
    strh r4, [r1]
    adds r2, #1
    orrs r2, r3
    adds r1, #64
    strh r2, [r1]
    pop {r4}
    pop {r3}
    bx r3

@ ---------------------------------------------------------------------------
@ At 0x08011E30, in code 0F (r5 = state, r6 = the pen's entry; r2, r4 and
@ r7 stay): the key arrow in the column after the pen's (its lower tile).
@ Returns to a branch over the rest of the replaced code.
    .global hook_arrow
    .thumb_func
hook_arrow:
    push {r2, r4, lr}
    adds r0, r5, #0
    bl arabic_state
    adds r1, r6, #2
    cmp r2, #0
    beq 1f
    bl mirror_entry
1:
    ldr r2, =BLANK_TILE
    strh r2, [r1]
    ldr r2, =ARROW_TILE
    adds r1, #64
    strh r2, [r1]
    pop {r2, r4}
    pop {r3}
    bx r3

@ ---------------------------------------------------------------------------
@ At 0x08011DAE, in code 15 (r0 = the text after the name, already kept at
@ +36; r5 = state): the text continues with the name.
    .global hook_name
    .thumb_func
hook_name:
    ldr r1, =NAME_BUFFER
    str r1, [r5, #TEXT]
    ldr r2, =ARABIC_TEXT
    subs r0, r0, r2
    ldr r2, =ARABIC_BANK
    cmp r0, r2
    bhs 1f
    adds r0, r1, #0
    b reverse_name
1:
    bx lr

@ At 0x08011DA2, in code 00 (r0 = the text after the name; r5 = state): the
@ name is done, and reversed back for an Arabic text.
    .global hook_name_end
    .thumb_func
hook_name_end:
    str r0, [r5, #TEXT]
    movs r1, #0
    str r1, [r5, #RETURN]
    ldr r2, =ARABIC_TEXT
    subs r0, r0, r2
    ldr r2, =ARABIC_BANK
    cmp r0, r2
    bhs 1f
    ldr r0, =NAME_BUFFER
    b reverse_name
1:
    bx lr

@ ---------------------------------------------------------------------------
@ At 0x08011DCE, in codes 14/16/17 (r4 = the new choice task, r5 = state,
@ r6 = the pen's entry): where the cursor stands.
    .global hook_choice
    .thumb_func
hook_choice:
    push {lr}
    adds r0, r5, #0
    bl arabic_state
    adds r0, r6, #2
    cmp r2, #0
    beq 1f
    @ The Yes place: column left + 20 of the answers' row, and bit 0.
    ldr r0, [r5, #MAP]
    movs r1, #ROW
    ldrb r1, [r5, r1]
    lsls r1, r1, #6
    adds r0, r0, r1
    movs r1, #LEFT
    ldrb r1, [r5, r1]
    adds r1, #YES_COLUMN
    lsls r1, r1, #1
    adds r0, r0, r1
    adds r0, #1
1:
    str r0, [r4, #PLACE]
    pop {r3}
    bx r3

@ At 0x08018692, for `bl 0x08012A68` (the English answers; r0 = r1 = 0,
@ r2 = the cursor's place).
    .global hook_labels
    .thumb_func
hook_labels:
    lsls r0, r2, #31
    bne 1f
    ldr r0, =PRINT_TEXT
    mov ip, r0
    movs r0, #0
    bx ip
1:
    bx lr

@ At 0x08018698 and 0x080186E8, for `bl 0x0801862C` (r0 = the choice task).
    .global hook_cursor
    .thumb_func
hook_cursor:
    ldr r1, [r0, #PLACE]
    lsls r2, r1, #31
    bne 1f
    ldr r2, =DRAW_CURSOR
    bx r2
1:
    push {r4, lr}
    subs r1, #1
    ldr r2, =BLANK_TILE
    adds r3, r1, #0
    strh r2, [r3]
    adds r3, #64
    strh r2, [r3]
    subs r3, #72
    strh r2, [r3]
    adds r3, #64
    strh r2, [r3]
    movs r3, #CHOICE
    ldrsh r3, [r0, r3]
    lsls r3, r3, #3
    subs r1, r1, r3
    ldr r2, =CURSOR_TILE | HFLIP
    strh r2, [r1]
    adds r2, #1
    adds r1, #64
    strh r2, [r1]
    ldr r0, [r0, #OWNER]
    ldr r4, =REFRESH
    bl call_r4
    pop {r4}
    pop {r0}
    bx r0

@ At 0x080186C0 and 0x080186D8, for `movs r0, #mask; ldrh r1, [r1, #12]`
@ (r1 = the keys, r4 = the choice task; r2 stays): the keys pressed, Left
@ and Right swapped for Arabic answers.
    .global hook_keys_back
    .thumb_func
hook_keys_back:
    movs r0, #0x20
    b 1f
    .global hook_keys_next
    .thumb_func
hook_keys_next:
    movs r0, #0x12
1:
    ldrh r1, [r1, #12]
    ldr r3, [r4, #PLACE]
    lsls r3, r3, #31
    beq 2f
    push {r0, r2}
    movs r0, #0x30
    ands r0, r1
    bics r1, r0
    lsrs r2, r0, #5
    lsls r2, r2, #4
    orrs r1, r2
    lsls r0, r0, #27
    lsrs r0, r0, #31
    lsls r0, r0, #5
    orrs r1, r0
    pop {r0, r2}
2:
    bx lr

@ ---------------------------------------------------------------------------
@ Helpers.

@ r0 = state. r2 = 1 when it prints Arabic text, else 0. Uses r2, r3.
    .thumb_func
arabic_state:
    ldr r2, [r0, #TEXT]
    ldr r3, =ARABIC_TEXT
    subs r2, r2, r3
    ldr r3, =ARABIC_BANK
    cmp r2, r3
    blo 1f
    ldr r2, [r0, #RETURN]
    ldr r3, =ARABIC_TEXT
    subs r2, r2, r3
    ldr r3, =ARABIC_BANK
    cmp r2, r3
    blo 1f
    movs r2, #0
    bx lr
1:
    movs r2, #1
    bx lr

@ r0 = state, r1 = a tilemap entry in its text area. r1 = the mirrored
@ entry on the same row. Uses r2, r3.
    .thumb_func
mirror_entry:
    push {r4}
    ldr r2, [r0, #MAP]
    subs r3, r1, r2
    lsls r4, r3, #26
    lsrs r4, r4, #27
    subs r3, r3, r4
    subs r3, r3, r4
    adds r2, r2, r3
    movs r3, #LEFT
    ldrb r3, [r0, r3]
    lsls r3, r3, #1
    adds r3, #LAST_COLUMN
    subs r3, r3, r4
    lsls r3, r3, #1
    adds r1, r2, r3
    pop {r4}
    bx lr

@ r0 = a string (at most NAME_LIMIT characters are reversed). Uses r0-r3.
    .thumb_func
reverse_name:
    adds r1, r0, #0
    movs r3, #NAME_LIMIT
1:
    ldrb r2, [r1]
    cmp r2, #0
    beq 2f
    adds r1, #1
    subs r3, #1
    bne 1b
2:
    subs r1, #1
3:
    cmp r0, r1
    bhs 4f
    ldrb r2, [r0]
    ldrb r3, [r1]
    strb r3, [r0]
    strb r2, [r1]
    adds r0, #1
    subs r1, #1
    b 3b
4:
    bx lr

@ r0 = 16 rows of 8 pixels (4 bytes each), r1 = the glyph's tile pair in
@ VRAM (the next pair follows), r2 = the pen's pixel in it, r3 = the advance.
@ ORs the rows in at the pen, clearing a pair the glyph starts; r0 = r3.
    .thumb_func
blit:
    push {r4-r7}
    lsls r2, r2, #29
    lsrs r2, r2, #29
    cmp r2, #0
    bne 2f
    movs r4, #0
    movs r5, #64
1:
    subs r5, #4
    str r4, [r1, r5]
    bne 1b
2:
    adds r4, r2, r3
    cmp r4, #8
    bls 4f
    movs r4, #0
    movs r5, #128
3:
    subs r5, #4
    str r4, [r1, r5]
    cmp r5, #64
    bne 3b
4:
    push {r3}
    cmp r3, #0
    beq 7f
    lsls r4, r2, #2
    movs r5, #32
    subs r5, r5, r4
    movs r6, #0
5:
    ldr r7, [r0, r6]
    adds r2, r7, #0
    lsls r2, r4
    ldr r3, [r1, r6]
    orrs r3, r2
    str r3, [r1, r6]
    lsrs r7, r5
    beq 6f
    adds r2, r6, #0
    adds r2, #64
    ldr r3, [r1, r2]
    orrs r3, r7
    str r3, [r1, r2]
6:
    adds r6, #4
    cmp r6, #64
    blo 5b
7:
    pop {r0}
    pop {r4-r7}
    bx lr

@ r0 = a game glyph's rows ((width + 1) / 2 bytes each), r1 = 16 rows of 4
@ bytes to fill, r2 = its width (at most 7). Each row flipped, after a free
@ column. Uses r0-r3.
    .thumb_func
flip_glyph:
    push {r4-r7}
    adds r4, r2, #1
    lsrs r4, r4, #1
    movs r7, #16
1:
    movs r3, #0
    movs r5, #0
2:
    cmp r5, r2
    bhs 3f
    lsrs r6, r5, #1
    ldrb r6, [r0, r6]
    lsls r6, r6, #28
    lsrs r6, r6, #28
    lsls r3, r3, #4
    orrs r3, r6
    adds r5, #1
    cmp r5, r2
    bhs 3f
    lsrs r6, r5, #1
    ldrb r6, [r0, r6]
    lsrs r6, r6, #4
    lsls r3, r3, #4
    orrs r3, r6
    adds r5, #1
    b 2b
3:
    lsls r3, r3, #4
    str r3, [r1]
    adds r1, #4
    adds r0, r0, r4
    subs r7, #1
    bne 1b
    pop {r4-r7}
    bx lr

    .thumb_func
call_r4:
    bx r4

    .pool
