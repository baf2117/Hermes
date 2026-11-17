---
name: taste
description: >-
  Reverse-engineer the design taste of a reference website. Only runs when the user
  explicitly types `/taste <url>`. Opens the page in a real browser (Playwright MCP),
  captures DOM data and screenshots, and runs a 4-step analysis that writes
  docs/references/{domain}/{domain}.md and {domain}.json with concrete design tokens
  (colors, typography, spacing, radii, shadows, grid) and "taste DNA" trade-offs
  (Trigger, Decision, Reason, Evidence). Use it to study a site's visual language as
  input for a plan's "Interfaz" section. Not for scraping data or summarizing content.
disable-model-invocation: true
compatibility: >-
  Requires the `playwright-taste` MCP server declared in this repo's .mcp.json
  (@playwright/mcp pinned, installed Chrome, isolated profile). Tools are named
  mcp__playwright-taste__browser_*.
metadata:
  version: "1.1.0-sdd.1"
  author: Senlin (upstream) / adapted for the SDD template
  upstream: https://github.com/senlindesign/taste-skill
---

> **Adapted for the SDD template.** Original: `senlindesign/taste-skill` v1.1.0 (MIT, see
> `NOTICE.md` at the repo root). Changes from upstream: manual activation only (no
> auto-trigger on URLs); outputs go to `docs/references/{domain}/` instead of the project
> root; export targets (Cursor, CLAUDE.md, Bolt…) and their phase were removed, so this
> skill never writes agent config files; the JSON check uses Node instead of Python;
> tool names use the `playwright-taste` server; a "Responsible use" section was added.
> The four analysis prompts in `references/` and `references/extract.js` are unchanged
> except for the tool name in the extractor's header comment.

# Taste — Reverse-Engineer a Website's Design DNA

This skill turns a URL into two files, inside `docs/references/{domain}/`:

- **`{domain}.md`** — human-readable. Two sections:
  - **Design Map** — practical tokens (colors, type scale, spacing, radii, shadows, grid)
  - **Taste DNA** — 3-4 opinionated trade-offs (Trigger → Decision → Reason → Evidence)
- **`{domain}.json`** — structured. Same data, machine-parseable.

The pipeline rejects generic descriptions like "clean and modern". A finished analysis should
read like a senior designer explaining *why* this particular page made *these particular*
choices — and what plausible alternatives it rejected.

## Activation

Run this skill **only** when the user explicitly types `/taste <url>`. Never start it because
a URL appears in a request, even a design-related one. If the user mentions a URL and asks
about design without typing `/taste`, answer normally and mention that `/taste <url>` exists.

## Responsible use

- The goal is to **study a site's visual language** (measurements and principles) as input
  for original work. Never copy another site's code, copy, images, logos or signature
  effects into the project.
- Screenshots of third-party sites stay local: `docs/references/**` image files are
  git-ignored. Only the `.md` and `.json` analysis is versioned.
- Record the source URL and the date in the output. Do not analyze pages behind a login.

## Prerequisites

The skill needs the `playwright-taste` MCP server from this repo's `.mcp.json` (isolated
profile, so cookies and sessions never leak into the analyzed page, and the installed Chrome,
so there is no browser download). Check that the tools `mcp__playwright-taste__browser_*`
are available. If they are not, stop and tell the user: "I need the playwright-taste MCP
server. Check .mcp.json, restart Claude Code, approve the server, and try again." Do not fall
back to WebFetch: the screenshot is essential for Step 1.

## Workflow

Follow these phases in order. Each has explicit success criteria — do not advance until the
current phase has produced what the next one needs.

### Phase 0 — Parse the URL and crawl scope

**Step 1 — URL.** Extract the URL from the message (`/taste https://linear.app`). Add
`https://` if missing. If there is no real URL, ask for one. If it is a file path, ask whether
they meant a hosted page. Do not proceed without a real URL.

**Step 2 — Domain for file naming.** Take the hostname and strip any `www.`:
`https://www.stripe.com` → `stripe.com`. Store it as `{domain}`. Output directory:
`docs/references/{domain}/`. Create it with Bash: `mkdir -p docs/references/{domain}`.
Never use the generic name `taste.md`.

**Step 3 — Crawl scope.** If the user did not say, ask once:

> "Crawl scope — this page only, or explore 2–3 linked pages?
>  1  This page only       → faster, focused on exactly what you gave me
>  2  Explore linked pages → I'll visit 2–3 nav pages and merge the data"

Store `{crawlScope}`. Default: `single`. Do not ask again. There is no export question: this
skill only writes the two analysis files.

### Phase 1 — Capture page data (Playwright MCP)

Run these steps in order. If any step errors, stop and report the error — do not continue
with degraded data silently.

1. **Resize the viewport** to 1440×900 so measurements are consistent:

   ```
   mcp__playwright-taste__browser_resize  width=1440  height=900
   ```

2. **Navigate** to the URL:

   ```
   mcp__playwright-taste__browser_navigate  url=<the URL>
   ```

