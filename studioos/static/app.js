'use strict';
const state={user:null,approvals:{costs:[],payments:[]},agents:{agents:[],hooks:[],write_events:0,chat_messages:0,context_summaries:0},users:[],view:'overview', tickets:[], ticketDetail:null, newTypes:[], newTypeDetail:null, newTypeDashboard:null, newTypeWorkflowResult:null, projects:[],summary:null,budgets:[],tasks:[],costs:[],activity:[],settings:null,docs:[],site:[],suggestions:[],messages:[],sessionId:sessionStorage.getItem('studioos-chat-id')||''};
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function text(s){return esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');}
function inr(n){return '₹'+Number(n||0).toLocaleString('en-IN',{minimumFractionDigits:0,maximumFractionDigits:2});}
function time(s){if(!s)return '';const raw=String(s).trim();const iso=/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(raw)?raw.replace(' ','T')+'Z':raw;let d=new Date(iso);return Number.isNaN(d.getTime())?s:d.toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'});}
function csrf(){return decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('studioos_csrf='))?.split('=')[1]||'');}
function hasFinance(){return ['admin','manager','accounts'].includes(state.user?.role);}
function isApprover(){return ['admin','manager'].includes(state.user?.role);}
function isAdmin(){return state.user?.role==='admin';}
async function api(path,opts={}){
 const session=state.session;
 const method=(opts.method||'GET').toUpperCase();
 const headers={'Content-Type':'application/json',...(opts.headers||{})};
 if(!['GET','HEAD'].includes(method))headers['X-CSRF-Token']=csrf();
 let r;
 try{r=await fetch(path,{credentials:'same-origin',...opts,headers});}
 catch(error){if(!(error instanceof TypeError))throw error;throw new TypeError('Check your connection and try again.',{cause:error});}
 const data=await r.json().catch(()=>({}));
 if(session!==state.session)throw new DOMException('Session ended','AbortError');
 if(r.status===401&&state.user){showLogin();throw new Error('Session ended. Please sign in again.');}
 if(!r.ok){const err=new Error(plainRequestError(r.status,data.detail));err.status=r.status;err.data=data;throw err;}
 return data;
}
const VIEW_DATA={documents:['documents'],agents:['agents']};   // loaded only when that screen is open, so every refresh is lighter
function refreshKeys(){if(state.mustSetup2fa)return ['auth/2fa'];return ['auth/2fa','projects',...(['admin','manager'].includes(state.user?.role)?['projects/form-options']:[]),'summary','tasks','settings','site-reports','work-queue',`tickets?limit=100&offset=${state.ticketPageOffset || 0}`,'new-types/inbox',...(hasFinance()?['budgets','activity']:[]),...(isAdmin()?['users','system/data-safety']:[]),...(VIEW_DATA[state.view]||[]).filter(k=>k!=='agents'||isApprover()),...(state.view==='documents'&&isApprover()?['documents/categories']:[])];}
async function refresh(){if(!state.user)return;const gen=state.session;const keys=refreshKeys();const results=await Promise.allSettled(keys.map(k=>api('/api/'+k)));if(gen!==state.session)return;state.refreshFailed=failedKeys(results,keys);results.forEach((r,i)=>{if(r.status==='fulfilled')state[{'documents':'docs','projects/form-options':'projectFormOptions','site-reports':'site','schema-suggestions':'suggestions','new-types/inbox':'newTypes','work-queue':'workQueue','auth/2fa':'twoFactor','system/data-safety':'safety','documents/categories':'docCategories'}[keys[i].split('?')[0]]||keys[i].split('?')[0]]=r.value;else console.warn('Load failed',keys[i],r.reason);});render();restoreTyping();}
function notify(message,error=false){const node=document.createElement('div');node.className='toast'+(error?' error':'');node.setAttribute('role',error?'alert':'status');const text=document.createElement('span');text.textContent=plainChangeCopy(message);node.appendChild(text);
 if(error){const close=document.createElement('button');close.type='button';close.className='toast-close';close.setAttribute('aria-label','Close this message');close.textContent='×';close.addEventListener('click',()=>node.remove());node.appendChild(close);}   // an error stays until the person closes it
 $('toasts').appendChild(node);if(!error)setTimeout(()=>node.remove(),4200);}
const TYPING_KEY='studioos-kept-typing';
function typingToKeep(username,chatText,dialogType,dialogValues,requestKey){const hasValues=dialogValues&&Object.values(dialogValues).some(v=>String(v||'').trim());const chat=String(chatText||'').trim()?String(chatText):'';if(!chat&&!hasValues)return null;return {user:username,chat,dialogType:hasValues?dialogType:'',dialogValues:hasValues?dialogValues:{},requestKey:hasValues?requestKey:''};}
function keepTyping(){try{if(!state.user)return;const form=$('entryForm'),d=$('entryDialog');const open=d&&d.open&&form&&['project','task','cost','payment','site','siteexpense'].includes(d.dataset.type);const kept=typingToKeep(state.user.username,$('chatInput')?.value,open?d.dataset.type:'',open?Object.fromEntries(new FormData(form).entries()):{},open?d.dataset.requestKey:'');if(kept)sessionStorage.setItem(TYPING_KEY,JSON.stringify(kept));}catch(e){}}   // so a sign-out or timeout does not lose what was typed
function restoreTyping(){try{const raw=sessionStorage.getItem(TYPING_KEY);if(!raw||!state.user)return;const kept=JSON.parse(raw);if(kept.user!==state.user.username)return;sessionStorage.removeItem(TYPING_KEY);
 if(kept.dialogType&&state.projects.length!==undefined){modal(kept.dialogType);const d=$('entryDialog');if(d.open){for(const [k,v] of Object.entries(kept.dialogValues||{})){const el=$('entryForm').elements[k];if(el&&el.type!=='file'&&el.type!=='hidden'&&(el.tagName!=='SELECT'||Array.from(el.options).some(o=>o.value===v)))el.value=v;}syncNewProjectClient($('entryForm'));if(kept.requestKey)d.dataset.requestKey=kept.requestKey;}}
 if(kept.chat){const input=$('chatInput');if(input)input.value=kept.chat;}notify('Welcome back. What you were typing has been kept.');}catch(e){}}
