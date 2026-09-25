# دليل المترجم

يحفظ Classic Retro الترجمة العربية لكل لعبة في ملف بيانات، لا في الكود. المترجم يعمل على هذا الملف وحده، ولا يحتاج إلى تعديل أي سطر برمجي.

## أين الترجمات

لكل لعبة ملف في `src/classic_retro/translations/`:

| الملف | اللعبة |
|-------|--------|
| `firered.json` | Pokémon FireRed |
| `minish-cap.json` | The Legend of Zelda: The Minish Cap |
| `ff6a.json` | Final Fantasy VI Advance |
| `golden-sun.json` | Golden Sun |
| `fire-emblem.json` | Fire Emblem: The Sacred Stones |
| `pmd-red.json` | Pokémon Mystery Dungeon: Red Rescue Team |
| `mmbn.json` | Mega Man Battle Network |
| `mlss.json` | Mario & Luigi: Superstar Saga |
| `fomt.json` | Harvest Moon: Friends of Mineral Town |
| `advance-wars.json` | Advance Wars |
| `metroid-fusion.json` | Metroid Fusion |

في كل ملف:

- `notation`: شرح الأوامر التي يستعملها نص هذه اللعبة، مثل `{wait}` و`\n`.
- `glossary`: المسرد، أي كيف يُكتب كل اسم أو مصطلح بالعربية في كل مكان.
- `entries`: مدخل لكل نص، وفيه:
  - `id`: معرّف ثابت، لا تغيّره.
  - `context`: من يتكلم وأين.
  - `text`: الترجمة العربية.

لا يحفظ المستودع أي نص من اللعبة الأصلية. مكان كل نص في اللعبة وبصمته يبقيان في الكود، والترجمة وحدها في ملف البيانات.

## ١. استخراج مساحة عمل

مساحة العمل هي ملف الترجمة نفسه، مضافًا إليه النص الأصلي لكل مدخل (`source`) مأخوذًا من نسختك أنت من اللعبة، لترى ما تترجمه:

```text
classic-retro targets extract fomt "path/to/game.gba"
```

يكتب الأمر `fomt.workspace.json` في المجلد الحالي، ويمكن اختيار اسم آخر بـ `--out`.

- **ألعاب الروم:** أعطِ الأمر صورة اللعبة التي يدعمها الهدف نفسها. الإصدار والبصمة في دليل كل لعبة (`docs/*_ARABIC_TEST_AR.md`).
- **FireRed وMinish Cap:** أعطِ الأمر نسختك من مشروع التفكيك (`pokefirered` أو `tmc`) على الـ commit المثبت، قبل ترقيعها.
- يتحقق الأمر من بصمة كل نص أصلي قبل أن يكتبه، فالمساحة تطابق النسخة المدعومة دائمًا.
- **مساحة العمل فيها نص اللعبة، فتبقى على جهازك.** لا ترفعها إلى المستودع ولا تشاركها. الملفات `*.workspace.json` مستثناة في git.
- لتحديث مساحة قديمة بترجمات أحدث استعمل `--translations الملف` لأخذ العربية منه، و`--force` لاستبدال ملف موجود.

## ٢. الترجمة

عدّل الحقل `text` فقط:

- اكتب العربية بترتيبها المنطقي، كما تُكتب عادة. الأداة تتولى الاتجاه وأشكال الحروف واتصالها.
- لا تعكس النص، ولا تضع محارف تحكم في الاتجاه. الملف يرفضها.
- احتفظ بكل أوامر الأصل وبترتيبها، كما يشرح حقل `notation` للعبة. نهايات الأسطر يمكن نقلها.
- اكتب أسماء المسرد كما هي فيه.
- الحقلان `context` و`notes` للبشر، وتعديلهما لا يغيّر شيئًا في اللعبة.

## ٣. التحقق

```text
classic-retro targets check-translations fomt --translations fomt.workspace.json \
  --font reference-font.ttf --preview-dir previews
```

- يتحقق من الأوامر في كل ترجمة.
- مع `--font`، يرسم كل نص بالخط المرجعي، ويقيسه على صندوق اللعبة، ويكتب صور المعاينة في `previews`.
- الخط المرجعي هو Noto Kufi Arabic SemiBold، وبصمته في دليل كل لعبة.
- مع مساحة عمل يضيف التقرير قائمة `glossary`، وفيها كل مدخل ذكر أصله اسمًا من المسرد ولم تستعمل ترجمته كتابته. هذا تذكير لا خطأ، فقد تقول الترجمة «هو» بدل تكرار الاسم.

## ٤. البناء والتجربة

ألعاب الروم:

```text
classic-retro targets build fomt "path/to/game.gba" --font reference-font.ttf \
  --out-dir build --translations fomt.workspace.json
```

- يبني الأمر باتش BPS من نسختك.
- القيمة `matches_reference` في التقرير تصبح `false` لأن الترجمة تغيّرت، وهذا متوقع.
- جرّب الباتش في المحاكي كما يشرح دليل اللعبة.

FireRed وMinish Cap:

```text
classic-retro targets prepare firered "path/to/pokefirered" --font reference-font.ttf \
  --translations firered.workspace.json
```

- يرقّع الأمر نسخة نظيفة من مشروع التفكيك.
- ابنِ النسخة المرقّعة بأداة المشروع كما يشرح دليل اللعبة.
- لتجربة تعديل جديد ابدأ من نسخة نظيفة.

## ٥. اعتماد الترجمة

```text
classic-retro targets strip fomt.workspace.json --out fomt.json
```

- يكتب الأمر الترجمات دون النصوص الأصلية.
- انسخ الملف الناتج مكان `src/classic_retro/translations/fomt.json`، واعرضه للمراجعة في طلب دمج.
- يتحقق الـ CI من الملف: كل مدخل يطابق النصوص المثبتة، والأوامر محفوظة، وكل سطر يُرسم بالخط المرجعي.
- الترجمة الجديدة تغيّر باتش اللعبة، فتُحدَّث بصمته المرجعية `reference_patch_sha256` في طلب الدمج نفسه (`docs/ADDING_A_TARGET.md`).

## المسرد

كل مصطلح في `glossary` ثلاثة حقول:

- `term`: الاسم كما في الأصل.
- `text`: كتابته العربية.
- `notes`: ملاحظة، وهو اختياري.

مثال:

```json
{"term": "Dora", "text": "دورا"}
```

- حين يتداخل مصطلحان يُعتمد الأطول، فمثلًا `MegaMan.EXE` قبل `MegaMan`.
- أضف كل اسم جديد إلى المسرد قبل استعماله، ليبقى مكتوبًا بالطريقة نفسها في كل ترجمات اللعبة.

## حدود هذه المرحلة

- **نطاق كل لعبة ثابت في الكود.** أي نص خارج `entries` يحتاج إلى تثبيته أولًا، أي تحديد مكانه في اللعبة وبصمته وأوامره، في وحدة اللعبة ثم إضافة مدخله.
- **صور Fire Emblem:** المدخلات `legend.*` هي سطور صور المقدمة، ولا نص أصليًا لها في مساحة العمل لأنها صور.
- **FF6 Advance:** مسرده مأخوذ من الترجمة وحدها، لأنه لا صورة للعبة عند كتابة هذا الدليل.