3. **Wait briefly** for client-side hydration (heavy SPAs need a few seconds):

   ```
   mcp__playwright-taste__browser_wait_for  time=3
   ```

   If the page still looks like a loading skeleton, wait another 3 seconds. If it is still a
   skeleton, note it in the final output ("page may be incompletely rendered; some
   measurements approximate").

4. **Take two screenshots** — viewport first, then full-page. Use explicit filenames inside
   the output directory:

   **4a. Viewport screenshot** (primary visual reference for Step 1):
   ```
   mcp__playwright-taste__browser_take_screenshot  type=jpeg  filename=docs/references/{domain}/{domain}-viewport.jpeg
   ```

   **4b. Conditional full-page screenshot** — first check the page height:
   ```
   mcp__playwright-taste__browser_evaluate  function=() => document.documentElement.scrollHeight
   ```

   - If **≤ 6× viewport height** (≤ 5400px): take a full-page screenshot:
     ```
     mcp__playwright-taste__browser_take_screenshot  fullPage=true  type=jpeg  filename=docs/references/{domain}/{domain}-fullpage.jpeg
     ```
   - If **> 6× viewport height**: skip full-page (too tall, wastes tokens). Take two
     targeted viewport shots:
     ```js
     // Mid-page (50% scroll)
     mcp__playwright-taste__browser_evaluate  function=() => window.scrollTo(0, document.documentElement.scrollHeight * 0.5)
     mcp__playwright-taste__browser_take_screenshot  type=jpeg  filename=docs/references/{domain}/{domain}-mid.jpeg
     // Footer
     mcp__playwright-taste__browser_evaluate  function=() => window.scrollTo(0, document.documentElement.scrollHeight)
     mcp__playwright-taste__browser_take_screenshot  type=jpeg  filename=docs/references/{domain}/{domain}-footer.jpeg
     // Scroll back to top
     mcp__playwright-taste__browser_evaluate  function=() => window.scrollTo(0, 0)
     ```

   Use the **viewport screenshot** as the primary visual reference in Step 1 — it is the first
   impression the designer intended. Use the others to verify patterns lower on the page.

5. **Run the DOM extractor.** Read `references/extract.js` and pass its **entire contents**
   as the `function` argument:

   ```
   mcp__playwright-taste__browser_evaluate  function=<contents of references/extract.js>
   ```

   The tool returns a JSON object. Keep it as `domData` — you will feed it into Step 1. The
   extractor only reads computed styles and stylesheets; it changes nothing on the page.

6. (Optional cleanup) The browser stays open for the rest of the session.

**Multi-page capture** (only if `{crawlScope}` is `multi`):

After the primary page, extract navigation links and visit up to 2 more pages of the same site.

**6a. Extract nav links** from the primary page:

```js
(function() {
  const links = [];
  const seen = new Set([location.pathname]);
  const skip = /\/(login|logout|signup|sign-in|register|auth|account|checkout|cart|password|reset)\b/i;
  document.querySelectorAll('nav a, header a, [role="navigation"] a').forEach(a => {
    try {
      const u = new URL(a.href);
      if (u.hostname !== location.hostname) return;
      if (skip.test(u.pathname)) return;
      if (seen.has(u.pathname)) return;
      if (u.pathname === '/' && location.pathname !== '/') return;
      seen.add(u.pathname);
      links.push({ href: u.origin + u.pathname, text: (a.innerText || a.textContent).trim().slice(0, 40) });
    } catch(e) {}
  });
  return links.slice(0, 6);
})()
```

**6b. Pick 2 pages** from the list. Prefer shorter paths and distinct section names (Product,
Pricing, Docs — not just different slugs under one section). Avoid the root `/` if already
captured.

**6c. For each extra page**, run a lighter loop (navigate → wait 3s → viewport screenshot
only → DOM extractor). Name screenshots `docs/references/{domain}/{domain}-viewport-2.jpeg`,
`-viewport-3.jpeg`. Store each page's data as `pages[1]`, `pages[2]` (`pages[0]` is the
primary URL). If a linked page fails or is blocked, skip it and note it in the Phase 5 report.

**6d. Merge data** before Phase 2. Combine color and typography candidates across pages
(union). A value on 2+ pages is a **system signal** — mark it. A value on one page is
**local** — keep it, weight it lower. In Steps 1–3 always state how many pages were analyzed
and distinguish system patterns from local ones.

**Success criterion for Phase 1**: at least one screenshot AND a populated `domData` with
`colors`, `typography`, `layout`, `effects`, `cards`, `images`, `spacingSamples`,
`sectionGaps` and `grid`. If any is completely empty while the screenshot shows real content,
note it and proceed.

**Degraded-data path**: if `domData.errors` is non-empty, the extractor partially failed. In
Step 1 mark affected categories `~approx (extractor section failed)` and rely on the
screenshot. In Phase 5 list the failed sections as a caveat.

### Phase 2 — Run the 4-step analysis

> **Screenshot is ground truth.** The viewport screenshot shows what a human actually sees.
> The DOM data supplies exact numbers. When they conflict, trust the screenshot. A color that
> appears in the DOM but covers <5% of the visible surface is decorative — do not list it as a
> brand color. Dividers that do not appear in the screenshot do not exist. Imperceptible
> shadows (≤3% opacity) are CSS artifacts, not design decisions.

