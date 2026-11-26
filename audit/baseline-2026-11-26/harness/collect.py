"""Build scorecard.csv from results/*.json plus each run's helper log (interaction count and seconds come from the helper,
not from the tester). Usage: python collect.py <audit-dir> <out.csv>   (audit-dir holds results/ and run_<ID>/)"""
import csv, glob, json, os, statistics as st, sys
root, out = sys.argv[1], sys.argv[2]
CATS = ['feature_discoverability', 'ease_of_use', 'visual_quality', 'information_hierarchy', 'clarity_of_terminology', 'workflow_efficiency',
        'navigation_clarity', 'system_feedback', 'error_prevention', 'error_recovery', 'accessibility', 'overall_user_experience']
rows = []
for p in sorted(glob.glob(f'{root}/results/*.json')):
    if 'invalid' in p:
        continue
    r = json.load(open(p)); i = r['test_id']
    log = f'{root}/run_{i}/actions.jsonl'
    acts = [json.loads(l) for l in open(log)] if os.path.exists(log) else []
    rt = r.get('ratings', {}); nums = [v for v in rt.values() if isinstance(v, (int, float))]
    rows.append(dict(test_id=i, usability_status=r.get('completion_status'), helper_interactions=len(acts),
                     seconds=round((acts[-1]['t'] - acts[0]['t']) / 1000) if len(acts) > 1 else 0,
                     wrong_turns=len(r.get('incorrect_navigation_attempts', [])), mean_rating=round(st.mean(nums), 2) if nums else '',
                     **{k: rt.get(k) for k in CATS}))
with open(out, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows), 'cases ->', out)
