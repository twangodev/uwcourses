"""Rebuild the fixed STAT 301/371 comparison evidence from the local import."""
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from evidence import summarize

ROOT = Path(__file__).resolve().parents[2]
status = json.loads((ROOT / '.site/import/status.json').read_text())
result = {'source': {k: status[k] for k in ('repository', 'revision', 'projection_id', 'observed_at')},
          'review_window': {'start': '2021-09-01', 'end': status['observed_at'][:10]},
          'grade_window': {'start': '1222', 'end': '1264'}, 'courses': []}
with sqlite3.connect(f'file:{ROOT}/.site/import/site.sqlite?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    for code in ('STAT 301', 'STAT 371'):
        course = db.execute('SELECT uid FROM courses WHERE code=?', (code,)).fetchone()
        if course is None:
            raise ValueError(f'Missing course: {code}')
        grades = [dict(r) for r in db.execute('SELECT term,a,ab,b,bc,c,d,f FROM grade_summaries WHERE uid=? AND term BETWEEN ? AND ? ORDER BY term', (course['uid'], '1222', '1264'))]
        reviews = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM reviews WHERE course_uid=? ORDER BY review_date,profile_id,review_id', (course['uid'],))]
        recent = [r for r in reviews if result['review_window']['start'] <= str(r.get('review_date') or '')[:10] <= result['review_window']['end']]
        records = [{**{k: r[k] for k in ('source_review_id','source_instructor_id','instructor_name','review_date','source_url')}, 'comment_sha256': hashlib.sha256((r.get('comment') or '').encode()).hexdigest()} for r in recent]
        result['courses'].append({'code': code, 'uid': course['uid'], 'pooled': summarize(grades), 'terms': [{'term': r['term'], **summarize([r])} for r in grades], 'captured_reviews': len(reviews), 'review_records': records, 'review_counts_by_instructor': dict(Counter(r['instructor_name'].strip() for r in recent))})
target = ROOT / 'static/blog/stat-301-vs-stat-371-uw-madison.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
for c in result['courses']:
    print(c['code'], c['pooled'], len(c['review_records']))
