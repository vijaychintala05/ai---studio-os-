"""Side-by-side, never invent unrun model results.

python -m tests.compare_benchmarks  # use after generating benchmark_results_demo.json
python -m tests.run_benchmark_v2 --provider openai
python -m tests.compare_benchmarks
"""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent.parent
FIX=json.loads((ROOT/'tests/benchmark_v2_37cases.json').read_text())

def load(which):
    p=ROOT/f'benchmark_results_{which}.json'
    return json.loads(p.read_text()) if p.exists() else None

demo=load('demo'); live=load('openai')
if demo is None:raise SystemExit('Run the offline benchmark first')
d={r['id']:r for r in demo['results']};l={r['id']:r for r in live['results']} if live else {}
rows=['# StudioOS v0.5 — Demo vs live provider benchmark', '',
      '## Measurement status', '',
      '| Metric | Offline demo | OpenAI live |','|---|---|---|',
      f"| Cases passed | {demo['summary']['passed']}/{demo['summary']['total']} | {str(live['summary']['passed'])+'/'+str(live['summary']['total']) if live else 'NOT RUN — no API key'} |",
      f"| Questions raised by test responses | {demo['summary'].get('questions_asked','N/A')} | {live['summary'].get('questions_asked','N/A') if live else 'N/A'} |",
      f"| API requests | 0 | {live['summary']['usage'].get('calls','N/A') if live else 'N/A'} |",
      f"| Estimated model token cost (USD) | $0.00 | ${live['summary']['usage'].get('reported_cost_usd',0):.6f} (configured rates)" if live else '| Estimated model token cost (USD) | $0.00 | N/A |',
      '',
      'Live model calls are explicitly limited to an isolated fictional benchmark database, one call per chat message, zero model tools, and a backend authorization ledger. Reported costs use operator-configured per-token rates and are not verified provider invoices.',
      '', '## Per-case results', '',
      '| Case | Category | Demo | Live model | Live questions | Live estimated cost |',
      '|---:|---|---|---|---:|---:|']
for case in FIX['cases']:
    i=case['id'];x=d.get(i,{});y=l.get(i,{})
    usd=((y.get('usage') or {}).get('charged_micro') or 0)/1_000_000
    rows.append(f"| {i} | {case.get('category','—')} | {x.get('status','MISSING')} | {y.get('status','NOT RUN')} | {len(y['actual_questions']) if 'actual_questions' in y else '—'} | {f'${usd:.6f}' if y.get('usage') else '—'} |")
rows+=['','## Failures and untested cases','']
if not live:
    rows+=['**Live model was not run:** `OPENAI_API_KEY` was not available in this environment. No model requests were made. Accordingly, there are no live model outputs or live pass/fail scores to report.',
           '', 'Run `python -m tests.run_benchmark_v2 --provider openai` only after setting a test key, configured model price rates, and a daily budget in your local `.env`. Then rerun this comparison command.', '']
else:
    for case in FIX['cases']:
        x=l.get(case['id'],{})
        if x.get('status')=='PASS':continue
        rows.extend([f"### Case {case['id']} — {x.get('status','NOT RUN')}",'',
            '**Failed checks:** '+ ('; '.join(x.get('errors',[])) or 'No output'),'',
            '**Raw model output (fictional benchmark only):**','', '```json',
            x.get('raw_model_output') or '(unavailable: provider produced no accessible output)',
            '```',''])
rows+=['## Known limitations','',
    '- Demo tests grade a defined subset of expected fields and behavior; they are not proof of general language understanding.',
    '- Chromium rendered the real HTML/CSS/JS using fictional mock API JSON because local server navigation was blocked by the sandbox.',
    '- Live API accuracy, runtime billing, tokens and prompt-injection resistance remain untested unless live results are present above.',
    '- The backend spend gate uses operator-defined model rates and upper-bound reservations; it cannot guarantee provider invoices or unknown billing items. Use provider-account limits too.',
    '- No real NAS, customer records or production database was connected.',
    '- PostgreSQL, multi-user concurrency, audio/photos, actual native CAD analysis, and deployment security remain untested.',
    '- Ticket approvals and financial approvals remain separate, unchanged from v0.4.', '']
(ROOT/'V05_COMPARISON_REPORT.md').write_text('\n'.join(rows))
print('Wrote',ROOT/'V05_COMPARISON_REPORT.md')