The four files in `references/` contain the full prompts for each step. Read each one when you
reach it (do not preload all four; the steps are deliberately sequential).

For each step: read the reference file, generate the output it asks for in your own response,
start it with the marker line the reference specifies, and keep earlier outputs in the
conversation — the next step takes them as input.

- **Step 1 — Measure** (`references/step1-measure.md`): inputs `domData` + screenshot;
  produces 20 categories of measurements, each value cited with px / hex / ratio.
- **Step 2 — Pattern** (`references/step2-pattern.md`): input Step 1; produces 5-8 systematic
  patterns, each with Pattern / Evidence / Design Goal.
- **Step 3 — Taste** (`references/step3-taste.md`): inputs Steps 1 and 2; produces 4 taste
  principles (Trigger / Decision / Reason / Evidence), at least one a Restraint trade-off.
- **Step 4 — Observer** (`references/step4-observer.md`): inputs Steps 1-3 and the original
  URL (substitute it into the JSON's `source` field); produces a fenced ```json``` block
  followed by the Markdown Design Map + Taste DNA.

### Phase 3 — Write the output files

Step 4's response contains both formats:

1. **JSON**: the first ```json``` fenced block. It must be valid JSON; if it is not, re-run
   Step 4 once pointing out the parse error.
2. **Markdown**: everything after the JSON block, with leading whitespace stripped.

Write two files in `docs/references/{domain}/`:

- `docs/references/{domain}/{domain}.md` — the Markdown portion, preceded by one line:
  `Source: <URL> · analyzed on <YYYY-MM-DD> · for style study, not for copying`
- `docs/references/{domain}/{domain}.json` — the JSON, pretty-printed with 2-space indent

If either file exists, overwrite it without asking: the latest analysis wins.

### Phase 4 — Self-audit (Anti-Slop pass)

Run this grep with the Bash tool — do not scan mentally:

```bash
grep -icE 'clean|modern|sleek|visually appealing|user-friendly|intuitive|seamless|\belegant\b|minimalist|polished|refined|sophisticated|delightful|stunning|\bbeautiful\b|\bpremium\b' docs/references/{domain}/{domain}.md
```

If the count is **0**, the file passes. If **>0**, show the offending lines with the same
pattern and `grep -inE`. For each hit: inside a quoted foil ("they could have gone for a
'clean and modern' look, but…") it is fine; used as a positive descriptor of *this* design it
is slop — edit the principle, re-save, and re-run the grep until the count is 0.

Verify both sections exist (must return **2**):

```bash
grep -c "Design Map\|Taste DNA" docs/references/{domain}/{domain}.md
```

Validate the JSON with Node (no Python needed):

```bash
node -e "JSON.parse(require('fs').readFileSync('docs/references/{domain}/{domain}.json','utf8')); console.log('valid')"
```

If any check fails, fix and re-run before shipping.

### Phase 5 — Report

Print to the user (substitute the real `{domain}`, line count and byte count):

```
✓ Wrote docs/references/{domain}/{domain}.md (<line-count> lines) and {domain}.json (<byte-count> bytes)
  Screenshots are kept locally and are git-ignored.

  Sharpest principle: "<name of the strongest taste principle>"
  → <one-sentence quote of its Decision>

  Next: use it as a reference when planning the interface (the planner reads docs/references/).
```

Keep it tight. The files do the talking.

## Error handling

| Failure | Response |
|---|---|
| `playwright-taste` MCP not available | Stop with the message from Prerequisites. Do not fall back to WebFetch. |
| URL unreachable / 404 / DNS fail | Tell the user the page did not load. Do not ship an analysis of an error page. |
| Cloudflare / bot-detection block | The screenshot will show a "verify you are human" page (large whitespace, one "Verify" button). Tell the user the site blocks automated access; suggest a different page of the same domain. |
| SPA still rendering after two waits | Proceed with what is there. Add: "Page may have been mid-hydration; some measurements approximate." |
| File path instead of URL | Ask whether they meant a hosted version. This skill is for live pages. |
| URL behind a login | Detect the login page (form with a password input). Tell the user this skill does not handle authenticated pages; suggest the public page. |
| Step 4 returns malformed JSON | Re-run Step 4 once with the parse error. If it fails again, save the raw output as `docs/references/{domain}/{domain}-raw.md` and tell the user to inspect it. |

## Notes on philosophy (read once, internalize, then mostly forget)

Design tokens alone are useless for an AI agent. Tokens say "spacing is 8px"; taste says
"spacing is 8px *because* the designer chose readable rhythm over data density". The Reason is
what lets the same agent generate good design for a *different* page instead of copying
numbers.

The four prompts in `references/` exist to avoid generic output — paragraphs of "this design
uses a clean, modern aesthetic" that contain zero information. The Anti-Slop checks (banned
phrases, mandatory Restraint trade-off, evidence requirement) are why every weak principle
deleted is worth ten extra well-evidenced ones added.

When in doubt about a principle, ask: "could I have written this without ever seeing this
specific website?" If yes, it is slop. Throw it out.
