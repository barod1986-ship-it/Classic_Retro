# اختبار العربية على The Legend of Zelda: The Minish Cap

هذه تجربة لتعريب **افتتاحية اللعبة الجديدة كاملة**: المقدمة المصوّرة (الزجاج الملوّن)،
ومشهد بيت سميث مع زيلدا، والطريق إلى بلدة هايرول، والوصول إلى المهرجان (26 رسالة).
القوائم وأسماء الأدوات وشاشات الحفظ وإدخال الاسم وبقية حوارات اللعبة لم تُترجم بعد.

## الملف المطلوب

- النسخة: `Legend of Zelda, The - The Minish Cap (USA).gba`
- الحجم: `16777216` بايت.
- SHA-1: `b4bd50e4131b027c334547b4524e2dbbd4227130`
- SHA-256: `bedc74df62755f705398273de8ed3bc59be610cf55760d0b9aa277f1f5035e73`

الاسم وحده لا يثبت تطابق النسخة. افحصها بعد تثبيت المشروع:

```sh
classic-retro detect "Legend of Zelda, The - The Minish Cap (USA).gba"
```

يجب أن تظهر `"supported": true` ومعرّف اللعبة `zelda-minish-cap-usa`.

## لماذا لا تبنيها GitHub Actions مثل FireRed؟

مشروع pokefirered يحتوي كل ملفات اللعبة، أما zeldaret/tmc فيستخرج الرسوم والأصوات
والنصوص من نسختك الأصلية (`baserom.gba`) أثناء البناء. لا يجوز رفع النسخة إلى
المستودع، لذلك يفحص CI التعديل على المصدر ويترجم الملفات البرمجية المعدّلة فقط،
وتُبنى الرقعة محليًا من نسختك (الخطوات في آخر الملف).

## تطبيق الرقعة

1. افتح [Flips](https://github.com/bates64/flips) واختر Apply Patch.
2. اختر ملف `minish-cap-usa-arabic-opening.bps` ثم نسختك الأصلية المذكورة أعلاه.
3. احفظ الناتج باسم جديد وافتحه في محاكي GBA مثل mGBA.
4. ابدأ ملفًا جديدًا، واكتب اسمًا، ثم اختر START.

```sh
flips --apply minish-cap-usa-arabic-opening.bps original.gba minish-cap-arabic-test.gba
```

تتحقق BPS من الملف الأصلي ومن نتيجة التطبيق. لا تطبّق الرقعة على نسخة معدّلة مسبقًا،
ولا ترفع ملف اللعبة الأصلي أو الناتج إلى المستودع.

## ما يجب فحصه

- نصوص المقدمة المصوّرة بالعربية وفي منتصف الشاشة، ومنها النص الضيق بجانب صورة البطل.
- في بيت سميث: الحوار يُكتب من اليمين إلى اليسار، ويبدأ كل سطر من الحافة اليمنى.
- اسم اللاعب اللاتيني يظهر بترتيبه الصحيح وباللون الأخضر داخل الجملة العربية.
  جرّب اسمًا من 6 أحرف أيضًا (أطول اسم تسمح به اللعبة).
- الألوان: الأسماء بالأخضر، «مهرجان بيكوري» بالأزرق، «السيف» و«سيف سميث» بالأحمر.
- تغيّر السطر والصفحة وسهم المتابعة دون قص أو تراكب.
- رسالة «لقد استلمت سيف سميث!» بعد تسلّم السيف.
- الطريق إلى البلدة: «من هنا!»، «أسرع! هيا بنا!»، «ها قد وصلنا إلى بلدة هايرول!».
- بعد «هيا! لنتجول في المكان!» تتابع اللعبة، وتظهر الرسائل الإنجليزية بشكلها المعتاد.

## البناء من المصدر

المتطلبات كما في [INSTALL.md لمشروع tmc](https://github.com/zeldaret/tmc/blob/master/INSTALL.md):
`build-essential` و`cmake` و`libpng-dev` و`arm-none-eabi-gcc` وPython مع `pycparser`.

```sh
git clone https://github.com/zeldaret/tmc
git -C tmc checkout d92d4581e202ae531bdcc206a7d6a90ddb8fd907
git clone https://github.com/pret/agbcc
git -C agbcc checkout da598c1d918402c42c0c0d7128ba14567f3175e9
(cd agbcc && ./build.sh && ./install.sh ../tmc)

cd tmc
make tools
cp "/path/to/Legend of Zelda, The - The Minish Cap (USA).gba" baserom.gba
make            # يبني النسخة الأصلية ويتحقق من SHA-1 قبل أي تعديل

classic-retro tmc prepare-arabic-source . --font /path/to/NotoKufiArabic-SemiBold.ttf
make CUSTOM=1
flips --create --exact --bps baserom.gba tmc.gba minish-cap-usa-arabic-opening.bps
```

الخط المرجعي هو Noto Kufi Arabic SemiBold نفسه المستخدم في تجربة FireRed
(رخصة SIL Open Font License 1.1)، وبصمته SHA-256:
`aa30cd2663f1eb1c940c9cd6a898877f307c2572e72a8a352896fe23f512018e`.
يكتب الأمر `prepare-arabic-source` معاينة للخط في
`data/classic_retro/arabic_font_preview.png`.

إذا سبق تجهيز المصدر بإصدار قديم من التعديل، استخدم نسخة نظيفة من الـ commit المحدد.

## الحدود الحالية

- لا حركات عربية، ولا أقواس تحتاج إلى عكس، ونمط خط عربي واحد بحجم 10 بكسل.
- إدخال الاسم لاتيني فقط، والقوائم وأسماء الأدوات بالإنجليزية.
- لا تُقاس أيقونات الأزرار والرموز داخل الأسطر العربية بعد.
- هذه التجربة لا تعني اكتمال دعم بقية اللعبة أو ألعاب GBA الأخرى.

التفاصيل التقنية في [TMC_ARABIC_RENDERER.md](TMC_ARABIC_RENDERER.md).