function head(title,subtitle,buttonLabel='',action=''){if(action==='project'&&!['admin','manager'].includes(state.user?.role))buttonLabel='';if(action==='cost'&&!hasFinance())buttonLabel='';if(action==='site'&&!['admin','manager','site_engineer'].includes(state.user?.role))buttonLabel='';if(action==='task'&&!['admin','manager','architect'].includes(state.user?.role))buttonLabel='';if(action==='index-nas'&&!isApprover())buttonLabel='';return `<div class="headline"><div><h1>${esc(title)}</h1><div class="subhead">${esc(subtitle)}</div></div>${buttonLabel?`<button class="btn btn-primary" data-action="${esc(action)}">+ &nbsp;${esc(buttonLabel)}</button>`:''}</div>`;}
function statusWords(status){return ({pending:'Waiting for approval',draft:'Draft',approved:'Approved',rejected:'Rejected',returned:'Returned for correction',committed:'Saved',reversed:'Undone',in_review:'In review',approved_design_only:'Design approved',done:'Done',open:'Open'})[status]||String(status||'').replaceAll('_',' ');}   // plain words for a status
function pill(label,variant=''){return `<span class="tag ${variant}">${esc(label)}</span>`;}
function empty(icon,title,caption){return `<div class="empty"><div class="empty-big">${icon}</div><strong>${esc(title)}</strong><br>${esc(caption)}</div>`;}
function financial(){const s=state.summary||{costs:{actual:0,commitments:0,known_costs:0},total_budget:0};return `<div class="financial-strip"><div class="financial-tile"><div class="label">Approved project budgets</div><div class="num">${inr(s.total_budget)}</div><small>Across all projects</small></div><div class="financial-tile"><div class="label">Incurred costs</div><div class="num">${inr(s.costs.actual)}</div><small>Expenses only</small></div><div class="financial-tile"><div class="label">Purchase commitments</div><div class="num">${inr(s.costs.commitments)}</div><small>Orders not in expenses</small></div><div class="financial-tile"><div class="label">Expenses and orders</div><div class="num">${inr(s.costs.known_costs)}</div><small>Expenses + commitments</small></div></div>`;}
function projectRows(limit=0) {
 const rows = limit ? state.budgets.slice(0,limit) : state.budgets;
 if (!rows.length) return empty('▤','No projects yet','Create a project to get started.');
 return '<div class="table-wrap"><table class="data-table"><thead><tr><th>Project</th><th>Stage</th><th>Budget</th><th>Expenses and orders</th><th>Headroom</th></tr></thead><tbody>'+rows.map(p=>
  '<tr><td><strong>'+esc(p.name)+'</strong><div class="muted">'+esc(p.client||'No client')+'</div></td><td>'+pill(p.stage,'gray')+
  '</td><td>'+inr(p.budget)+'</td><td>'+inr(p.known_costs)+'</td><td>'+pill(inr(p.remaining),p.remaining<0?'critical':'good')+'</td></tr>'
 ).join('')+'</tbody></table></div>';
}
function activityList(limit=7){const list=state.activity.slice(0,limit);return list.length?list.map(a=>`<div class="activity-row"><div class="activity-symbol">${a.entity_type==='cost'?'₹':a.entity_type==='task'?'☑':a.entity_type==='project'?'▤':'◷'}</div><div><div class="activity-text">${esc(plainChangeCopy(a.description))}</div><div class="activity-time">${time(a.created_at)} · ${esc(a.actor)}</div></div></div>`).join(''):empty('◷','No activity','Saved actions will be recorded here.');}
function safetyBanner(){const s=state.safety;if(!isAdmin()||!s||s.overall!=='fail')return '';const bad=s.checks.filter(c=>c.level==='fail').map(c=>esc(c.title)).join(' · ');return `<div class="notice fail"><span><strong>Data safety needs attention:</strong> ${bad}</span><button class="btn btn-secondary btn-sm" data-view="safety">Open Data safety</button></div>`;}
function overview(){const s=state.summary||{projects:0,open_tasks:0,budget_alerts:0,total_budget:0,costs:{actual:0,commitments:0,known_costs:0}};return safetyBanner()+head('Good to see you, '+(state.user?.display_name||state.user?.username||'team')+'.','Your architecture and construction firm, in one place.','New project','project')+`<div class="stats"><div class="stat"><div class="stat-top"><span>Active projects</span><span class="stat-icon">▤</span></div><div class="stat-value">${s.projects}</div><div class="stat-foot">Project portfolios</div></div><div class="stat"><div class="stat-top"><span>Open tasks</span><span class="stat-icon">☑</span></div><div class="stat-value">${s.open_tasks}</div><div class="stat-foot">Across all projects</div></div><div class="stat"><div class="stat-top"><span>Incurred costs</span><span class="stat-icon">₹</span></div><div class="stat-value stat-value-sm">${hasFinance()?inr(s.costs.actual):'—'}</div><div class="stat-foot">${s.costs.basis==='posted_books'?'From approved books':'Approved entries'}</div></div><div class="stat stat-warn"><div class="stat-top"><span>Budget alerts</span><span class="stat-icon">!</span></div><div class="stat-value">${hasFinance()?s.budget_alerts:'—'}</div><div class="stat-foot">Expenses and orders over budget</div></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Project portfolio</div><div class="panel-sub">Budgets and known financial exposure</div></div><button class="link-btn" data-view="projects">View projects →</button></div>${hasFinance()?projectRows(5):'<div class="panel-body">Project financial details are limited to authorized roles.</div>'}</section><section class="panel"><div class="panel-head"><div><div class="panel-title">Recent activity</div><div class="panel-sub">Every confirmed change is logged</div></div><button class="link-btn" data-view="activity">View all →</button></div><div class="panel-body">${activityList(6)}</div></section></div><div class="section-gap"><div class="budget-banner"><div><h2>Manage your firm by simply describing the work.</h2><p>AI suggests changes. An authorized person reviews and saves them.</p></div><button class="btn btn-primary" data-view="assistant">Open AI assistant ✦</button></div></div>`;}
function projects(){return head('Projects','One source of truth for your design and construction jobs.','New project','project')+ (state.budgets.length?`<div class="list-cards">${state.budgets.map(p=>`<div class="project-card"><div class="project-top"><div class="project-initial">${esc(p.name.slice(0,1).toUpperCase())}</div><div><button type="button" class="project-name" data-project-open="${Number(p.id)}">${esc(p.name)}</button><div class="muted">${esc(p.client||'No client specified')}</div></div></div><div class="project-line"></div><div class="project-metrics"><div><div class="metric-label">Approved budget</div><div class="metric-val">${inr(p.budget)}</div></div><div><div class="metric-label">Expenses and orders</div><div class="metric-val">${inr(p.known_costs)}</div></div></div><div class="row-between mt-17"><span class="muted">${esc(p.stage)}</span>${peopleButton(p)}${pill(p.remaining<0?'Over budget':'Within known budget',p.remaining<0?'critical':'good')}</div></div>`).join('')}</div>`:(state.projects.length?`<div class="list-cards">${state.projects.map(p=>`<div class="project-card"><button type="button" class="project-name" data-project-open="${Number(p.id)}">${esc(p.name)}</button><p class="muted">${esc(p.client||'')} · ${esc(p.stage)}</p>${peopleButton(p)}</div>`).join('')}</div>`:empty('▤','No projects yet','Create your first project to begin.')));}
function tasks(){const canComplete=['admin','manager','architect','site_engineer'].includes(state.user?.role);return head('Team tasks','What needs to happen, who owns it, and what is complete.','New task','task')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Task register</div><div class="panel-sub">Changes appear after review and approval.</div></div></div>${state.tasks.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Task</th><th>Project</th><th>Assigned to</th><th>Due date</th><th>Status</th>${canComplete?'<th>Action</th>':''}</tr></thead><tbody>${state.tasks.map(t=>`<tr><td><strong>${esc(t.title)}</strong></td><td>${esc(t.project)}</td><td>${esc(t.assignee||'Unassigned')}</td><td>${t.due_date?esc(t.due_date):'—'}</td><td>${pill(statusWords(t.status),t.status==='done'?'good':'warn')}</td>${canComplete?`<td>${t.status==='open'?`<button class="btn btn-secondary btn-sm" data-action="complete" data-id="${t.id}">Mark complete</button>`:'—'}</td>`:''}</tr>`).join('')}</tbody></table></div>`:(state.ovFilterActive&&state.ovTotalTasks>0?empty('☑','No tasks match your current filters','Clear or adjust your filters to see all tasks.'):empty('☑','No tasks yet','Create tasks manually or by talking to AI.'))}</section>`;}
function budgets() {
 const report = state.budgetLedger?.session === state.session ? state.budgetLedger?.data : null;
 const kinds = {DIRECT_EXPENSE_POSTED:'Expense', SUPPLIER_BILL_ACCEPTED:'Supplier bill', DIRECT_BILL_POSTED:'Direct supplier bill',
  TEXT_ENTRY_POSTED:'Books entry', JOURNAL_REVERSAL:'Reversal', STAFF_CLAIM:'Staff expense'};
 const rows = report ? [
  ...(report.orders||[]).map(row=>['Purchase order',row.number,row.amount_paise]),
  ...(report.entries||[]).map(row=>[kinds[row.source_event]||'Posted entry','#'+row.journal_id,row.side==='credit'?-row.amount_paise:row.amount_paise]),
 ] : [];
 const list = report ? (rows.length ?
  '<div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Reference</th><th>Amount</th></tr></thead><tbody>'+
   rows.map(([type,ref,amount])=>'<tr><td>'+esc(type)+'</td><td>'+esc(ref)+'</td><td class="num">'+inr(amount/100)+'</td></tr>').join('')+
  '</tbody></table></div>' : '<p class="panel-body">No Books entries for this project.</p>') : '';
 const options=(state.projects||[]).map(p=>'<option value="'+Number(p.id)+'"'+(p.id===report?.project_id?' selected':'')+'>'+esc(p.name)+'</option>').join('');
 return head('Budgets & Costs','Posted expenses and approved purchase orders from Books.')+financial()+
  '<section class="panel"><div class="panel-head"><div class="panel-title">Project financial position</div></div>'+projectRows()+'</section>'+
  '<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Books entries</div></div>'+
  '<div class="panel-body"><div class="row-actions"><button type="button" class="btn btn-primary" data-action="books-expense">Record expense</button>'+
  (isAdmin()?'<button type="button" class="btn btn-secondary" data-action="books-order">New purchase order</button>':'')+
  '<button type="button" class="btn btn-secondary" data-action="books-payment">Record payment</button></div>'+
  (options?'<form id="budgetBooksForm" class="row-actions section-gap"><label for="budgetBooksProject">Project</label><select id="budgetBooksProject" name="project" class="form-input">'+options+
   '</select><button class="btn btn-secondary" type="submit">Show entries</button></form>':'')+'</div>'+list+
  (report?.truncated||report?.orders_truncated?'<p class="panel-body muted">This list shows only part of the project history. The totals include all posted entries.</p>':'')+'</section>';
}
function site(){return head('Site Reports','Store site observations and daily progress against projects.','New site report','site')+(['admin','manager','site_engineer'].includes(state.user?.role)?`<div class="mb-14"><button class="btn btn-secondary btn-sm" data-action="siteexpense">+ Site expense (up to ₹5,000)</button></div>`:'')+myPettyCashPanel()+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Site update timeline</div><div class="panel-sub">A simple first version; photos and checklists come later.</div></div></div><div class="panel-body">${state.site.length?state.site.map(s=>`<div class="activity-row"><div class="activity-symbol">▧</div><div><div class="activity-text"><strong>${esc(s.project)}</strong> — ${esc(s.note)}</div><div class="activity-time">${time(s.created_at)}</div></div></div>`).join(''):empty('▧','No site reports','Site engineers can start reporting project activities here.')}</div></section>`;}
function docCategorySelect(d){const list=state.docCategories.categories;return `<select class="form-input" data-doc-category="${Number(d.id)}" aria-label="Category for ${esc(d.name)}"><option value="">Uncategorized</option>${list.map(c=>`<option value="${esc(c)}"${c===d.category?' selected':''}>${esc(c)}</option>`).join('')}</select>`;}
function documents(){const viewer=state.user?.role==='viewer';return head(viewer?'Project documents':'NAS Documents',viewer?'Files indexed for your projects.':'Read-only indexing of filenames, types and file paths stored on your NAS.','Scan NAS folder','index-nas')+`<div class="panel"><div class="panel-head"><div><div class="panel-title">Document index</div><div class="panel-sub">The application does not open, change or upload the original files.</div></div>${viewer?'':pill(state.settings?.nas_configured?'Project folder connected':'Project folder not connected',state.settings?.nas_configured?'good':'warn')}</div>${state.docs.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Category</th><th>Format</th><th>Relative path</th><th>Size</th></tr></thead><tbody>${state.docs.map(d=>`<tr><td><strong>${esc(d.name)}</strong></td><td>${isApprover()&&state.docCategories?.categories?docCategorySelect(d):pill(d.category||'Uncategorized',d.category?'ok':'gray')}</td><td>${pill(d.doc_type||'file','gray')}</td><td><span class="code">${esc(d.relative_path)}</span></td><td>${(d.size_bytes/1024).toFixed(0)} KB</td></tr>`).join('')}</tbody></table></div>`:empty('▥','No documents yet',viewer?'Project files will appear here once shared.':'Ask the person who manages StudioOS to connect the project folder.')}</div>${viewer?'':'<div class="info-card section-gap"><div class="tip-icon">ⓘ</div><h3>How NAS indexing works</h3><p>Scan a connected project folder to find files by name and location. Originals stay in the project folder.</p></div>'}`;}
function activity(){return head('Activity Log','An audit trail of confirmed changes across StudioOS.')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">All recorded changes</div><div class="panel-sub">See who saved each change and when.</div></div></div><div class="panel-body">${activityList(80)}</div></section>`;}
function settings(){const s=state.settings||{provider:'demo',providers:[]};const names={demo:'Offline Demo Parser',openai:'OpenAI',claude:'Anthropic Claude',gemini:'Google Gemini'};const descriptions={demo:'No API key needed. Recognizes limited sample phrases.',openai:'Uses the key your server administrator has set up.',claude:'Uses the key your server administrator has set up.',gemini:'Uses the key your server administrator has set up.'};return head('AI Provider Settings','The business database stays unchanged when you switch AI providers.')+`<div class="mb-18"><a class="btn btn-secondary" href="/api/export" download="studioos-export.json">↓ Export business records</a></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Select your intelligence engine</div><div class="panel-sub">Keys stay on the server and are never sent to the browser.</div></div></div><div class="panel-body">${s.providers.map(p=>`<div class="provider-row"><div><div class="provider-title"><span class="status-dot ${p.configured?'on':''}"></span>${names[p.id]}</div><div class="provider-desc">${descriptions[p.id]}</div></div>${p.id===s.provider?pill('Active','good'):`<button class="btn btn-secondary btn-sm" data-action="switch-provider" data-provider="${p.id}" ${p.configured?'':'disabled title="API key not configured"'}>Select</button>`}</div>`).join('')}<p class="muted">To enable another provider, set its environment variable and restart the application. Provider switching requires no data migration.</p></div></section><section class="panel"><details class="tech-details"><summary class="panel-head"><div><div class="panel-title">How StudioOS is built</div><div class="panel-sub">Technical background — open only if you are curious</div></div></summary><div class="panel-body"><div class="info-card"><h3>Permanent</h3><p>PostgreSQL (or SQLite during local development), projects, costs, tasks, staff inputs and audit history.</p></div><div class="info-card"><h3>Replaceable</h3><p>OpenAI, Claude and Gemini adapters; prompts and model settings; document intelligence.</p></div><div class="info-card"><h3>Before going live</h3><p>Stage 1 has login and role-based access. It still requires production security review, reliable backups and full construction accounting before rollout.</p></div></div></details></section></div>`;}
function assistant(){return head('AI Project Assistant','Describe work naturally. AI suggests changes; no AI proposal can directly save business records.')+`<div class="mb-14"><button class="btn btn-secondary" data-action="new-conversation">+ Start new conversation</button> <button class="btn btn-secondary" data-view="newtypes">Open New Data Inbox</button></div><div class="chat-shell"><section class="panel chat-panel"><div class="panel-head panel-head-rule"><div><div class="panel-title">StudioOS AI</div><div class="panel-sub">${state.settings?.provider==='demo'?'Demo interpreter — limited offline language support':`Provider: ${esc(state.settings?.provider||'loading')}`}</div></div><div class="chat-messages" id="chatMessages">${state.messages.length?state.messages.map(chatBubble).join(''):`<div class="chat-welcome"><div class="welcome-icon">✦</div><h3>Your firm's command centre.</h3><p>Create tasks, log purchases, ask about budgets and see exactly what was saved — all through conversation.</p><div class="chips"><button class="chip" data-prompt="Show all projects">Show all projects</button><button class="chip" data-prompt="What happened today?">What happened today?</button><button class="chip" data-prompt="Create project Villa A with budget ₹20 lakh">Create a sample project</button><button class="chip" data-prompt="Show the budget summary">Budget summary</button></div></div>`}</div><div class="chat-bottom"><form class="chat-form" id="chatForm"><textarea class="chat-input" id="chatInput" rows="1" placeholder="Ask anything about your projects, budgets or team..." required></textarea><button class="send-btn" type="submit" id="chatSend" aria-label="Send message">↑</button></form><label class="file-hint" for="chatFiles">Attach files or photos for review</label><input class="newtype-file-input" type="file" id="chatFiles" multiple accept="image/*,.pdf,.txt,.csv" /><div class="chat-hint">AI-created business changes are saved only after a reviewer approves them. Manual forms still use their existing paths.</div></div></section><aside><div class="info-card"><div class="tip-icon">✦</div><h3>Try these examples</h3><ul><li>“Create project Villa A with budget ₹20 lakh”</li><li>“Create task: Review drawings for Villa A”</li><li>“Purchased 25 bags of cement for Villa A”</li><li>“What is the budget for Villa A?”</li><li>“Show pending tasks”</li></ul></div><div class="info-card"><div class="tip-icon">◈</div><h3>Data protection by design</h3><p>AI suggests changes. An authorized person reviews and saves them. Payments do not duplicate costs.</p></div></aside></div>`;}
function friendlyValue(k,value,itemType){   // names and rupees in review, not raw ids or paise
 const num=Number(value);const ok=value!==null&&value!==''&&Number.isInteger(num);
 if((k==='project'||k==='project_id')&&ok){const p=(state.projects||[]).find(x=>Number(x.id)===num);if(p)return p.name;}
 if(k==='cost_id'&&ok){const c=(state.costs||[]).find(x=>Number(x.id)===num);if(c)return c.title+(c.project?' ('+c.project+')':'');}
 if(k==='id'&&ok&&itemType==='update_task'){const t=(state.tasks||[]).find(x=>Number(x.id)===num);if(t)return t.title;}
 if(k==='id'&&ok&&itemType==='update_project'){const p=(state.projects||[]).find(x=>Number(x.id)===num);if(p)return p.name;}
 return null;}
function evidenceGrid(i){
 const data=i.after||{}, source=i.field_evidence||{};
 const keys=[...new Set([...Object.keys(data),...Object.keys(source)])].filter(k=>k!=='idempotency_key'&&k!=='request_key');   // internal request keys are not for people
 return `<div class="preview-fields">${keys.map(k=>{
  const value=data[k], e=source[k]||{marker: value==null||value===''?'missing':'guessed'};
  const status=e.marker||'guessed', sourceText=e.source_words?`<small>Source: “${esc(e.source_words)}”</small>`:'<small>No exact source phrase located</small>';
  const named=i.display_values?.[k]??friendlyValue(k,value,i.item_type);const v=named!==null?named:value===null||value===undefined||value===''?'— missing —':(k.endsWith('_paise')&&Number.isInteger(value))?inr(value/100):typeof value==='object'?JSON.stringify(value):String(value);
  return `<div class="preview-field"><div class="field-key">${esc(changeFieldLabel(k))} <span class="source-chip ${esc(status)}">${esc(status)}</span></div><div class="field-value">${esc(v)}</div>${sourceText}<button class="field-edit" data-action="edit-ticket-field" data-id="${Number(i.id)}" data-field="${esc(k)}">Edit field</button></div>`;
 }).join('')}</div>`;
}
function previewCard(preview){if(!preview?.items?.length)return '';
 return `<section class="ticket-preview" aria-label="Proposed changes"><div class="preview-title">Change request #${Number(preview.id)} · Review before saving <span class="tag warn">DRAFT</span></div>
 ${preview.items.map(i=>`<div class="preview-item"><strong>${esc(plainChangeCopy(i.title || 'Proposed change'))}</strong> · ${esc(statusWords(i.status))}${evidenceGrid(i)}
 ${(i.flags||[]).map(f=>`<div class="preview-flag">⚑ ${esc(plainChangeCopy(f))}</div>`).join('')}</div>`).join('')}
 <button class="btn btn-primary preview-open" data-action="open-ticket" data-id="${Number(preview.id)}">Open full review</button></section>`;}
function chatBubble(m){
 const link=m.ticket_id?`<div class="chat-actions"><button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(m.ticket_id)}">Review change #${Number(m.ticket_id)}</button></div>`:'';
 return `<div class="message ${m.role==='user'?'user':'assistant'}">${m.role==='assistant'?'<div class="message-avatar">✦</div>':''}<div class="bubble">${text(m.reply)}${m.preview?previewCard(m.preview):''}${m.holding_item?newTypeCard(m.holding_item):''}${link}</div></div>`;
}

function requirementRows(h){
 const design=h.proposal||{};
 const states=(h.match_review?.last_field_preview?.field_states||[]);
 const byName=Object.fromEntries(states.map(x=>[x.name,x]));
 const fields=design.fields||[];
 const phaseLabels={draft:'Needed for draft',approve:'Needed before approval',close:'Needed to close',optional:'Optional information'};
 return ['draft','approve','close','optional'].map(level=>{
  const subset=fields.filter(f=>f.required_level===level);
  if(!subset.length)return '';
  return `<div class="requirement-group"><h4>${phaseLabels[level]}</h4><div class="newtype-fields">${subset.map(f=>{
    const assessment=byName[f.name];
    const state=assessment?.state||(f.default!==null&&f.default!==undefined?'generated':'missing');
    const appearance=state==='filled'||state==='generated'||state==='defaulted'?'sourced':state==='unknown'?'guessed':'invalid';
    const label=state==='generated'?'system generated':state==='defaulted'?'default':state;
    const allowed=f.allowed_values?.length?f.allowed_values.join(', '):f.format||'Not specified';
    return `<div class="newtype-field" data-field="${esc(f.name)}" data-state="${esc(state)}">
      <div class="req-field-header"><strong>${esc(f.name)}</strong><span class="source-chip ${appearance}">${esc(label)}</span></div>
      <small>${esc(f.meaning||f.description||'')}</small>
      <small><b>Type:</b> ${esc(f.type)} · <b>Allowed/format:</b> ${esc(allowed)}</small>
      <small><b>Default:</b> ${esc(f.default===null||f.default===undefined?'none':JSON.stringify(f.default))} · <b>Unique:</b> ${f.unique?'yes':'no'} · <b>Link:</b> ${esc(f.link||'none')}</small>
      <small><b>Edit roles:</b> ${esc((f.editable_roles||[]).join(', '))} · <b>Approval on change:</b> ${f.change_requires_approval?'yes':'no'}</small>
      <small><b>Reason:</b> ${esc(f.required_reason||'')}</small>
      <small><b>Source words:</b> ${esc(f.source_words||'(no source value supplied)')}</small>
      </div>`;}).join('')}</div></div>`;
 }).join('');
}
function capabilityFormPreview(fields){
 const allowedInput={text:'text',number:'number',date:'date',datetime:'datetime-local'};
 const chosen=(fields||[]).filter(f=>!f.read_only&&f.field!=='extra_attributes').slice(0,6);
 return `<div class="capability-sample-form">${chosen.map(f=>{
  let field='';
  if(f.control==='checkbox')field='<input disabled type="checkbox" />';
  else if(Array.isArray(f.allowed_values)&&f.allowed_values.length&&f.allowed_values.length<=20)
   field=`<select disabled><option>Choose value</option>${f.allowed_values.map(v=>`<option>${esc(v)}</option>`).join('')}</select>`;
  else if(f.control==='json-editor')field='<textarea disabled rows="2" placeholder="Structured details"></textarea>';
  else field=`<input disabled type="${allowedInput[f.control]||'text'}" placeholder="Preview — no information saved" />`;
  return `<label><span>${esc(f.label||f.field)} · ${esc(f.required_level||'optional')}</span>${field}</label>`;
 }).join('')}</div>`;
}
function capabilityPreviewCard(design){
 const b=design?.capability_blueprint;
 if(!b)return '';
 const form=b.interface?.form||{},workflow=b.workflow||{},dashboard=b.interface?.dashboards||[];
 const questions=b.questions||[];
 return `<section class="capability-preview" aria-label="Proposed self-evolving capability">
   <div class="capability-heading"><strong>Proposed capability · ${esc(b.strategy||'')}</strong><span class="source-chip guessed">Preview only</span></div>
   <p><strong>Purpose:</strong> ${esc(b.purpose||'Not confirmed — owner must explain the purpose')}</p>
   <p><strong>One record:</strong> ${esc(b.record_unit||'Not confirmed — record unit must be clarified')}</p>
   <div class="capability-parts">
     <div class="capability-part"><h4>Data design</h4><p>${Number(b.data_model?.fields?.length||0)} fields · ${(b.data_model?.relationships||[]).map(l=>esc(l.entity||'')).join(', ')||'No confirmed links'}</p><small>Uncertain fields remain flexible; original source is preserved.</small></div>
     <div class="capability-part"><h4>Workflow (inactive)</h4>${(workflow.transitions||[]).map(t=>`<div class="capability-step">${esc(t.from)} → ${esc(t.to)} · ${esc(t.action)} · approval level: ${esc(t.required_level)}</div>`).join('')}</div>
     <div class="capability-part"><h4>Generated form and list (preview)</h4><p>${Number(form.fields?.length||0)} form controls, ${(b.interface?.list?.columns||[]).length} list columns</p><small>${(b.interface?.list?.columns||[]).map(esc).join(' · ')}</small><details class="capability-form-detail"><summary>View generated form</summary>${capabilityFormPreview(form.fields)}</details></div>
     <div class="capability-part"><h4>Dashboard definitions (not queried)</h4>${dashboard.map(d=>`<div class="capability-step">${esc(d.title)} · ${esc(d.metric)} by ${esc(d.group_by)}</div>`).join('')}</div>
   </div>
   ${questions.length?`<p class="capability-questions"><strong>Needs your answers:</strong> ${questions.map(q=>esc(q.question)).join(' · ')}</p>`:''}
   <p class="muted">No code, database migration, dashboard query, or new workflow is executed. Approval covers the design; runtime activation requires a separate implementation and review.</p>
 </section>`;
}
function evolutionDashboardsUI(result){
 if(!result||!Array.isArray(result.charts))return '';
 return `<section class="capability-live" aria-label="Live approved record dashboards"><h3>Live records (permission-filtered)</h3><p class="muted">Counts from stored records, not model-generated SQL.</p>${result.charts.map(x=>`<div class="capability-live-chart"><strong>${esc(x.title)} · ${Number(x.total)||0} records</strong>${x.groups.length?x.groups.map(g=>`<div class="capability-chart-row"><span>${esc(g.label)}</span><progress class="capability-progress" max="${Math.max(1,...x.groups.map(v=>Number(v.count)||0))}" value="${Number(g.count)||0}"></progress><strong>${Number(g.count)||0}</strong></div>`).join(''):'<p class="muted">No accessible records yet.</p>'}</div>`).join('')}</section>`;
}
function evolutionDiagnosisUI(fit){
 const d=fit.problem_diagnosis;
 if(!d)return '';
 return `<section class="capability-advice"><h3>Problem analysis · ${esc(d.provider||'')}</h3><p class="muted">Advisory only; not an approval or workflow instruction.</p>${(d.suggestions||[]).map(x=>`<div class="capability-advice-item"><strong>${esc(x.kind)}</strong><p>${esc(x.reason)}</p><small>Source: ${esc(x.evidence||'No exact quote')}</small></div>`).join('')}${(d.questions||[]).length?`<p><strong>Further questions:</strong> ${d.questions.map(esc).join(' · ')}</p>`:''}</section>`;
}
function newTypeCard(h){
 const fit=h.match_review||{},design=h.proposal||{},risks=design.risks||[];
 return `<section class="newtype-card" aria-label="design review new-data preview">
 <div class="newtype-card-head"><strong>Holding inbox #${Number(h.id)} · ${esc(statusWords(h.state))}</strong>${pill(fit.decision||'parked','warn')}</div>
 <p class="newtype-source"><strong>Your original words:</strong> ${esc(h.raw_payload?.text||'')}</p>
 <p class="muted">Checked ${Number(fit.inspected_tables||0)} tables and ${Number(fit.inspected_fields||0)} fields. No dynamic table has been created.</p>
 ${(fit.near_fits||[]).length?`<p><strong>Possible existing fits:</strong> ${fit.near_fits.map(x=>esc(x.table)).join(', ')}</p>`:''}
 ${design.table_name?`<h4>Minimal proposal: ${esc(design.table_name)}</h4><p>${esc(design.description||'')}</p>
 <p class="muted">Database rules are proposed, not installed in design review.</p>
 ${requirementRows(h)}
 ${capabilityPreviewCard(design)}
 <p class="muted">Source-only sample records: ${(design.sample_records||[]).length}. ${risks.includes('insufficient_source_values_for_2_to_3_sample_records')?'Insufficient actual values; nothing invented.':''}</p>`:''}
 ${fit.last_field_preview?`<p><strong>Last field preview:</strong> ${fit.last_field_preview.valid?'Valid for selected phase':'Incomplete / not approvable'} · ${(fit.last_field_preview.blocking||[]).length} blocking fields</p>`:''}
 ${(h.questions||[]).length&&h.state==='proposed'?`<p><strong>Questions:</strong> ${h.questions.map(q=>esc(q.text)).join(' · ')}</p>`:''}
 ${(h.attachments||[]).length?`<p>${h.attachments.map(f=>esc(f.filename)+' (SHA256 '+esc(f.sha256.slice(0,12))+'…)').join(', ')}</p>`:''}
 ${risks.map(r=>`<div class="preview-flag">⚑ ${esc(r)}</div>`).join('')}
 ${fit.untrusted_instructions_detected?'<div class="preview-flag">⚠ Untrusted instructions detected in source. Ignored as instructions.</div>':''}
 <button class="btn btn-primary" data-action="open-new-type" data-id="${Number(h.id)}">Review in New Data Inbox</button></section>`;
}
function newTypeDetail(h){
 const design=h.proposal||{}, fit=h.match_review||{};
 return `<section class="panel section-gap" id="newTypeReview"><div class="panel-head"><div><div class="panel-title">Holding item #${Number(h.id)} · ${esc(statusWords(h.state))}</div><div class="panel-sub">The raw source cannot be changed. Approval records a design only.</div></div><button class="btn btn-secondary" data-action="close-new-type">Close</button></div>
 <div class="panel-body">${newTypeCard(h)}
 ${h.state==='proposed'?`<div class="req-try"><h3>Preview a hypothetical record — no save</h3><p class="muted">Try example field values as structured details. Missing and unknown fields are highlighted above; no business record is created.</p>
 <form id="previewRequirementForm" data-id="${Number(h.id)}"><textarea name="record" rows="4" spellcheck="false" placeholder='{ "project_id": 1, "area": "Kitchen", "description": "Cracked tile" }'></textarea>
 <label>Check required fields at <select name="phase"><option value="draft">Draft</option><option value="approve" selected>Approval</option><option value="close">Closure</option></select></label>
 <button type="submit" class="btn btn-secondary">Check field requirements</button></form></div>`:''}
 ${design.capability_blueprint?`<div class="capability-operations"><button class="btn btn-secondary" data-action="diagnose-new-type" data-id="${Number(h.id)}">Analyze problem with selected AI</button>${h.state==='approved_design_only'?`<button class="btn btn-secondary" data-action="dashboard-new-type" data-id="${Number(h.id)}">Load live dashboards</button>`:''}</div>${evolutionDiagnosisUI(fit)}${state.newTypeDashboard?.id===h.id?evolutionDashboardsUI(state.newTypeDashboard):''}${h.state==='approved_design_only'?`<form class="capability-check-form" id="capabilityCheckWorkflow" data-id="${Number(h.id)}"><h3>Evaluate lifecycle policy (read-only)</h3><label>Existing record ID <input name="record_id" inputmode="numeric" type="number" min="1" required></label><label>Requested stage <select name="destination"><option value="active">Draft → Active</option><option value="closed">Active → Closed</option></select></label><button type="submit" class="btn btn-secondary">Check eligibility</button><p class="muted">The preview leaves the record as it is.</p></form>${state.newTypeWorkflowResult?.id===h.id?`<div class="capability-advice-item"><strong>${state.newTypeWorkflowResult.allowed?'Eligible for review':'Not eligible'}</strong><p>Missing: ${(state.newTypeWorkflowResult.missing||[]).map(esc).join(', ')||'None'}. No record changed.</p></div>`:''}`:''}`:''}
 <details class="newtype-advanced"><summary>Advanced: full structure and evidence</summary><pre class="newtype-json">${esc(JSON.stringify({fit,design},null,2))}</pre></details>
 ${h.state==='proposed'?`<h3>Answer only what is missing</h3><form id="newTypeAnswers" data-id="${Number(h.id)}" class="newtype-questions">${(h.questions||[]).map(q=>`<label>${esc(q.text)}<textarea rows="2" name="${esc(q.id)}" placeholder="Leave blank if unknown">${esc(h.answers?.[q.id]||'')}</textarea></label>`).join('')}<button type="submit" class="btn btn-primary">Update proposed design</button></form>
 <div class="approval-buttons">${isAdmin()?`<button class="btn btn-primary" data-action="approve-new-type" data-id="${Number(h.id)}">Approve structure (design only)</button>`:''}<button class="btn btn-secondary" data-action="edit-new-type" data-id="${Number(h.id)}">Edit design</button><button class="btn btn-secondary" data-action="keep-new-type" data-id="${Number(h.id)}">Keep in inbox only</button><button class="btn btn-danger" data-action="reject-new-type" data-id="${Number(h.id)}">Reject proposal</button></div>`:''}
 </div></section>`;
}
function newTypesView(){let rows=state.newTypes||[];return head('New Data Inbox','Unmatched information is parked here; Admin alone can approve schema designs.')+
 `<section class="panel"><div class="panel-head"><div><div class="panel-title">Holding inbox</div><div class="panel-sub">Raw words and attachments are retained. No migration runs in design review.</div></div></div>
 ${rows.length?rows.map(h=>`<div class="approval-card ticket-list-row"><div><strong>Holding #${Number(h.id)}</strong> ${pill(statusWords(h.state),h.state==='approved_design_only'?'good':'warn')}<p>${esc((h.raw_payload?.text||'').slice(0,150))}</p><small>${esc(h.match_review?.decision||'')} · ${(h.attachments||[]).length} attachments</small></div><button class="btn btn-primary" data-action="open-new-type" data-id="${Number(h.id)}">Review</button></div>`).join(''):empty('▧','Inbox is empty','Describe a new type of information in chat to park it here.')}</section>
 ${state.newTypeDetail?newTypeDetail(state.newTypeDetail):''}`;}

function changeRequestSummary(text){
 const message=String(text||'').trim();
 if(message.startsWith('Typed form reviewed as a draft'))return 'Submitted from a form.';
 const cleaned=message.replace(/\s*\{"[\s\S]*$/,'').replace(/\s*\{[^{}]{20,}\}\s*/g,' ').replace(/\s*\[[^\[\]]{20,}\]\s*/g,' ').replace(/\s+/g,' ').trim();
 return plainChangeCopy(cleaned||message);
}
function tickets(){let rows=state.tickets||[];const offset=state.ticketPageOffset||0;const rawLen=state.ticketPageRawCount!==undefined?state.ticketPageRawCount:rows.length;const rangeText=rows.length?`Showing ${offset+1}–${offset+rows.length}`:'Showing 0';const seg=state.ticketInboxSeg;const emptyBlock=seg==='needs'?empty('✓','All caught up','Nothing needs your review right now.'):seg==='sent'?empty('◇','Nothing waiting on others','Change requests you send for approval appear here.'):seg==='updates'?empty('◇','No completed requests yet','Approved and undone change requests appear here.'):empty('◇','No change requests yet','Send a business update in chat to create a change request.');return head('Change requests','Review proposed changes and save the ones you approve.')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Proposed changes</div></div></div>${rows.length?rows.map(t=>`<div class="approval-card ticket-list-row"><div><strong>Change request #${t.id}</strong> ${pill(statusWords(t.status),t.status==='committed'?'good':'warn')}<p>${esc(changeRequestSummary(t.summary))}</p><small>${t.items.length} item(s) · ${time(t.created_at)}</small></div><button class="btn btn-primary" data-action="open-ticket" data-id="${t.id}">Review change</button></div>`).join(''):emptyBlock}</section><div class="g-actions ticket-pager"><button class="btn btn-secondary" data-action="ticket-page" data-offset="${Math.max(0,offset-100)}" ${offset===0?'disabled':''}>Newer requests</button><span class="muted">${rangeText}</span><button class="btn btn-secondary" data-action="ticket-page" data-offset="${offset+100}" ${rawLen<100?'disabled':''}>Older requests</button></div>${state.ticketDetail?ticketDetail(state.ticketDetail):''}`;}
function bankBatchReview(t){
 if(['committed','reversed'].includes(t.status)||!t.items?.length||t.items.some(i=>i.item_type!=='finance_reconcile_bank'||!['pending','approved'].includes(i.status))||!hasFinance())return '';
 if(t.can_approve!==true&&t.can_commit!==true)return '<p class="muted">An authorized reviewer must review and save these bank matches.</p>';
 return `<section class="panel section-gap"><div class="panel-body"><h3>Review bank matches</h3><p>Check every proposed match below against the statement. Each match keeps its own approval record. Saving rechecks the evidence and exact bank amount; a failed check prevents the changes from being saved.</p><label><input type="checkbox" id="bankBatchChecked"> I checked every proposed match against the statement.</label><button class="btn btn-primary" data-action="approve-bank-batch" data-id="${Number(t.id)}">Approve and save bank matches</button></div></section>`;
}
function changeFieldLabel(key){
 const known={name:'Name',title:'Description',amount_paise:'Amount (₹)',project:'Project',project_id:'Project',entity_id:'Company',company_id:'Company',project_ids_to_assign:'Projects to assign',client_id:'Client',supplier_id:'Vendor',party_id:'Contact',kind:'Type',cost_id:'Related expense',note:'Note',vendor_id:'Vendor',paid_through_id:'Paid through',expense_account_id:'Expense account',receipt_id:'Receipt',personal_payment:'Paid personally',claim_id:'Staff claim',payment_date:'Payment date',ap_code:'AP code',ar_code:'AR code',bank_masked:'Bank account (masked)',no_vendor:'No vendor',no_vendor_name:'Paid to',suggested_vendor_name:'Suggested vendor',tax_rate_bps:'GST rate',rate_paise:'Rate (₹)',total_paise:'Total (₹)',subtotal_paise:'Subtotal (₹)',tax_paise:'Tax (₹)'};
 return known[key]||key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
}
function formatProposedLines(lines){
 return lines.map(ln=>{
  if(!ln||typeof ln!=='object')return String(ln);
  const parts=[];
  if(ln.description||ln.title)parts.push(String(ln.description||ln.title));
  if(ln.quantity!=null&&ln.rate_paise!=null)parts.push(`${ln.quantity} × ${inr(ln.rate_paise/100)}`);
  else if(ln.amount_paise!=null)parts.push(inr(ln.amount_paise/100));
  if(ln.tax_rate_bps!=null)parts.push(`GST ${(ln.tax_rate_bps/100).toFixed(ln.tax_rate_bps%100?2:0)}%`);
  return parts.length?parts.join(' · '):JSON.stringify(ln);
 }).join('; ');
}
function proposedValues(item, data){
 const entries=Object.entries(data||{}).filter(([key])=>!IMMUTABLE_ITEM_KEYS.has(key)||key==='receipt_intake_id');
 return entries.length?'<dl class="change-values">'+entries.map(([key,value])=>{
  let shown=item.display_values?.[key]??friendlyValue(key,value,item.item_type);
  if(shown===null||shown===undefined){
   if(typeof value==='boolean')shown=value?'Yes':'No';
   else if(key.endsWith('_paise')&&Number.isInteger(value))shown=inr(value/100);
   else if(key.endsWith('_bps')&&Number.isInteger(value))shown=(value/100).toFixed(value%100?2:0)+'%';
   else if(key==='lines'&&Array.isArray(value))shown=formatProposedLines(value);
   else shown=value;
  }
  if(key==='receipt_intake_id'&&Number.isSafeInteger(value)&&value>0){
   return `<dt>Receipt</dt><dd><a href="/api/intake/items/${value}/file">Download receipt photo</a></dd>`;
  }
  return `<dt>${esc(changeFieldLabel(key))}</dt><dd>${esc(typeof shown==='object'&&shown!==null?JSON.stringify(shown):shown??'—')}</dd>`;
 }).join('')+'</dl>':'<p class="muted">No values</p>';
}
function changeSaveReview(id){
 const ticket=state.ticketDetail;
 if(ticket?.id!==Number(id))return null;
 const checks=[...$('ticketReview').querySelectorAll('[name="change-check"]')];
 const incomplete=checks.find(check=>!check.checked);
 if(incomplete){
   incomplete.focus();notify('Complete the review checks before saving.',true);
   return null;
 }
 const fingerprints=ticket.items.every(item=>item.review_fingerprint)
   ?Object.fromEntries(ticket.items.map(item=>[item.id,item.review_fingerprint])):undefined;
 return {confirmed:checks.map(check=>check.value),review_fingerprints:fingerprints};
}
function ticketDetail(t){
 const active=!['committed','reversed'].includes(t.status);
 const pending=t.items.filter(item=>item.status==='pending');
 const bank=bankBatchReview(t);
 const oneStep=active && !bank && t.can_approve===true && pending.length>0;
 const flags=pending.flatMap(item=>item.flags||[]).join(' ').toLowerCase();
 const checks=`${/possible_duplicate|near_match_existing/.test(flags)?'<label><input type="checkbox" name="change-check" value="duplicate"> I checked for a duplicate</label>':''}
 ${/unusually_high_amount|amount_from_file/.test(flags)?'<label><input type="checkbox" name="change-check" value="amount"> I checked the amount</label>':''}`;
 const canSave=active && t.can_commit===true;
 const buttons=(i)=>!active?'':i.status==='returned'?`<p>Returned for correction: ${esc(plainChangeCopy(i.note||''))}</p>${state.user?.id===t.submitter_id||isAdmin()?`
 <button class="btn btn-secondary" data-action="edit-ticket-item" data-id="${i.id}">Fix change</button><button class="btn btn-primary" data-action="resubmit-item" data-id="${i.id}">Send again</button>`:''}`:
 `${i.can_approve===true&&(!oneStep||pending.length>1)?`<button class="btn btn-primary" data-action="approve-ticket-item" data-id="${i.id}">Approve item</button>`:''}
 <button class="btn btn-secondary" data-action="edit-ticket-item" data-id="${i.id}">Edit change</button>
 ${i.can_return===true?`<button class="btn btn-secondary" data-action="return-item" data-id="${i.id}">Return for correction</button>`:''}
 ${i.can_reject===true?`<button class="btn btn-danger" data-action="reject-ticket-item" data-id="${i.id}">Reject change</button>`:''}`;
 return `<section class="panel section-gap ticket-review" id="ticketReview"><div class="panel-head"><div><h2 class="panel-title">Change request #${t.id} · ${esc(statusWords(t.status))}</h2>
 <p class="panel-sub">${esc(changeRequestSummary(t.summary))}</p></div><button class="btn btn-secondary" data-action="close-ticket">Close</button></div>
 <div class="panel-body">${bank}${t.items.map(i=>`<div class="approval-card"><h3>${esc(plainChangeCopy(i.title||'Proposed change'))}</h3>${pill(statusWords(i.status),i.status==='approved'?'good':'gray')}
 ${proposedValues(i,i.after)}${approvalFiles(i)}<details><summary>Advanced</summary><h4>Before</h4>${proposedValues(i,i.before)}<h4>After and source details</h4>${evidenceGrid(i)}</details>
 ${(i.flags||[]).map(f=>`<p class="preview-flag">${esc(plainChangeCopy(f.replaceAll('_',' ')))}</p>`).join('')}<div class="approval-buttons">${buttons(i)}</div></div>`).join('')}
 ${oneStep?`<div class="change-approval">${checks}<button class="btn btn-primary" data-action="approve-save-change" data-id="${t.id}">${pending.length>1?"Approve and save all":"Approve and save"}</button></div>`:''}
 ${active&&t.can_approve!==true&&pending.length>0?`<p class="muted">${esc(t.reason||'An authorized reviewer needs to review this change.')}</p>`:''}
 ${canSave?`<button class="btn btn-primary" data-action="commit-ticket" data-id="${t.id}">${t.items.some(item=>item.status==="approved")?"Save approved changes":"Save review"}</button>`:''}
 ${t.status==='committed'&&isAdmin()?`<button class="btn btn-danger" data-action="reverse-ticket" data-id="${t.id}">Undo save</button>`:''}
 <details><summary>Original conversation</summary><div class="ticket-transcript">${(t.conversation||[]).map(m=>`<p><strong>${esc(m.speaker)}:</strong> ${text(m.speaker==='user'&&!m.text.startsWith('Typed form reviewed as a draft')?m.text:changeRequestSummary(m.text))}</p>`).join('')}</div></details>
 </div></section>`;
}

function approvalFiles(c){
 const links=(c.attachments||[]).map(file=>{
  const path=`/api/expense-images/${Number(file.id)}`+(file.ticket_id?`?ticket_id=${Number(file.ticket_id)}`:'');
  const label=esc(file.filename);
  const content=file.is_image?`<img src="${esc(path)}" alt="${label}" loading="lazy">`:label;
  return `<a href="${esc(path)}" target="_blank" rel="noopener">${content}</a>`;
 });
 return links.length?`<p class="approval-files">${links.join('')}</p>`:'';
}
function approvals(){return tickets();}
function projectNames(ids){const names=Object.fromEntries((state.projects||[]).map(p=>[p.id,p.name]));return (ids||[]).map(id=>names[id]||('#'+id)).join(', ');}
function peopleButton(p){return isAdmin()?`<button class="btn btn-secondary btn-sm" data-action="project-members" data-id="${Number(p.id)}">People</button>`:'';}
function userActions(x){if(x.role==='admin'||x.id===state.user?.id)return '<span class="muted">Owner</span>';
 return `<div class="row-actions"><button class="btn btn-secondary btn-sm" data-action="user-toggle" data-id="${Number(x.id)}" data-active="${x.active?'1':'0'}">${x.active?'Deactivate':'Reactivate'}</button>`+
  `<button class="btn btn-secondary btn-sm" data-action="reset-password" data-id="${Number(x.id)}">Reset password</button>`+
  (x.two_factor?`<button class="btn btn-secondary btn-sm" data-action="user-reset-2fa" data-id="${Number(x.id)}">Reset two-factor</button>`:'')+`</div>`;}
function team(){const me=state.user||{};return head('Team & Roles','Create logins, control access and assign people to projects.','Add person','user')+
 (isAdmin()&&!me.two_factor?`<div class="notice warn">Your Admin account has no two-factor login yet. <button class="btn btn-secondary btn-sm" data-view="account">Set it up</button></div>`:'')+
 `<section class="panel"><div class="panel-head"><div><div class="panel-title">Team accounts</div><div class="panel-sub">Admin, managers and accounts see every project. Everyone else sees only projects you assign (Projects → People).</div></div></div><div class="table-wrap"><table class="data-table team-table"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Projects</th><th>Two-factor</th><th>Status</th><th>Actions</th></tr></thead><tbody>${state.users.map(x=>`<tr><td data-label="Name"><strong>${esc(x.display_name)}</strong></td><td data-label="Username">${esc(x.username)}</td><td data-label="Role">${pill(x.role.replaceAll('_',' '),'gray')}</td><td data-label="Projects">${x.sees_all_projects?'All projects':esc(projectNames(x.project_ids)||'None assigned')}</td><td data-label="Two-factor">${x.two_factor?pill('On','good'):pill('Off','gray')}</td><td data-label="Status">${x.active?'Active':pill('Deactivated','critical')}</td><td data-label="Actions">${userActions(x)}</td></tr>`).join('')}</tbody></table></div></section>`;}
function accountField(form,label,name,type='password',autocomplete='off',extra=''){return `<div class="field"><label for="${form}-${name}">${label}</label><input class="form-input" id="${form}-${name}" name="${name}" type="${type}" autocomplete="${autocomplete}" required ${extra}></div>`;}
function codeField(form){return accountField(form,'6-digit code from your app (or a recovery code)','code','text','one-time-code','minlength="6" maxlength="40"');}
function twoFactorBody(){const t=state.twoFactor||{},setup=state.twoFactorSetup,codes=state.recoveryCodes;
 if(codes)return `<p><strong>Save these recovery codes now.</strong> Each one works once if you lose your phone. They will not be shown again.</p><ol class="recovery-codes">${codes.map(c=>`<li><code>${esc(c)}</code></li>`).join('')}</ol><button class="btn btn-primary" data-action="dismiss-codes">I have saved these codes</button>`;
 if(setup){const key=(setup.secret||'').match(/.{1,4}/g)?.join(' ')||'';
  return `<ol class="steps"><li>Install an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy or 1Password).</li><li>Scan the QR code in your authenticator app.<img class="authenticator-qr" src="data:image/png;base64,${esc(setup.qr_png)}" alt="Two-factor setup code"> On your phone, you can also tap <a class="btn btn-secondary btn-sm" href="${esc(setup.otpauth_uri)}">Add to authenticator app</a>, or choose “enter a setup key” in the app and type this key:<div class="secret-key"><code>${esc(key)}</code></div></li><li>Enter the 6-digit code the app shows.</li></ol>
  <form id="twoFactorEnableForm" class="form-grid">${accountField('tfe','6-digit code','code','text','one-time-code','inputmode="numeric" minlength="6" maxlength="6"')}<div class="row-actions"><button class="btn btn-primary" type="submit">Turn on two-factor login</button><button class="btn btn-secondary" type="button" data-action="cancel-2fa-setup">Cancel</button></div></form>`;}
 if(!t.enabled)return `<p class="muted">After you turn this on, signing in needs your password and a 6-digit code from your phone. ${t.required?'<strong>Required for the Admin account.</strong>':'Strongly recommended for the Admin and anyone who approves money.'}</p><form id="twoFactorSetupForm" class="form-grid">${accountField('tfs','Confirm your password','password','password','current-password')}<button class="btn btn-primary" type="submit">Set up two-factor login</button></form>`;
 return `<p>Two-factor login is on. Recovery codes left: <strong>${Number(t.recovery_codes_left||0)}</strong>.</p>
  <details class="account-more"><summary>Moving to a new phone</summary><p class="muted">Confirm with your current app or a recovery code. Then enter a code from the new phone to finish.</p><form id="twoFactorSetupForm" class="form-grid">${accountField('tfr','Confirm your password','password','password','current-password')}${codeField('tfr')}<button class="btn btn-secondary" type="submit">Set up on a new phone</button></form></details>
  <details class="account-more"><summary>Get new recovery codes</summary><form id="twoFactorCodesForm" class="form-grid">${accountField('tfc','Your password','password','password','current-password')}${codeField('tfc')}<button class="btn btn-secondary" type="submit">Replace my recovery codes</button></form></details>
  ${t.required?'':`<details class="account-more"><summary>Turn off two-factor login</summary><form id="twoFactorDisableForm" class="form-grid">${accountField('tfd','Your password','password','password','current-password')}${codeField('tfd')}<button class="btn btn-secondary" type="submit">Turn off</button></form></details>`}`;}
function safetyView(){const s=state.safety;const label={ok:['All good','good'],warn:['Check soon','warn'],fail:['Action needed','critical']};
 if(!s)return head('Data safety','Backups, the copy off the NAS and restore tests.')+empty('⛨','No status yet','The backup service has not reported yet.');
 const [word,variant]=label[s.overall]||label.fail;
 return head('Data safety','Backups, the copy off the NAS and restore tests. Checked automatically.')+
 `<section class="panel"><div class="panel-head"><div><div class="panel-title">Overall</div><div class="panel-sub">${s.environment==='production'?'Live data':s.environment==='test'?'Test copy (not live data)':'Development'} · updated ${esc(time(s.updated_at)||'never')}</div></div>${pill(word,variant)}</div><div class="panel-body"><div class="safety-list">${s.checks.map(c=>`<div class="safety-row ${esc(c.level)}"><span class="safety-icon">${c.level==='ok'?'✓':c.level==='warn'?'!':'✕'}</span><div><div class="safety-title">${esc(c.title)}</div><div class="muted">${esc(c.detail)}</div></div></div>`).join('')}</div></div></section>
 <section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">If something goes wrong</div><div class="panel-sub">Step-by-step instructions are in RUNBOOK.md, included with StudioOS.</div></div></div><div class="panel-body"><ol class="steps"><li>Nothing is lost while backups show green: the newest verified backup and its off-NAS copy can always be restored.</li><li>To look inside an old backup without touching live data, use <code>restore-copy</code>.</li><li>To roll the live system back, use <code>swap-in</code>: the current database is renamed and kept, never deleted.</li></ol></div></section>`;}
function account(){const t=state.twoFactor||{};return head('My account','Your password and two-factor login.')+
 (state.mustSetup2fa?`<div class="notice warn">Two-factor login is required for the Admin account. Finish the setup below to unlock StudioOS.</div>`:'')+
 `<div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Two-factor login</div><div class="panel-sub">A code from your phone as well as your password.</div></div>${pill(t.enabled?'On':'Off',t.enabled?'good':'warn')}</div><div class="panel-body">${twoFactorBody()}</div></section>
 <section class="panel"><div class="panel-head"><div><div class="panel-title">Change password</div><div class="panel-sub">Your other devices will be signed out.</div></div></div><div class="panel-body"><form id="changePasswordForm" class="form-grid">${accountField('cp','Current password','current_password','password','current-password')}${accountField('cp','New password (12+ characters)','new_password','password','new-password','minlength="12"')}${accountField('cp','Repeat new password','repeat_password','password','new-password','minlength="12"')}<button class="btn btn-primary" type="submit">Change password</button></form></div></section></div>`;}


function agents(){const a=state.agents||{agents:[],hooks:[],write_events:0,chat_messages:0,context_summaries:0};return head('Specialist agents & hooks','Editable Markdown roles. Enforced safety checks remain in the backend.')+`<div class="stats"><div class="stat"><div class="stat-top">Defined specialist agents</div><div class="stat-value">${a.agents?.length||0}</div></div><div class="stat"><div class="stat-top">Enabled lifecycle hooks</div><div class="stat-value">${a.hooks?.filter(h=>h.status==='enabled').length||0}</div></div><div class="stat"><div class="stat-top">Journalled business changes</div><div class="stat-value">${a.write_events||0}</div></div><div class="stat"><div class="stat-top">Retained chat messages</div><div class="stat-value">${a.chat_messages||0}</div></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Specialist agents</div><div class="panel-sub">The checks that run automatically and what each may do</div></div></div><div class="panel-body">${(a.agents||[]).map(x=>`<div class="provider-row"><div><div class="provider-title">${esc(x.name)}</div><div class="provider-desc" title="${esc(x.definition_file)}">${esc(x.permissions)}</div></div>${pill(x.defined?'Defined':'Missing',x.defined?'good':'critical')}</div>`).join('')}</div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">Automatic lifecycle hooks</div><div class="panel-sub">Safe allowlisted handlers; no arbitrary scripts</div></div></div><div class="panel-body">${(a.hooks||[]).map(x=>`<div class="provider-row"><div><div class="provider-title" title="${esc(x.handler)}">${esc(x.event.replaceAll('_',' '))}</div></div>${pill(x.status,'good')}</div>`).join('')}<div class="info-card"><h3>Lossless conversation history</h3><p>Context summaries: ${a.context_summaries||0}. Original messages are always retained and chat write events point to the original instruction.</p></div><div class="info-card"><h3>Upgrade safety guard</h3><p>Every upgrade involving existing records must create a verified database backup before database changes begin. The upgrade stops if backup fails.</p></div></div></section></div><section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Schema reviewer — try an idea</div><div class="panel-sub">Advisory review only. Never applies migrations.</div></div></div><div class="panel-body"><form id="agentReviewForm" class="chat-form"><textarea id="agentReviewInput" class="chat-input" rows="2" placeholder="e.g. Add vendor GSTIN field and track subcontractor advances" required></textarea><button class="btn btn-primary" type="submit">Review</button></form><div id="agentReviewResult" class="muted mt-12">No proposed change has been reviewed in this session.</div></div></section>`;}

document.addEventListener('DOMContentLoaded',()=>{try{window.__pristineState=JSON.parse(JSON.stringify(state));}catch(e){}});   // every screen's starting values, taken once all scripts have loaded
function clearSessionData(){const keep=new Set(['sessionId','session']);for(const k of Object.keys(state)){if(!keep.has(k))delete state[k];}
 if(window.__pristineState)Object.assign(state,JSON.parse(JSON.stringify(window.__pristineState)));
 if(typeof clearUniversalSession==='function')clearUniversalSession();
 if(typeof chatOffer!=='undefined')chatOffer=null;
 if(typeof ppPhotoFor!=='undefined')ppPhotoFor=null;
 if(typeof flowClearHold==='function')flowClearHold();
 const overlays=$('ovRoot');if(overlays){overlays.hidden=true;overlays.replaceChildren();}
 const outbox=$('outboxChip');if(outbox){outbox.hidden=true;outbox.replaceChildren();}
 const main=$('mainContent');if(main)main.innerHTML='';}   // nothing from the previous person stays in memory or on screen
function showLogin(){keepTyping();for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();state.session=(state.session||0)+1;clearSessionData();state.user=null;state.mustSetup2fa=false;state.twoFactorSetup=null;state.recoveryCodes=null;state.sessionId='';sessionStorage.removeItem('studioos-chat-id');document.querySelector('.shell').inert=true;$('loginLayer').classList.remove('hidden');$('loginUsername').focus();}
function updateIdentity(){
 $('sampleBadge').hidden=!state.settings?.sample_data;
 const env=state.settings?.environment||'development';
 $('envLabel').dataset.env=env;document.body.dataset.env=env;$('envText').textContent=({production:'LIVE DATA',test:'TEST COPY · NOT LIVE',development:'DEVELOPMENT'})[env]||'DEVELOPMENT';
 $('safetyBadge').hidden=!(isAdmin()&&state.safety&&state.safety.overall==='fail');$('safetyBadge').title='Something needs attention. Open Settings, then System check.';$('safetyBadge').setAttribute('aria-label','Needs attention: open System check');
 const fin=hasFinance(),approver=isApprover(),admin=isAdmin();
 document.querySelectorAll('.finance-only').forEach(x=>x.classList.toggle('allowed',fin));
 document.querySelectorAll('.approver-only').forEach(x=>x.classList.toggle('allowed',approver));
 document.querySelectorAll('.admin-only').forEach(x=>x.classList.toggle('allowed',admin));
 const displayName=state.user?.display_name||state.user?.username||'StudioOS';
 $('userDisplay').textContent=displayName;
 $('userRole').textContent=state.user?.role?.replaceAll('_',' ')||'employee';
 const footAvatar=document.querySelector('.foot-user .avatar');
 if(footAvatar)footAvatar.textContent=displayName.slice(0,1).toUpperCase();
 applyRoleMenu();
 $('approvalBadge').textContent=(state.approvals?.costs?.length||0)+(state.approvals?.payments?.length||0);
}
function signedIn(r){state.user=r.user;state.mustSetup2fa=!!r.two_factor_setup_required;if(state.mustSetup2fa)state.view='account';$('loginLayer').classList.add('hidden');document.querySelector('.shell').inert=false;}
async function initialize(){try{let r=await api('/api/auth/me');signedIn(r);await refresh();}catch(err){showLogin();}}
$('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();$('loginError').textContent='';
 const btn=$('loginForm').querySelector('.auth-submit');
 if(btn&&btn.disabled)return;
 const prev=btn?btn.innerHTML:'';
 if(btn){btn.disabled=true;btn.setAttribute('aria-busy','true');btn.textContent='Signing in…';}
 try{let r=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:$('loginUsername').value,password:$('loginPassword').value,otp:$('loginOtp').value})});
  $('loginPassword').value='';$('loginOtp').value='';$('otpField').hidden=true;state.view=homeViewFor(r.user&&r.user.role);signedIn(r);await refresh();switchView(state.view);}
 catch(err){if(err.data?.otp_required){$('otpField').hidden=false;$('loginOtp').focus();}$('loginError').textContent=err.message;}
 finally{if(btn){btn.disabled=false;btn.removeAttribute('aria-busy');btn.innerHTML=prev;}}
});
$('logoutBtn').addEventListener('click',async()=>{keepTyping();try{await api('/api/auth/logout',{method:'POST'});}catch(e){}showLogin();});
function render(){updateIdentity();const views={overview,assistant,tickets,newtypes:newTypesView,universal:universalView,ledger:ledgerView,projects,tasks,budget:budgets,site,documents,activity,settings,approvals,team,agents,account,safety:safetyView};if(state.mustSetup2fa)state.view='account';$('mainContent').innerHTML=(views[state.view]||overview)();$('breadcrumb').textContent=({overview:'Overview',assistant:'Chat',tickets:'Change requests',newtypes:'New Data Inbox',universal:'Universal Types',ledger:'Accounting Ledger',projects:'Projects',tasks:'Tasks',budget:'Budgets & Costs',site:'Site Reports',documents:'NAS Documents',activity:'Activity Log',settings:'AI Providers',approvals:'Approvals',team:'Team & Roles',agents:'Agents & Hooks',account:'My account',safety:'Data safety'})[state.view];document.querySelectorAll('.nav-link').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));if(state.view==='assistant'){const m=$('chatMessages');if(m)m.scrollTop=m.scrollHeight;}}
function switchView(v){state.view=v;document.body.classList.toggle('chat-mode',v==='assistant');render();$('sidebar').classList.remove('open');window.scrollTo(0,0);if(VIEW_DATA[v]&&state.user)refresh();}
function optionsHtml(){return state.projects.length?state.projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join(''):'<option disabled>No projects — create one first</option>';}
function amountEcho(text){const t=String(text||'').trim().replace(/^(?:₹|rs\.?|inr)\s*/i,'');if(!/^[0-9][0-9,]*(\.[0-9]{1,2})?$/.test(t))return '';const whole=t.split('.')[0];if(whole.includes(',')&&!/^(?:[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}|[0-9]{1,3}(?:,[0-9]{3})+)$/.test(whole))return 'Check the commas, e.g. 1,25,000';const n=Number(t.replace(/,/g,''));if(!isFinite(n)||n<=0)return '';const words=n>=1e7?' ('+(n/1e7).toLocaleString('en-IN',{maximumFractionDigits:2})+' crore)':n>=1e5?' ('+(n/1e5).toLocaleString('en-IN',{maximumFractionDigits:2})+' lakh)':'';return inr(n)+words;}   // says the amount back as you type
const field=(label,name,type='text',placeholder='',required=true)=>`<div class="field"><label for="f-${name}">${label}</label><${type==='textarea'?'textarea':'input'} class="form-input" id="f-${name}" name="${name}" ${type==='amount'?'type="text" inputmode="decimal" autocomplete="off"':type!=='textarea'?`type="${type}"`:''} ${required?'required':''} placeholder="${esc(placeholder)}" ${type==='number'?'step="0.01" min="0"':''}>${type==='textarea'?'</textarea>':''}${type==='amount'?`<small class="muted amount-echo" data-amount-for="${name}" aria-live="polite"></small>`:''}</div>`;
function projectOwnerFields(options, project = {}, allowNew = false) {
 const {companies, clients} = options;
 const company = companies.find(row => row.id === project.company_id) || (companies.length === 1 ? companies[0] : null);
 const companyField = companies.length === 1
   ? '<div class="field"><label for="f-company_display">Company</label><input class="form-input" id="f-company_display" value="'+esc(company.name)+'" readonly><input type="hidden" name="company_id" value="'+Number(company.id)+'"></div>'
   : '<div class="field"><label for="f-company_id">Company</label><select id="f-company_id" name="company_id" class="form-input" required><option value="">Choose a company</option>'+companies.map(row=>'<option value="'+Number(row.id)+'"'+(row.id===company?.id?' selected':'')+'>'+esc(row.name)+'</option>').join('')+'</select></div>';
 const clientField = '<div class="field"><label for="f-client_id">Client (optional)</label><select id="f-client_id" name="client_id" class="form-input"><option value="">No client yet</option>'+clients.map(row=>'<option value="'+Number(row.id)+'"'+(row.id===project.client_id?' selected':'')+'>'+esc(row.name)+'</option>').join('')+(allowNew?'<option value="new">+ Add client</option>':'')+'</select></div>';
 const newClient = allowNew ? '<div class="field" id="newProjectClient" hidden><label for="f-client">New client name</label><input class="form-input" id="f-client" name="client" minlength="2" maxlength="200" disabled><small class="muted">The client is created when the project is approved.</small></div>' : '';
 return companyField + clientField + newClient;
}
function syncNewProjectClient(form) {
 const field = form.querySelector('#newProjectClient');
 if (!field) return;
 const addClient = form.elements.client_id.value === 'new';
 field.hidden = !addClient;
 form.elements.client.disabled = !addClient;
 form.elements.client.required = addClient;
}
function projectLinkValues(values) {
 const links = {company_id: Number(values.company_id)};
 if (values.client_id === 'new') links.client = values.client.trim();
 else links.client_id = Number(values.client_id) || null;
 return links;
}
function formMarkup(type){const projectSelect=`<div class="field"><label for="f-project_id">Project</label><select name="project_id" class="form-input" id="f-project_id" required>${optionsHtml()}</select></div>`;
 const extras=typeof extraCreateFields==='function'?extraCreateFields(type):'';
 if(type==='project')return field('Project name','name','text','e.g. Villa A')+projectOwnerFields(state.projectFormOptions, {}, true)+field('Location','location','text','',false)+field('Client phone','client_phone','tel','',false)+field('Approved budget (₹)','budget','amount','',false)+extras;
 if(type==='task')return projectSelect+field('Task title','title','text','e.g. Issue revised flooring drawings')+assigneeField()+field('Due date','due_date','date','',false)+extras;
 if(type==='user')return field('Username','username','text','')+field('Display name','display_name','text','')+field('Password (12+ characters)','password','password','')+`<div class="field"><label for="f-role">Role</label><select id="f-role" name="role" class="form-input" required><option value="architect">Architect</option><option value="site_engineer">Site engineer</option><option value="accounts">Accounts</option><option value="manager">Manager</option><option value="viewer">Viewer</option></select></div>`+extras;
 if(type==='siteexpense')return projectSelect+field('What was it for?','title','text','e.g. Tea and snacks for the crew')+'<div id="siteExpensePayment">Loading Books options…</div>'+field('Amount (₹, up to 5,000)','amount','amount','e.g. 1,200')+'<p class="muted">Someone else approves the expense before it is saved.</p>';
 if(type==='site')return projectSelect+field('Work done today','work_done','textarea','e.g. Slab shuttering finished on the first floor')+field('People on site (number)','people_on_site','number','e.g. 12')+field('Materials received','materials','text','e.g. 40 bags cement',false)+field('Delays or problems','issues','textarea','Anything that held work up, or "None"',false)+field('Plan for tomorrow','tomorrow','text','e.g. Start brickwork',false);return '';
}
async function peopleModal(projectId){const r=await api('/api/projects/'+Number(projectId)+'/members');const members=new Set(r.members.map(m=>m.user_id));
 const staff=(state.users||[]).filter(u=>!u.sees_all_projects&&u.active);const project=(state.projects||[]).find(p=>p.id===Number(projectId));
 const d=$('entryDialog');d.dataset.type='members';d.dataset.target=String(Number(projectId));$('modalTitle').textContent='People on '+(project?.name||'project');
 $('modalFields').innerHTML=`<p class="muted">${esc(r.note)}</p>`+(staff.length?`<div class="checkbox-list">${staff.map(u=>`<label class="checkbox-row"><input type="checkbox" name="user_ids" value="${Number(u.id)}" ${members.has(u.id)?'checked':''}> <span><strong>${esc(u.display_name)}</strong> · ${esc(u.role.replaceAll('_',' '))}</span></label>`).join('')}</div>`:'<p>No staff accounts need assigning yet. Add architects or site engineers in Team &amp; Roles.</p>');
 $('saveEntry').textContent='Save people';d.showModal();}
