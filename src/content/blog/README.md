# Writing a post

Add a `lowercase-hyphenated-slug.svx` file here. The filename becomes `/blog/lowercase-hyphenated-slug`.

```yaml
---
title: Your post title
description: A short summary for the blog list and search engines.
date: "2026-09-13"
draft: true
---
```

Write Markdown below the frontmatter. Start headings at `##`; the page supplies the title. mdsvex also supports importing and embedding Svelte components. Only trusted repository content should be used.

Set `draft: false` (or omit it) to publish on the next deployment. Drafts are excluded from the list, sitemap, feed, and production routes. During `bun run dev`, open the draft's URL directly to preview it; previews are marked noindex. Dates must be quoted `YYYY-MM-DD` strings; they control sorting, not scheduled publishing. Put images in `static/blog/` and reference them as `/blog/image-name.webp` with descriptive alt text.

Run `bun run dev` to preview and `bun run check` before publishing. Posts are prerendered during the site build.

## Math

Use `$E = mc^2$` for inline math, or `$$` on separate lines for a display equation:

```tex
$$
\bar{x} = \frac{1}{n} \sum_{i=1}^{n} x_i
$$
```

KaTeX renders math at build time. Wide display equations scroll horizontally on smaller screens.

## Footnotes

Use named Markdown notes for citations and supporting detail:

```md
A claim with a source.[^guide]

Another reference to the same source.[^guide]

[^guide]: [Official source](https://guide.wisc.edu/), checked September 13, 2026.
```

Notes are numbered automatically and collected under “Notes and sources.” Each repeated reference has its own return link. Navigation works without JavaScript. Keep important qualifications, such as unconfirmed course availability, beside the recommendation rather than hiding them in a footnote.

## RSS

The feed at `/blog/rss.xml` includes published post titles, summaries, dates, and links, newest first. It updates on each deployment and is discoverable from every blog page.

## Guides based on course data

Use `web/blog/evidence.py` to generate a fixed evidence snapshot from an article selection JSON. The generator reads `.site/import/site.sqlite` without changing it. Review the snapshot alongside the prose; builds do not refresh editorial data automatically.

Check requirements and designations against the current official Guide. Verify any claims about future offerings against the published schedule. Distinguish student sentiment, workload reports, and historical grades, and show where review coverage is thin.

Each article should answer a distinct student question, link to the courses and sources it discusses, and explain how its evidence was selected. Update an existing article when the underlying facts change rather than publishing near-duplicate versions each semester.
