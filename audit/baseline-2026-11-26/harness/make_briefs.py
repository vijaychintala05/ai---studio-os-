import json,os,subprocess,sys
pub={c['test_id']:c for c in json.load(open('/tmp/aud/cases_public.json'))  # kept outside git: it contains the synthetic logins}
WAVE=sys.argv[2].split(',')
port0=int(sys.argv[1])
os.makedirs('/tmp/aud/briefs',exist_ok=True)
BRIEF='''# Usability test brief: {id}

You are a first-time user of a business web application used by an architecture and construction firm. You have never seen it before and nobody will explain it. Your job is to find out how to do ONE thing, using only what you can see on the screen, exactly as a new employee would.

## Your account
- Your role: {role}
- User name: {user}
- Password: {pw}
- The application is already open in a browser, on its sign-in page. You cannot type an address.

## Your objective
{objective}

## Information you may need
{data}

## How you control the browser (the ONLY way you may touch the application)
A helper program is running. Use Bash with curl against it, and nothing else, to act on the application:
- See the screen: `curl -s "http://127.0.0.1:{port}/shot"` returns a file path; then look at it with the Read tool (it is a screenshot, 1366 by 768 pixels; coordinates are measured from the top-left of that picture).
- Click: `curl -s "http://127.0.0.1:{port}/click?x=100&y=200"` (also /dblclick, /rightclick, /move)
- Type text into the focused box: `curl -s -G "http://127.0.0.1:{port}/type" --data-urlencode "text=hello"`
- Press a key: `curl -s "http://127.0.0.1:{port}/press?key=Enter"` (Tab, Escape, ArrowDown, Control+a ...)
- Scroll: `curl -s "http://127.0.0.1:{port}/scroll?dy=400"` (negative scrolls up)
- Wait: `curl -s "http://127.0.0.1:{port}/wait?ms=1000"`
- Browser back: `curl -s "http://127.0.0.1:{port}/back"`
- Choose a file after you have clicked an upload control that opens a file dialog: `curl -s -G "http://127.0.0.1:{port}/upload" --data-urlencode "path=/tmp/aud/assets/<file>"` (only files in /tmp/aud/assets)
- List files the browser downloaded: `curl -s "http://127.0.0.1:{port}/downloads"` (you may Read a downloaded file)
- When completely done: `curl -s "http://127.0.0.1:{port}/finish"`

## Strict rules (breaking any of them invalidates the test)
1. Do NOT read, list, search or open any source code, documentation, tests, configuration or other files on this computer. The only files you may read are screenshots from the helper, downloaded files from the helper, and this brief.
2. Do NOT call any web address, API or database yourself, and do not use curl for anything except the helper program above. Do not look for ports or addresses.
3. You cannot and must not inspect the page's hidden structure or run scripts. Work only from what you can see in screenshots.
4. Do not look for help outside the application. If the application offers help or hints on screen, using them is allowed and worth noting.
5. If you cannot work out how to do something, do not guess wildly forever: try the obvious places, think like a new user, and after about 60 actions without progress stop and record it honestly as "Not discoverable" (you never found where) or "Blocked" (you found it but something stopped you).
6. Use only the information given above. Do not invent data. Never use real personal data.
7. Do not give up early either: a normal person would try for a while.

## While you work
Keep a private log of: how many screens/places you tried that turned out wrong, steps that felt unnecessary, words that confused you, moments the app gave no feedback or an unclear message, anything unexpected or broken, anything that looked untidy, inconsistent or hard to read, and anything you could not use with a keyboard or read clearly. Note the time at the start and end using `date +%s`.

## Final report
When finished (or stopped), write this JSON to /tmp/aud/results/{id}.json (create the folder if needed) using Bash, and also show it in your final answer:
{{
 "test_id": "{id}",
 "completion_status": "Passed | Partially completed | Failed | Not discoverable | Blocked | Not applicable",
 "what_you_believe_happened": "plain description of what you did and what the app showed at the end (your belief, not a guess about the database)",
 "start_epoch": 0, "end_epoch": 0,
 "interactions_estimate": 0,
 "incorrect_navigation_attempts": ["where you went that was wrong"],
 "unnecessary_steps": ["..."],
 "confusing_terminology": ["word or label -> why it confused you"],
 "missing_feedback": ["..."],
 "unexpected_behaviour": ["..."],
 "errors_encountered": ["exact visible message"],
 "visual_issues": ["..."],
 "accessibility_issues": ["..."],
 "observations": "free text",
 "ratings": {{
   "feature_discoverability": 1, "ease_of_use": 1, "visual_quality": 1, "information_hierarchy": 1,
   "clarity_of_terminology": 1, "workflow_efficiency": 1, "navigation_clarity": 1, "system_feedback": 1,
   "error_prevention": 1, "error_recovery": 1, "accessibility": 1, "overall_user_experience": 1
 }},
 "rating_justifications": {{"<category rated 1 or 2>": "evidence: what you saw"}}
}}
Ratings are 1 (very poor) to 5 (excellent), or the text "N/A" when a category could not be judged. Do not give high ratings just because it worked; a feature that took many tries to find is poor on discoverability even if it works. Every rating of 1 or 2 needs a justification with what you saw. The helper keeps its own count of your interactions; give your best estimate.
'''
for i,id_ in enumerate(WAVE):
    c=pub[id_]; port=port0+i
    d=f'/tmp/aud/run_{id_}'
    open(f'/tmp/aud/briefs/{id_}.md','w').write(BRIEF.format(id=id_,role=c['user_role'],user=c['login']['username'],pw=c['login']['password'],objective=c['objective'],data=c['input_data_and_prerequisites'],port=port))
    subprocess.Popen(['node','/tmp/aud/ui_driver.js',str(port),'http://127.0.0.1:8780/',d],stdout=open(f'/tmp/aud/drv_{id_}.log','w'),stderr=subprocess.STDOUT,start_new_session=True)
    print(id_,port)
