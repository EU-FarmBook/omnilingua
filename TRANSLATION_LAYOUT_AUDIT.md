# Translation + Layout Audit — OmniLingua

**Goal of this document:** explain, in plain language, how well OmniLingua actually
translates documents into all **24 EU languages while keeping the original layout**, what
was broken, what we fixed, and what is still a known limitation. Everything here is backed by
real test runs, not guesses.

---

## 1. The short version

| Question | Answer |
| --- | --- |
| Can it translate into all 24 EU languages? | Yes — at the API/validation level all 24 are accepted. |
| Did the output look correct for all 24? | **No.** Before the fix, ~11 languages came out with broken characters in the PDF "direct" engine. **Now fixed.** |
| Does it preserve layout? | Yes, but with one honest trade-off: when a translation is longer than the original box, text can be shrunk, truncated, or (rarely) dropped. This used to happen **silently**; now it is **logged and counted.** |
| Which way of translating is most reliable? | DOCX / PPTX / TXT (the `/translate/document` route). For PDFs, the `direct` engine (`/translate/pdf`). See section 5. |

---

## 2. Background: why fonts are the hard part

A PDF does not store "letters" the way a text file does. To put translated text back onto a
page, we have to **draw** each character using a font. If the font we draw with does not
contain a particular letter (for example the Polish `ł` or the Greek `μ`), the PDF shows a
blank box or a `?` instead of the letter. This is called a **notdef** (a "not defined"
glyph).

The 24 EU languages use three different writing systems:

- **Latin** (most languages) — but with many extra accented letters: `ł ą ę ż` (Polish),
  `č ř š ž ů` (Czech), `ő ű` (Hungarian), `ș ț ă` (Romanian), `ā ē ī ū ļ ņ` (Latvian), etc.
- **Greek** — `el` (Greek): `α β γ δ …`
- **Cyrillic** — `bg` (Bulgarian): `а б в г …`

A basic built-in PDF font (Helvetica) only knows **Western European Latin** (the so-called
"WinAnsi" set: `é ü ñ ç à …`). It does **not** know the Central/Eastern-European Latin
letters, Greek, or Cyrillic. For those we must switch to a full Unicode font (we ship
**DejaVu Sans**, which covers all three systems).

---

## 3. Critical bug (now fixed): broken characters for ~11 languages

### What was wrong

The code decided "do I need the full Unicode font?" with this check
(`app/pipeline/fonts.py`):

```python
if cp > 0x024F:   # only switch fonts for Greek/Cyrillic and beyond
    return True
```

`0x024F` is the end of the "Latin Extended" range. The problem: the special letters for
Polish, Czech, Slovak, Hungarian, Romanian, Lithuanian, Latvian, Croatian, Slovenian and
Maltese live **inside** that range (below `0x024F`), so the check returned `False` and the
code drew them with plain Helvetica — which doesn't have them.

### Evidence (real render test)

We drew each string into a PDF using the exact code path the "direct" engine uses, then read
the text back out:

```
=== Render with base-14 Helvetica (what the direct engine used to do) ===
pl  in='Zażółć gęślą'      ->  out='Za?ó?? g??l?'      match=False
cs  in='Příliš žluťoučký'  ->  out='P?íli? ?lu?ou?ký'  match=False
ro  in='Înălțimea școlii'  ->  out='În?l?imea ?colii'  match=False
hu  in='árvíztűrő'         ->  out='árvízt?r?'          match=False

=== Same text with the DejaVu Unicode font ===
pl  in='Zażółć gęślą'      ->  out='Zażółć gęślą'      match=True
cs  in='Příliš žluťoučký'  ->  out='Příliš žluťoučký'  match=True
ro  in='Înălțimea școlii'  ->  out='Înălțimea școlii'  match=True
```

So every `?` above was a letter the reader would simply **not see** in the translated PDF.

> Note: a tempting but **wrong** way to check this is `fitz.Font('helv').has_glyph(...)`.
> It reported "yes, the glyph exists" for all of these, because it secretly consults a
> different fallback font — not the one actually embedded in the page. The only reliable test
> is to render and read back, which is what we did.

### Languages affected (before the fix)

Polish, Czech, Slovak, Hungarian, Romanian, Lithuanian, Latvian, Croatian, Slovenian,
Maltese — and any Estonian word containing `š`/`ž`. That is the **default production path**
(`/translate/pdf`, `--layout-engine direct`). Greek and Bulgarian were already fine because
they sit above the old threshold.

### The fix

One line — lower the threshold so **anything beyond basic Western Latin** uses the Unicode
font:

```python
if cp > 0x00FF:   # anything above Latin-1 -> use the Unicode fallback font
    return True
```

We verified this turns the Unicode font **on** for exactly the broken languages and leaves
the fast Helvetica path **on** for languages that don't need it (English, German, French,
Spanish, Italian, Dutch, Danish, Swedish, Portuguese, Irish, Finnish, Estonian's Latin-1
words):

```
lang  before   after    text
pl    False     True     Zażółć gęślą jaźń       <- now fixed
cs    False     True     Příliš žluťoučký kůň    <- now fixed
ro    False     True     Înălțimea școlii        <- now fixed
mt    False     True     Ċensiment ħġieġ żraben  <- now fixed
el    True      True     Καλημέρα                (already worked)
bg    True      True     Добър ден               (already worked)
de    False     False    Grüße Straßen           (Helvetica is fine)
en    False     False    Hello world             (Helvetica is fine)
```

The same fix also repairs translated **text drawn over images** (the image-overlay path uses
the same font decision).

### Guard against regression

