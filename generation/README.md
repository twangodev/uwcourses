# Local pipeline

Run from the project root with Python 3.12 and `uv sync --locked`. Scraping,
processing, and publication are independent commands with persistent checkpoints.
Run these manually on the local machine each semester; GitHub Actions does not
scrape or publish datasets. Published data lives on
[Hugging Face](https://huggingface.co/datasets/twangodev/uwcourses).

```sh
export UWCOURSES_WORKSPACE=/path/to/persistent/uwcourses
export MADGRADES_API_KEY=...
uv run uwcourses scrape --semester 1272
uv run uwcourses status RUN_ID
uv run uwcourses resume RUN_ID
uv run uwcourses release RUN_ID
export HF_TOKEN=...
uv run uwcourses publish RELEASE_ID --repo OWNER/DATASET
```

Use UW's four-digit enrollment term code. Scraping collects the catalog, Madgrades
history, and enrollment for that semester, then validates and freezes a source
snapshot. It does **not** require inference servers or download model weights.
Faculty-directory and RMP collection are required. Every instructor lookup must
finish, including all teacher-search and review pages; a successful lookup with
no matching profile is distinct from a failed request. Raw candidates, comments,
ratings, course labels, and dates are retained. Unambiguous profile matches with
explicit course/date attribution feed the LLM student-experience input.

The `buildings` spider also collects the official [campus building directory](https://map.wisc.edu/buildings/)
and each linked map record. It preserves FP&M building numbers (including leading
zeros and suffixes), separate map-object IDs, names, addresses, metadata, center
coordinates, and complete GeoJSON geometry. Individual and partial building
records are retained; group entries without a building number are skipped.
Requests use the same response archive, retry, replay, and source checkpoints as
the other spiders. A failed building crawl prevents the new snapshot from completing.

Releases include a typed `buildings_current` Parquet table for the selected snapshot
and full historical records in `building_observations` and `archive_observations`. These are included in Hugging
Face publication. This is an additive schema-v6 table; older snapshots export an
empty table and older published releases remain readable by the website. Website
imports project the official outlines, retaining holes and multiple polygons, and
use them in the campus maps. The background map remains attributed to OpenStreetMap.
Building names and coordinates from course schedules retain their enrollment source;
the map records do not assert that two source identities are equivalent.

To add or refresh buildings in an existing native snapshot without collecting the
other sources again:

```sh
uv run uwcourses refresh-buildings RUN_ID
uv run uwcourses release NEW_RUN_ID
uv run uwcourses publish RELEASE_ID --repo OWNER/DATASET
```

The refresh creates a new snapshot and preserves reused source timestamps. It
supports `--source-workspace PATH` for a separate destination workspace.
It does not run inference. To retain current LLM fields in a release of the new
snapshot, use the enrichment reuse workflow below and select the resulting job
with `release --enrichment JOB_ID`.

To fill instructor data for an existing snapshot without re-scraping its catalog,
grades, or enrollment, create a new snapshot:

```sh
uv run uwcourses refresh-instructors RUN_ID
```

`--source-workspace PATH` can read an existing snapshot into a separate destination
workspace. Reused observations keep their original timestamps and source-run
provenance; the old snapshot and its LLM jobs remain immutable. Run enrichment
against the new snapshot to include the collected reviews. The LLM input samples
up to 30 reviews across instructors and time periods, without an age cutoff;
all collected reviews remain in the source archive.

Instructor refreshes reuse completed building observations too. If the original
snapshot predates the building spider, the refresh collects the buildings source.

The command prints its ID before starting. Logs live in `runs/RUN_ID/`. A fixed
browser-style user agent is reused on resume. Successful sources are skipped;
interrupted sources reuse archived successful responses and retry failures.
Independent sources continue when another source fails. Defaults allow 32 requests
in flight, 16 per domain, with adaptive throttling targeting 8 per domain and a
0.1-second download delay. Override with `--concurrency`, `--per-domain`,
`--target-concurrency`, and `--download-delay`; limits are recorded in the snapshot. Failed runs never advance
`current_*` views. Keep at least 10 GiB free, plus room for history and exports.

Changed parser code requires a new snapshot. To reuse archived responses:

```sh
uv run uwcourses replay OLD_RUN_ID --source catalog
uv run uwcourses resume NEW_RUN_ID
```

Replay runs sources up through the selected source offline; missing archived
responses fail explicitly. Resume collects the remaining sources normally. Keep
an active scraper on its original checkout and uv environment until it finishes.

## Database maintenance

The generation pipeline uses SQLAlchemy Core over SQLite. Named tables live in
`generation/uwcourses/schema.py`; snapshot, job, response-cache, and release writes
use explicit columns. SQLite-specific views and analytical export queries remain
SQL. Core and those queries share one connection and transaction through
`generation/uwcourses/database.py`.

Writable `Store` and `Jobs` opens automatically apply Alembic migrations under an
exclusive SQLite migration transaction. Existing pipeline schemas v1/v2 and the
original processing schema are recognized and baselined without copying observation
or result tables. Read-only opens do not migrate or stamp databases. Unknown schemas
are rejected. Keep active scraping/inference commands on their original checkout
until they finish before upgrading the workspace.

Private migrations live in `generation/uwcourses/migrations/versions/` and are
forward-only. Add a revision for each schema or view change; preserve old revision
files. The existing SQLite `user_version` remains 2 for snapshot compatibility;
`alembic_version` tracks subsequent private revisions. Disposable release databases
keep their independent archive schema version and contain no migration bookkeeping.

The live `current_*` views select the latest completed run containing course
observations. Auxiliary source runs cannot activate empty course projections or
serve as enrichment/release course snapshots. Their observations remain available
in release history. Records with conflicting payloads from multiple sources require
an explicit source selection. Term records retain the existing precedence explicitly:
Madgrades, then enrollment, then legacy. A source refresh still requires explicit
enrichment reuse; changing database libraries does not rebind generated results.

## Optional processing

For official learning outcomes, cited skills, and the source-only pilot, see
[COURSE_SKILLS.md](COURSE_SKILLS.md). The optional local System 1 classifier and
its held-out acceptance gates are documented in [CLASSIFICATION.md](CLASSIFICATION.md).

Model profiles live in `inference/models.toml`. Pin the selected profiles once;
both clients and server launchers use the resulting JSON file:

```sh
uv run uwcourses models-lock --models-config inference/models.toml \
  --profile enrichment \
  --output "$UWCOURSES_WORKSPACE/models.lock.json"
```

Start the generation server for the chosen profile:

```sh
uv run python scripts/serve_inference.py --workspace "$UWCOURSES_WORKSPACE" \
  --models-config "$UWCOURSES_WORKSPACE/models.lock.json" --profile enrichment
```

The separate `inference/` uv project locks vLLM and its GPU dependencies. Servers
bind to loopback; `--dry-run` prints a launch command without downloading weights.
Profiles control model/revision, token limits, dimensions, document prefix,
concurrency and server arguments. Alternative vLLM/SGLang servers can
use the same HTTP boundary; serve the identity `HF_MODEL_ID@COMMIT_SHA` and record
the actual engine/version in the profile. Optional authentication uses
`COURSEMAP_INFERENCE_API_KEY`. No client loads model weights directly.

The default generation candidate is Qwen3.6-35B-A3B-FP8. Select
`enrichment-nvfp4` for NVIDIA's Qwen3.6-35B-A3B-NVFP4, or `enrichment-bf16` as a
reference. Lock that profile and use the same name in the server and enrichment
commands. These are configurable candidates, not task-quality benchmark results.
Concurrency and token limits are profile settings. Lock profiles again to adopt
changed defaults. Run one generation profile at a time.

For generative enrichment, start with a stable sample of 100 courses:

```sh
uv run uwcourses enrich RUN_ID --models-config "$UWCOURSES_WORKSPACE/models.lock.json" \
  --task inference/tasks/course_profiles.json --limit 100
uv run uwcourses job-status ENRICHMENT_ID
uv run uwcourses enrich-resume ENRICHMENT_ID
```

`--prepare-only` creates a job without contacting inference; `--limit 0` selects
all courses. The task manifest defines source inputs, Markdown prompt files, a JSON Schema file, and task
version. The initial task produces summaries, topics, skills, and search phrases;
topic/skill evidence must quote the description. It does not estimate workload,
grades, or instructor quality. Schema and exact-quote checks reject malformed
outputs, but human review is still needed to assess semantic quality.

`processing.sqlite` records per-course inputs, outputs, usage, failures, and
immutable task/model provenance. A single writer commits bounded concurrent HTTP
results. Resume retries unfinished courses; unchanged inputs reuse validated
outputs across snapshots. Prompt, schema, model, and generation settings change
the cache identity. Completed jobs cannot be silently overwritten.

Explicitly select optional outputs for a release:

```sh
uv run uwcourses release RUN_ID --enrichment ENRICHMENT_ID
uv run uwcourses publish RELEASE_ID --repo OWNER/DATASET
```

Repeat `--enrichment` to attach multiple completed jobs. Partial or failed jobs
cannot be released; completed samples include their coverage counts. A source-only
release remains available even when an optional model job fails. Scraping,
derivation, enrichment, and publication have separate locks; different processing
jobs can run alongside a scrape. Each build/job permits only one active worker.

## Qwen requirements parsing

For combined search metadata, requirements, and evidence-backed student experience,
use `inference/tasks/course_enrichment.json` with the `enrichment-unified` profile:

```sh
uv run uwcourses models-lock --models-config inference/models.toml \
  --profile enrichment-unified --output "$UWCOURSES_WORKSPACE/unified-models.lock.json"
uv run uwcourses enrich RUN_ID --models-config "$UWCOURSES_WORKSPACE/unified-models.lock.json" \
  --profile enrichment-unified --task inference/tasks/course_enrichment.json \
  --course "CS 300" --course "CS/ECE 759"
```

One conversation plans local `get_course` lookups, generates all sections, and can
repair rejected sections without overwriting accepted ones. The bulk task defers failed ASTs so search metadata can finish without expensive
AST retries. For focused repair runs, set `ast_repair_attempts` to 1 or 2 in a copy
of the task JSON. Those repairs enable thinking and receive the rejected candidate
and combined quote, cycle, reachability, and global-exclusion diagnostics. Each
attempt records its thinking setting and rejected AST in dataset provenance. Lookups use the same
snapshot, at most six calls and depth two; no browsing or code execution occurs.
Consulted-record hashes (including missing lookups) invalidate cached results when
their evidence changes. Original requirement text/AST and normalized display text
remain distinct. Related descriptions inform background, never formal eligibility.
Requirement graphs pass deterministic validation and are compared with the legacy
AST when possible. Structural disagreements require review; neither parser is
automatically authoritative. Search citations may reference the root title or description. Explicitly excluded
courses cannot supply assumed-background claims; summaries ending mid-clause are
rejected for correction. Citation aliases, quotation styles, and abbreviated quotes are resolved
only against supplied records and ordered verbatim source fragments; repairs are
recorded in the result.

Each section has its own status: `valid`, `needs_review`, `invalid`, or
`insufficient_evidence`. Job completion means processing finished, not that every
section passed. Instructor-wide RMP comments lacking course/date attribution cannot
support course sentiment. The current collector does not supply attributable
course reviews; those sections explicitly report insufficient evidence.

Dataset exports include all sections and rejected candidates in
`enrichment_sections`, with the model name and immutable revision. Full results
retain settings, task/worker versions, lookup traces, dependencies, history, and
source requirements. The dataset card lists the exact generation model strings.
To select these outputs, use `uwcourses release RUN_ID --enrichment JOB_ID`.

Lock the `requirements` profile and launch it using the same model-server command.
It uses Qwen3.6-35B-A3B-NVFP4 with a 16K context and 4K output budget:

```sh
uv run uwcourses enrich RUN_ID --models-config "$UWCOURSES_WORKSPACE/qwen-models.lock.json" \
  --profile requirements --task inference/tasks/requirements.json --limit 100
```

The task receives raw requirements text and linked course references, excluding
existing parser output. Results contain an AND/OR/NOT tree, course timing and grade
qualifiers, verbatim non-course conditions, evidence quotes, and review notes.
Structural validation rejects cycles, missing nodes, invented course references,
and quotes absent from the source. Ambiguous rules are marked `needs_review`.
Whitespace-equivalent evidence is restored to its literal source substring before
validation; other quote differences are rejected. Retries receive validation
feedback. The model sees the schema as well as the constrained output grammar.
A separate `Not open to students with credit for ...` sentence must constrain all
eligibility alternatives in a parsed result. Review notes are bounded, and failed
rows retain a short validation reason for diagnosis.
These checks cannot prove semantic equivalence; review the pilot before using the
results for eligibility decisions. Parsed requirements remain
separate enrichment records, with the original wording preserved.

Run the small manually checked regression benchmark before changing the task or
model, then inspect a fresh catalog sample. The benchmark checks Boolean grouping,
exclusions, grades, concurrency, and review status; it is a development suite,
not an estimate of catalog-wide accuracy.

```sh
uv run python scripts/evaluate_requirements.py \
  --models-config "$UWCOURSES_WORKSPACE/qwen-models.lock.json" \
  --output "$UWCOURSES_WORKSPACE/audits/requirements-eval.json"
```

## Storage and Hugging Face

`pipeline.sqlite` stores versioned observations and source checkpoints. Compressed,
content-addressed raw responses remain local. Keep the workspace private: raw
bodies and Scrapy queues may contain authentication details. They are not exported.

`releases/RELEASE_ID/` contains a public relational SQLite database, equivalent
Parquet tables, a dataset card, and a checksummed manifest. Nested source structures
remain JSON columns. History joins by `run_id`; `current_*` views select the chosen
snapshot. Releases record source history, exporter identity, selected build/model
provenance, and enrichment coverage. Releases contain dataset tables, schema metadata, and provenance.
Schema v4 stores complete distinct course records in `course_versions` and their
presence in each run in `course_snapshots`. A changed description or other source
field creates a new version; unchanged courses reuse the version. `courses` and
`course_history` remain convenient SQLite views. Parquet consumers join the two
base tables with `runs`; the old `courses.parquet` is replaced by these tables.
Course IDs retain source identity; renumberings are not silently merged.

All completed enrichment jobs for included snapshots are exported automatically.
`enrichment_outputs` deduplicates cached outputs; `course_enrichment_runs` connects
them to course snapshots and jobs. `enrichment_output_sections` retains section
statuses and rejected candidates. SQLite `course_enrichments` and
`enrichment_sections` provide the expanded view, while `course_enrichment_history`
adds course-version and semester context. `--enrichment` selects jobs for the
`current_*` enrichment views; archived experiments are never implicitly selected.
Unfinished jobs are excluded. Completed-job content hashes are part of release
identity, so later enrichment creates a new immutable release. Source observations,
grades, offerings, and meetings retain their per-snapshot history.

To inspect description changes:

```sql
SELECT semester, observed_at, version_id, description
FROM course_history WHERE course_id = 'COMPSCI 300'
ORDER BY observed_at, run_id;
```

Missing required data, reference errors, and unexplained count drops block source
completion. SQLite foreign keys and file hashes are checked before publication.

HF uploads are explicit, batched, resumable, and tagged by immutable revision.
Only a completed upload promotes `latest.json` on the dataset's main branch;
concurrent pointer changes block promotion. Consumers read that pointer and use
its exact `revision` for every file. SQLite/Parquet and Dataset Viewer configuration
live on the release revision. Website paths map to
`web/<sha256(logical_path)[:2]>/<logical_path>` to avoid oversized HF directories.

The same promotion updates `sync.json` with scan timestamps, course count, snapshot
count, and data revision. Shields dynamic JSON badges can read `$.last_scan_utc`
and `$.courses` from its `raw/main/sync.json` URL; badge caches delay refreshes.

No Cloudflare deployment is activated here. Scraping runs manually on this machine.
Retired combined runs require their original checkout; use a new snapshot for new work.

Instructor reconciliation indexes parsed names by exact normalized surname, then
uses up to 24 CPU processes in batches of 256. Set `COURSEMAP_NAME_WORKERS` to
change the worker count. A single writer checkpoints results; cache keys include
the candidate roster, and ties use stable candidate ordering.

## One-time backfill

```sh
uv run python scripts/backfill_legacy.py --repository /path/to/uwcourses/data \
  --workspace "$UWCOURSES_WORKSPACE" --all
```

Without `--all`, imports HEAD only. Each Git commit imports atomically and is safe
to rerun. Observation timestamps prevent old backfills replacing newer snapshots.
Legacy course/instructor JSON and available meetings are retained; unavailable raw
responses and model provenance are not invented. Historical grade totals are
snapshots: **do not sum them across runs**. Legacy snapshots can be released or
used for generative enrichment without rebuilding their unavailable source responses.

## Checks

```sh
uv run python -m unittest discover -s generation/tests -v
uv run ruff check generation scripts/serve_inference.py
uv run ruff format --check generation scripts/serve_inference.py
```

## Public datasets

`release` also writes typed `public/*.parquet` tables: `courses_current` (the HF
Viewer default), `courses_history`, `catalog_versions`, `grades_latest`, and
`offerings_current`, plus course identities/aliases, observation links, instructors,
section grades and teacher links, current classes/meetings, and version-bound LLM
results and traces. Preserve the workspace's `course-identities.json` across runs;
`public/course_identity_registry.json` provides a portable recovery copy.
Lists are native Parquet lists, grade counts are integers,
credits are nullable numbers, and observation times are UTC timestamps. Flexible
requirement ASTs remain JSON. `public/schema.json` describes each row and column.
The archive remains available under `archive_*` HF configurations.

Catalog IDs hash identity, title, description and original requirement text;
changes to grades, term activity or parser output do not create catalog versions.
Full-record IDs still link to the complete archive. `grades_latest` selects one
latest observation per course and grading term across included snapshots; it does
not sum repeated scrapes. Credits come from current enrollment offerings and are
null when unavailable. Only explicitly selected LLM jobs populate public courses;
the newest selected job per course wins. Rejected search metadata stays out of public search fields. Requirement trees
retain their validation status and always provide at least one display node.

To build a small public release from an existing verified archive without copying
its SQLite/history tables or running inference:

```bash
uv run uwcourses --workspace "$UWCOURSES_WORKSPACE" public-export RELEASE_ID
```

This writes a separate checksummed release with the archive ID and manifest hash.
Consumers read the Parquet tables and pin one HF revision for consistent joins.
Search indexes and website responses belong to the consuming Worker; the pipeline
does not generate static JSON shards, maps, sitemaps, or website graphs.

Resume inference with a scheduling override (1–512 concurrent client workers):

```bash
uv run uwcourses --workspace "$UWCOURSES_WORKSPACE" enrich-resume JOB_ID --concurrency 384
```

This preserves the job's model/task configuration and completed checkpoints;
fresh outputs record `provenance.client_concurrency`. The vLLM server's
`--max-num-seqs` and `--max-num-batched-tokens` must be configured separately.

Rejected sections can be repaired in a separate, resumable conversation job:

```bash
uv run uwcourses --workspace "$UWCOURSES_WORKSPACE" enrich-repair PARENT_JOB_ID \
  --models-config models.lock.json --profile enrichment-unified --limit 20 --turns 3
```

Use `--limit 0` for all rejected courses, or repeated `--course` canonical IDs for
specific failures. Each turn sends the preceding assistant response and exact
validator feedback back to the same pinned Qwen model with thinking enabled.
Accepted sections are locked. The result preserves the parent output hash,
section origins, full repair conversation, and each attempted validation. A job
can complete with unresolved sections after its bounded retry budget; those stay
invalid or review-required. Missing review evidence is not repairable by inference.
Use `enrich-resume` with the new job ID after interruption.

PydanticAI owns generation, native `get_course` tool calls, and validator-driven
`ModelRetry` conversations. Install through the root `uv.lock`; only its slim
OpenAI-compatible client extra is required. vLLM remains the local inference
engine. `profiles.enrichment-unified` enables the Qwen XML tool parser and uses a
32K context, 16K output budget, and the measured 192-sequence/256-client throughput
settings. Hardware power limits are managed separately.

Jobs record their worker version. Resume older jobs from their original checkout;
the worker-version check prevents mixing implementations. The exact PydanticAI
version is included in job identity, cache keys and output provenance. Native
message histories (including tool returns and retry feedback) are saved in
`provenance.conversation`, without the private inference URL. Chained repairs can
reload these histories with `ModelMessagesTypeAdapter`. Completed course results
remain the durable checkpoint boundary; an interrupted in-flight course restarts
from its saved input/parent conversation. SQLite still owns job state and source
history; public Parquet contracts are unchanged.

Course agents use PydanticAI tool-output mode (`submit_sections`) alongside
`get_course`; the live Qwen/vLLM check showed native-JSON mode can suppress tool
calls. Generic extraction tasks without tools use native structured JSON.

The unified profile uses temperature 0.6, top-p 0.95, and top-k 20. A thinking-only
token-limit failure gets one recovery continuation with thinking disabled. Its
original trace is retained in `provenance.recovery_events`; the continuation
omits unfinished thinking to avoid repeating it and overflowing the context.
Accepted sections remain locked, and the shared request/tool budgets still apply.

Chained repairs retain the direct-output fallback after a previous thinking
truncation, rather than re-entering the same failed thinking mode.

Plain JSON final submissions use PydanticAI TextOutput and the same section
validators when vLLM does not return a tool-call envelope. This fallback never
executes tools described in text.

Use `uwcourses --workspace PATH job-report JOB_ID` for a read-only snapshot of
completion counts, section quality, failure categories, truncation recoveries,
recorded usage, and verification that retained sections were unchanged. A
completed job can still contain rejected or review-required sections.

The public `llm_traces` Parquet config preserves each archived job/course output
and its task/model settings, including recorded Qwen thinking, tool calls,
validator feedback, and truncation recovery conversations. `has_conversation`
distinguishes older outputs without recorded histories. Traces are separate from
current-course rows and include rejected and unselected experiments for auditing.

Long repair runs can resume with `enrich-resume JOB_ID --concurrency 256
--request-timeout-seconds 1800`. Execution overrides are recorded on new results;
they do not change model sampling, job identity, or completed checkpoints.

Repair jobs revalidate saved candidates before spending inference tokens. Safe
source-only normalization and its field changes are recorded; outputs accepted
without a new model call have `provenance.validation_only=true` and retain the
original trace and parent-output hash.

Context-window errors allow one compact repair continuation with current source
evidence, lookup results, rejected candidates, and validator errors. The discarded
conversation remains in `recovery_events`; request and tool budgets remain shared.

`public/rmp_reviews.parquet` retains all comments on matched RMP profiles, including historical instructors. Rows retain source review/profile IDs, dates, scores, and original course labels; unresolved course links remain null. LLM sentiment uses a bounded historical sample and cites its review evidence.

For a review refresh, repeat `enrich --reuse-job JOB_ID` for the previously selected jobs. Unchanged source and lookup evidence is revalidated before retaining search/requirements sections with their original provenance. Review sentiment is regenerated; courses without attributable reviews need no model call when their other sections can be reused. Ambiguous eligibility rules retain a best-effort Boolean tree, the source text, and assumptions in notes, marked `needs_review`.

Sentiment themes include deterministic `scope` metadata (cited instructors and review-year range), derived from their review IDs. Model-written leading date labels are normalized to that evidence with the original text recorded in the trace.

Parquet-only HF publication
--------------------------

`uv run uwcourses publish RELEASE_ID --repo twangodev/uwcourses --parquet-only`
uploads public and archive Parquet tables, the minimal dataset card, manifest, and
`sync.json` together. It verifies remote sizes and hashes. The SQLite source archive stays local. Sync metadata identifies the release and manifest checksum,
so it survives a later repository-history squash.

For targeted repairs with corrected instructions, `enrich-repair --task PATH`
accepts a versioned task with the same output schema. Accepted sections remain
locked. Review citation handles are resolved exactly to the original IDs; raw
comments and model conversations remain in the dataset.

Public prerequisite ASTs are best-effort display trees and always have a root node. Trees marked `needs_review` remain available. Failed, missing, or empty parses fall back to one original-text condition node (or “No prerequisites listed” when empty). The original LLM status and archived outputs remain unchanged; these display trees are not eligibility decisions.

Instructor-specific review themes include `subject_instructor_id`, the instructor name in their summary, and review citations for that instructor and course. Teaching themes must name their subject. Historical scope remains explicit; the review sample does not establish a student-wide preference or instructor ranking.

Edit prompt text in `inference/prompts/`, output contracts in `inference/schemas/`, and versions/options in `inference/tasks/`. Prompt paths resolve relative to the manifest. Jobs store the resolved text and schema, so later file edits do not change recorded jobs; content changes also invalidate cached outputs. Inline prompt/schema tasks remain supported.

For student-focused previews, run `enrich` with `--task inference/tasks/student_summary.json` and `--reuse-job` for the selected catalog enrichment jobs. The workflow uses the snapshot's current enrollment roster, summarizes each professor independently, and keeps other instructors’ reviews in a historical paragraph. Grade sentences are computed temporarily from raw letter-grade counts for the last three usable terms; no aggregate-stat table is exported. Review and grade citations identify their source rows. Results appear in `llm_student_summary_json`; prerequisite trees and supported catalog metadata are retained. Empty catalog descriptions suppress inferred search metadata; the source title and original archived output remain available.

Student previews also include cited teaching-term history without predicting future schedules. A separate grounding check compares each draft claim with its cited reviews and returns substantive errors to the same repair conversation. Writer and checker traces are retained, including failed attempts; schema validity alone does not establish factual accuracy.

Grade and teaching citations also include `source_record`, identifying the archived observation by file, source, kind, and entity ID. Together with the citation’s run, term, and optional section number, this remains resolvable after a later snapshot replaces the row in a latest-only table.
