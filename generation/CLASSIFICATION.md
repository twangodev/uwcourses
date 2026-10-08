# Local course activity classification

[Laya](https://huggingface.co/convaiinnovations/laya) is an Apache-2.0 open-weight candidate for six evidence-backed activity tags. Its model card reports weak zero-shot typed-decision results and recommends domain tuning/calibration. A high raw probability alone does not enable publication.

The taxonomy `course-activities-v1` contains `programming`, `data-analysis`, `mathematical-reasoning`, `writing`, `lab-work`, and `presentations`. Questions ask only about activities explicitly supported by a short official description/outcome passage. Each is a three-option choice (`yes`, `no`, `unknown`), repeated with reversed option order. There is no generated free text. Qwen extraction remains the fallback for every unvalidated category. Neither command publishes tags or changes archive/course records.

## Prepare manual evaluation data

Keep JSONL outside Git, e.g. `.coursemap/classification/`. One row represents one passage/category decision:

```json
{"course_id":"COMP SCI 200","course_identity":"canonical-crosslisted-course-id","aliases":[],"source_id":"archived-source-identity","source_url":"https://guide.wisc.edu/courses/comp_sci/","passage":"Develop and debug computer programs.","quote":"Develop and debug computer programs.","label":"programming","split":"calibration","gold":true,"reviewed":true}
```

This line demonstrates the format; it is not a verified course fact or manual evaluation result. Replace every field with actual archived source data. `reviewed: true` is required by evaluation; unlabeled templates use `reviewed: false` and are rejected. `gold` is independently manually labeled `true`, `false`, or `null` for unknown. `quote` must occur exactly in `passage`; do not include unrelated instructor ratings or inferred workload. `passage` is limited to 1800 characters: choose individual outcomes or short description passages, the real runtime additionally rejects passages exceeding its reserved token budget rather than silently truncating evidence.

Assign `train`, `calibration`, or `eval` by canonical course identity before labeling; all aliases and passages of a cross-listed course must stay in that same split. The validator rejects split leakage for provided identities/aliases, duplicate decisions, invalid scores, and mixed model revisions. Supply complete alias lists from the course identity table; the classifier cannot discover omitted aliases.

Start with the 40-course source/extraction pilot and extend manual labeling to at least 500 decisions. Laya category acceptance needs larger samples where necessary: at least 20 accepted calibration decisions and 100 accepted held-out decisions **per category**, each at 97% or higher measured precision. Include at least 10 unknown and 10 unrelated held-out cases per category (`case_kind: "unrelated"`); all held-out rows must include reversed-option predictions, whose maximum yes-probability difference must be <=0.05. Unknown accepted decisions count as incorrect. Calibration chooses the lowest successful threshold above 0.5; held-out labels never tune that threshold. These are empirical gates, not statistical confidence guarantees. Independently reviewed evidence is still required before publishing accepted tags.

## Optional local model inference

Use a separate local inference environment rather than adding GPU dependencies to website builds. Install this project and the pinned runtime there (Python 3.12):

```sh
uv venv /tmp/coursemap-laya-env --python 3.12
uv pip install --python /tmp/coursemap-laya-env/bin/python -e . 'laya==0.3.20'
```

Resolve the model's full 40-character Hub commit SHA and record it with the run. Inference explicitly downloads the English checkpoint on first use; no model is loaded by scrape, website build, import, or evaluation. English root has a small context budget; inspect truncation on your real short inputs before accepting performance results. Run:

```sh
USE_TF=0 /tmp/coursemap-laya-env/bin/uwcourses classifier-predict --input .coursemap/classification/labeled.jsonl --output .coursemap/classification/laya-predictions.jsonl --revision FULL_40_CHARACTER_COMMIT_SHA --device cuda
```

The revision must be immutable, never `main`. The adapter resolves the English root artifacts with `huggingface_hub.snapshot_download(revision=SHA)` and supplies that local snapshot path to the pinned Laya SDK; it does not depend on the SDK accepting a revision keyword. Predictions retain original evidence, labels and split plus model revision, taxonomy, full probability maps, reversed probabilities and elapsed time. Missing runtime dependencies produce installation guidance. Output files are created exclusively and never overwritten.

## Offline evaluation and Qwen comparison

```sh
uv run --locked uwcourses classifier-evaluate --input .coursemap/classification/laya-predictions.jsonl --output .coursemap/classification/laya-report.json
```

This command needs no Laya runtime or weights. It reports per-category precision, recall, ECE, accepted coverage, thresholds, reversal checks, enable/fallback status, and SHA-256 of the evaluation records. Throughput is reported only if every prediction includes positive finite elapsed time, and includes both option orders (excluding model load). A report from supplied fixtures is a fixture check, not proof that Laya ran.

For a fair Qwen comparison, use the same manually labeled rows and probability contract, an immutable Qwen revision, and separately recorded timing; evaluate its file separately. Do not synthesize a probability from a generated confidence statement and describe it as calibrated. If Qwen cannot supply comparable probability scores, compare reviewed precision/recall and throughput separately instead. This tooling does not claim either model meets acceptance until genuine held-out results exist.

Fine-tuning and temperature fitting remain separate experiments using only train/calibration splits. A tuned checkpoint must receive a new immutable model ID/revision and a fresh report. No checked-in evaluation counts or thresholds represent a real run.
