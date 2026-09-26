# Castlevania: Symphony of the Night (USA): the Arabic hooks of ST0's dialogue.
#
# This file is assembled with mipsel-linux-gnu-as -march=r3000 and linked at
# HOOK_CODE_ADDRESS (0x801C2600), in the part the overlay adds to ST0.BIN.
# Both hooks draw with draw_glyph, which writes one glyph of the Arabic font
# into a line image in RAM: 192 pixels, 16 rows, 4 bits a pixel (96 bytes a
# row), pixel x in the low nibble of byte x / 2 when x is even. A glyph is
# 16 rows of 16 pixels (8 bytes a row) and as wide as its entry in the widths
# table; its pixels are written where it has ink, so the glyph painted before
# it keeps its joining stroke.
#
# hook_glyph takes the dialogue's MoveImage call, which copies a glyph of the
# game's 8x8 font into the line being typed. A code below 0x80 goes on to
# MoveImage as before. A code of the Arabic font is drawn at the pen, which
# starts a line at its right edge (LINE_RIGHT) and moves left by each glyph's
# width, then the whole line image goes to the line's place in VRAM. A line
# starts when the game's pen (nextCharX, a1) is at the line's start
# (nextLineX): the line image is cleared and the pen goes back to the right.
#
# hook_name takes the call that draws the speaker's name with a sprite a
# letter. It draws the name's glyphs (NAMES, by the speaker's index) into a
# second line image from the right edge, sends it to NAME_ROW in VRAM and
# shows it with one sprite whose right edge is the text's, as the game's
# routine would: allocated for the dialogue's names, hidden until the text
# starts, the entity destroyed when no primitive is left.

    .set noreorder
    .set noat
    .text

    .equ DIALOGUE, 0x801C24CC          # g_Dialogue
    .equ SCRIPT_CUR, 0x00
    .equ START_X, 0x04
    .equ START_Y, 0x08
    .equ NEXT_LINE_X, 0x0C
    .equ NAME_PRIMS, 0x34              # primIndex[1]
    .equ MOVE_IMAGE, 0x80012BEC
    .equ LOAD_IMAGE, 0x80012B24
    .equ ALLOC_PRIMITIVES, 0x8003C7B8  # g_api.AllocPrimitives
    .equ PRIM_BUF, 0x80086FEC          # g_PrimBuf, 0x34 bytes a primitive
    .equ DESTROY_ENTITY, 0x801B4908
    .equ ARABIC_FIRST, 0x80
    .equ LINE_RIGHT, 160
    .equ LINE_HALFWORDS, 48
    .equ ROWS, 16
    .equ ROW_BYTES, 96
    .equ LINE_BYTES, 1536
    .equ NAME_ROW, 448
    .equ NAME_TOP, 1
    .equ TEXT_LEFT, 4
    .equ TEXT_CLUT, 0x1A1
    .equ SPRITE, 6
    .equ HIDDEN, 8
    .equ PRIORITY, 0x1FF

    .equ WIDTHS, 0x801C2A00
    .equ NAMES, 0x801C2A80
    .equ GLYPHS, 0x801C3400
    .equ LINE_IMAGE, 0x801C7400
    .equ NAME_IMAGE, 0x801C7A00
    .equ PEN, 0x801C8000

# ---------------------------------------------------------------------------
# hook_glyph(a0 = the glyph's RECT, a1 = nextCharX, a2 = the line's VRAM row)

    .globl hook_glyph
hook_glyph:
    lui     $t0, %hi(DIALOGUE)
    lw      $t1, %lo(DIALOGUE + SCRIPT_CUR)($t0)
    nop
    lbu     $t1, -1($t1)               # the code the routine just read
    nop
    sltiu   $t2, $t1, ARABIC_FIRST
    beqz    $t2, 1f
    nop
    j       MOVE_IMAGE                 # a glyph of the game's font
    nop
1:
    addiu   $sp, $sp, -32
    sw      $ra, 24($sp)
    sw      $s0, 20($sp)
    sw      $s1, 16($sp)
    move    $s0, $a2
    move    $s1, $t1
    lh      $t2, %lo(DIALOGUE + NEXT_LINE_X)($t0)
    lui     $a2, %hi(LINE_IMAGE)
    bne     $a1, $t2, 2f
    addiu   $a2, $a2, %lo(LINE_IMAGE)
    jal     clear_image                # a new line: clear it, pen to the right
    move    $a0, $a2
    li      $t0, LINE_RIGHT
    lui     $at, %hi(PEN)
    sw      $t0, %lo(PEN)($at)
