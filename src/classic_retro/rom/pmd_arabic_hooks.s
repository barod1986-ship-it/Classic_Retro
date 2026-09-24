@ Right-to-left text hooks for Pokémon Mystery Dungeon: Red Rescue Team (USA, B24E).
@
@ Assembled at 0x08272C00, in the 0xFF padding between the code (which ends
@ at 0x08272B3C) and the data at 0x08300000; every hook site reaches it with
@ BL. Addresses come from the pret/pmd-red decompilation, which builds this
@ exact image.
@
@ A right-to-left glyph is a charmap entry whose byte 8 (unused by the game,
@ 0 in every original glyph) is 1. The game draws every glyph through
@ DrawCharOnWindowInternal(windows, x, y, chr, color, windowId); its three
@ callers now call hook_draw, which draws such a glyph at the mirrored
@ position of the cursor inside its window,
@
@     draw_x = window.width * 8 - x - glyph.width
@
@ with 12 rows instead of the charmap's 11 and a drop shadow limited to the
@ bits of the ink colour: joined letters touch, and a shadow falling on the
@ neighbour's stroke must not change its colour (the game ORs pixels).
@
@ hook_draw also records, in the padding byte at 0x47 of the window, whether
@ the last glyph drawn there was right-to-left. hook_wait_arrow (the key
@ arrow of {WAIT_PRESS}) and the menu cursor hooks read it: after
@ right-to-left text the arrow goes to the left of the last glyph, and a
@ right-to-left menu gets its cursor on the right, flipped.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ ADD_SPRITE, 0x080050B0
    .equ DRAW_CHAR_ON_WINDOW_INTERNAL, 0x08007468
    .equ GET_CHARACTER, 0x08008584
    .equ TEXT_COLORS, 0x080B853C        @ gUnknown_80B853C: colour -> ink bits - 1
    .equ WINDOWS, 0x02027370            @ gWindows
    .equ CURRENT_CHARMAP, 0x020274AC    @ gCurrentCharmap
    .equ CHAR_HEIGHT, 0x0202B028        @ gCharHeight[2]
    .equ TEXT_SHADOW_MASK, 0x0202B030   @ gTextShadowMask
    .equ WINDOW_SIZE, 0x48
    .equ WINDOW_X, 0x00                 @ s16, tiles
    .equ WINDOW_WIDTH, 0x04             @ s16, tiles
    .equ WINDOW_RTL, 0x47               @ padding after unk46
    .equ GLYPH_WIDTH, 0x06              @ unkChar.width (s16)
    .equ GLYPH_FLAGS, 0x08              @ unkChar.unk8
    .equ RTL_ROWS, 12
    .equ ARROW_RTL_OFFSET, 14           @ the 16-pixel arrow has ink in columns 3..13
    .equ CURSOR_WIDTH, 8
    .equ SPRITE_H_FLIP, 0x1000          @ attrib2 bit 12

@ u32 DrawCharOnWindowInternal(windows, x, y, chr, color, windowId), called
@ from DrawCharOnWindow and DrawStringInternal.
    .global hook_draw
    .thumb_func
