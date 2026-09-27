# Ridge Racer (USA): the Arabic hook of the game's two text routines.
#
# This file is assembled with mipsel-linux-gnu-as -march=r3000 and linked at
# HOOK_ADDRESS (0x80068A00), in zeros after SCUS-943.00's data that nothing
# reads or writes; the overlay's data (DATA) follows it there. The overlay puts
# a jump to small_entry in place of the first word of SMALL_ROUTINE (an 8x8
# sprite a character, 8 pixels apart) and to large_entry in place of
# LARGE_ROUTINE's (16x16 sprites, 16 apart), and a nop after each. Both
# routines take (x, y, string, palette).
#
# A string whose first byte is CENTRE or MIRROR is Arabic: that byte, a
# parameter byte, then the codes of its glyphs in visual order (left to right)
# and a zero. The entry sends it to `arabic`, which returns to the routine's
# caller; any other string goes on through the game's routine, its first two
# instructions done here. `arabic` draws each glyph as a sprite of its own
# size from the font's table (its descriptor's first word; eight bytes a code
# from 0x20: u, v, width, height, the row offset from y), in the palette the
# game would use, in the texture page of the Arabic glyphs:
#
# - CENTRE: the text centred on the English it replaces, a parameter of n
#   characters as wide as the font's cells;
# - MIRROR: the text ending at the mirror of the English text's left edge
#   (320 - x), moved by the parameter less 128.
#
# In the large font the palette -1 colours a glyph by its code, as the game
# colours a character: LARGE_PALETTES[(code - 0x20) % 6]. The first Arabic
# string uploads the glyphs to VRAM (LoadImage of RECT from PIXELS) and sets
# UPLOADED. Like the routines, the hook leaves the next free primitive in v0.

    .set noreorder
    .set noat
    .text

    .equ SMALL_ROUTINE, 0x80027ed4
    .equ LARGE_ROUTINE, 0x8003e230
    .equ LOAD_IMAGE, 0x80041750
    .equ DRAW_SYNC, 0x80041538
    .equ ADD_PRIM, 0x80043f38
    .equ SET_DRAW_MODE, 0x8004221c
    .equ PRIM_POINTER, 0x1f800000     # the next free primitive
    .equ ORDER_TABLE, 0x80130ea4      # the frame's ordering table
    .equ TEXTURE_WINDOW, 0x80079f88   # the routines' texture window
    .equ LARGE_PALETTES, 0x80074168   # the large font's six palettes for -1
    .equ CENTRE, 1
    .equ MIRROR, 2
    .equ MIRROR_BIAS, 128
    .equ SCREEN_WIDTH, 320
    .equ DATA, 0x80068d00
    .equ UPLOADED, DATA
    .equ RECT, DATA + 4
    .equ SMALL_FONT, DATA + 12        # a font's descriptor, below
    .equ LARGE_FONT, DATA + 24
    .equ PIXELS, DATA + 0x840
    .equ FONT_TABLE, 0                # word: the glyph table
    .equ FONT_SLOT, 4                 # half: the ordering table's entry, in bytes
    .equ FONT_TPAGE, 6                # half: the glyphs' texture page
    .equ FONT_CELL, 8                 # byte: the English cell's width
    .equ FONT_CYCLES, 9               # byte: 1 when the palette -1 cycles
    .equ GLYPH_BYTES, 8
    .equ FIRST_CODE, 0x20
    .equ PALETTES, 6
    .equ SPRITE_TAG, 0x04000000       # four words follow the tag
    .equ SPRITE, 0x65000000           # SPRT, raw texture
    .equ SPRITE_BYTES, 20
    .equ DRAW_MODE_BYTES, 12

    .globl small_entry
small_entry:
    lbu     $t0, 0($a2)
    nop
    addiu   $t0, $t0, -CENTRE
    sltiu   $t0, $t0, 2
    bnez    $t0, small_arabic
    nop
    addiu   $sp, $sp, -64              # the routine's own first two words
    j       SMALL_ROUTINE + 8
    sw      $ra, 60($sp)
small_arabic:
    lui     $t8, %hi(SMALL_FONT)
    j       arabic
    addiu   $t8, $t8, %lo(SMALL_FONT)

    .globl large_entry
large_entry:
    lbu     $t0, 0($a2)
    nop
    addiu   $t0, $t0, -CENTRE
    sltiu   $t0, $t0, 2
    bnez    $t0, large_arabic
    nop
    addiu   $sp, $sp, -80
    j       LARGE_ROUTINE + 8
    sw      $ra, 76($sp)
large_arabic:
    lui     $t8, %hi(LARGE_FONT)
    j       arabic
    addiu   $t8, $t8, %lo(LARGE_FONT)

# a0 x, a1 y, a2 the string, a3 the palette, t8 the font
arabic:
    addiu   $sp, $sp, -56              # 16: SetDrawMode's fifth argument
    sw      $ra, 52($sp)
    sw      $s6, 48($sp)
    sw      $s5, 44($sp)
    sw      $s4, 40($sp)
    sw      $s3, 36($sp)
    sw      $s2, 32($sp)
    sw      $s1, 28($sp)
    sw      $s0, 24($sp)
    move    $s0, $a0                   # x, then the pen
    move    $s1, $a1                   # y
    move    $s2, $a2                   # the string
    move    $s3, $a3                   # the palette
    move    $s4, $t8                   # the font
    lui     $t0, %hi(UPLOADED)         # the glyphs to VRAM, once
    lw      $t1, %lo(UPLOADED)($t0)
    nop
    bnez    $t1, measure
    li      $t1, 1
    sw      $t1, %lo(UPLOADED)($t0)
    lui     $a0, %hi(RECT)
    addiu   $a0, $a0, %lo(RECT)
    lui     $a1, %hi(PIXELS)
    jal     LOAD_IMAGE
    addiu   $a1, $a1, %lo(PIXELS)
    jal     DRAW_SYNC
    move    $a0, $zero
