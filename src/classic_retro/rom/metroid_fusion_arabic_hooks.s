@ Right-to-left text hooks for Metroid Fusion (USA, AMTE).
@
@ Assembled at 0x0879F000, in the 0xFF padding at the end of the image. The
@ game's code is 7 MiB away, beyond a BL's reach: every hook but hook_width is
@ called through a BL to a veneer written over Dma3Transfer_Unused1
@ (0x08098940), which nothing calls. A veneer jumps through a register its
@ sites do not need: ip for hook_draw (`bx pc; nop; ldr ip, [pc]; bx ip`), r3
@ or r1 for the others (`ldr rN, [pc]; bx rN`); the fade keeps its loop's end
@ in ip. hook_width replaces GetCharacterWidth itself (a literal jump at its
@ entry).
@
@ The text routines draw a line from left to right into a strip of 4bpp
@ tiles, 32 bytes a column and 0x400 bytes a row of tiles, a line taking two
@ rows: the new-file intro's IntroProcessText and NewFileIntroProcessAdamText
@ at 0x0600D000 (two lines, one character every three frames) and
@ SpecialCutsceneProcessMonologue at 0x06000000 (nine lines, whose tiles then
@ fade in one by one); the briefings' NavigationConversationProcessText at
@ 0x06007000 or 0x06006000 (two lines, the second 0x800 bytes down) and their
@ question (0x0807A0FC) at 0x06007000. They keep their pen; the hooks mirror
@ where each right-to-left glyph lands, on a line 224 pixels wide:
@
@     left' = LINE_WIDTH - pen - width
@
@ - hook_width: the widths of the right-to-left glyphs (codes 0xB040 up);
@ - hook_draw: DrawCharacter at the mirrored place, for those codes;
@ - hook_fade: the fade of a monologue page's tile in its mirrored column;
@ - hook_arrow: the intro's next-page arrow at the bottom left, not right;
@ - hook_cursor: the ship computer's typing cursor left of its text;
@ - hook_nav_cursor, hook_nav_cursor_start: a briefing's typing cursor left of
@   its text, and at the right end of the line before the first character.
@
@ A text is right to left when it lies in the Arabic bank: the intro's is the
@ first word of gNonGameplayRam (0x03001484); a briefing's is found as the
@ game finds it, in the list of the language for the conversation.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ NONGAMEPLAY_RAM, 0x03001484
    .equ CONVERSATION, 0x220
    .equ PREVIOUS_CONVERSATION, 0x03000B88
    .equ LANGUAGE, 0x03000011
    .equ NAVIGATION_LANGUAGES, 0x0879C0F0
    .equ ARABIC_TEXT, 0x087A0000
    .equ ARABIC_BANK, 0x40000
    .equ GAME_WIDTHS, 0x08576234
    .equ GAME_CODES, 0x04A0
    .equ RTL_FIRST_CODE, 0xB040
    .equ RTL_CODES, 0x0800
    .equ RTL_WIDTHS, 0x0879F800
    .equ DEFAULT_WIDTH, 10
    .equ DRAW_CHARACTER, 0x0807913D
    .equ LINE_WIDTH, 224
    .equ LAST_COLUMN, 27
    .equ ARROW_X, 235
    .equ ARROW_X_RTL, 4
    .equ CURSOR_OFFSET, 14
    .equ CURSOR_MIRROR, 240 - CURSOR_OFFSET
    .equ SECOND_LINE, 0xE0
    .equ NAV_CURSOR_OFFSET, 8
    .equ NAV_CURSOR_WIDTH, 6
    .equ NAV_CURSOR_MIRROR, 240 - NAV_CURSOR_OFFSET - NAV_CURSOR_WIDTH

@ ---------------------------------------------------------------------------
@ GetCharacterWidth (0x08079118), r0 = character: the game's width table up
@ to 0x49F, the right-to-left widths from 0xB040, otherwise 10 as before.
    .global hook_width
    .thumb_func