`tests/test_font_coverage.py` now renders a sample sentence for **all 24 EU languages**
through the real code path and fails if any letter comes back as `?`. It also asserts the
Latin-Extended languages take the Unicode font path.

We also added **`fonts-noto-core`** to the Docker image (alongside `fonts-dejavu-core`). The
"direct" engine uses DejaVu directly; the "html" engine relies on the browser's own font
fallback, and Noto gives it broader coverage.

---

## 4. Known limitation (now made visible): translations that are longer than the box

### Why this happens

Translations are usually **longer** than English. German, Finnish and Greek often run
**20–35% longer**. But in a PDF we must fit the new text into the **same box** the original
text occupied (that is what "preserving layout" means). When the translation doesn't fit, the
engine tries, in order:

1. grow the box a little (down/right),
2. shrink the font (down to ~72% of the original size),
3. (html engine) squeeze the text horizontally (down to 85% width),
4. as a last resort, **cut the text** and add `…`.

Steps 1–3 are fine. Step 4 means **real text is lost.** Previously this happened **silently** —
nothing in the logs, and the block was even mis-counted as "skipped."

### Evidence (real run)

**Normal one-line box** — long translations fit by growing/shrinking, no loss:

```
DE (+~35%)  wanted : Das System reduziert den Wasserverbrauch erheblich und nachhaltig.
            on page: Das System reduziert den Wasserverbrauch erheblich und nachhaltig.
```

**Tight box** (caption / table cell / label) with a very long translation — the text could
**not** be placed at all:

```
kind=caption  written=False  chars kept=0/178
   wanted : Wasserverbrauch pro Tonne verarbeitetem landwirtschaftlichem Material unter
            Berücksichtigung saisonaler Schwankungen und regionaler Unterschiede in der
            Bewässerungsinfrastruktur.
   on page: (empty)
```

This is the worst case: because the original text is **erased first** (redacted) and the new
text doesn't fit, the box ends up **blank** — the information is gone.

### What we changed

We did **not** change the fitting behavior (shrinking/truncating is a legitimate trade-off for
keeping layout). Instead we made the loss **impossible to miss**:

- `_fit_and_write_block` now returns a clear status: `fit`, `truncated`, `dropped`, or
  `skipped` (degenerate/empty box, source untouched).
- Each truncation/drop prints a warning naming the block, its kind, and the page, e.g.:
  ```
  ⚠️  block 42 (caption) p3: translation could not be placed after redaction — DROPPED (content lost): 'Wasserverbrauch pro Tonne verarbeitetem landwirtschaftli…'
  ```
- The run prints a summary, and the stats now include `blocks_truncated` and `blocks_dropped`.
  The CLI prints these too.
- The **html** engine likewise now counts boxes that still overflow after shrink+squeeze and
  warns that `overflow: hidden` will clip them.

So the behavior is the same, but operators can now **see** exactly how much text didn't fit
and on which pages — instead of shipping a silently incomplete PDF.

### How to reduce it further (future options, not done here)

- Allow a small, controlled font reduction across a whole paragraph rather than per-line.
- Permit boxes to grow downward and reflow following blocks (harder; changes layout).
- Ask the translator for a **more concise** rendering when a box is very tight.

---

## 5. Which endpoint is most reliable?

There are three translation endpoints. They differ a lot in how much can go wrong.

| Endpoint | What it does | Reliability | Why |
| --- | --- | --- | --- |
| **`/translate/document`** (DOCX / PPTX / TXT) | Edits the document's own text in place | **Highest** | No fonts to embed, no boxes to fit. The text is replaced in the file's XML and the viewer (Word/PowerPoint) re-flows it with real fonts. None of the PDF problems above apply. |
| **`/translate/pdf`** (PDF, `direct` engine) | Extracts text blocks, removes them, redraws the translation in place | **Good (recommended for PDF)** | Few moving parts, no browser, fast. Subject to the font issue (now fixed) and the box-fit trade-off (now visible). |
| **`/translate/pdf/advanced`** (`html` engine, image-text, mapping) | Converts PDF→HTML→PDF via Poppler + headless Chromium | **Lowest** | Most moving parts: Poppler conversion, a real browser, page-size scaling heuristics, font fallback inside Chromium, and `overflow: hidden` clipping. More ways to drift from the original. |

**Recommendations:**

- If the source exists as **DOCX/PPTX/TXT**, translate that, not a PDF of it — it is the most
  faithful and has none of the font/overflow risks.
- For **PDF**, use **`/translate/pdf`** (the `direct` engine). It is the default and the most
  predictable PDF path.
- Use the **`html`** engine (`/translate/pdf/advanced`) only when `direct` struggles with a
  very unusual layout, and review the output.

---

## 6. Summary of changes made in this pass

| File | Change |
| --- | --- |
| `app/pipeline/fonts.py` | Lower Unicode-font threshold `0x024F` → `0x00FF` (fixes ~11 languages). |
| `Dockerfile` | Add `fonts-noto-core` for broader html-engine coverage. |
| `app/pipeline/translate_pdf_direct.py` | `_fit_and_write_block` returns `fit/truncated/dropped/skipped`; warns on loss; new `blocks_truncated` / `blocks_dropped` stats + summary. |
| `app/pipeline/render_html_to_pdf.py` | Count and warn about boxes still overflowing after shrink/squeeze (html engine). |
| `cli.py` | Print truncated/dropped counts for the direct engine. |
| `tests/test_font_coverage.py` | New: 24-language render round-trip (no `?`), Unicode-font threshold guard, layout-fit status tests. |

All changes are behavior-preserving except the font fix, which makes previously-broken output
correct.