function resetPasswordModal(userId){const u=(state.users||[]).find(x=>x.id===Number(userId));const d=$('entryDialog');d.dataset.type='reset-password';d.dataset.target=String(Number(userId));
 $('modalTitle').textContent='Reset password for '+(u?.display_name||'employee');
 $('modalFields').innerHTML=`<p class="muted">They will be signed out everywhere and must use the new password. Tell them in person or by phone, not in a group chat.</p><div class="form-grid">${accountField('rp','New password (12+ characters)','new_password','password','new-password','minlength="12"')}</div>`;$('saveEntry').textContent='Reset password';d.showModal();}
function composeSiteReport(v){const line=(label,text)=>String(text||'').trim()?label+': '+String(text).trim():'';return [line('Work done today',v.work_done),line('People on site',v.people_on_site),line('Materials received',v.materials),line('Delays or problems',v.issues),line('Plan for tomorrow',v.tomorrow)].filter(Boolean).join('\n');}   // the standard daily site report, saved as one note
function assigneeField(){const people=(state.users||[]).filter(u=>u.active!==false&&u.role!=='viewer');   // a picker when the team list is available, so names are not typed (and mistyped)
 if(!people.length)return field('Assigned to','assignee','text','e.g. Ravi',false);
 return `<div class="field"><label for="f-assignee">Assigned to</label><select name="assignee" class="form-input" id="f-assignee"><option value="">Not assigned yet</option>${people.map(u=>`<option value="${esc(u.display_name||u.username)}">${esc(u.display_name||u.username)} · ${esc(String(u.role).replaceAll('_',' '))}</option>`).join('')}</select></div>`;}
