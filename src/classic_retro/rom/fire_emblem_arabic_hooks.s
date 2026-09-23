@ Right-to-left talk hooks for Fire Emblem: The Sacred Stones (USA, BE8E).
@
@ Assembled at 0x08F00000 (linker padding at the end of the image). The game
@ reaches hook_decomp through a jump written over CallARM_DecompText and the
@ other hooks through ARM veneers in an unused debug routine (0x08003ABC),
@ since BL cannot reach this far. Addresses come from the fireemblem8u
@ decompilation, which builds this exact image.
@
@ A message whose first byte is 0x1E is right-to-left: the talk skips the
@ byte and sets bit 15 of its flags (sTalkState->config, cleared when every
@ talk starts). While the bit is set, widths and glyphs come from the
@ right-to-left glyph table and each glyph is drawn at the mirrored cursor:
@
@     draw_x = axis - cursor - width
@
@ where the axis is the bubble's text width, (activeWidth - 2) * 8, or 220
@ in the world map's sprite text box. That box shows 28 tiles and its text
@ starts 4 pixels in, but the game clears only 27 tiles of a line (English
@ never reaches the last one), so right-to-left text ends at pixel 216.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ STATE_POINTER, 0x0859133C      @ sTalkState (points to sTalkStateCore)
    .equ ACTIVE_FONT, 0x02028E70        @ gActiveFont
    .equ DECODE_STRING_RAM, 0x03004150  @ pointer to the ARM DecodeString copy
    .equ GET_STR_TALK_LEN, 0x08008B45
    .equ GET_CHAR_TEXT_LEN, 0x08003F3D
    .equ TEXT_DRAW_CHARACTER, 0x08004181
    .equ RTL_GLYPHS, 0x08F01000
    .equ RTL_MARKER, 0x1E
    .equ RTL_FLAG, 0x8000
    .equ CONFIG, 0x80                   @ TalkState.config (u16)
    .equ ACTIVE_WIDTH, 0x0E             @ TalkState.activeWidth (u8, tiles)
    .equ FLAG_SPRITE, 0x20              @ TALK_FLAG_SPRITE
    .equ SPRITE_AXIS, 220
    .equ FALLBACK, 0x3F * 4             @ '?' like the game's own lookup
    .equ TEXT_X, 2                      @ Text.x (u8)
    .equ GLYPH_WIDTH, 5                 @ Glyph.width (u8)
    .equ FONT_DRAW_GLYPH, 8             @ Font.drawGlyph

@ CallARM_DecompText(src, dst): a source with bit 31 set is an uncompressed
@ message, copied up to and including its terminator.
    .global hook_decomp
    .thumb_func
hook_decomp:
    cmp r0, #0
    blt 1f
    ldr r2, =DECODE_STRING_RAM
    ldr r2, [r2]
    bx r2
1:
    lsls r0, r0, #1
    lsrs r0, r0, #1
2:
    ldrb r2, [r0]
    strb r2, [r1]
    adds r0, #1
    adds r1, #1
    cmp r2, #0
    bne 2b
    bx lr

@ StartTalkExt's GetStrTalkLen(str, 0): consume the marker, then measure.
    .global hook_start
    .thumb_func
hook_start:
    ldrb r2, [r0]
    cmp r2, #RTL_MARKER
    bne 1f
    adds r0, #1
    ldr r2, =STATE_POINTER
    ldr r2, [r2]
    str r0, [r2]
    adds r2, #CONFIG
    ldrh r3, [r2]
    ldr r1, =RTL_FLAG
    orrs r3, r1
    strh r3, [r2]
    movs r1, #0
1:
    ldr r2, =GET_STR_TALK_LEN
    bx r2

@ GetStrTalkLen's GetCharTextLen(str, &width).
    .global hook_width
    .thumb_func
hook_width:
    ldr r2, =STATE_POINTER
    ldr r2, [r2]
    adds r2, #CONFIG
    ldrh r2, [r2]
    lsls r2, r2, #16
    bmi 1f
    ldr r2, =GET_CHAR_TEXT_LEN
    bx r2
1:
    ldrb r2, [r0]
    adds r0, #1
    lsls r2, r2, #2
    ldr r3, rtl_glyphs_pointer
    ldr r2, [r3, r2]
    cmp r2, #0
    bne 2f
    movs r2, #FALLBACK
    ldr r2, [r3, r2]
2:
    ldrb r2, [r2, #GLYPH_WIDTH]
    str r2, [r1]
    bx lr

@ r0 <- mirror axis; r2 and r3 clobbered.
rtl_axis:
    ldr r2, =STATE_POINTER
    ldr r2, [r2]
    adds r2, #CONFIG
    ldrh r3, [r2]
    movs r0, #FLAG_SPRITE
    tst r3, r0
    beq 1f
    movs r0, #SPRITE_AXIS
    bx lr
1:
    subs r2, #(CONFIG - ACTIVE_WIDTH)
    ldrb r0, [r2]
    subs r0, #2
    lsls r0, r0, #3
    bx lr

@ Talk_OnIdle's Text_DrawCharacter(text, str): returns the next character.
    .global hook_draw
    .thumb_func
hook_draw:
    ldr r2, =STATE_POINTER
    ldr r2, [r2]
    adds r2, #CONFIG
    ldrh r2, [r2]
    lsls r2, r2, #16
    bmi 1f
    ldr r2, =TEXT_DRAW_CHARACTER
    bx r2
1:
    push {r4, r5, r6, r7, lr}
    adds r4, r0, #0
    adds r5, r1, #0
    ldrb r2, [r5]
    lsls r2, r2, #2
    ldr r3, rtl_glyphs_pointer
    ldr r6, [r3, r2]
    cmp r6, #0
    bne 2f
    movs r2, #FALLBACK
    ldr r6, [r3, r2]
2:
    bl rtl_axis
    ldrb r7, [r4, #TEXT_X]
    ldrb r2, [r6, #GLYPH_WIDTH]
    subs r0, r0, r7
    subs r0, r0, r2
    bpl 3f
    movs r0, #0
3:
    strb r0, [r4, #TEXT_X]
    adds r7, r7, r2
    ldr r3, =ACTIVE_FONT
    ldr r3, [r3]
    ldr r3, [r3, #FONT_DRAW_GLYPH]
    adds r0, r4, #0
    adds r1, r6, #0
    bl via_r3
    strb r7, [r4, #TEXT_X]
    adds r0, r5, #1
    pop {r4, r5, r6, r7}
    pop {r1}
    bx r1

@ TalkInterpret's Text_GetCursor(text) for [A]: the key arrow is placed at
@ text x + returned value + 4; right-to-left it ends 4 pixels left of the text.
    .global hook_arrow
    .thumb_func
hook_arrow:
    ldr r2, =STATE_POINTER
    ldr r2, [r2]
    adds r2, #CONFIG
    ldrh r2, [r2]
    lsls r2, r2, #16
    bmi 1f
    ldrb r0, [r0, #TEXT_X]
    bx lr
1:
    push {r4, lr}
    ldrb r4, [r0, #TEXT_X]
    bl rtl_axis
    subs r0, r0, r4
    subs r0, #16
    pop {r4}
    pop {r1}
    bx r1

via_r3:
    bx r3

    .align 2
    .global rtl_glyphs_pointer
rtl_glyphs_pointer:
    .word RTL_GLYPHS

    .pool
