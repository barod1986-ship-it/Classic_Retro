@ Right-to-left Arabic pages for Mega Man Battle Network (USA, AREE).
@
@ Assemble: arm-none-eabi-as -mcpu=arm7tdmi; link with -Ttext 0x08160B00.
@ Addresses come from the Silenthal/bn1 disassembly (source/text.S).
@
@ Every translated page is drawn ahead of time and cut into 8x16 cells; the
@ cells of a page form a bank laid out like the dialogue font. bank_table,
@ written after this code by the ROM builder, is
@     u32 end      address after the rebuilt script archives
@     u32 count    number of entries (at least one)
@     count x {u32 address, u32 bank}, sorted by address
@ Text at or after an entry's address (and before the next one) uses its
@ bank, given as a glyph offset from the font (bank = font + 64 * offset).
@ NO_BANK (0x80000000) marks text that keeps the game's font and layout, as
@ does any text before the first entry or at or after `end`.
@
@ Both hooks read r4, the text pointer of Text_Main's character pass and of
@ its layout pass, and r5, the text handler.

    .syntax unified
    .cpu arm7tdmi
    .thumb
    .text

    .equ Text_CopyCharTile, 0x080137C0

    .global hook_copy
    .global hook_column
    .global bank_offset
    .global bank_table

@ Text_Main, 0x080136F2: `bl Text_CopyCharTile` for a one-byte character
@ (r1 = its code). In a translated page the code is a cell of the page's bank.
    .thumb_func
hook_copy:
    push    {lr}
    bl      bank_offset
    pop     {r0}
    mov     lr, r0
    movs    r0, #1
    lsls    r0, r0, #31
    cmp     r2, r0
    beq     1f
    adds    r1, r1, r2
1:
    ldr     r0, =Text_CopyCharTile + 1
    bx      r0

@ Text_LoadCharTileLayout, 0x08013806: replaces
@     ldrb r6, [r5, #14] / adds r0, r6, #1 / strb r0, [r5, #14] / adds r6, #8
@ which take the next column of the line (textCol + 8, textCol += 1). A
@ translated page counts its columns from the right edge instead: 27 - textCol.
    .thumb_func
hook_column:
    push    {lr}
    ldrb    r6, [r5, #14]
    adds    r0, r6, #1
    strb    r0, [r5, #14]
    bl      bank_offset
    movs    r0, #1
    lsls    r0, r0, #31
    cmp     r2, r0
    beq     1f
    movs    r0, #27
    subs    r6, r0, r6
    pop     {pc}
1:
    adds    r6, #8
    pop     {pc}

@ r2 = bank offset of the text at r4, or NO_BANK. Uses r0; binary search.
    .thumb_func
bank_offset:
    ldr     r0, =bank_table
    ldr     r2, [r0]
    cmp     r4, r2
    bhs     4f
    ldr     r2, [r0, #8]
    cmp     r4, r2
    blo     4f
    push    {r1, r3}
    ldr     r1, [r0, #4]
    adds    r0, #8
1:
    @ The answer is one of the r1 entries from r0; the first one is <= r4.
    cmp     r1, #1
    beq     3f
    lsrs    r3, r1, #1
    lsls    r2, r3, #3
    ldr     r2, [r0, r2]
    cmp     r4, r2
    blo     2f
    lsls    r2, r3, #3
    adds    r0, r0, r2
    subs    r1, r1, r3
    b       1b
2:
    movs    r1, r3
    b       1b
3:
    ldr     r2, [r0, #4]
    pop     {r1, r3}
    bx      lr
4:
    movs    r2, #1
    lsls    r2, r2, #31
    bx      lr

    .pool
    .align  2
bank_table:
