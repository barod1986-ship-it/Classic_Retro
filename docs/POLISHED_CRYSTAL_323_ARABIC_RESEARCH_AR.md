# تعريب Pokémon Polished Crystal v3.2.3

## الحالة: فهرسة وبحث؛ ليست ترجمة قابلة للعب

تم التحقق من ملف اللعبة الذي قدّمه المستخدم:
- نظام Game Boy Color، الحجم 2,097,152 بايت.
- SHA-256: f06dbebe3fd20db54e7804605f7a55ad05b8ca203c62209705290d8880864803
- SHA-1: 6930b48af5844d373e3c9130f26d6dd1084cf4ed
- المصدر: https://github.com/Rangi42/polishedcrystal
- الإصدار v3.2.3 فقط، commit: 3fa43192379df5c3e7b09a08e4d5d79af4f02f42
- أداة البناء الأصلية: RGBDS 1.0.0؛ make crystal

**لا توجد حتى الآن رقعة BPS عربية قابلة للعب لهذه اللعبة.** التعرف على اللعبة وفهرسة نصوصها خطوة تأسيسية.

## لماذا لا يصلح استبدال النصوص مباشرة؟

- constants/charmap.asm: ترميزات الحروف ورموز التحكم.
- macros/scripts/text.asm: ضغط Huffman لنصوص الحوارات.
- home/text.asm: فك الضغط، الأسماء الديناميكية، الانتقال بين الأسطر والصفحات.
- engine/gfx/load_font.asm: خطوط متعددة.
- engine/gfx/vwf.asm وhome/vwf.asm: نظام الخط متغير العرض.

عند فحص ROM الذي أرسله المستخدم، ظهرت شجرة Huffman عند الإزاحة 0x3D14، بطول 248 بايت. إن العثور على بايت 0x5D داخل الملف لا يكفي لاعتباره حوارًا كاملًا: قد يكون جزءًا من بيانات أخرى أو منتصف نص.

## استخراج فهرس من المصدر الصحيح

استخرج المصدر من https://github.com/Rangi42/polishedcrystal عند commit المذكور (لا تستخدم master المتغيّر)، ثم شغّل:

    git clone https://github.com/Rangi42/polishedcrystal.git
    cd polishedcrystal
    git checkout 3fa43192379df5c3e7b09a08e4d5d79af4f02f42

ومن بيئة Classic Retro:

    classic-retro detect /path/to/polishedcrystal-3.2.3.gbc
    classic-retro research polished-crystal-catalog /path/to/polishedcrystal --out polished-crystal.local.workspace.json
    classic-retro research polished-crystal-check /path/to/polishedcrystal polished-crystal.local.workspace.json

ينشأ ملف JSON محلي يحوي النصوص الأصلية، لذا **لا ترفعه إلى GitHub**. الأداة لا تعدّل ملفات المصدر أو ROM وترفض الكتابة فوق فهرس موجود.

لكل عنصر معرف من مسار الملف والسطر، نص أصلي، خانة Arabic فارغة، وبصمة الملف. تُقسم النتائج إلى:
- dialogue: أوامر الحوار مثل text وline وcont وpara.
- string: السلاسل ضمن db وrawchar؛ قد تكون أسماء أو قوائم أو بيانات ثنائية.
- review: أي اقتباس آخر؛ يجب تحديد هل هو نص ظاهر للاعب أم جزء برمجي.

اكتب الترجمة في حقل arabic مع إبقاء الرموز مثل <PLAYER> و<RIVAL> وعلامة النهاية @ كما هي. يراجع أمر check هذه الرموز وتطابق المصدر والتغطية. يمكن وسم review بأنه not_text بعد فحصه فقط، وليس للتحايل على إكمال الحوارات.

## ما الذي ينقص حتى يُقال: تعريب كامل؟

1. مراجعة كل النصوص، بما فيها القوائم والأسماء والأدوات والحركات والقتال والبوكيدكس والهاتف والخيارات، بالإضافة إلى الرسومات التي تحتوي نصوصًا.
2. صنع خط عربي متصل، ودعم الكتابة RTL، الأرقام والأسماء المختلطة، والمعلومات المتغيرة أثناء اللعب.
3. إعادة البناء والتشغيل على محاكي Game Boy Color دقيق، واختبار القصة من البداية للنهاية وما بعد النهاية.
4. بناء رقعة BPS محققة من النسخة المحددة دون نشر ملف ROM.

لم تتم إضافة اللعبة بعد إلى سجل localization targets القابلة للبناء، لأن عارض العربية الخاص بها لم يُنفّذ.