2:
    lui     $at, %hi(WIDTHS - ARABIC_FIRST)
    addu    $at, $at, $s1
    lbu     $t1, %lo(WIDTHS - ARABIC_FIRST)($at)
    lui     $at, %hi(PEN)
    lw      $a1, %lo(PEN)($at)
    move    $a0, $s1
    subu    $a1, $a1, $t1
    sw      $a1, %lo(PEN)($at)
    lui     $a2, %hi(LINE_IMAGE)
    jal     draw_glyph
    addiu   $a2, $a2, %lo(LINE_IMAGE)
    move    $a0, $s0                   # the line's row
    lui     $a1, %hi(LINE_IMAGE)
    jal     load_line
    addiu   $a1, $a1, %lo(LINE_IMAGE)
    lw      $ra, 24($sp)
    lw      $s0, 20($sp)
    lw      $s1, 16($sp)
    jr      $ra
    addiu   $sp, $sp, 32

# ---------------------------------------------------------------------------
# hook_name(a0 = the speaker's index, a1 = the cutscene entity)

    .globl hook_name
hook_name:
    addiu   $sp, $sp, -40
    sw      $ra, 36($sp)
    sw      $s3, 32($sp)
    sw      $s2, 28($sp)
    sw      $s1, 24($sp)
    sw      $s0, 20($sp)
    andi    $s0, $a0, 0xFFFF
    move    $s1, $a1
    lui     $v0, %hi(ALLOC_PRIMITIVES)
    lw      $v0, %lo(ALLOC_PRIMITIVES)($v0)
    li      $a0, SPRITE
    jalr    $v0
    li      $a1, 1
    sll     $v0, $v0, 16
    sra     $v0, $v0, 16
    li      $t0, -1
    bne     $v0, $t0, 1f
    nop
    jal     DESTROY_ENTITY             # no primitive left, as the game's routine
    move    $a0, $s1
    b       9f
    nop
1:
    lui     $at, %hi(DIALOGUE)
    sw      $v0, %lo(DIALOGUE + NAME_PRIMS)($at)
    sll     $t0, $v0, 1                # the primitive: g_PrimBuf + 0x34 * index
    addu    $t0, $t0, $v0
    sll     $t0, $t0, 2
    addu    $t0, $t0, $v0
    sll     $t0, $t0, 2
    lui     $s2, %hi(PRIM_BUF)
    addiu   $s2, $s2, %lo(PRIM_BUF)
    addu    $s2, $s2, $t0
    lui     $a0, %hi(NAME_IMAGE)
    jal     clear_image
    addiu   $a0, $a0, %lo(NAME_IMAGE)
    sll     $s0, $s0, 4                # the name: a count, then its codes in paint order
    lui     $at, %hi(NAMES)
    addu    $at, $at, $s0
    addiu   $s0, $at, %lo(NAMES)
    lbu     $s3, 0($s0)
    li      $a1, LINE_RIGHT
    sw      $a1, 16($sp)
2:
    beqz    $s3, 3f
    addiu   $s0, $s0, 1
    lbu     $a0, 0($s0)
    lw      $a1, 16($sp)
    lui     $at, %hi(WIDTHS - ARABIC_FIRST)
    addu    $at, $at, $a0
    lbu     $t1, %lo(WIDTHS - ARABIC_FIRST)($at)
    nop
    subu    $a1, $a1, $t1
    sw      $a1, 16($sp)
    lui     $a2, %hi(NAME_IMAGE)
    jal     draw_glyph
    addiu   $a2, $a2, %lo(NAME_IMAGE)
    b       2b
    addiu   $s3, $s3, -1