hook_width:
    lsls r0, r0, #16
    lsrs r0, r0, #16
    ldr r1, =GAME_CODES
    cmp r0, r1
    bhs 1f
    ldr r1, =GAME_WIDTHS
    ldrb r0, [r1, r0]
    bx lr
1:
    ldr r1, =RTL_FIRST_CODE
    subs r0, r0, r1
    bcc 2f
    ldr r1, =RTL_CODES
    cmp r0, r1
    bhs 2f
    ldr r1, =RTL_WIDTHS
    ldrb r0, [r1, r0]
    bx lr
2:
    movs r0, #DEFAULT_WIDTH
    bx lr

@ ---------------------------------------------------------------------------
@ At the five `bl DrawCharacter` of the text routines:
@ r0 = character, r1 = its tile (row base + 32 * the pen's column), r2 = width,
@ r3 = the pen's pixel inside the column, [sp] = colour. A right-to-left glyph
@ goes to its mirrored place. The call goes on to DrawCharacter with the
@ caller's lr, r4, r5 and stack, so it returns to the caller and finds its
@ fifth argument.
    .global hook_draw
    .thumb_func
hook_draw:
    push {r4, r5}
    ldr r4, =RTL_FIRST_CODE
    subs r4, r0, r4
    ldr r5, =RTL_CODES
    cmp r4, r5
    bhs 2f
    lsrs r4, r1, #5
    movs r5, #31
    ands r4, r5
    lsls r4, r4, #3
    adds r4, r4, r3
    adds r4, r4, r2
    movs r5, #LINE_WIDTH
    subs r4, r5, r4
    bpl 1f
    movs r4, #0
1:
    lsrs r1, r1, #10
    lsls r1, r1, #10
    lsrs r5, r4, #3
    lsls r5, r5, #5
    adds r1, r1, r5
    movs r3, #7
    ands r3, r4
2:
    ldr r4, =DRAW_CHARACTER
    mov ip, r4
    pop {r4, r5}
    bx ip

@ ---------------------------------------------------------------------------
@ At 0x080981F8 in the monologue's fade (0x08098158), for
@ `lsls r2, r6, #1; lsls r0, r7, #7`: r6 = the tile's column, r7 = its line.
@ The fade walks the tiles in the pen's order and updates the tilemap entry at
@ 2 * column + 128 * line; in Arabic, the entry of the mirrored column.
    .global hook_fade
    .thumb_func
hook_fade:
    push {r4, r5, lr}
    lsls r2, r6, #1
    bl arabic_text
    bcs 1f
    movs r1, #2 * LAST_COLUMN
    subs r2, r1, r2
1:
    lsls r0, r7, #7
    pop {r4, r5}
    pop {r1}
    bx r1

@ ---------------------------------------------------------------------------
@ At 0x08098C1E in NewFileIntroProcessTextCursor, for
@ `movs r0, #235; strh r0, [r2, #12]`: r2 = the arrow's sprite, whose x is its
@ centre. In Arabic the arrow stands at the other end of the bottom line.
    .global hook_arrow
    .thumb_func
hook_arrow:
    push {r4, r5, lr}
    bl arabic_text
    movs r0, #ARROW_X
    bcs 1f
    movs r0, #ARROW_X_RTL
1:
    strh r0, [r2, #12]
    pop {r4, r5}
    pop {r1}
    bx r1

@ ---------------------------------------------------------------------------
@ At 0x08090740 in NewFileIntroProcessAdamTextCursor, for
@ `adds r0, #14; movs r1, #0`: r0 = the pen in pixels, r2 = the cursor's
@ sprite, r3 = gNonGameplayRam (kept). The cursor's x: 14 pixels past the pen,
@ or in Arabic its mirror on the 240-pixel screen.
    .global hook_cursor
    .thumb_func
hook_cursor:
    push {r4, r5, lr}
    bl arabic_text
    bcs 1f
    movs r1, #CURSOR_MIRROR
    subs r0, r1, r0
    b 2f
1:
    adds r0, #CURSOR_OFFSET
2:
    movs r1, #0
    pop {r4, r5}
    pop {r4}
    bx r4

@ ---------------------------------------------------------------------------
@ In NavigationConversationHandler, where the typing cursor follows the pen:
@ at 0x0807A696 for `adds r1, r2, #0; adds r1, #8` (the first line) and at
@ 0x0807A65A for `ldr r4, =0xFF28; adds r1, r2, r4` (the second, whose pen
@ starts at 0xE0). r2 = the pen; r0 = the cursor's sprite and r3 =
@ gNonGameplayRam (both kept). r1 = the cursor's x: 8 pixels past the pen on
@ its line, or in Arabic its mirror (the cursor is 6 pixels wide).
    .global hook_nav_cursor
    .thumb_func
hook_nav_cursor:
    push {r0, r3, r5, lr}
    cmp r2, #SECOND_LINE
    blo 1f
    subs r2, #SECOND_LINE
1:
    bl navigation_arabic
    bcs 2f
    movs r1, #NAV_CURSOR_MIRROR
    subs r1, r1, r2
    b 3f
2:
    movs r1, #NAV_CURSOR_OFFSET
    adds r1, r1, r2
3:
    pop {r0, r3, r5}
    pop {r4}
    bx r4

@ ---------------------------------------------------------------------------
@ In NavigationConversationHandler, where a briefing starts (0x0807AB5C) and
@ where it starts again when its question is answered No (0x0807ADF6), for
@ `movs r1, #8; strh r1, [r0, #0x2e]`: the typing cursor before the first
@ character, 8 pixels past the start of the line, or in Arabic at its mirror.
@ r0 = the cursor's sprite; r2 to r7 are kept.
    .global hook_nav_cursor_start
    .thumb_func
hook_nav_cursor_start:
    push {r0, r2, r3, r4, r5, lr}
    bl navigation_arabic
    movs r1, #NAV_CURSOR_OFFSET
    bcs 1f
    movs r1, #NAV_CURSOR_MIRROR
1:
    pop {r0, r2, r3, r4, r5}
    strh r1, [r0, #0x2e]
    pop {r0}
    bx r0

@ ---------------------------------------------------------------------------
@ Carry clear when the text being drawn lies in the Arabic bank. Uses r4, r5.
    .thumb_func
arabic_text:
    ldr r4, =NONGAMEPLAY_RAM
    ldr r4, [r4]
    ldr r5, =ARABIC_TEXT
    subs r4, r4, r5
    ldr r5, =ARABIC_BANK
    cmp r4, r5
    bx lr

@ ---------------------------------------------------------------------------
@ Carry clear when the briefing's text lies in the Arabic bank: the text the
@ game reads, the list of the language's entry (conversation - 1) * 2, one
@ more when the conversation comes again. Uses r0, r3, r4, r5.
    .thumb_func
navigation_arabic:
    ldr r3, =NONGAMEPLAY_RAM
    ldr r4, =CONVERSATION
    ldrb r0, [r3, r4]
    subs r5, r0, #1
    lsls r5, r5, #1
    ldr r4, =PREVIOUS_CONVERSATION
    ldrb r4, [r4]
    cmp r0, r4
    bne 1f
    adds r5, #1
1:
    ldr r4, =LANGUAGE
    movs r0, #0
    ldrsb r4, [r4, r0]
    lsls r4, r4, #2
    ldr r3, =NAVIGATION_LANGUAGES
    ldr r4, [r3, r4]
    lsls r5, r5, #2
    ldr r4, [r4, r5]
    ldr r5, =ARABIC_TEXT
    subs r4, r4, r5
    ldr r5, =ARABIC_BANK
    cmp r4, r5
    bx lr

    .ltorg