function homeViewFor(role){return ({site_engineer:'home',accounts:'home',architect:'home',viewer:'home'})[role]||'assistant';}   // the first screen each role sees after signing in
const SITE_DRAFT_FIELDS=['project_id','work_done','people_on_site','materials','issues','tomorrow'];
function siteDraftKey(username){return 'studioos-site-draft:'+String(username||'');}
function saveSiteDraft(store,username,values){try{const kept={};for(const k of SITE_DRAFT_FIELDS)if(String(values[k]||'').trim())kept[k]=String(values[k]);if(Object.keys(kept).length)store.setItem(siteDraftKey(username),JSON.stringify(kept));else store.removeItem(siteDraftKey(username));}catch(e){}}   // a half-written site report stays on this phone until it is sent
function readSiteDraft(store,username){try{const raw=store.getItem(siteDraftKey(username));return raw?JSON.parse(raw):null;}catch(e){return null;}}
function clearSiteDraft(store,username){try{store.removeItem(siteDraftKey(username));}catch(e){}}
const IMMUTABLE_ITEM_KEYS=new Set(['id','idempotency_key','request_key','original_ticket_id','expected_digest','intake_id','record_type','record_id','expected','action','type_key','site_expense','expense_id','claim_id','receipt_intake_id','receipt_ids']);
function itemFieldPlan(after){   // how each field of a proposed item is edited; null when it has nested data (the text editor is used then)
 const fields=[];for(const [k,v] of Object.entries(after||{})){if(['attachment_ids','receipt_ids'].includes(k)&&Array.isArray(v)){fields.push({key:k,kind:'readonly',value:v,display:v.length+(v.length===1?' file':' files')});continue;}
  if(k==='custom'&&v&&typeof v==='object'&&!Array.isArray(v)){
   for(const [key,value] of Object.entries(v))fields.push({key:'custom.'+key,kind:'text',value});
   continue;
  }
  if(v!==null&&typeof v==='object')return null;
  let kind='text';if(IMMUTABLE_ITEM_KEYS.has(k))kind='readonly';else if(k.endsWith('_paise'))kind='amount';else if(k==='project'||k==='project_id')kind='project';else if(k==='cost_id')kind='cost';else if(k==='assignee')kind='person';else if(/(^|_)date$/.test(k))kind='date';else if(['no_vendor','personal_payment'].includes(k))kind='boolean';else if(['vendor_id','receipt_id','paid_through_id'].includes(k))kind='optional-number';else if(typeof v==='number')kind='number';
  fields.push({key:k,kind,value:v});}
 return fields;}
