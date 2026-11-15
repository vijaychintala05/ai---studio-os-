"""Browser layout check of actual StudioOS JS and CSS using fictional JSON responses.

Chromium in this environment blocks localhost navigation; page.set_content runs
application source with mocked API JSON captured from a fictional test fixture.
These are NOT live-network screenshots. No user data or NAS files are accessed.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
API=json.loads((ROOT/'preview_fixtures.json').read_text())
css=(ROOT/'studioos/static/styles.css').read_text()
js=(ROOT/'studioos/static/app.js').read_text()
html=(ROOT/'studioos/static/index.html').read_text()
html=html.replace('<link rel="stylesheet" href="/static/styles.css" />','<style>'+css+'</style>')
fetch_js='''const API_DATA = '''+json.dumps(API,ensure_ascii=False)+''';
window.fetch = async (path, options={}) => ({ok:true,status:200,
 json: async()=>API_DATA[String(path)] || (String(path).startsWith('/api/tickets/')?{}:{})});'''
html=html.replace('<script src="/static/app.js"></script>',
                  '<script>'+fetch_js+'</script><script>'+js+'</script>')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True)
    errs=[]
    page.on('pageerror',lambda exc: errs.append(str(exc)))
    page.evaluate("""() => {Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}})}""")
    page.set_content(html,wait_until='domcontentloaded')
    page.wait_for_function("document.getElementById('loginLayer').classList.contains('hidden')",timeout=15000)
    page.wait_for_timeout(300)
    tickets=API['/api/tickets']
    ticket=API['/api/tickets/'+str(tickets[0]['id'])]
    results={}
    page.evaluate("switchView('assistant')")
    page.evaluate("""() => {state.messages=[{role:'user',reply:'What tasks need approval today?'},{role:'assistant',reply:'I can look up the ticket inbox. No financial record was changed.'}];render();document.getElementById('chatMessages').scrollTop=0}""")
    page.wait_for_timeout(100)
    page.screenshot(path=str(ROOT/'preview-mobile/chat.png'),full_page=True)
    results['chat']={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'head':page.locator('#mainContent').inner_text()[:110]}
    page.evaluate("""(ticket) => {state.messages=[{role:'user',reply:ticket.summary},{role:'assistant',reply:'Draft preview ready; business records unchanged.',preview:ticket,ticket_id:ticket.id}];render()}""",ticket)
    page.wait_for_timeout(100)
    page.evaluate("""() => {document.getElementById('chatMessages').style.maxHeight='none';document.getElementById('chatMessages').style.overflow='visible';document.getElementById('chatMessages').scrollTop=0;document.querySelector('.chat-panel').style.overflow='visible'}""")
    page.screenshot(path=str(ROOT/'preview-mobile/preview-card.png'),full_page=True)
    results['preview-card']={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'cards':page.locator('.ticket-preview').count()}
    page.evaluate("state.ticketDetail=null;switchView('tickets')")
    page.wait_for_timeout(100)
    page.screenshot(path=str(ROOT/'preview-mobile/ticket-inbox.png'),full_page=True)
    results['ticket-inbox']={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'tickets':page.locator('.ticket-list-row').count()}
    page.evaluate('(ticket)=>{state.ticketDetail=ticket;render()}',ticket)
    page.wait_for_timeout(100)
    page.screenshot(path=str(ROOT/'preview-mobile/ticket-review.png'),full_page=True)
    results['ticket-review']={'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'fields':page.locator('.preview-field').count()}
    results['browser_errors']=errs
    results['viewport']={'width':390,'height':844}
    (ROOT/'preview-mobile/mobile_results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
    browser.close()
