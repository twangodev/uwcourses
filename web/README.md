# Website

SvelteKit SSR reads build-generated JSON through Cloudflare Static Assets. HF is the source of truth; Drizzle + D1 serves search, filters, and paginated records.

```sh
bun install --frozen-lockfile
uv run --locked uwcourses-site import --limit 8
bun run dev
```

Omit `--limit` for the complete dataset. `--source /path/to/release` reads a local release; `--revision HF_COMMIT` pins a remote release. The importer is the `uwcourses_site` Python package, installed by uv. Generated `.site/` outputs are disposable and ignored by Git. The importer owns `.site/import`; serving documents, social cards, and browser D1 have separate directories.

```sh
bun run check
bun run test
uv run --locked python -m unittest discover -s web/tests -p 'test_*.py'
bun run site:data
bun x playwright install chromium
bun run site:social
bun run build
bun run seo:check
uv run --locked uwcourses-site assets-check
bun x playwright test
```

Production preview reads the prepared assets and uses a local D1 for interactive queries. After importing a dataset, prepare its browser database before starting preview:

```sh
bun run test:browser:setup
bun run preview --ip 0.0.0.0 --port 4173 --persist-to .site/browser-state
```

`TEST_PREVIEW=1 bun x playwright test` runs browser checks against the production preview. Set `TEST_PORT` to use a different port.

## Cloudflare setup

### WebMCP

The root layout registers catalog tools when `document.modelContext` is available:

- Read: `search_courses`, `get_course`, `get_course_grades`, `search_instructors`,
  `get_instructor`, `get_instructor_reviews`, `get_instructor_courses`,
  `get_instructor_history`, `list_departments`, `get_department`,
  `get_department_catalog`
- Navigate: `open_course`, `open_instructor`, `open_department`, `open_explorer`,
  `open_search`

Read tools reuse the public JSON endpoints and return compact summaries where
documents are large. Navigation tools call SvelteKit `goto` so the student sees
the ordinary page. `webmcp-types` supplies browser typings; Zod validates tool
input and generates its JSON Schema. No runtime polyfill or MCP server is
required. Unsupported browsers continue to use the ordinary interface.