function itemEditorMarkup(plan){const sel=(k,label,options,chosen)=>`<div class="field"><label for="ie-${esc(k)}">${esc(label)}</label><select class="form-input" id="ie-${esc(k)}" name="${esc(k)}">${options.map(([val,text])=>`<option value="${esc(val)}" ${String(val)===String(chosen)?'selected':''}>${esc(text)}</option>`).join('')}</select></div>`;
 const label=k=>k.replace(/_paise$/,'').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
 return plan.map(f=>{const k=f.key,v=f.value;
  if(f.kind==='readonly')return `<div class="field"><label>${esc(label(k))}</label><div class="muted">${esc(f.display||v)} (cannot be changed here)</div></div>`;
  if(f.formField && ['text','date','choice'].includes(f.kind)){
   const control=regControl(f.formField,'ie-'+k,v,k);
   if(control)return `<div class="field"><label for="ie-${esc(k)}">${esc(f.formField.label)}</label>${control}</div>`;
  }
  if(f.kind==='amount')return `<div class="field"><label for="ie-${esc(k)}">${esc(label(k))} (₹)</label><input class="form-input" id="ie-${esc(k)}" name="${esc(k)}" type="text" inputmode="decimal" autocomplete="off" value="${v?esc(String(v/100)):''}"><small class="muted amount-echo" data-amount-for="${esc(k)}" aria-live="polite">${v?esc(amountEcho(String(v/100))):''}</small></div>`;
  if(f.kind==='project'){const projects=(state.projects||[]),byName=typeof v==='string',known=projects.some(p=>byName?p.name===v:Number(p.id)===Number(v));const opts=projects.map(p=>[byName?p.name:p.id,p.name]);if(!known&&v!==''&&v!=null)opts.unshift([v,'(current) '+v]);if(v===null)opts.unshift(['','No project']);return sel(k,label(k),opts,v??'');}
  if(f.kind==='cost')return sel(k,'Related expense or purchase',(state.costs||[]).map(c=>[c.id,'#'+c.id+' – '+c.title+(c.project?' ('+c.project+')':'')]),v);
  if(f.kind==='person'){const people=(state.users||[]).filter(u=>u.active!==false&&u.role!=='viewer').map(u=>[u.display_name||u.username,(u.display_name||u.username)+' · '+String(u.role).replaceAll('_',' ')]);if(!people.length)return `<div class="field"><label for="ie-${esc(k)}">${esc(label(k))}</label><input class="form-input" id="ie-${esc(k)}" name="${esc(k)}" type="text" value="${esc(v)}"></div>`;if(v&&!people.some(x=>x[0]===v))people.unshift([v,'(current) '+v]);return sel(k,label(k),[['','Not assigned yet'],...people],v);}
  if(f.kind==='date')return `<div class="field"><label for="ie-${esc(k)}">${esc(label(k))}</label><input class="form-input" id="ie-${esc(k)}" name="${esc(k)}" type="date" value="${esc(v)}"></div>`;
  if(f.kind==='boolean')return sel(k,changeFieldLabel(k),[['true','Yes'],['false','No']],v);
  if(f.kind==='choice')return sel(k,(f.label||label(k))+(f.required?' *':''),[['','Choose…'],...f.options.map(o=>Array.isArray(o)?o:[o,o])],v??'');
  if(f.kind==='number'||f.kind==='optional-number')return `<div class="field"><label for="ie-${esc(k)}">${esc(changeFieldLabel(k))}</label><input class="form-input" id="ie-${esc(k)}" name="${esc(k)}" type="number" step="1" min="0" value="${esc(v??'')}"></div>`;
  return `<div class="field"><label for="ie-${esc(k)}">${esc(label(k))}</label><input class="form-input" id="ie-${esc(k)}" name="${esc(k)}" type="text" value="${esc(v)}"></div>`;}).join('');}
function collectItemEdit(plan,values){const after={};for(const f of plan){const k=f.key,raw=values[k];
  if(k.startsWith('custom.')){(after.custom??={})[k.slice(7)]=String(raw??'');continue;}
  if(f.kind==='readonly'){after[k]=f.value;continue;}
  if(f.kind==='amount'){const paise=rupeesToPaise(raw);if(paise===null)throw new Error('Enter the amount like 5,000 or 1,25,000.');after[k]=paise;continue;}
  if(f.kind==='project'){if(typeof f.value==='string'){after[k]=String(raw);}else{after[k]=raw===''?null:Number(raw);}continue;}
  if(f.kind==='cost'){after[k]=Number(raw);continue;}
  if(f.kind==='boolean'){after[k]=raw==='true';continue;}
  if(f.kind==='number'||f.kind==='optional-number'){const t=String(raw==null?'':raw).trim();if(!t&&f.kind==='optional-number'){after[k]=null;continue;}if(!/^[0-9]+$/.test(t))throw new Error('This field expects a whole number.');after[k]=Number(t);continue;}
  after[k]=raw==null?'':String(raw);}
 return after;}
