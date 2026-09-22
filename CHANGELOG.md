# Changelog — This Fork

This fork (`ThePerramus/comic-translate`, branch `v2.8.8-work`, based on upstream `v2.8.9`) adds
a workflow for pages that already have a translation to reuse instead of retranslating them, plus
several general-purpose editing and lettering improvements built along the way.

46 commits, 32 files touched, roughly +2,710/−110 lines relative to `v2.8.9`.

## Reference-page reveal workflow

For comics where a high-quality foreign-language scan and a separate, already-translated
low-quality scan both exist, re-running OCR and translation on the HQ page throws away a
translation that's already correct. This workflow cleans the HQ page's bubbles as usual, aligns
the LQ scan onto it, and reveals the LQ page's own pixels through the holes.

- **Manual corner alignment** — drag a semi-transparent overlay of the reference scan by its four
  corners until its art lines up with the page.
- **Automatic starting guess** — detects text blocks and panel boundaries on both scans and fits a
  starting perspective transform from the matches.
- **Reset Alignment** — one click back to the default full-page rectangle if the automatic guess
  goes wrong.
- **Bulk reference books** — load a whole cbz/cbr of the reference edition and pair pages to the
  working book by index plus an offset.
- **Piecewise offsets** — set a new offset partway through a book so inserted/divider pages don't
  throw off every page after them.
- **Per-page exclusion** — mark an HQ-only bonus page as having no reference counterpart at all.
- **Reveal Pencil** — an inpainting-style brush that paints with the aligned reference's own pixels
  instead of a flat color.
- **Content-aware auto-reveal** — reveals only the reference's actual detected text (dilated to
  keep its anti-aliased/halftone edges), not the whole cleaned rectangle, so an irregular bubble's
  corners keep Clean's own fill instead of the reference's off-tone scan background.
- **Pipeline integration** — on a reference page, Recognize/Translate disable themselves and
  Render reveals instead of drawing new text.
- **Full persistence** — alignment, offsets, exclusions, and the reference book's path all survive
  closing and reopening the project.

## Precision editing

- **Shift-constrain** — hold Shift while drawing with the brush, eraser, pencil, patch eraser, or
  reveal pencil to lock the stroke to a straight horizontal or vertical line.
- **Arrow-key nudging** — 1px steps (10px with Shift) for reference-alignment corners and selected
  text boxes, coalesced into a single undo step.

## Lettering & text rendering

- **Justify alignment** — a fourth option beside left/center/right; the paragraph's final line
  keeps its natural width instead of being stretched.
- **Live word-wrap** — neither the manual Render step nor the automatic "Translate All"
  pipeline bake hard line breaks into the translation anymore; the text box reflows live
  when the font size or box size changes.
- **Syllable hyphenation** — long words that don't fit a narrow bubble break at a real syllable
  boundary instead of overflowing or splitting arbitrarily.

## Inpainting touch-ups

- **Eyedropper, pencil, patch eraser** — hand tools for touching up cleaned pages, each with its
  own independently remembered brush size.
- The patch eraser also fixes a reveal-pencil stroke that ran over the edge of a bubble.
- **Pencil/patch layering fixes** — a pencil correction used before a reference page's first
  reveal now merges directly into Clean's own patch(es) underneath (even when a stroke spans more
  than one, e.g. one Clean patch per text line) instead of sitting on top as a separate layer that
  blocked the real text; one used after a reveal still stays as a permanent top layer. Also fixed
  the patch eraser and reveal-pencil losing each other's work through the same "opaque rectangle
  instead of real stroke shape" root cause.

## Stability fixes

Assorted general-purpose fixes made along the way: a Windows heap-corruption crash, rectangular
text boxes collapsing into ellipses, erased inpaint patches reverting after a project reload, a
broken brush-size hover preview, an image-cache desync crash, a save/navigation race, and an
unnecessary forced-login requirement.

## On the next upstream release

This branch sits well ahead of the `v2.8.9` tag it's built on, across files that are central to
the app (canvas event handling, the text item class, the rendering pipeline, the main window's
tool wiring) rather than a separate plug-in. When a new upstream tag lands, a single
`git merge <new-tag>` into this branch is the practical move — it reconciles the two histories
once, at a single merge commit, instead of replaying every commit here one at a time the way a
rebase would.