For local testing, enable `chrome://flags/#enable-webmcp-testing`, restart Chrome,
and open the site with the Model Context Tool Inspector extension. Search for
`CS 300`, pass the result's `course_id` to `get_course`, and its `course_uid` to
`get_course_grades`. Check instructor search, department lookup, pagination,
cancellation, and `open_course`. See the [WebMCP documentation](https://developer.chrome.com/docs/ai/webmcp).

### Endpoint inventory

`bun run cloudflare:endpoints` prints the endpoint inventory from the local OpenAPI
spec without network access. It covers the documented JSON/Markdown and `/api`
operations, not every HTML page, static asset, or implicit HEAD request. Cloudflare
requires whole-segment variables, so `/courses/{course}.json` and `.md` map to
`/courses/{course}`. This groups detail HTML/JSON/Markdown traffic together; more
specific registered paths take precedence. The current 40 OpenAPI operations
produce 36 monitoring patterns. Application URLs and OpenAPI remain unchanged.

Set `CLOUDFLARE_ZONE_ID` to the uwcourses.com zone ID and `CLOUDFLARE_API_TOKEN` to a
token with API Gateway edit access scoped to that zone (the API calls this permission
Domain API Gateway). Keep the token in your environment, not in the repository.

```sh
bun run cloudflare:endpoints --plan
bun run cloudflare:endpoints --apply
```

The plan reads all existing zone operations and checks the Free plan's 100-entry
limit, including other hosts in the zone. Apply adds missing operations and verifies
the resulting inventory. Existing operations are preserved; renamed/removed routes
are not deleted automatically. The sole repair exception is the eight exact
percent-encoded detail patterns created by the original sync (for example,
`/courses/%7Bcourse%7D.json`). The plan lists them, and apply removes them only after
their replacements are verified, then verifies removal. Other hosts and encoded
paths are preserved. The zone must have room for replacements before cleanup.
Rerunning is safe after a partial failure.
Verification retries inventory reads over 17 seconds without repeating writes.
CI logs record the accepted operation IDs and patterns; a persistent mismatch
reports the missing and observed operations. Unexpected pattern changes fail
explicitly rather than silently treating broader coverage as equivalent.

This calls the [operations API](https://developers.cloudflare.com/api/resources/api_gateway/subresources/operations/methods/create/)
with host, method, and path only. It does not upload schemas, enable validation,
create routing rules, or configure rate limits. OpenAPI 3.1 can therefore remain the
source. Review registered operations in Security > Web Assets and matched traffic
in Security Analytics; available analytics depend on the zone plan.

Production CI runs the sync after a successful Worker deployment, under the same
deployment lock, and saves `.site/endpoint-sync.json` in the `website-release`
artifact. Pull requests, superseded releases, and unchanged nightly runs do not
sync. Add `CLOUDFLARE_ZONE_ID` as a variable in GitHub's `production` environment
and grant the existing `CLOUDFLARE_API_TOKEN` API Gateway edit access to that zone.
A sync failure fails the workflow after deployment; the website remains deployed.
Fix the credentials or capacity issue and rerun the failed job to retry.

### Deployment

The single D1 database is configured in `wrangler.json` as `DB`. Set `CLOUDFLARE_ACCOUNT_ID` as a GitHub variable and `CLOUDFLARE_API_TOKEN` as a secret in the `production` environment. The token needs Workers Scripts and D1 edit permissions. `HF_TOKEN` is optional for the public dataset.

Run the **Svelte** workflow manually with **First deployment** enabled once to create the Worker. Validate its workers.dev preview, then attach `uwcourses.com` in Cloudflare. Subsequent runs leave that option disabled.

The Svelte workflow checks pushes and pull requests and deploys successful main pushes, manual runs, and nightly runs at 03:17 America/Los_Angeles. Each run resolves HF once to a pinned revision. Import, serving documents, social cards, and browser D1 use separate input-hashed caches with file-integrity manifests; artifacts carry the exact outputs between jobs. App compilation runs alongside document and social-card preparation; `bun run site:assemble` joins their outputs before auditing. Browser tests run on two independent runners. A nightly run skips when both the deployed website commit and HF revision are unchanged.

Only production deployment is serialized. Before production writes, `uwcourses-site deploy` rejects superseded commits, imports D1 only when its projection differs, verifies the database, and publishes matching code/assets. Scraping, inference, and HF publication remain local; no Cloudflare cron is needed.

Imports temporarily disable search/filter queries. Static pages and their JSON/Markdown remain available. A verified-import marker and projection check prevent partial or mismatched query results; requests check before and after querying. Failed imports can be retried, and failed Worker publication reuses a matching completed import. Worker rollback does not restore D1; restore the matching dataset to recover queries after a data rollback. Production jobs are serialized and only this workflow should modify the production database. GitHub stores release metadata for each run.

D1 SQL is emitted as ordered 16 MiB files, with each statement below 100 KB. The workflow imports them sequentially and checks a completion marker and dataset identity before deployment.

History and traces are paged static JSON. Unusually large trace records use ordered text fragments that concatenate to the original JSON. Assets are checked against 90,000 files and 20 MiB per file. Search and filtered grades use `/api`; outdated page requests return 409 and ask the student to reload.

Grades use course aggregates or instructor sections, never both. Identical cross-list distributions are deduplicated; conflicting course/term distributions are preserved for inspection and excluded from calculated GPA. Co-teachers share a section's distribution. Catalog timestamps represent observations, not validity intervals. Instructor identities remain separate even when names match.

Social cards use `web/social-card.html` and are generated automatically from dataset metadata by the Cloudflare adapter, without rendering the website pages. Chromium is required (`bun x playwright install chromium`). The renderer caches unchanged titles, fonts and artwork under `.site/social-cache`; production serves static PNGs, while Vite generates preview cards on demand.

Sitemaps remain build-time assets. Their `lastmod` is the dataset observation timestamp, not the deployment timestamp; priorities and change frequencies are included.

## Public representations

Append `.json` or `.md` to a page URL (`/courses/COMPSCI_300.json`, `/search.md?q=java`); the homepage uses `/index.json` and `/index.md`. HTML advertises both via HTTP `Link` and `<link rel="alternate">`. These are public, read-only APIs with CORS enabled; alternate formats are noindex.

`/openapi.json` serves OpenAPI 3.1, generated from the same Zod schemas used to validate document responses. TypeScript consumers can import inferred types from `src/lib/api/schemas.ts` or generate a client from the spec. Documents are validated during the build; query-dependent responses are validated at runtime. Core entities have named fields; additional source fields use the recursive `JsonValue` schema. The existing `/api` interaction endpoints are also documented and validated.

JSON has `schema_version`, `url`, `title`, `dataset`, and `data`. The dataset includes its pinned HF revision and projection identity. `data` is the same payload the page loader returns; nested LLM evidence and model provenance are retained. Large history/trace files remain linked from that payload rather than duplicated. Markdown renders the same records, with tables and JSON blocks for nested data. Neither format requires browser JavaScript.

Public GET documents are cached for 24 hours in Cloudflare's Cache API. Keys include the deployment, data projection, URL, and query. Browser responses revalidate with ETags. Cache hits still invoke the Worker; the cache is local to each data center. Authenticated/cookie requests, navigation transport, errors, and existing `/api` endpoints bypass this document cache. Preview caching requires `SITE_COMMIT` and `DATA_PROJECTION`; without them requests render directly.

Canonical page loaders and public representations share generated documents. Course comparisons are computed during data preparation and also emitted as compact assets for search badges. Historical instructor profiles are grouped into 4,096 deterministic buckets to bound the file count. `bun run site:data` generates these assets using the shared typed data readers. `bun run site:social` renders social cards; `bun run build` compiles the app and assembles their completed outputs. Rerun the relevant preparation command when its data or generator changes. HTML remains SSR and term controls remain interactive.

Drizzle owns interactive database reads; the Python importer owns the read-model schema and ordered SQL import. Complex FTS and grade aggregations use bound SQL through Drizzle on D1. Development reads the imported local SQLite database.