function openItemEditor(item,plan){if(plan&&typeof withRequiredFields==='function')plan=withRequiredFields(item,plan);const d=$('entryDialog');d.dataset.type='ticket-item';d.dataset.target=String(Number(item.id));state.itemEdit={id:item.id,plan,ticketId:state.ticketDetail?.id};
 $('modalTitle').textContent='Edit proposed item';$('modalFields').innerHTML=`<div class="form-grid">${itemEditorMarkup(plan)}</div><p class="muted">After you save, the item has to be approved again.</p>`;$('saveEntry').textContent='Save changes';$('saveEntry').disabled=false;d.showModal();}
function failedKeys(results,keys){return results.map((r,i)=>r.status==='rejected'?keys[i]:null).filter(Boolean);}   // which requests did not come back
function refreshBanner(){if(!(state.refreshFailed||[]).length)return '';return `<div class="notice fail" id="refreshBanner"><span>Some information could not be refreshed, so what you see may be out of date.</span><button class="btn btn-secondary btn-sm" data-action="retry-refresh">Try again</button></div>`;}
function formRequestKey(){
 const bytes=crypto.getRandomValues(new Uint8Array(16));
 return 'form-'+Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
}   // one per opened form, so a double tap or retry reuses it
function myPettyCashPanel(){
 return `<section class="panel section-gap">
  <div class="panel-head"><h2>My petty cash</h2></div>
  <div class="panel-body"><button class="btn btn-secondary" type="button" data-petty-cash-load>Show my petty cash</button>
   <div id="myPettyCash" aria-live="polite"></div>
  </div></section>`;
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-petty-cash-load]');
 if(!button||button.disabled)return;
 const target=$('myPettyCash');
 button.disabled=true;
 try{
  const data=await api('/api/petty-cash/mine');
  if(!target?.isConnected)return;
  if(!data.accounts.length){target.textContent='You do not have a petty cash account yet.';return;}
  target.innerHTML=data.accounts.map(account=>`<article class="newtype-card">
   <h3>${esc(account.company_name)}</h3>
   <p>You hold <strong>${esc(inr(account.balance_paise/100))}</strong></p>
   ${account.missing_receipt_count?`<p>${Number(account.missing_receipt_count)} expense${account.missing_receipt_count===1?' needs':'s need'} a receipt photo.</p>`:''}
   <form class="form-grid" data-petty-cash-form data-account="${Number(account.id)}" data-key="${formRequestKey()}">
    ${moneyAmountField(`petty-top-up-${Number(account.account_id)}`, 'Top-up amount (₹)')}
    <button class="btn btn-primary" type="submit">Ask for petty cash</button>
   </form>
  </article>`).join('');
 }catch(err){if(target?.isConnected)target.textContent=err.message;}
 finally{button.disabled=false;}
});
document.addEventListener('submit',async e=>{
 const form=e.target.closest('[data-petty-cash-form]');
 if(!form)return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 const amount=rupeesToPaise(form.elements.amount.value);
 if(amount===null||amount<=0){notify('Enter a top-up amount in rupees.',true);return;}
 button.disabled=true;
 try{
  const result=await api('/api/petty-cash/proposals',{method:'POST',body:JSON.stringify({
   account_id:Number(form.dataset.account),amount_paise:amount,request_key:form.dataset.key,
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Top-up change request #'+result.ticket_id+' was sent for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
let siteExpenseOptionsRequest=0;
function syncSiteVendorChoice(form){
 const choice=form.elements.vendor_id?.value;
 for(const [field,option] of [['suggested_vendor_name','suggest'],['no_vendor_name','none']]){
  const input=form.elements[field];
  if(!input)continue;
  const shown=choice===option;
  input.closest('.field').hidden=!shown;
  input.disabled=!shown;
  input.required=shown;
 }
}
async function loadSiteExpenseOptions(initial=false){
 const dialog=$('entryDialog'),fields=$('siteExpensePayment'),form=$('entryForm'),submit=$('saveEntry');
 if(!fields||dialog.dataset.type!=='siteexpense')return;
 if(initial)delete dialog.dataset.siteBooks;
 const seq=++siteExpenseOptionsRequest,project=Number(form.elements.project_id.value);
 const current=()=>seq===siteExpenseOptionsRequest&&dialog.open&&fields.isConnected;
 submit.disabled=true;
 try{
  const options=await api('/api/site-expenses/options?project_id='+project);
  if(!current())return;
  const select=(name,label,choices,required='')=>`<div class="field"><label for="se-${name}">${label}</label><select class="form-input" id="se-${name}" name="${name}" ${required}>${choices.map(([id,txt])=>`<option value="${esc(id)}">${esc(txt)}</option>`).join('')}</select></div>`;
  dialog.dataset.siteBooks='true';
  const paying=[...(options.paid_through?[['petty',options.paid_through.name]]:[]),['personal','I paid for this myself']];
  fields.innerHTML=`<input type="hidden" name="ledger" value="true">${options.company_name?'<p class="muted">Paid by '+esc(options.company_name)+'</p>':''}${select('site_payment','Paid through',paying,'required')}
    ${options.categories?.length?select('category_id','Expense category',[['','Other expense'],...options.categories.map(c=>[c.id,c.name])]):''}
    <div class="field"><label for="se-date">Expense date</label><input class="form-input" id="se-date" type="date" name="expense_date" value="${esc(options.today)}" required></div>
    ${select('vendor_id','Vendor',[['','Choose a project vendor'],...options.vendors.map(v=>[v.id,v.name]),['suggest','Suggest a new vendor'],['none','No vendor']],'required')}
    <div class="field" hidden><label for="se-suggested-vendor">Vendor name for review</label><input class="form-input" id="se-suggested-vendor" name="suggested_vendor_name" minlength="2" maxlength="200" disabled></div>
    <div class="field" hidden><label for="se-unregistered-payee">Who was paid?</label><input class="form-input" id="se-unregistered-payee" name="no_vendor_name" minlength="2" maxlength="120" disabled></div>
    <div class="field"><label for="se-photo">Take or choose a receipt photo</label><input id="se-photo" class="form-input" type="file" accept="image/jpeg,image/png" capture="environment">
    <input type="hidden" name="receipt_intake_id"><small id="se-photo-status" aria-live="polite"></small>
    <button type="button" class="btn btn-secondary btn-sm" id="se-remove-photo" hidden>Remove photo</button></div>
    ${select('receipt_id','Or choose a filed receipt',[['','No filed receipt'],...options.receipts.map(r=>[r.id,r.name])])}`;
  restoreEntryDraft(dialog);
  syncSiteVendorChoice(form);
  showSitePhotoState(form);
  submit.disabled=false;
 }catch(err){
  if(!current())return;
  fields.replaceChildren(Object.assign(document.createElement('p'),{textContent:err.message}));
 }
}
function showSitePhotoState(form){
 const photo=$('se-photo');
 if(!photo)return;
 const uploaded=Boolean(form.elements.receipt_intake_id.value);
 $('se-photo-status').textContent=uploaded?'Receipt photo uploaded.':'';
 $('se-remove-photo').hidden=!uploaded&&!photo.files.length;
}
async function prepareSitePhoto(form, values){
 const field=form.elements.receipt_intake_id;
 const photo=$('se-photo');
 if(!field||!photo)return;
 if(photo.files.length&&!field.value){
  const selected=photo.files[0];
  const {filename,base64}=await encodeFile(selected);
  const result=await api('/api/intake/upload',{method:'POST',body:JSON.stringify({filename,base64})});
  if(!['image/jpeg','image/png'].includes(result.media_type)||['quarantined','rejected'].includes(result.status))
   throw new Error('Choose a JPG or PNG receipt photo that can be checked.');
  if(!field.isConnected||!$('entryDialog').open||photo.files[0]!==selected)
   throw new Error('The receipt choice changed. Review the form and send it again.');
  field.value=String(result.id);
  rememberEntryDraft({target:field});
  if(field.isConnected)showSitePhotoState(form);
 }
 if(field.value)values.receipt_intake_id=Number(field.value);
 else delete values.receipt_intake_id;
}
async function withBusyButton(btn,label,fn){
 if(btn&&btn.disabled)return;
 const prev=btn?btn.textContent:'';
 if(btn){btn.disabled=true;btn.setAttribute('aria-busy','true');if(label)btn.textContent=label;}
 try{return await fn();}
 finally{if(btn&&btn.isConnected){btn.disabled=false;btn.removeAttribute('aria-busy');if(label)btn.textContent=prev;}}
}
function showDraftRestoredBar(){
 const holder=$('modalFields');
 if(!holder||$('entryDraftBar'))return;
 holder.insertAdjacentHTML('afterbegin','<div class="notice" id="entryDraftBar"><span>Draft restored from earlier.</span><button type="button" class="btn btn-secondary btn-sm" data-action="clear-entry-draft">Start fresh</button></div>');
}
async function modal(type, opts={}){
 const session=state.session;
 if(['project','task','user'].includes(type)&&typeof loadCreateFormOptions==='function'){
  try{await loadCreateFormOptions(true);}
  catch(error){if(state.session===session)notify(error.message,true);return;}
  if(state.session!==session)return;
 }
 if(type==='index-nas'){scanNas(opts.button);return;}if(!['project','task','site','user','siteexpense'].includes(type))return;if(type==='project'&&!state.projectFormOptions){notify('Company and client choices are unavailable. Refresh and try again.',true);return;}if(type==='project'&&!state.projectFormOptions.companies.length){notify(isAdmin()?'Set up your company first.':'Ask the owner to set up the company first.',true);if(isAdmin()){switchView('ledger');document.querySelector('[data-u="setup-finance"]')?.click();}return;}if(!['project','user'].includes(type)&&!state.projects.length){notify('Create a project first.',true);switchView('projects');return;}const d=$('entryDialog');d.dataset.type=type;d.dataset.requestKey=formRequestKey();$('saveEntry').disabled=false;$('modalTitle').textContent=({project:'New project',task:'New task',site:'New site report',siteexpense:'Site expense',user:'Add person'})[type];$('modalFields').innerHTML=`<div class="form-grid">${formMarkup(type)}</div>`;if(typeof applyCreateRequirements==='function')applyCreateRequirements(type,$('entryForm'));$('saveEntry').textContent=(type==='user'?'Save entry':'Send for approval');d.showModal();const restored=restoreEntryDraft(d);if(restored)showDraftRestoredBar();if(type==='site'){const draft=readSiteDraft(window.localStorage,state.user?.username);if(draft){for(const [k,v] of Object.entries(draft)){const el=$('entryForm').elements[k];if(el&&el.type!=='file')el.value=v;}showDraftRestoredBar();notify('Your unsent site report draft was restored.');}}if(opts&&opts.projectId){const sel=document.querySelector('#modalFields select[name="project_id"], #modalFields select[name="project"]');if(sel&&[...sel.options].some(o=>o.value===String(opts.projectId)))sel.value=String(opts.projectId);}}
async function submitModal(e){e.preventDefault();const d=$('entryDialog'),type=d.dataset.type,form=$('entryForm'),values=Object.fromEntries(new FormData(form).entries());
 if(type==='project'){
  const links=projectLinkValues(values);
  delete values.client_id;
  delete values.client;
  Object.assign(values,links);
 }
 if(type==='siteexpense'&&values.ledger==='true'){
  values.ledger=true;values.no_vendor=values.vendor_id==='none';
  if(values.vendor_id!=='suggest')delete values.suggested_vendor_name;
  if(!values.no_vendor)delete values.no_vendor_name;
  if(values.category_id)values.category_id=Number(values.category_id);
  else delete values.category_id;
  values.personal_payment=values.site_payment==='personal';delete values.site_payment;
  values.vendor_id=Number(values.vendor_id)||null;values.receipt_id=Number(values.receipt_id)||null;
 }
 if(type==='ticket-item'){const btn=$('saveEntry');if(btn.disabled)return;const edit=state.itemEdit;try{const after=collectItemEdit(edit.plan,values);btn.disabled=true;await api('/api/tickets/items/'+Number(edit.id),{method:'PATCH',body:JSON.stringify({after,note:'Edited in ticket review'})});d.close();state.ticketDetail=await api('/api/tickets/'+Number(edit.ticketId));await refresh();notify('Item updated. It needs approving again.');}catch(err){notify(err.message,true);}finally{btn.disabled=false;}return;}
 if(type==='members'||type==='reset-password'){try{
   if(type==='members'){const ids=new FormData(form).getAll('user_ids').map(Number);await api('/api/projects/'+Number(d.dataset.target)+'/members',{method:'PUT',body:JSON.stringify({user_ids:ids})});notify('Project people updated.');}
   else{await api('/api/users/'+Number(d.dataset.target)+'/reset-password',{method:'POST',body:JSON.stringify({new_password:values.new_password})});notify('Password reset. They have been signed out everywhere.');}
   d.close();await refresh();}catch(err){notify(err.message,true);}return;}const map={project:'/api/projects',task:'/api/tasks',site:'/api/site-reports',siteexpense:'/api/site-expenses',user:'/api/users'};if(type==='site'){values.note=composeSiteReport(values);for(const k of ['work_done','people_on_site','materials','issues','tomorrow'])delete values[k];}for(let k of ['project_id','cost_id'])if(values[k])values[k]=Number(values[k]);if(['project','task','user'].includes(type)&&typeof regCollect==='function')regCollect(type,values);if(!d.dataset.requestKey)d.dataset.requestKey=formRequestKey();if(type!=='user')values.request_key=d.dataset.requestKey;const saveButton=$('saveEntry');if(saveButton.disabled)return;saveButton.disabled=true;try{if(type==='siteexpense'&&values.ledger===true)await prepareSitePhoto(form,values);const saved=await api(map[type],{method:'POST',body:JSON.stringify(values)});d.close();clearEntryDraft(type);if(type==='site')clearSiteDraft(window.localStorage,state.user?.username);notify(saved.ticket_id?'Draft sent for approval.':'Entry saved successfully.');await refresh();}catch(err){notify(err.message,true);}finally{saveButton.disabled=false;}}
async function scanNas(btn){return withBusyButton(btn,'Scanning…',async()=>{try{const r=await api('/api/documents/index-nas',{method:'POST'});notify(`Scanned NAS metadata. ${r.added} new documents indexed.`);await refresh();}catch(err){notify(err.message,true);}});}
async function encodeFile(file){
 const buf=await file.arrayBuffer();const bytes=new Uint8Array(buf);
 if(bytes.length>8*1024*1024)throw new Error('Attachment exceeds 8MB');
 let s='';for(let n=0;n<bytes.length;n+=8192)s+=String.fromCharCode(...bytes.subarray(n,n+8192));
 return {filename:file.name,media_type:file.type||'application/octet-stream',base64:btoa(s)};
}
async function sendChat(content){
 const v=content?.trim();if(!v)return;
 const files=Array.from($('chatFiles')?.files||[]);
 state.messages.push({role:'user',reply:v});render();
 const input=$('chatInput');if(input)input.value='';
 try{
  let r;
  if(files.length){
   let attachments=[];for(let f of files)attachments.push(await encodeFile(f));
   r=await api('/api/new-types/intake',{method:'POST',body:JSON.stringify({text:v,session_id:state.sessionId,attachments})});
   r={...r,reply:'Files and original input parked. Review the fit result and answer questions in New Data Inbox.',changed:false};
  }else r=await api('/api/chat',{method:'POST',body:JSON.stringify({message:v,session_id:state.sessionId,...(state.scope&&state.scope.project_id?{project_id:state.scope.project_id}:{})})});
  state.sessionId=r.session_id;sessionStorage.setItem('studioos-chat-id',state.sessionId);
  state.messages.push({role:'assistant',reply:r.reply,proposal:r.proposal,ticket_id:r.ticket_id,preview:r.preview,holding_item:r.holding_item});
  if(r.ticket_id||r.changed||r.holding_item)await refresh();else render();
 }catch(err){state.messages.push({role:'assistant',reply:'Error: '+err.message});render();}
}
// Delegated listeners survive rerenders.
document.addEventListener('click',async e=>{let b=e.target.closest('[data-view],[data-action],[data-prompt]');if(!b)return;if(b.dataset.view){switchView(b.dataset.view);return;}if(b.dataset.prompt){switchView('assistant');sendChat(b.dataset.prompt);return;}const a=b.dataset.action;
 if (a === 'books-expense') { await openMoneyEntry(state.budgetLedger?.data?.project_id); return; }
 if (a === 'books-order') { switchView('ledger'); await showPurchaseOrderForm(); return; }
 if (a === 'books-payment') {
   if (isAdmin() || state.user?.role === 'accounts') { await openBooksDue(); return; }
   switchView('ledger');
   const project = state.projects.find(row=>row.id===state.budgetLedger?.data?.project_id);
   if (project?.company_id) await showVendorPayment(project.company_id);
   else document.querySelector('[data-u="load-companies"]')?.click();
   return;
 }
 if(a==='clear-entry-draft'){
  const d=$('entryDialog'),t=d?.dataset.type;
  clearEntryDraft(t);
  if(t==='site')clearSiteDraft(window.localStorage,state.user?.username);
  $('entryForm')?.reset();
  $('entryDraftBar')?.remove();
  if(t==='siteexpense')loadSiteExpenseOptions(true);
  return;
 }
 if(['diagnose-new-type','dashboard-new-type'].includes(a)){
  const id=Number(b.dataset.id);
  if(a==='diagnose-new-type'){
   if(!await askConfirm('Analyze source information using the selected AI provider? A live provider may incur API charges. Nothing will be approved or executed.'))return;
   await withBusyButton(b,'Analyzing…',async()=>{
    try{
     await api(`/api/new-types/${id}/diagnose`,{method:'POST',body:'{}'});
     state.newTypeDetail=await api('/api/new-types/'+id);
     render();document.querySelector('#newTypeReview')?.scrollIntoView({block:'start'});
    }catch(err){notify(err.message,true);}
   });
  }else{
   await withBusyButton(b,'Loading…',async()=>{
    try{
     const charts=await Promise.all([0,1].map(idx=>api(`/api/new-types/${id}/dashboard/${idx}`)));
     state.newTypeDashboard={id,charts};
     render();document.querySelector('#newTypeReview')?.scrollIntoView({block:'start'});
    }catch(err){notify(err.message,true);}
   });
  }
  return;
 }
 if(['open-new-type','close-new-type','approve-new-type','edit-new-type','keep-new-type','reject-new-type'].includes(a)){
  try{
   if(a==='close-new-type'){state.newTypeDetail=null;render();return;}
   if(a==='open-new-type'){state.newTypeDetail=await api('/api/new-types/'+Number(b.dataset.id));switchView('newtypes');document.querySelector('#newTypeReview')?.scrollIntoView({behavior:'smooth'});return;}
   const id=Number(b.dataset.id);
   if(a==='approve-new-type'){
    if(!await askConfirm('Admin approval saves ONLY the schema design. No business table will be created. Proceed?'))return;
    await api(`/api/new-types/${id}/approve-structure`,{method:'POST',body:JSON.stringify({note:'The owner approved the design.'})});
   }else if(a==='edit-new-type'){
    const h=state.newTypeDetail||await api('/api/new-types/'+id);
    const edited=await askText('Edit the proposed design.',JSON.stringify(h.proposal||{},null,2));
    if(edited===null)return;
    await api(`/api/new-types/${id}/proposal`,{method:'PATCH',body:JSON.stringify({design:JSON.parse(edited),recompile:true})});
   }else{
    let action=a==='keep-new-type'?'keep':'reject';
    await api(`/api/new-types/${id}/${action}`,{method:'POST',body:JSON.stringify({note:'Reviewed in design review UI'})});
   }
   state.newTypeDetail=await api('/api/new-types/'+id);await refresh();notify('New data type review updated; no database migration ran.');
  }catch(err){notify(err.message,true);}return;
 }
 if(['project-members','reset-password','user-toggle','user-reset-2fa','dismiss-codes','cancel-2fa-setup'].includes(a)){
  try{
   if(a==='project-members'){await peopleModal(b.dataset.id);return;}
   if(a==='reset-password'){resetPasswordModal(b.dataset.id);return;}
   if(a==='dismiss-codes'){state.recoveryCodes=null;render();return;}
   if(a==='cancel-2fa-setup'){state.twoFactorSetup=null;render();return;}
   const reason=await askText(a==='user-toggle'?(b.dataset.active==='1'?'Reason for deactivating this account:':'Reason for reactivating this account:'):'Reason for resetting their two-factor login (e.g. lost phone):','');
   if(reason===null)return;if(reason.trim().length<5)throw new Error('Please give a reason of at least 5 characters.');
   if(a==='user-toggle'){await api('/api/users/'+Number(b.dataset.id)+'/active',{method:'PATCH',body:JSON.stringify({active:b.dataset.active!=='1',reason})});notify(b.dataset.active==='1'?'Account deactivated and signed out.':'Account reactivated.');}
   else{await api('/api/users/'+Number(b.dataset.id)+'/reset-2fa',{method:'POST',body:JSON.stringify({reason})});notify('Two-factor login reset; they have been signed out.');}
   await refresh();
  }catch(err){notify(err.message,true);}return;
 }
 if(a==='new-conversation'){state.sessionId='';state.messages=[];sessionStorage.removeItem('studioos-chat-id');render();return;}
 if(a==='ticket-page'){state.ticketPageOffset=Math.max(0,Number(b.dataset.offset)||0);state.ticketDetail=null;await refresh();return;}
 if(['open-ticket','close-ticket','approve-ticket-item','reject-ticket-item','return-item','resubmit-item','edit-ticket-item','edit-ticket-field','reverse-ticket','commit-ticket','approve-bank-batch','approve-save-change'].includes(a)){
  try{
   if(a==='close-ticket'){state.ticketDetail=null;render();return;}
   if(a==='open-ticket'){const gen=state.session;const t=await api('/api/tickets/'+b.dataset.id);if(gen!==state.session)return;state.ticketDetail=t;render();document.getElementById('ticketReview')?.scrollIntoView({behavior:'smooth'});return;}
   if(a==='approve-save-change'){
    const id=Number(b.dataset.id), session=state.session;
    const review=b.dataset.review?JSON.parse(b.dataset.review):changeSaveReview(id);
    if(!review||b.disabled)return;
    b.disabled=true;
    try{
      await api('/api/tickets/'+id+'/approve-and-save',{method:'POST',body:JSON.stringify(review)});
      if(session!==state.session)return;
      if(state.ticketDetail?.id===id){
        const saved=await api('/api/tickets/'+id);
        if(session!==state.session)return;
        if(state.ticketDetail?.id===id)state.ticketDetail=saved;
      }
      await refresh();if(session===state.session)notify('Change saved.');
    }finally{b.disabled=false;}
    return;
   }
   if(a==='approve-bank-batch'){
    if(!document.getElementById('bankBatchChecked')?.checked)throw new Error('Check every proposed match against the statement first.');
    if(!await askConfirm('Approve and save every reviewed bank match in this change request? Any failed check rolls back the entire request.'))return;
    await withBusyButton(b,'Saving…',async()=>{
     const review_fingerprints=Object.fromEntries(state.ticketDetail.items.map(item=>[item.id,item.review_fingerprint]));
     await api('/api/tickets/'+b.dataset.id+'/approve-and-save',{method:'POST',body:JSON.stringify({confirmed:[],review_fingerprints,note:'Reviewed every proposed bank match against the independent statement'})});
     state.ticketDetail=await api('/api/tickets/'+b.dataset.id);await refresh();notify('Reviewed bank matches saved.');
    });
    return;
   }
   if(a==='reverse-ticket'){
    const reason=await askText('Why are you undoing this save? Use at least 10 characters.','');
    if(reason===null)return;
    const draft=await api('/api/tickets/'+b.dataset.id+'/reverse',{method:'POST',body:JSON.stringify({reason})});
    state.ticketDetail=await api('/api/tickets/'+draft.ticket_id);await refresh();notify('Undo request #'+draft.ticket_id+' opened. Review and approve it to undo the saved change.');return;
   }
   if(a==='edit-ticket-field'){
    const item=state.ticketDetail?.items?.find(x=>String(x.id)===String(b.dataset.id))||state.messages.map(m=>m.preview?.items||[]).flat().find(x=>String(x.id)===String(b.dataset.id));
    if(!item)throw new Error('Open the change request before editing.');
    const key=b.dataset.field;const value=item.after?.[key];
    const inPaise=key.endsWith('_paise');
    const entered=await askText(inPaise?'Edit '+key.replace(/_paise$/,'')+' in rupees, like 5,000 (you will need to reapprove the item):':'Edit '+key+' (you will need to reapprove the item):',inPaise?(value?String(value/100):''):(value==null?'':typeof value==='object'?JSON.stringify(value):String(value)));
    if(entered===null)return;
    const update={...item.after};
    if(inPaise){const paise=rupeesToPaise(entered);if(paise===null)throw new Error('Enter the amount like 5,000 or 1,25,000.');update[key]=paise;}
    else if(typeof value==='number'||(value==null&&key.endsWith('_id'))){
      if(!/^\d+$/.test(entered.trim()))throw new Error('This field expects a whole number.');
      update[key]=Number(entered);
    }else if(value!==null&&typeof value==='object'){update[key]=JSON.parse(entered);}else{update[key]=entered;}
    await api('/api/tickets/items/'+item.id,{method:'PATCH',body:JSON.stringify({after:update,note:'Edited field '+key+' from mobile review'})});
    state.ticketDetail=await api('/api/tickets/'+(state.ticketDetail?.id||item.ticket_id||state.messages.find(m=>m.ticket_id)?.ticket_id));
    await refresh();notify('Field edited. Reapproval required.');return;
   }
   if(a==='commit-ticket'){
    if(!b.dataset.flowGo&&!await askConfirm('Save all approved changes?'))return;
    await api('/api/tickets/'+b.dataset.id+'/commit',{method:'POST'});notify('Approved changes saved.');state.ticketDetail=await api('/api/tickets/'+b.dataset.id);await refresh();return;
   }
   let itemId=b.dataset.id;
   if(a==='edit-ticket-item'){
    let item=state.ticketDetail?.items?.find(x=>String(x.id)===String(itemId));
    const plan=itemFieldPlan(item?.after);if(plan){openItemEditor(item,plan);return;}
    const raw=await askText('Edit proposed values. The change will need approval again.',JSON.stringify(item?.after||{},null,2),'Save changes');
    if(raw===null)return;
    let after=JSON.parse(raw);
    await api('/api/tickets/items/'+itemId,{method:'PATCH',body:JSON.stringify({after,note:'Edited in ticket review'})});
   } else {
    const op=a==='approve-ticket-item'?'approve':a==='return-item'?'return':a==='resubmit-item'?'resubmit':'reject';
    const note=(op==='resubmit'||(op==='approve'&&b.dataset.flowGo==='1'))?'':await askText(op==='return'?'What needs correcting?':op==='reject'?'Reason for rejection (optional)':'Reviewer note (optional)','',op==='return'?'Return for correction':op==='reject'?'Reject change':'Approve item');
    if(note===null)return;if(op==='return'&&note.trim().length<3){notify('Say what needs correcting, so the person knows what to fix.',true);return;}
    const review_fingerprint=op==='approve'?state.ticketDetail.items.find(item=>String(item.id)===itemId)?.review_fingerprint:undefined;
    await api('/api/tickets/items/'+itemId+'/'+op,{method:'POST',body:JSON.stringify({note,review_fingerprint})});
   }
   state.ticketDetail=await api('/api/tickets/'+state.ticketDetail.id);await refresh();notify('Review recorded.');
  }catch(err){notify(err.message,true);}return;
 }
 if (['project','task','site','siteexpense','user','index-nas'].includes(a)) {
   modal(a, {button:b});
   if (a === 'siteexpense') loadSiteExpenseOptions(true);
   return;
 }
 if(a==='complete'){await withBusyButton(b,'Submitting…',async()=>{try{const draft=await api('/api/tasks/'+b.dataset.id+'/complete',{method:'PATCH'});await refresh();notify('Task completion request #'+draft.ticket_id+' opened. Review it in Change requests to save the change.');}catch(err){notify(err.message,true);}});return;}if(a==='switch-provider'){await withBusyButton(b,'Switching…',async()=>{try{await api('/api/settings/provider',{method:'POST',body:JSON.stringify({provider:b.dataset.provider})});notify('AI provider changed; project data is untouched.');await refresh();}catch(err){notify(err.message,true);}});return;}});
async function accountSubmit(form){const v=Object.fromEntries(new FormData(form).entries());
 try{
  if(form.id==='changePasswordForm'){if(v.new_password!==v.repeat_password)throw new Error('The two new passwords do not match.');
   const r=await api('/api/auth/change-password',{method:'POST',body:JSON.stringify({current_password:v.current_password,new_password:v.new_password})});form.reset();notify('Password changed.'+(r.other_sessions_ended?' Other devices were signed out.':''));return;}
  if(form.id==='twoFactorSetupForm'){state.twoFactorSetup=await api('/api/auth/2fa/setup',{method:'POST',body:JSON.stringify({password:v.password,code:v.code})});render();return;}
  if(form.id==='twoFactorEnableForm'){const r=await api('/api/auth/2fa/enable',{method:'POST',body:JSON.stringify({code:v.code})});state.twoFactorSetup=null;state.recoveryCodes=r.recovery_codes;
   const wasLocked=state.mustSetup2fa;state.mustSetup2fa=false;state.user={...state.user,two_factor:true};await refresh();notify(wasLocked?'Two-factor login is on. StudioOS is unlocked.':'Two-factor login is on.');return;}
  if(form.id==='twoFactorCodesForm'){const r=await api('/api/auth/2fa/recovery-codes',{method:'POST',body:JSON.stringify({password:v.password,code:v.code})});state.recoveryCodes=r.recovery_codes;render();return;}
  if(form.id==='twoFactorDisableForm'){if(!await askConfirm('Turn off two-factor login? Signing in will need only your password.'))return;
   await api('/api/auth/2fa/disable',{method:'POST',body:JSON.stringify({password:v.password,code:v.code})});state.user={...state.user,two_factor:false};await refresh();notify('Two-factor login is off.');return;}
 }catch(err){notify(err.message,true);}}
document.addEventListener('submit',e=>{
 if(['changePasswordForm','twoFactorSetupForm','twoFactorEnableForm','twoFactorCodesForm','twoFactorDisableForm'].includes(e.target.id)){e.preventDefault();accountSubmit(e.target);return;}
 if(e.target.id==='previewRequirementForm'){
 e.preventDefault();const form=e.target;
 let record;
 try{record=JSON.parse(new FormData(form).get('record')||'{}');}
 catch(err){notify('Check the format of the example values and try again.',true);return;}
 api('/api/new-types/'+Number(form.dataset.id)+'/preview-record',{method:'POST',
   body:JSON.stringify({record,phase:new FormData(form).get('phase')})})
 .then(async()=>{state.newTypeDetail=await api('/api/new-types/'+Number(form.dataset.id));render();
   document.querySelector('#newTypeReview')?.scrollIntoView({behavior:'smooth'});
   notify('Requirements checked. This preview did not save a business record.');})
 .catch(err=>notify(err.message,true));return;
 }
if(e.target.id==='capabilityCheckWorkflow'){
 e.preventDefault();const form=e.target;const id=Number(form.dataset.id);
 const data=Object.fromEntries(new FormData(form));
 api(`/api/new-types/${id}/workflow/evaluate`,{method:'POST',body:JSON.stringify({record_id:Number(data.record_id),destination:data.destination})})
 .then(result=>{state.newTypeWorkflowResult={id,...result};render();})
 .catch(err=>notify(err.message,true));return;
}
if(e.target.id==='newTypeAnswers'){
  e.preventDefault();const form=e.target;let answers={};
  for(const [k,v] of new FormData(form).entries()){if(String(v).trim())answers[k]=String(v);}
  api('/api/new-types/'+Number(form.dataset.id)+'/answers',{method:'POST',body:JSON.stringify({answers})})
   .then(async h=>{state.newTypeDetail=h;await refresh();notify('Proposal updated; source preserved.');})
   .catch(err=>notify(err.message,true));return;
 }
if(e.target.id==='agentReviewForm'){e.preventDefault();const idea=$('agentReviewInput').value;api('/api/agents/review',{method:'POST',body:JSON.stringify({agent:'schema-reviewer',record:{idea}})}).then(result=>{const el=$('agentReviewResult');if(el)el.textContent=result.decision+': '+result.findings.map(x=>x.message).join(' · ');}).catch(err=>notify(err.message,true));return;}if(e.target.id==='chatForm'){e.preventDefault();const val=$('chatInput').value;sendChat(val);}});
document.addEventListener('keydown',e=>{if(e.target.id==='chatInput'&&e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat(e.target.value);}});
$('entryForm').addEventListener('submit',submitModal);
$('closeModal').addEventListener('click',()=>$('entryDialog').close());
$('cancelModal').addEventListener('click',()=>{const d=$('entryDialog'),t=d?.dataset.type;clearEntryDraft(t);if(t==='site')clearSiteDraft(window.localStorage,state.user?.username);d.close();});
$('refreshBtn').addEventListener('click',()=>withBusyButton($('refreshBtn'),null,()=>refresh().then(()=>notify('Dashboard refreshed.'))));
$('menuBtn').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&$('sidebar').classList.contains('open')){
  $('sidebar').classList.remove('open');$('menuBtn').focus();
 }
});
document.addEventListener('click',event=>{
 if(!event.target.closest('#sidebar,#menuBtn'))$('sidebar').classList.remove('open');
});
// Sign-in starts only once every script has loaded. If it ran sooner, a quick answer could clear the screens' starting values before they were saved (see __pristineState above).
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize);else initialize();
document.addEventListener('input',e=>{const el=e.target;if(!el||el.tagName!=='INPUT'||el.getAttribute('inputmode')!=='decimal')return;const out=el.form&&el.form.querySelector('[data-amount-for="'+el.name+'"]');if(out)out.textContent=amountEcho(el.value);});
function tableRowMatches(rowText,query){const q=String(query||'').trim().toLowerCase();return !q||String(rowText||'').toLowerCase().includes(q);}   // search: a row stays if it contains the typed words
function addTableSearch(){document.querySelectorAll('.table-wrap').forEach(wrap=>{const table=wrap.querySelector('table.data-table');if(!table||wrap.dataset.hasSearch==='1'||wrap.previousElementSibling?.classList.contains('table-search'))return;const tbody=table.querySelector('tbody');const rows=[...table.querySelectorAll('tbody tr')];if(rows.length<8)return;
 wrap.dataset.hasSearch='1';
 const box=document.createElement('input');box.type='search';box.className='form-input table-search';box.placeholder='Search this list';box.setAttribute('aria-label','Search this list');
 const count=document.createElement('small');count.className='muted table-search-count';count.setAttribute('aria-live','polite');
 const cols=table.querySelectorAll('thead th').length||1;
 const emptyRow=document.createElement('tr');emptyRow.className='table-no-matches';emptyRow.hidden=true;emptyRow.innerHTML=`<td colspan="${cols}" class="muted">No matching rows</td>`;
 if(tbody)tbody.appendChild(emptyRow);
 box.addEventListener('input',()=>{let shown=0;rows.forEach(r=>{const ok=tableRowMatches(r.textContent,box.value);r.hidden=!ok;if(ok)shown++;});emptyRow.hidden=shown>0;count.textContent=box.value.trim()?`Showing ${shown} of ${rows.length}`:'';});
 wrap.parentNode.insertBefore(box,wrap);wrap.parentNode.insertBefore(count,wrap);});}
// Extra work that must follow every screen draw is registered here, in order, instead of wrapping render() again.
const afterRenderHooks=[];function onAfterRender(fn){afterRenderHooks.push(fn);}
{const _renderCore=render;render=function(){_renderCore.apply(this,arguments);for(const hook of afterRenderHooks){try{hook();}catch(e){}}};}
onAfterRender(()=>{addTableSearch();});
function waitingCounts(st){const wq=st.workQueue;   // the server counts across ALL tickets; the loaded page is only a fallback
 if(wq&&typeof wq.to_review==='number')return {tickets:wq.to_review,parked:Number(wq.parked)||0,toSave:Number(wq.approved_to_save)||0,returned:Number(wq.returned_for_correction)||0};
 const open=t=>!['committed','reversed'].includes(t.status)&&(t.items||[]).some(i=>i.status==='pending');const parkedDone=['approved_design_only','rejected','revoked_design_only','kept'];
 return {tickets:(st.tickets||[]).filter(open).length,parked:(st.newTypes||[]).filter(h=>!parkedDone.includes(h.state)).length,toSave:0,returned:0};}   // one place to see everything waiting for you
function waitingItems(st,limit=5){const c=waitingCounts(st);const open=t=>!['committed','reversed'].includes(t.status)&&(t.items||[]).some(i=>i.status==='pending');const parkedDone=['approved_design_only','rejected','revoked_design_only','kept'];
 return {counts:c,tickets:(st.tickets||[]).filter(open).slice(0,limit),parked:(st.newTypes||[]).filter(h=>!parkedDone.includes(h.state)).slice(0,limit)};}
function waitingForYou(){const w=waitingItems(state),c=w.counts;if(!c.tickets&&!c.parked&&!c.toSave&&!c.returned)return `<section class="panel v-pad"><strong>Nothing is waiting for you.</strong></section>`;   // one list of everything waiting, with a button on each row
 const ticketRows=w.tickets.map(t=>`<li class="row-between"><span><strong>Change request #${Number(t.id)}</strong> <span class="muted">${esc(changeRequestSummary(t.summary).slice(0,80))}</span></span><button class="btn btn-primary btn-sm" data-action="open-ticket" data-id="${Number(t.id)}">Review</button></li>`).join('');
 const parkedRows=w.parked.map(h=>`<li class="row-between"><span><strong>Waiting for a place #${Number(h.id)}</strong> <span class="muted">${esc(String(h.raw_payload?.text||'').slice(0,80))}</span></span><button class="btn btn-secondary btn-sm" data-action="open-new-type" data-id="${Number(h.id)}">Review</button></li>`).join('');
 return `<section class="panel v-pad"><strong>Waiting for you</strong><ul class="rs-history">${ticketRows}${parkedRows}</ul><div class="row-between mt-17">${c.toSave?`<button class="btn btn-secondary btn-sm" data-view="tickets">${c.toSave} approved, waiting to be saved</button>`:''}${c.returned?`<button class="btn btn-secondary btn-sm" data-view="tickets">${c.returned} sent back for correction</button>`:''}${c.tickets>w.tickets.length?`<button class="btn btn-secondary btn-sm" data-view="tickets">All ${c.tickets} change requests</button>`:''}${c.parked>w.parked.length?`<button class="btn btn-secondary btn-sm" data-view="newtypes" data-tab="waiting">All ${c.parked} waiting for a place</button>`:''}</div></section>`;}
function approvalLimitPanel(){const v=state.approvalLimit,m=state.approvalMonthly;return `<section class="panel section-gap" id="approvalLimitPanel"><div class="panel-head"><div><div class="panel-title">Manager approval limit</div><div class="panel-sub">Let Managers approve costs and payments up to this amount each, entered by someone else. Above it, only you can approve. Leave empty or 0 to switch it off.</div></div></div>
 <form class="panel-body" id="approvalLimitForm"><div class="field"><label for="f-limit">Limit per entry (₹)</label><input class="form-input" id="f-limit" name="limit" type="text" inputmode="decimal" autocomplete="off" value="${v?esc(String(v/100)):''}" placeholder="e.g. 5,000"><small class="muted amount-echo" data-amount-for="limit" aria-live="polite">${v?esc(amountEcho(String(v/100))):''}</small></div><div class="field"><label for="f-monthly">Monthly total for each Manager (₹, optional)</label><input class="form-input" id="f-monthly" name="monthly" type="text" inputmode="decimal" autocomplete="off" value="${m?esc(String(m/100)):''}" placeholder="e.g. 50,000"><small class="muted amount-echo" data-amount-for="monthly" aria-live="polite">${m?esc(amountEcho(String(m/100))):''}</small></div><div class="g-actions"><button class="btn btn-primary" type="submit">Save limits</button></div></form></section>`;}
function moneyAmountField(id, label, value='') {
 const hint=`${id}-amount-echo`;
 return `<div class="field"><label for="${esc(id)}-amount">${esc(label)}</label>
  <input class="form-input" id="${esc(id)}-amount" name="amount" inputmode="decimal" value="${esc(value)}"
   aria-describedby="${esc(hint)}" placeholder="e.g. 1,250.50" required>
  <small id="${esc(hint)}" class="muted amount-echo" data-amount-for="amount" aria-live="polite">${esc(amountEcho(value))}</small></div>`;
}
function rupeesToPaise(raw){raw=String(raw||'').trim();if(!raw||raw==='0')return 0;const echo=amountEcho(raw);if(!echo||echo.startsWith('Check'))return null;return Math.round(Number(raw.replace(/^(?:₹|rs\.?|inr)\s*/i,'').replace(/,/g,''))*100);}
document.addEventListener('submit',async e=>{if(e.target.id!=='approvalLimitForm')return;e.preventDefault();const f=new FormData(e.target);const paise=rupeesToPaise(f.get('limit')),monthly=rupeesToPaise(f.get('monthly'));
 if(paise===null||monthly===null){notify('Enter an amount such as 5,000',true);return;}
 try{const r=await api('/api/approval-limits',{method:'PUT',body:JSON.stringify({manager_per_transaction_paise:paise,monthly_per_manager_paise:monthly})});state.approvalLimit=r.manager_per_transaction_paise;state.approvalMonthly=r.monthly_per_manager_paise;notify(paise?'Manager approval limits saved.':'Manager approval limits switched off.');render();}catch(err){notify(err.message,true);}});
function personLimitsPanel(){const rows=(state.personLimits||[]);
 const body=rows.length?rows.map(p=>{const per=p.per_transaction_paise,mon=p.monthly_paise;return `<form class="person-limit-form panel-body" data-user="${Number(p.user_id)}"><div><strong>${esc(p.display_name||p.username)}</strong> <span class="muted">${p.inherits_role?'follows the limit above':'has their own limits'}</span></div>
  <div class="field"><label for="pl-per-${Number(p.user_id)}">Per entry (₹)</label><input class="form-input" id="pl-per-${Number(p.user_id)}" name="per" type="text" inputmode="decimal" autocomplete="off" value="${per?esc(String(per/100)):''}" placeholder="0 = cannot approve money"><small class="muted amount-echo" data-amount-for="per" aria-live="polite">${per?esc(amountEcho(String(per/100))):''}</small></div>
  <div class="field"><label for="pl-mon-${Number(p.user_id)}">Monthly total (₹)</label><input class="form-input" id="pl-mon-${Number(p.user_id)}" name="monthly" type="text" inputmode="decimal" autocomplete="off" value="${mon?esc(String(mon/100)):''}" placeholder="empty = no monthly total"><small class="muted amount-echo" data-amount-for="monthly" aria-live="polite">${mon?esc(amountEcho(String(mon/100))):''}</small></div>
  <div class="g-actions"><button class="btn btn-primary btn-sm" type="submit">Save for ${esc(p.display_name||p.username)}</button>${p.inherits_role?'':`<button class="btn btn-secondary btn-sm" type="button" data-person-clear="${Number(p.user_id)}">Use the role limit</button>`}</div></form>`}).join(''):'<div class="panel-body"><p class="muted">There are no active Managers yet.</p></div>';
 return `<section class="panel section-gap" id="personLimitsPanel"><div class="panel-head"><div><div class="panel-title">Limits for each Manager</div><div class="panel-sub">Give one Manager their own limits. A Manager without their own follows the limit above. Per entry 0 means they cannot approve money; a monthly total left empty means no monthly total.</div></div></div>${body}</section>`;}
async function loadPersonLimits(){state.personLimits=await api('/api/approval-limits/people');}
document.addEventListener('submit',async e=>{const form=e.target.closest&&e.target.closest('.person-limit-form');if(!form)return;e.preventDefault();const f=new FormData(form);const per=rupeesToPaise(f.get('per')),mon=rupeesToPaise(f.get('monthly'));
 if(per===null||mon===null){notify('Enter an amount such as 5,000',true);return;}
 try{await api('/api/approval-limits/people/'+Number(form.dataset.user),{method:'PUT',body:JSON.stringify({per_transaction_paise:per,monthly_paise:mon})});await loadPersonLimits();notify('Limits saved for this Manager.');render();}catch(err){notify(err.message,true);}});
document.addEventListener('click',async e=>{const b=e.target.closest&&e.target.closest('[data-person-clear]');if(!b)return;try{await api('/api/approval-limits/people/'+Number(b.dataset.personClear),{method:'DELETE'});await loadPersonLimits();notify('This Manager now follows the role limit.');render();}catch(err){notify(err.message,true);}});
onAfterRender(()=>{if(state.view==='team'&&isAdmin()&&!$('approvalLimitPanel')){if(state.approvalLimit===undefined||state.personLimits===undefined){Promise.all([api('/api/approval-limits'),api('/api/approval-limits/people')]).then(([r,people])=>{state.approvalLimit=r.manager_per_transaction_paise;state.approvalMonthly=r.monthly_per_manager_paise;state.personLimits=people;render();}).catch(()=>{});return;}$('mainContent').insertAdjacentHTML('beforeend',approvalLimitPanel()+personLimitsPanel());}});
function approvalRightsPanel(){const r=state.myRights;if(!r)return '';const list=r.can_approve_everything?'<p>As the owner you can approve everything.</p>':(r.can_approve.length?`<p>${r.can_approve.map(esc).join(' · ')}</p>`:'<p class="muted">Nothing yet, apart from the money limit below.</p>');
 return `<section class="panel section-gap" id="approvalRightsPanel"><div class="panel-head"><div class="panel-title">What you can approve</div></div><div class="panel-body">${list}${r.money_limit_rupees?`<p>Costs and payments up to <strong>${inr(r.money_limit_rupees)}</strong> each, entered by someone else.</p>`:''}${r.monthly_total_rupees?`<p>Up to <strong>${inr(r.monthly_total_rupees)}</strong> in total each month; <strong>${inr(r.approved_this_month_rupees||0)}</strong> used so far.</p>`:''}<p class="muted">${esc(r.own_entry_rule)}</p></div></section>`;}
onAfterRender(()=>{if(state.view==='approvals'&&state.user&&!$('approvalRightsPanel')){if(state.myRights===undefined){state.myRights=null;api('/api/my-approval-rights').then(r=>{state.myRights=r;render();}).catch(()=>{});return;}$('mainContent').insertAdjacentHTML('beforeend',approvalRightsPanel());}});
document.addEventListener('input',e=>{const form=e.target&&e.target.closest&&e.target.closest('#entryForm');const d=$('entryDialog');if(!form||!d||d.dataset.type!=='site'||!state.user)return;saveSiteDraft(window.localStorage,state.user.username,Object.fromEntries(new FormData(form).entries()));});
document.addEventListener('change',async e=>{
 const picker=e.target.closest&&e.target.closest('[data-doc-category]');
 if(picker){const id=Number(picker.dataset.docCategory);const doc=state.docs.find(d=>d.id===id);const value=picker.value||null;
  if(!doc||(doc.category||null)===value)return;
  picker.disabled=true;
  try{const r=await api('/api/tickets/proposals',{method:'POST',body:JSON.stringify({kind:'document_categorize',data:{document_id:id,category:value},evidence:'File category chosen on the Documents screen'})});
   notify(`File category change #${r.ticket_id} sent for approval.`);}
  catch(err){notify(err.message,true);}
  finally{picker.value=doc.category||'';picker.disabled=false;}   // the list shows the saved category until the ticket is approved
  return;}
 if(e.target.name==='client_id'&&e.target.closest('#entryForm')&&$('entryDialog').dataset.type==='project')syncNewProjectClient($('entryForm'));
 if(e.target.name==='project_id'&&e.target.closest('#entryForm')&&$('entryDialog').dataset.type==='siteexpense')loadSiteExpenseOptions();
 if(e.target.name==='vendor_id'&&e.target.closest('#entryForm')&&$('entryDialog').dataset.type==='siteexpense')syncSiteVendorChoice($('entryForm'));
 const form=e.target.closest('#entryForm');
 if(!form||$('entryDialog').dataset.type!=='siteexpense')return;
 if(e.target.id==='se-photo'){
  form.elements.receipt_intake_id.value='';
  if(e.target.files.length)form.elements.receipt_id.value='';
  showSitePhotoState(form);
  rememberEntryDraft(e);
 }
 if(e.target.name==='receipt_id'&&e.target.value){
  form.elements.receipt_intake_id.value='';
  $('se-photo').value='';
  showSitePhotoState(form);
  rememberEntryDraft(e);
 }
});
document.addEventListener('click',e=>{
 if(e.target.id!=='se-remove-photo')return;
 const form=e.target.closest('#entryForm');
 form.elements.receipt_intake_id.value='';
 $('se-photo').value='';
 showSitePhotoState(form);
 rememberEntryDraft(e);
});
document.addEventListener('click',e=>{if(e.target.closest&&e.target.closest('[data-action="retry-refresh"]'))refresh();});
onAfterRender(()=>{if(state.user&&!$('refreshBanner')&&(state.refreshFailed||[]).length&&!document.body.classList.contains('chat-mode')){$('mainContent').insertAdjacentHTML('afterbegin',refreshBanner());}});

document.addEventListener('submit', async event => {
 const form = event.target;
 if (form.id !== 'budgetBooksForm') return;
 event.preventDefault();
 const button = form.querySelector('button[type="submit"]');
 const session = state.session;
 button.disabled = true;
 try {
   const data = await api('/api/finance-ledger/project-costs/'+Number(form.elements.project.value));
   if (state.view === 'budget' && state.session === session && form.isConnected) {
     state.budgetLedger = {session,data};
     render();
     document.getElementById('budgetBooksProject')?.focus();
   }
 } catch (error) { notify(error.message,true); }
 finally { button.disabled = false; }
});
