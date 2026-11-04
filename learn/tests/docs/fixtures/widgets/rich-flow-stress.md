# Widget matrix: rich flow stress

Hostile prose: <script>alert(1)</script> and bidi ‮evil‬ text.

```ui
s1 = flow(
  title: "Forty steps with branches, back edges and long titles",
  step: [
    {"id": "s0", "text": "<script>alert(1)</script> \"><img src=x onerror=1>", "next": ["s1"]},
    {"id": "s1", "text": "שלום עולם, זו תווית ארוכה בעברית", "next": ["s2"]},
    {"id": "s2", "text": "مرحبا بالعالم هذا نص عربي طويل", "next": ["s3"]},
    {"id": "s3", "text": "Step 3 xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "next": ["s4", "s6"]},
    {"id": "s4", "text": "Step 4 word word word word with a rather long title that wraps", "next": ["s5"]},
    {"id": "s5", "text": "Step 5 with a rather long title that wraps", "next": ["s6"]},
    {"id": "s6", "text": "Step 6 word with a rather long title that wraps", "next": ["s7"]},
    {"id": "s7", "text": "Step 7 word word with a rather long title that wraps", "next": ["s8"]},
    {"id": "s8", "text": "Step 8 word word word with a rather long title that wraps", "next": ["s9"]},
    {"id": "s9", "text": "Step 9 word word word word with a rather long title that wraps", "next": ["s10"]},
    {"id": "s10", "text": "Step 10 with a rather long title that wraps", "next": ["s11", "s13", "s6"]},
    {"id": "s11", "text": "Step 11 word with a rather long title that wraps", "next": ["s12"]},
    {"id": "s12", "text": "Step 12 word word with a rather long title that wraps", "next": ["s13"]},
    {"id": "s13", "text": "Step 13 word word word with a rather long title that wraps", "next": ["s14"]},
    {"id": "s14", "text": "Step 14 word word word word with a rather long title that wraps", "next": ["s15"]},
    {"id": "s15", "text": "Step 15 with a rather long title that wraps", "next": ["s16"]},
    {"id": "s16", "text": "Step 16 word with a rather long title that wraps", "next": ["s17"]},
    {"id": "s17", "text": "Step 17 word word with a rather long title that wraps", "next": ["s18", "s20"]},
    {"id": "s18", "text": "Step 18 word word word with a rather long title that wraps", "next": ["s19"]},
    {"id": "s19", "text": "Step 19 word word word word with a rather long title that wraps", "next": ["s20"]},
    {"id": "s20", "text": "Step 20 with a rather long title that wraps", "next": ["s21"]},
    {"id": "s21", "text": "Step 21 word with a rather long title that wraps", "next": ["s22", "s17"]},
    {"id": "s22", "text": "Step 22 word word with a rather long title that wraps", "next": ["s23"]},
    {"id": "s23", "text": "Step 23 word word word with a rather long title that wraps", "next": ["s24"]},
    {"id": "s24", "text": "Step 24 word word word word with a rather long title that wraps", "next": ["s25", "s27"]},
    {"id": "s25", "text": "Step 25 with a rather long title that wraps", "next": ["s26"]},
    {"id": "s26", "text": "Step 26 word with a rather long title that wraps", "next": ["s27"]},
    {"id": "s27", "text": "Step 27 word word with a rather long title that wraps", "next": ["s28"]},
    {"id": "s28", "text": "Step 28 word word word with a rather long title that wraps", "next": ["s29"]},
    {"id": "s29", "text": "Step 29 word word word word with a rather long title that wraps", "next": ["s30"]},
    {"id": "s30", "text": "Step 30 with a rather long title that wraps", "next": ["s31"]},
    {"id": "s31", "text": "Step 31 word with a rather long title that wraps", "next": ["s32", "s34"]},
    {"id": "s32", "text": "Step 32 word word with a rather long title that wraps", "next": ["s33", "s28"]},
    {"id": "s33", "text": "Step 33 word word word with a rather long title that wraps", "next": ["s34"]},
    {"id": "s34", "text": "Step 34 word word word word with a rather long title that wraps", "next": ["s35"]},
    {"id": "s35", "text": "Step 35 with a rather long title that wraps", "next": ["s36"]},
    {"id": "s36", "text": "Step 36 word with a rather long title that wraps", "next": ["s37"]},
    {"id": "s37", "text": "Step 37 word word with a rather long title that wraps", "next": ["s38"]},
    {"id": "s38", "text": "Step 38 word word word with a rather long title that wraps", "next": ["s39"]},
    {"id": "s39", "text": "Step 39 word word word word with a rather long title that wraps"},
  ],
)
```

```ui
s2 = flow(
  title: "One step",
  step: [{"id": "only", "text": "Only step", "next": ["only"]}],
)
```
