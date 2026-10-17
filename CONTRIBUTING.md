# Contributing to Snipe Systems

Thanks for wanting to contribute. This repo is the Snipe Systems company site and Library — the growing archive of articles, stories, and research reports. Everything here is licensed under Apache-2.0 (see `LICENSE`).

## Repo layout

| File | What it is |
|---|---|
| `index.html` | Page markup (hero, holdings, principles, Library, footer). |
| `styles.css` | All styles. No CSS framework — plain CSS. |
| `app.js` | Library data + reader logic. **This is where new pieces go.** |
| `LICENSE` | Apache-2.0 license text. |
| `CONTRIBUTING.md` | This file. |

The site is static — no build step. Open `index.html` in a browser, or serve the folder (`python3 -m http.server`) and visit `http://localhost:8000`.

## Adding a piece to the Library

Append one object to the `LIBRARY` array at the top of `app.js` (newest on top — entries render newest-first by array order):

```js
{
  id: "unique-slug",
  type: "Article",              // "Article" | "Research Report" | "Story"
  date: "October 17, 2026",     // display date
  title: "Title",
  dek: "One-line standfirst.",
  excerpt: "List-view summary.",
  mins: 6,                      // reading time in minutes
  body: [
    { h: "Section heading" },
    { p: "Paragraph text." },
  ],
}
```

Rules for Library pieces:

- **Facts must be verifiable.** Every number, date, and product claim needs a source. Link sources where the piece is presented, or note them in the PR.
- **No invented figures.** If a number can't be sourced, cut it — don't estimate it into the text.
- **Corrections beat speed.** If you spot an error in an existing piece, open a PR fixing it. Corrections are first-class contributions here.
- **Match the voice.** Direct, concrete, no hype. End pieces with statements, not rhetorical questions.

## Other contributions

- **Design / CSS:** keep it readable on mobile and desktop, no new dependencies without discussion.
- **Fixes:** typo, layout, or accessibility fixes are always welcome.
- **Ideas:** open an issue first for anything bigger than a small fix, so work doesn't duplicate.

## How to contribute

1. Fork the repo and create a branch (`git checkout -b add/my-piece`).
2. Make your change. Preview it locally (see above).
3. Note what you changed in modified files (Apache-2.0 §4(b) asks modified files to carry a notice that you changed them — a short comment at the top of the file is enough).
4. Open a pull request against `main` describing what you changed and, for Library pieces, where each load-bearing fact came from.

## What won't be merged

- Unverified numbers or claims presented as fact.
- Promotional content, referral links, or affiliate links.
- Anything that changes the license, removes attribution, or adds a dependency that phones home.

Questions? Open an issue — that's the right place for them.