3:
    li      $a0, NAME_ROW
    lui     $a1, %hi(NAME_IMAGE)
    jal     load_line
    addiu   $a1, $a1, %lo(NAME_IMAGE)
    lw      $t1, 16($sp)               # where the name starts
    li      $t0, SPRITE
    sb      $t0, 7($s2)
    li      $t0, 0x10                  # tpage: 4 bits, x 0, y 256
    sh      $t0, 26($s2)
    li      $t0, TEXT_CLUT
    sh      $t0, 14($s2)
    sb      $t1, 12($s2)               # u
    li      $t0, NAME_ROW - 256
    sb      $t0, 13($s2)               # v
    li      $t0, LINE_RIGHT
    subu    $t0, $t0, $t1
    sb      $t0, 24($s2)               # width
    li      $t0, ROWS
    sb      $t0, 25($s2)               # height
    li      $t0, PRIORITY
    sh      $t0, 38($s2)
    li      $t0, HIDDEN
    sh      $t0, 50($s2)
    lui     $at, %hi(DIALOGUE)
    lh      $t0, %lo(DIALOGUE + START_X)($at)
    lh      $t2, %lo(DIALOGUE + START_Y)($at)
    addu    $t0, $t0, $t1
    addiu   $t0, $t0, TEXT_LEFT
    sh      $t0, 8($s2)                # x: the text's line, at u
    addiu   $t2, $t2, NAME_TOP
    sh      $t2, 10($s2)               # y
9:
    lw      $ra, 36($sp)
    lw      $s3, 32($sp)
    lw      $s2, 28($sp)
    lw      $s1, 24($sp)
    lw      $s0, 20($sp)
    jr      $ra
    addiu   $sp, $sp, 40

# ---------------------------------------------------------------------------
# clear_image(a0 = a line image): LINE_BYTES of zeros.

clear_image:
    li      $t0, LINE_BYTES
1:
    addiu   $t0, $t0, -4
    addu    $t1, $a0, $t0
    bnez    $t0, 1b
    sw      $zero, 0($t1)
    jr      $ra
    nop

# ---------------------------------------------------------------------------
# load_line(a0 = VRAM row, a1 = a line image): LoadImage at (0, row), 48 x 16.

load_line:
    addiu   $sp, $sp, -32
    sw      $ra, 24($sp)
    sh      $zero, 16($sp)
    sh      $a0, 18($sp)
    li      $t0, LINE_HALFWORDS
    sh      $t0, 20($sp)
    li      $t0, ROWS
    sh      $t0, 22($sp)
    jal     LOAD_IMAGE
    addiu   $a0, $sp, 16
    lw      $ra, 24($sp)
    nop
    jr      $ra
    addiu   $sp, $sp, 32

# ---------------------------------------------------------------------------
# draw_glyph(a0 = code, a1 = x, a2 = a line image): the glyph's ink at x.

draw_glyph:
    lui     $at, %hi(WIDTHS - ARABIC_FIRST)
    addu    $at, $at, $a0
    lbu     $t9, %lo(WIDTHS - ARABIC_FIRST)($at)
    addiu   $t0, $a0, -ARABIC_FIRST    # the glyph: GLYPHS + 128 * (code - 0x80)
    sll     $t0, $t0, 7
    lui     $t1, %hi(GLYPHS)
    addiu   $t1, $t1, %lo(GLYPHS)
    addu    $t0, $t0, $t1
    li      $t8, ROWS
1:
    move    $t2, $zero                 # the glyph's column
2:
    beq     $t2, $t9, 4f
    srl     $t3, $t2, 1
    addu    $t3, $t0, $t3
    lbu     $t3, 0($t3)
    andi    $t4, $t2, 1
    beqz    $t4, 3f
    andi    $t5, $t3, 0x0F
    srl     $t5, $t3, 4
3:
    beqz    $t5, 5f
    addu    $t6, $a1, $t2              # the line's column
    srl     $t7, $t6, 1
    addu    $t7, $a2, $t7
    lbu     $t3, 0($t7)
    andi    $t6, $t6, 1
    beqz    $t6, 6f
    andi    $t4, $t3, 0x0F
    sll     $t5, $t5, 4                # odd column: the high nibble
    b       7f
    or      $t3, $t4, $t5
6:
    andi    $t3, $t3, 0xF0             # even column: the low nibble
    or      $t3, $t3, $t5
7:
    sb      $t3, 0($t7)
5:
    b       2b
    addiu   $t2, $t2, 1
4:
    addiu   $t0, $t0, 8
    addiu   $t8, $t8, -1
    bnez    $t8, 1b
    addiu   $a2, $a2, ROW_BYTES
    jr      $ra
    nop