hook_draw:
    push {r4-r7, lr}
    sub sp, #16                         @ color, windowId, saved mask, saved height
    movs r4, r0
    movs r5, r1
    movs r6, r2
    movs r7, r3
    ldr r0, [sp, #36]
    str r0, [sp, #0]
    ldr r0, [sp, #40]
    str r0, [sp, #4]
    movs r0, r7
    bl GET_CHARACTER
    ldrb r2, [r0, #GLYPH_FLAGS]
    movs r3, #1
    ands r2, r3
    ldr r1, [sp, #4]
    movs r3, #WINDOW_SIZE
    muls r1, r3
    adds r1, r1, r4
    movs r3, #WINDOW_RTL
    strb r2, [r1, r3]
    cmp r2, #0
    beq 1f
    movs r3, #WINDOW_WIDTH
    ldrsh r3, [r1, r3]
    lsls r3, r3, #3
    subs r3, r3, r5
    movs r2, #GLYPH_WIDTH
    ldrsh r2, [r0, r2]
    subs r5, r3, r2
    ldr r0, [sp, #0]                    @ shadow &= ink colour in every pixel
    movs r1, #15
    ands r0, r1
    lsls r0, r0, #2
    ldr r1, =TEXT_COLORS
    ldr r0, [r1, r0]
    ldr r1, =0x11111111
    adds r0, r0, r1
    ldr r1, =TEXT_SHADOW_MASK
    ldr r2, [r1]
    str r2, [sp, #8]
    ands r0, r2
    str r0, [r1]
    ldr r1, =CURRENT_CHARMAP
    ldr r1, [r1]
    lsls r1, r1, #2
    ldr r0, =CHAR_HEIGHT
    adds r1, r1, r0
    ldr r2, [r1]
    str r2, [sp, #12]
    movs r2, #RTL_ROWS
    str r2, [r1]
    movs r0, r4
    movs r1, r5
    movs r2, r6
    movs r3, r7
    bl DRAW_CHAR_ON_WINDOW_INTERNAL
    ldr r1, =TEXT_SHADOW_MASK
    ldr r2, [sp, #8]
    str r2, [r1]
    ldr r1, =CURRENT_CHARMAP
    ldr r1, [r1]
    lsls r1, r1, #2
    ldr r2, =CHAR_HEIGHT
    adds r1, r1, r2
    ldr r2, [sp, #12]
    str r2, [r1]
    b 2f
1:
    movs r0, r4
    movs r1, r5
    movs r2, r6
    movs r3, r7
    bl DRAW_CHAR_ON_WINDOW_INTERNAL
2:
    add sp, #16
    pop {r4-r7}
    pop {r1}
    bx r1

@ HandleCharFormatInternal, {WAIT_PRESS}: arrowSpritePosX. In: r5 = the
@ draw state (x at 0, arrowSpritePosX at 8), r8 = windows. Out: r2 = windows.
    .global hook_wait_arrow
    .thumb_func
hook_wait_arrow:
    mov r2, r8
    movs r3, #WINDOW_X
    ldrsh r0, [r2, r3]
    lsls r0, r0, #3
    ldrh r1, [r5, #0]
    movs r3, #WINDOW_RTL
    ldrb r3, [r2, r3]
    cmp r3, #0
    bne 1f
    adds r0, r0, r1
    subs r0, #2
    strh r0, [r5, #8]
    bx lr
1:
    movs r3, #WINDOW_WIDTH
    ldrsh r3, [r2, r3]
    lsls r3, r3, #3
    adds r0, r0, r3
    subs r0, r0, r1
    subs r0, #ARROW_RTL_OFFSET
    strh r0, [r5, #8]
    bx lr

@ UpdateMenuCursorSpriteCoords: cursorArrowPos.x. In: r4 = window, r5 = the
@ menu input (unk4 at 4, cursorArrowPos.x at 8); both are kept.
    .global hook_cursor_x
    .thumb_func
hook_cursor_x:
    movs r1, #WINDOW_X
    ldrsh r0, [r4, r1]
    lsls r0, r0, #3
    ldrh r2, [r5, #4]
    movs r1, #WINDOW_RTL
    ldrb r1, [r4, r1]
    cmp r1, #0
    bne 1f
    adds r0, r0, r2
    strh r0, [r5, #8]
    bx lr
1:
    movs r1, #WINDOW_WIDTH
    ldrsh r1, [r4, r1]
    lsls r1, r1, #3
    adds r0, r0, r1
    subs r0, #CURSOR_WIDTH
    subs r0, r0, r2
    strh r0, [r5, #8]
    bx lr

@ AddMenuCursorSprite_: AddSprite(sprite, 0xFF, NULL, NULL). In: r6 = the
@ menu input (windowId first). A right-to-left menu's cursor points left.
    .global hook_cursor_sprite
    .thumb_func
hook_cursor_sprite:
    push {r0-r3, lr}
    ldr r1, [r6, #0]
    movs r2, #WINDOW_SIZE
    muls r1, r2
    ldr r2, =WINDOWS
    adds r1, r1, r2
    movs r2, #WINDOW_RTL
    ldrb r1, [r1, r2]
    cmp r1, #0
    beq 1f
    ldrh r1, [r0, #2]
    ldr r2, =SPRITE_H_FLIP
    orrs r1, r2
    strh r1, [r0, #2]
1:
    pop {r0-r3}
    bl ADD_SPRITE
    pop {r3}
    bx r3

    .pool