measure:
    lw      $s5, FONT_TABLE($s4)       # the table, from code 0
    nop
    addiu   $s5, $s5, -FIRST_CODE * GLYPH_BYTES
    addiu   $t0, $s2, 2
    move    $t1, $zero                 # the text's width
width:
    lbu     $t2, 0($t0)
    addiu   $t0, $t0, 1
    beqz    $t2, place
    sll     $t2, $t2, 3
    addu    $t2, $t2, $s5
    lbu     $t3, 2($t2)
    b       width
    addu    $t1, $t1, $t3
place:
    lbu     $t2, 0($s2)                # the mode
    lbu     $t3, 1($s2)                # its parameter
    li      $t4, CENTRE
    bne     $t2, $t4, mirrored
    nop
    lbu     $t4, FONT_CELL($s4)        # centred on n cells
    nop
    mult    $t3, $t4
    mflo    $t3
    subu    $t3, $t3, $t1
    sra     $t3, $t3, 1
    b       sprites
    addu    $s0, $s0, $t3
mirrored:
    li      $t4, SCREEN_WIDTH          # ending at 320 - x, moved by the parameter
    subu    $t4, $t4, $s0
    subu    $t4, $t4, $t1
    addiu   $t3, $t3, -MIRROR_BIAS
    addu    $s0, $t4, $t3
sprites:
    lui     $t0, %hi(PRIM_POINTER)
    lw      $s6, %lo(PRIM_POINTER)($t0)
    addiu   $s2, $s2, 2
glyph:
    lbu     $t9, 0($s2)                # the code
    addiu   $s2, $s2, 1
    beqz    $t9, finish
    sll     $t2, $t9, 3
    addu    $t2, $t2, $s5              # the glyph's entry
    lbu     $t3, 3($t2)                # its height: 0 for a blank
    lbu     $t4, 2($t2)                # its width
    beqz    $t3, next
    move    $t5, $s3                   # the palette
    lbu     $t6, FONT_CYCLES($s4)
    li      $t7, -1
    beqz    $t6, clut
    nop
    bne     $t5, $t7, clut
    addiu   $t6, $t9, -FIRST_CODE      # -1 in the large font: by the code
    li      $t7, PALETTES
    divu    $t6, $t7
    mfhi    $t6
    sll     $t6, $t6, 1
    lui     $t7, %hi(LARGE_PALETTES)
    addu    $t7, $t7, $t6
    lh      $t5, %lo(LARGE_PALETTES)($t7)
    nop
clut:
    bgez    $t5, positive              # as the game: (palette / 16 + 480) << 6 | palette & 15
    move    $t6, $t5
    addiu   $t6, $t5, 15
positive:
    sra     $t6, $t6, 4
    addiu   $t6, $t6, 480
    sll     $t6, $t6, 6
    andi    $t7, $t5, 15
    addu    $t6, $t6, $t7
    lui     $t7, %hi(SPRITE_TAG)
    sw      $t7, 0($s6)
    lui     $t7, %hi(SPRITE)
    sw      $t7, 4($s6)
    sh      $s0, 8($s6)                # x
    lb      $t7, 4($t2)                # the row offset
    nop
    addu    $t7, $t7, $s1
    sh      $t7, 10($s6)               # y
    lbu     $t7, 0($t2)
    nop
    sb      $t7, 12($s6)               # u
    lbu     $t7, 1($t2)
    nop
    sb      $t7, 13($s6)               # v
    sh      $t6, 14($s6)               # the palette
    sh      $t4, 16($s6)               # width
    sh      $t3, 18($s6)               # height
    addu    $s0, $s0, $t4              # the pen past the glyph
    lh      $a0, FONT_SLOT($s4)
    lui     $t7, %hi(ORDER_TABLE)
    lw      $t7, %lo(ORDER_TABLE)($t7)
    move    $a1, $s6
    addu    $a0, $a0, $t7
    jal     ADD_PRIM
    addiu   $s6, $s6, SPRITE_BYTES
    b       glyph
    nop
next:
    b       glyph
    addu    $s0, $s0, $t4              # a blank: the pen only
finish:
    lhu     $a3, FONT_TPAGE($s4)       # the Arabic glyphs' page, as the routines set theirs
    lui     $t7, %hi(TEXTURE_WINDOW)
    addiu   $t7, $t7, %lo(TEXTURE_WINDOW)
    sw      $t7, 16($sp)
    move    $a0, $s6
    move    $a1, $zero
    jal     SET_DRAW_MODE
    li      $a2, 1
    lh      $a0, FONT_SLOT($s4)
    lui     $t7, %hi(ORDER_TABLE)
    lw      $t7, %lo(ORDER_TABLE)($t7)
    move    $a1, $s6
    jal     ADD_PRIM
    addu    $a0, $a0, $t7
    addiu   $v0, $s6, DRAW_MODE_BYTES
    lui     $at, %hi(PRIM_POINTER)
    sw      $v0, %lo(PRIM_POINTER)($at)
    lw      $ra, 52($sp)
    lw      $s6, 48($sp)
    lw      $s5, 44($sp)
    lw      $s4, 40($sp)
    lw      $s3, 36($sp)
    lw      $s2, 32($sp)
    lw      $s1, 28($sp)
    lw      $s0, 24($sp)
    jr      $ra
    addiu   $sp, $sp, 56
