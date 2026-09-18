# Development

Use Svelte 5 runes and modern event handlers. Bun manages frontend dependencies; uv manages Python. Keep generated data out of Git.

```sh
bun install --frozen-lockfile
uv run --locked uwcourses-site import --limit 8
bun run dev
bun run check
bun run test
uv run --locked python -m unittest discover -s web/tests -p 'test_*.py'
bun run build
uv run --locked uwcourses-site assets-check
bun x playwright test
```

The website is SvelteKit on Cloudflare Workers Static Assets + D1. `web/uwcourses_site` validates HF Parquet and builds disposable serving projections. `src/lib/server/data.ts` owns SQL queries. The nightly GitHub workflow uses native Wrangler commands and one D1 database for search. Page documents are built as static JSON and rendered on demand.

Scraping, LLM inference and HF publication remain independent local operations under `generation/uwcourses`. Use `uv run uwcourses`; do not couple inference to website builds. Test pipeline changes with `uv run python -m unittest discover -s generation/tests`.

Use the warm paper/charcoal palette and red accents from the Wisconsin reference site, with Overused Grotesk throughout. Use LayerChart for charts and Svelte Flow for prerequisite interaction. Preserve source identities, citations, uncertain requirement nodes and grade deduplication.

Use focused Conventional Commits and keep main deployable. Preserve unrelated work and use isolated worktrees for changes.
