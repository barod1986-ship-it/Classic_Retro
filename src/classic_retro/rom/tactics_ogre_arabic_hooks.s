@ Right-to-left text hooks for Tactics Ogre: The Knight of Lodis (USA, ATOE).
@
@ Assembled at 0x087D7000, in the padding after the end of the image's data.
@ The game's code is 7 MiB away, beyond a BL's reach: both hooks are called
@ through a BL to a veneer written over sub_0801C498, a glyph routine nothing
@ calls. hook_draw's veneer jumps through ip (`bx pc; nop; ldr ip, [pc];
@ bx ip`), which a call may clobber; hook_width's through r1
@ (`ldr r1, [pc]; bx r1`), which its site no longer needs.
@
@ The dialogue (0x08015188) lays a line out from the left: it draws a glyph at
@ a time with 0x0801B0C8, which composes it at the pen into the line's
@ columns of two 8x8 tiles (64 bytes, a row every 4). The window's line is its
@ longest line (measured by 0x080143E0), rounded up to whole columns. For a
@ message of the Arabic bank the hooks keep the pen and mirror where each
@ glyph lands, on that line:
@
@     left' = line - pen - width
@
@ - hook_width: the widths of the right-to-left glyphs, for the measure;
@ - hook_draw: a right-to-left glyph ORed into the line at its mirrored place.
@
@ In a message of the Arabic bank (ARABIC_TEXT up to the end of the image),
@ the glyph codes 0x00..0x7F are those of the right-to-left font: their widths
@ at RTL_WIDTHS, their glyphs at RTL_GLYPHS, 128 bytes each (two columns of 8
@ pixels, 16 rows of 4 bytes each).

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ ARABIC_TEXT, 0x087E0000
    .equ ARABIC_BANK, 0x20000
    .equ GAME_WIDTHS, 0x0815DE6C
    .equ RTL_WIDTHS, 0x087D7400
    .equ RTL_GLYPHS, 0x087D8000
    .equ DRAW_GLYPH, 0x0801B0C9
    .equ TEXT_WINDOW, 0x0200283C
    .equ LINE_COLUMNS, 0x1BA0
    .equ LINE_START, 0x1BC0
    .equ PEN, 0x030008C0
    .equ COLUMN_BYTES, 64

@ ---------------------------------------------------------------------------
@ At 0x08014560 in the width measure (0x080143E0), for `ldr r0, =widths;
@ ldrb r1, [r4]; adds r1, r1, r0; ldrb r0, [r1]`: r4 = the glyph. r0 = its
@ width: the right-to-left font's in a message of the Arabic bank, else the
@ game's. r1 and r2 are free.
    .global hook_width
    .thumb_func
hook_width:
    ldrb r0, [r4]
    ldr r1, =ARABIC_TEXT
    subs r1, r4, r1
    ldr r2, =ARABIC_BANK
    cmp r1, r2
    ldr r1, =GAME_WIDTHS
    bhs 1f
    ldr r1, =RTL_WIDTHS
1:
    ldrb r0, [r1, r0]
    bx lr

@ ---------------------------------------------------------------------------
@ At 0x080158F0 in the dialogue, for `bl 0x0801B0C8` (r0 = 0, r1 = the glyph,
@ r2 = 1, r3 = 0): r4 = the glyph in the message. Outside the Arabic bank the
@ call goes on to the game's routine with its arguments. In the bank the glyph
@ is ORed into the line's cleared tiles at its mirrored place, and the pen
@ moves on as the game's routine moves it:
@
@ - the pen (PEN): +0 the line's column where it starts, +4 the pen's column,
@   +8 the pen in pixels from the start of that first column;
@ - the window (TEXT_WINDOW): the line's width in columns at LINE_COLUMNS,
@   where its lines start at LINE_START (0 unless they are centred).
    .global hook_draw
    .thumb_func
hook_draw:
    ldr r0, =ARABIC_TEXT
    subs r0, r4, r0
    ldr r2, =ARABIC_BANK
    cmp r0, r2
    blo 1f
    movs r0, #0
    movs r2, #1
    ldr r3, =DRAW_GLYPH
    mov ip, r3
    movs r3, #0
    bx ip
1:
    push {r4, r5, r6, r7, lr}
    ldr r0, =RTL_WIDTHS
    ldrb r7, [r0, r1]
    ldr r0, =RTL_GLYPHS
    lsls r1, r1, #7
    adds r6, r0, r1
    ldr r0, =TEXT_WINDOW
    ldr r0, [r0]
    ldr r1, =LINE_START
    ldrb r2, [r0, r1]
    ldr r1, =LINE_COLUMNS
    ldrb r3, [r0, r1]
    lsls r3, r3, #3
    ldr r5, =PEN
    ldrh r4, [r5, #8]
    @ The pen from the line's start, then the glyph's mirrored left edge.
    lsrs r0, r2, #3
    lsls r0, r0, #3
    adds r0, r0, r4
    subs r3, r3, r0
    subs r3, r3, r7
    bpl 2f
    movs r3, #0
2:
    @ The game's pen moves on by the glyph's width.
    adds r4, r4, r7
    strh r4, [r5, #8]
    lsrs r4, r4, #3
    lsls r4, r4, #6
    ldr r1, [r5]
    adds r4, r1, r4
    str r4, [r5, #4]
    @ r5 = the column the glyph starts in; r3 = its shift in bits, r4 = 32 - r3.
    lsrs r2, r2, #3
    lsls r2, r2, #6
    subs r1, r1, r2
    lsrs r2, r3, #3
    lsls r2, r2, #6
    adds r5, r1, r2
    movs r0, #7
    ands r3, r0
    lsls r3, r3, #2
    movs r4, #32
    subs r4, r4, r3
    movs r0, #COLUMN_BYTES
    adds r0, r6, r0
    mov ip, r0
3:
    @ A row: pixels 0..7 into the first column and the next, 8..15 into the
    @ next two.
    ldr r0, [r6]
    ldr r1, [r6, #COLUMN_BYTES]
    adds r6, #4
    movs r2, r0
    lsls r2, r3
    beq 4f
    ldr r7, [r5]
    orrs r7, r2
    str r7, [r5]
4:
    lsrs r0, r4
    movs r2, r1
    lsls r2, r3
    orrs r2, r0
    beq 5f
    adds r5, #COLUMN_BYTES
    ldr r7, [r5]
    orrs r7, r2
    str r7, [r5]
    subs r5, #COLUMN_BYTES
5:
    lsrs r1, r4
    beq 6f
    adds r5, #2 * COLUMN_BYTES
    ldr r7, [r5]
    orrs r7, r1
    str r7, [r5]
    subs r5, #2 * COLUMN_BYTES
6:
    adds r5, #4
    cmp r6, ip
    bne 3b
    pop {r4, r5, r6, r7}
    pop {r0}
    bx r0

    .ltorg
