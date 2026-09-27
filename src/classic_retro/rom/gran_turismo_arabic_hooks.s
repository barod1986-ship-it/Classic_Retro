# Gran Turismo (USA) (Rev 1): the Arabic hook of the license briefings.
#
# This file is assembled with mipsel-linux-gnu-as -march=r3000 and linked at
# HOOK_ADDRESS (0x80029290), in place of the word loop of GTMAIN's briefing
# layout (0x800290F8), which ends at 0x80029370. Its first word is the delay
# slot the loop starts in, kept as the game has it (move s5, s6).
#
# The layout places the words of a line from the left: s3 is the pen, s1 a
# word's width, s0 its glyphs, s5 its number and s6 and s2 the line's first
# word and the one after its last; s8 is the room left on the line and s4 the
# gaps between its words, which justification spreads it over but on a
# paragraph's last line. The stack holds the line's y (24), the ordering table
# (32), the next word (48, its length byte first) and the paragraph's word
# count (72).
#
# `word` draws a word as the game does, but a word whose first glyph is an
# Arabic one (ARABIC_FIRST or above) at the mirror of its place in the
# 320-pixel line and DROP rows lower, under the taller Arabic title. The game's
# arithmetic is kept, without the compiler's checks of a divisor that is
# never 0 and with one multiplication less.
#
# `line_step` is called from the line's end (0x80029384), with t0 the next
# line's y; after a line whose last word is Arabic it puts the line three
# rows further, 15 rows from the last.

    .set noreorder
    .set noat
    .text

    .equ MEASURE, 0x8006c8e0           # (font, glyphs): a word's width
    .equ DRAW_WORD, 0x8006c9f0         # (ordering table, x, y, glyphs)
    .equ ARABIC_FIRST, 0x86
    .equ MIRROR, 320
    .equ DROP, 6
    .equ BODY_FONT, 1

    .word   0x02c0a821                 # move s5, s6 (the game's own encoding)
    .globl word
word:
    lw      $t0, 48($sp)
    li      $a0, BODY_FONT
    addiu   $s0, $t0, 1                # the word's glyphs
    jal     MEASURE
    move    $a1, $s0
    move    $s1, $v0                   # its width
    lbu     $t1, 0($s0)                # its first glyph
    lw      $a2, 24($sp)               # the line's y
    sltiu   $t1, $t1, ARABIC_FIRST
    bnez    $t1, draw                  # the game's text: where the game puts it
    move    $a1, $s3
    li      $t2, MIRROR                # Arabic: at the mirror of its place,
    subu    $a1, $t2, $s3
    subu    $a1, $a1, $s1
    addiu   $a2, $a2, DROP             # under the title
draw:
    lw      $a0, 32($sp)
    jal     DRAW_WORD
    move    $a3, $s0
    addiu   $v0, $s3, 4                # the pen past the word and a space
    lw      $t1, 48($sp)
    addu    $s3, $v0, $s1
    lbu     $v1, 0($t1)
    lw      $t0, 72($sp)
    addu    $v1, $t1, $v1
    addiu   $v1, $v1, 1
    beq     $s2, $t0, next             # a paragraph's last line is not spread
    sw      $v1, 48($sp)               # the next word
    subu    $v0, $s5, $s6              # this word's gap: room * (n + 1) / gaps
    mult    $s8, $v0                   #   - room * n / gaps
    mflo    $v1
    addu    $v0, $v1, $s8
    nop
    div     $zero, $v1, $s4
    mflo    $a0
    nop
    nop
    div     $zero, $v0, $s4
    mflo    $v0
    subu    $v0, $v0, $a0
    b       next
    addu    $s3, $s3, $v0

    .globl line_step
line_step:
    lbu     $t1, 0($s0)                # the line's last word's first glyph
    nop
    sltiu   $t1, $t1, ARABIC_FIRST
    bnez    $t1, stepped               # the game's text: 12 rows
    nop
    addiu   $t0, $t0, 3                # Arabic: 15
stepped:
    jr      $ra
    nop

    .org    0xe0
next:
