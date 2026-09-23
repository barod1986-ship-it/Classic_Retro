@ Final Fantasy VI Advance (USA, BZ6E01) Arabic right-to-left text hooks.
@
@ Assembled once for ARMv4T Thumb at ARABIC_CODE and stored as bytes in
@ ff6a_arabic.py; CI re-assembles this file and compares the bytes.
@
@ A message is right-to-left when the top-level message (reader 0) starts with
@ the marker code 0x5FF (bytes D7 BF). Arabic glyphs are text codes
@ ARABIC_BASE + slot, drawn from the Arabic FONT at ARABIC_FONT. Text is stored
@ in paint order and the logical cursor still advances left to right, so every
@ glyph is placed at the mirrored position inside the line:
@
@     draw_x = margin + RTL_RIGHT - cursor_x - advance
@
@ Each hook replaces original code with "ldr rN, [pc]; bx rN; .word hook" and
@ returns with an absolute branch to the original continuation.

    .syntax unified
    .cpu arm7tdmi
    .thumb

    .equ ARABIC_CODE,        0x08800000
    .equ ARABIC_FONT,        0x08801000
    .equ ARABIC_BASE,        0x600
    .equ RTL_MARKER_LEAD,    0xD7
    .equ RTL_MARKER_TRAIL,   0xBF
    .equ RTL_RIGHT,          224
    .equ LINE_STEP_LATIN,    12
    .equ LINE_STEP_ARABIC,   16
    .equ NARRATION_BAND,     63
    .equ NARRATION_BAND_AR,  72
    .equ LAST_LATIN_GLYPH,   0x10C

    .equ READER0_MESSAGE,    0x03002468
    .equ TEXT_CANVAS,        0x02022500
    .equ DRAW_GLYPH,         0x08150894
    .equ GLYPH_DONE,         0x081514D2
    .equ CONTROL_DISPATCH,   0x081514F0
    .equ LINE_OVERFLOW,      0x081513D4
    .equ MEASURE_LOOP,       0x08150EFE
    .equ MEASURE_CONTROLS,   0x08150F64
    .equ MEASURE_NAME,       0x0815103C
    .equ NEXT_CODE,          0x081519EE
    .equ BAND_CONTINUE,      0x08151A0C
    .equ NARRATION_CONTINUE, 0x0813BFCA

    .global hook_glyph, hook_measure, hook_newline, hook_newline_alt
    .global hook_dirty_band, hook_narration_band, arabic_font_object

@ Z set when the top-level message starts with the right-to-left marker.
    .macro RTL_TEST ra, rb
    ldr   \ra, =READER0_MESSAGE
    ldr   \ra, [\ra]
    ldrb  \rb, [\ra]
    cmp   \rb, #RTL_MARKER_LEAD
    bne   1f
    ldrb  \rb, [\ra, #1]
    cmp   \rb, #RTL_MARKER_TRAIL
1:
    .endm

    .text
    .align 2

@ Main text loop, character classification (replaces 0x081514AC..B3).
@ In: r4 = code, r6 = text state, sl = colour, sp = caller frame (3 stack args).
    .thumb_func
hook_glyph:
    push  {r5, r7}
    ldr   r0, =LAST_LATIN_GLYPH
    cmp   r4, r0
    bls   .Lglyph_latin
    ldr   r0, =ARABIC_BASE
    subs  r5, r4, r0
    ldr   r7, =arabic_font_object
    ldr   r0, [r7]
    ldrh  r0, [r0, #10]
    cmp   r5, r0
    bhs   .Lglyph_control
    b     .Lglyph_font
.Lglyph_latin:
    ldr   r7, [r6, #64]
    movs  r5, r4
.Lglyph_font:
    ldrb  r0, [r6, #24]
    cmp   r0, #240
    bhi   .Lglyph_overflow
    RTL_TEST r1, r2
    bne   .Lglyph_args
    ldr   r1, [r7]
    lsls  r2, r5, #2
    adds  r2, r2, r1
    ldr   r3, =LAST_LATIN_GLYPH
    adds  r2, r2, r3
    ldr   r2, [r2]
    ldrb  r2, [r1, r2]
    ldrb  r3, [r6, #22]
    adds  r3, #RTL_RIGHT
    subs  r3, r3, r0
    subs  r0, r3, r2
    bpl   .Lglyph_args
    movs  r0, #0
.Lglyph_args:
    str   r0, [sp, #8]
    ldrb  r0, [r6, #25]
    str   r0, [sp, #12]
    mov   r0, sl
    str   r0, [sp, #16]
    ldr   r0, =DRAW_GLYPH + 1
    mov   ip, r0
    movs  r0, r7
    movs  r3, r5
    pop   {r5, r7}
    ldr   r1, =TEXT_CANVAS
    movs  r2, #32
    bl    .Lcall_ip
    ldr   r1, =GLYPH_DONE + 1
    bx    r1
.Lglyph_control:
    pop   {r5, r7}
    ldr   r0, =CONTROL_DISPATCH + 1
    bx    r0
.Lglyph_overflow:
    pop   {r5, r7}
    ldr   r0, =LINE_OVERFLOW + 1
    bx    r0
.Lcall_ip:
    bx    ip

@ Line measurement used by centring (replaces 0x08150F5C..63).
@ In: r1 = code, r8 = accumulated width.
    .align 2
    .thumb_func
hook_measure:
    ldr   r0, =ARABIC_BASE
    subs  r2, r1, r0
    ldr   r0, =arabic_font_object
    ldr   r0, [r0]
    ldrh  r3, [r0, #10]
    cmp   r2, r3
    bhs   .Lmeasure_other
    lsls  r2, r2, #2
    adds  r2, r2, r0
    ldr   r3, =LAST_LATIN_GLYPH
    adds  r2, r2, r3
    ldr   r2, [r2]
    ldrb  r2, [r0, r2]
    add   r8, r2
    ldr   r0, =MEASURE_LOOP + 1
    bx    r0
.Lmeasure_other:
    ldr   r0, =0x13C
    cmp   r1, r0
    beq   .Lmeasure_name
    ldr   r3, =MEASURE_CONTROLS + 1
    bx    r3
.Lmeasure_name:
    ldr   r3, =MEASURE_NAME + 1
    bx    r3

@ Newline (replaces 0x08151652..5B). In: r2 = &line counter.
    .align 2
    .thumb_func
hook_newline:
    ldrb  r0, [r6, #22]
    strb  r0, [r6, #24]
    RTL_TEST r1, r3
    ldrb  r0, [r6, #25]
    bne   .Lnewline_latin
    adds  r0, #(LINE_STEP_ARABIC - LINE_STEP_LATIN)
.Lnewline_latin:
    adds  r0, #LINE_STEP_LATIN
    strb  r0, [r6, #25]
    ldrb  r0, [r2]
    adds  r0, #1
    strb  r0, [r2]
    ldr   r0, =NEXT_CODE + 1
    bx    r0

@ Newline, second window path (replaces 0x08151628..2F). In: r1 = &line counter.
    .align 2
    .thumb_func
hook_newline_alt:
    ldrb  r0, [r6, #22]
    strb  r0, [r6, #24]
    RTL_TEST r2, r3
    ldrb  r0, [r6, #25]
    bne   .Lnewline_alt_latin
    adds  r0, #(LINE_STEP_ARABIC - LINE_STEP_LATIN)
.Lnewline_alt_latin:
    adds  r0, #LINE_STEP_LATIN
    strb  r0, [r6, #25]
    ldrb  r0, [r1]
    adds  r0, #1
    strb  r0, [r1]
    ldr   r0, =NEXT_CODE + 1
    bx    r0

@ Canvas rows copied after drawing (replaces 0x08151A04..0B).
@ In: r0 = -8 (kept). Out: r1 = y + line height, r2 = r1 & -8.
    .align 2
    .thumb_func
hook_dirty_band:
    RTL_TEST r2, r3
    ldrb  r1, [r6, #25]
    bne   .Lband_latin
    adds  r1, #(LINE_STEP_ARABIC - LINE_STEP_LATIN)
.Lband_latin:
    adds  r1, #LINE_STEP_LATIN
    adds  r2, r1, #0
    ands  r2, r0
    ldr   r3, =BAND_CONTINUE + 1
    bx    r3

@ Scanlines of the window-less (narration) text band in the HBlank register
@ table (replaces 0x0813BFAC..B3): four 16-pixel Arabic lines need 72.
    .align 2
    .thumb_func
hook_narration_band:
    RTL_TEST r0, r1
    bne   .Lnarration_latin
    movs  r1, #NARRATION_BAND_AR
    b     .Lnarration_store
.Lnarration_latin:
    movs  r1, #NARRATION_BAND
.Lnarration_store:
    str   r1, [sp, #32]
    movs  r6, #97
    ldr   r2, =0xFFF8
    str   r2, [sp, #36]
    ldr   r0, =NARRATION_CONTINUE + 1
    bx    r0

    .pool
    .align 2
arabic_font_object:
    .word ARABIC_FONT
