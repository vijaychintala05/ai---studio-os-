'use strict';
const state={user:null,approvals:{costs:[],payments:[]},agents:{agents:[],hooks:[],write_events:0,chat_messages:0,context_summaries:0},users:[],view:'overview', tickets:[], ticketDetail:null, newTypes:[], newTypeDetail:null, newTypeDashboard:null, newTypeWorkflowResult:null, projects:[],summary:null,budgets:[],tasks:[],costs:[],activity:[],settings:null,docs:[],site:[],suggestions:[],messages:[],sessionId:sessionStorage.getItem('studioos-chat-id')||''};
const $=id=>document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function text(s){return esc(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');}
function inr(n){return '₹'+Number(n||0).toLocaleString('en-IN',{minimumFractionDigits:0,maximumFractionDigits:2});}
function time(s){if(!s)return '';let d=new Date(s);return Number.isNaN(d.getTime())?s:d.toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'});}
function csrf(){return decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('studioos_csrf='))?.split('=')[1]||'');}
function hasFinance(){return ['admin','manager','accounts'].includes(state.user?.role);}
function isApprover(){return ['admin','manager'].includes(state.user?.role);}
function isAdmin(){return state.user?.role==='admin';}
async function api(path,opts={}){
 const method=(opts.method||'GET').toUpperCase();
 const headers={'Content-Type':'application/json',...(opts.headers||{})};
 if(!['GET','HEAD'].includes(method))headers['X-CSRF-Token']=csrf();
 const r=await fetch(path,{credentials:'same-origin',...opts,headers});
 const data=await r.json().catch(()=>({}));
 if(r.status===401&&state.user){showLogin();throw new Error('Session ended. Please sign in again.');}
 if(!r.ok){const err=new Error(typeof data.detail==='string'?data.detail:`Request failed (${r.status})`);err.status=r.status;err.data=data;throw err;}
 return data;
}
async function refresh(){if(!state.user)return;const keys=state.mustSetup2fa?['auth/2fa']:['auth/2fa','projects','summary','tasks','settings','documents','site-reports',`tickets?limit=100&offset=${state.ticketPageOffset || 0}`,'new-types/inbox',...(hasFinance()?['budgets','costs','activity']:[]),...(isApprover()?['approvals','schema-suggestions','agents']:[]),...(isAdmin()?['users','system/data-safety']:[])];const results=await Promise.allSettled(keys.map(k=>api('/api/'+k)));results.forEach((r,i)=>{if(r.status==='fulfilled')state[{'documents':'docs','site-reports':'site','schema-suggestions':'suggestions','new-types/inbox':'newTypes','auth/2fa':'twoFactor','system/data-safety':'safety'}[keys[i].split('?')[0]]||keys[i].split('?')[0]]=r.value;else console.warn('Load failed',keys[i],r.reason);});render();}
function notify(message,error=false){const node=document.createElement('div');node.className='toast'+(error?' error':'');node.textContent=message;$('toasts').appendChild(node);setTimeout(()=>node.remove(),4200);}
function head(title,subtitle,buttonLabel='',action=''){if(action==='project'&&!['admin','manager'].includes(state.user?.role))buttonLabel='';if(action==='cost'&&!hasFinance())buttonLabel='';if(action==='site'&&!['admin','manager','site_engineer'].includes(state.user?.role))buttonLabel='';if(action==='task'&&!['admin','manager','architect'].includes(state.user?.role))buttonLabel='';if(action==='index-nas'&&!isApprover())buttonLabel='';return `<div class="headline"><div><div class="eyebrow">STUDIOOS / ${esc(state.view.toUpperCase())}</div><h1>${esc(title)}</h1><div class="subhead">${esc(subtitle)}</div></div>${buttonLabel?`<button class="btn btn-primary" data-action="${esc(action)}">+ &nbsp;${esc(buttonLabel)}</button>`:''}</div>`;}
function pill(label,variant=''){return `<span class="tag ${variant}">${esc(label)}</span>`;}
function empty(icon,title,caption){return `<div class="empty"><div class="empty-big">${icon}</div><strong>${esc(title)}</strong><br>${esc(caption)}</div>`;}
function financial(){const s=state.summary||{costs:{actual:0,commitments:0,known_costs:0},total_budget:0};return `<div class="financial-strip"><div class="financial-tile"><div class="label">Approved project budgets</div><div class="num">${inr(s.total_budget)}</div><small>Portfolio sum</small></div><div class="financial-tile"><div class="label">Incurred costs</div><div class="num">${inr(s.costs.actual)}</div><small>Expenses only</small></div><div class="financial-tile"><div class="label">Purchase commitments</div><div class="num">${inr(s.costs.commitments)}</div><small>Orders not in expenses</small></div><div class="financial-tile"><div class="label">Known costs</div><div class="num">${inr(s.costs.known_costs)}</div><small>Expenses + commitments</small></div></div>`;}
function projectRows(limit=0){const list=limit?state.budgets.slice(0,limit):state.budgets;return list.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Project</th><th>Stage</th><th>Budget</th><th>Known costs</th><th>Headroom</th></tr></thead><tbody>${list.map(p=>`<tr><td><strong>${esc(p.name)}</strong><div class="muted">${esc(p.client||'No client')}</div></td><td>${pill(p.stage,'gray')}</td><td>${inr(p.budget)}</td><td>${inr(p.known_costs)}</td><td>${pill(inr(p.remaining),p.remaining<0?'critical':'good')}</td></tr>`).join('')}</tbody></table></div>`:empty('▤','No projects yet','Create a project to get started.');}
function activityList(limit=7){const list=state.activity.slice(0,limit);return list.length?list.map(a=>`<div class="activity-row"><div class="activity-symbol">${a.entity_type==='cost'?'₹':a.entity_type==='task'?'☑':a.entity_type==='project'?'▤':'◷'}</div><div><div class="activity-text">${esc(a.description)}</div><div class="activity-time">${time(a.created_at)} · ${esc(a.actor)}</div></div></div>`).join(''):empty('◷','No activity','Saved actions will be recorded here.');}
function safetyBanner(){const s=state.safety;if(!isAdmin()||!s||s.overall!=='fail')return '';const bad=s.checks.filter(c=>c.level==='fail').map(c=>esc(c.title)).join(' · ');return `<div class="notice fail"><span><strong>Data safety needs attention:</strong> ${bad}</span><button class="btn btn-secondary btn-sm" data-view="safety">Open Data safety</button></div>`;}
function overview(){const s=state.summary||{projects:0,open_tasks:0,budget_alerts:0,total_budget:0,costs:{actual:0,commitments:0,known_costs:0}};return safetyBanner()+head('Good to see you, '+(state.user?.display_name||state.user?.username||'team')+'.','Your architecture and construction firm, in one place.','New project','project')+`<div class="stats"><div class="stat"><div class="stat-top"><span>Active projects</span><span class="stat-icon">▤</span></div><div class="stat-value">${s.projects}</div><div class="stat-foot">Project portfolios</div></div><div class="stat"><div class="stat-top"><span>Open tasks</span><span class="stat-icon">☑</span></div><div class="stat-value">${s.open_tasks}</div><div class="stat-foot">Across all projects</div></div><div class="stat"><div class="stat-top"><span>Incurred costs</span><span class="stat-icon">₹</span></div><div class="stat-value stat-value-sm">${hasFinance()?inr(s.costs.actual):'—'}</div><div class="stat-foot">${s.costs.basis==='posted_books'?'From approved books':'Approved entries'}</div></div><div class="stat stat-warn"><div class="stat-top"><span>Budget alerts</span><span class="stat-icon">!</span></div><div class="stat-value">${hasFinance()?s.budget_alerts:'—'}</div><div class="stat-foot">Known costs over budget</div></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Project portfolio</div><div class="panel-sub">Budgets and known financial exposure</div></div><button class="link-btn" data-view="projects">View projects →</button></div>${hasFinance()?projectRows(5):'<div class="panel-body">Project financial details are limited to authorized roles.</div>'}</section><section class="panel"><div class="panel-head"><div><div class="panel-title">Recent activity</div><div class="panel-sub">Every confirmed change is logged</div></div><button class="link-btn" data-view="activity">View all →</button></div><div class="panel-body">${activityList(6)}</div></section></div><div class="section-gap"><div class="budget-banner"><div><h2>Manage your firm by simply describing the work.</h2><p>AI creates review tickets; only authorized approval can save proposed changes.</p></div><button class="btn btn-primary" data-view="assistant">Open AI assistant ✦</button></div></div>`;}
function projects(){return head('Projects','One source of truth for your design and construction jobs.','New project','project')+ (state.budgets.length?`<div class="list-cards">${state.budgets.map(p=>`<div class="project-card"><div class="project-top"><div class="project-initial">${esc(p.name.slice(0,1).toUpperCase())}</div><div><div class="project-name">${esc(p.name)}</div><div class="muted">${esc(p.client||'No client specified')}</div></div></div><div class="project-line"></div><div class="project-metrics"><div><div class="metric-label">Approved budget</div><div class="metric-val">${inr(p.budget)}</div></div><div><div class="metric-label">Known costs</div><div class="metric-val">${inr(p.known_costs)}</div></div></div><div class="row-between mt-17"><span class="muted">${esc(p.stage)}</span>${peopleButton(p)}${pill(p.remaining<0?'Over budget':'Within known budget',p.remaining<0?'critical':'good')}</div></div>`).join('')}</div>`:(state.projects.length?`<div class="list-cards">${state.projects.map(p=>`<div class="project-card"><div class="project-name">${esc(p.name)}</div><p class="muted">${esc(p.client||'')} · ${esc(p.stage)}</p>${peopleButton(p)}</div>`).join('')}</div>`:empty('▤','No projects yet','Create your first project to begin.')));}
function tasks(){return head('Team tasks','What needs to happen, who owns it, and what is complete.','New task','task')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Task register</div><div class="panel-sub">Changes appear after review and approval.</div></div></div>${state.tasks.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Task</th><th>Project</th><th>Assigned to</th><th>Status</th><th>Action</th></tr></thead><tbody>${state.tasks.map(t=>`<tr><td><strong>${esc(t.title)}</strong></td><td>${esc(t.project)}</td><td>${esc(t.assignee||'Unassigned')}</td><td>${pill(t.status,t.status==='done'?'good':'warn')}</td><td>${t.status==='open'?`<button class="btn btn-secondary btn-sm" data-action="complete" data-id="${t.id}">Mark complete</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('☑','No tasks yet','Create tasks manually or by talking to AI.')}</section>`;}
function budgets(){return head('Budgets & Costs','Structured financial records with approval-aware AI entry.','New expense / PO','cost')+`<div class="budget-banner"><div><h2>Financial control</h2><p>Expenses are incurred costs. Purchase orders are separate commitments. Payments do not increase project cost twice.</p></div><div class="text-right"><div class="banner-num">${inr((state.summary||{}).total_budget)}</div><div class="banner-label">APPROVED PROJECT BUDGETS</div></div></div>${financial()}<section class="panel"><div class="panel-head"><div><div class="panel-title">Project financial position</div><div class="panel-sub">Remaining = approved budget − incurred costs − purchase commitments. Not a final completion forecast.</div></div></div>${projectRows()}</section><section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Cost register</div><div class="panel-sub">Pending entries require manager approval before affecting budget totals.</div></div><button class="btn btn-secondary btn-sm" data-action="payment">+ Record payment</button></div>${state.costs.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>ID / Description</th><th>Project</th><th>Type</th><th>Status</th><th>Vendor</th><th>Amount</th><th>Paid</th><th>Action</th></tr></thead><tbody>${state.costs.map(c=>`<tr><td><strong>#${c.id} · ${esc(c.title)}</strong></td><td>${esc(c.project)}</td><td>${pill(c.kind,c.kind==='commitment'?'warn':'good')}</td><td><span class="status-pill ${esc(c.status)}">${esc(c.status)}</span></td><td>${esc(c.vendor||'—')}</td><td>${inr(c.amount)}</td><td>${inr(c.paid)}</td><td>${c.kind==='commitment'&&c.status==='approved'?`<button class="btn btn-secondary btn-sm" data-action="recognize" data-id="${c.id}">Mark invoiced</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('₹','No cost entries','Use New expense / PO or the AI assistant.')}</section>`;}
function site(){return head('Site Reports','Store site observations and daily progress against projects.','New site report','site')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Site update timeline</div><div class="panel-sub">A simple first version; photos and checklists come later.</div></div></div><div class="panel-body">${state.site.length?state.site.map(s=>`<div class="activity-row"><div class="activity-symbol">▧</div><div><div class="activity-text"><strong>${esc(s.project)}</strong> — ${esc(s.note)}</div><div class="activity-time">${time(s.created_at)}</div></div></div>`).join(''):empty('▧','No site reports','Site engineers can start reporting project activities here.')}</div></section>`;}
function documents(){return head('NAS Documents','Read-only indexing of filenames, types and file paths stored on your NAS.','Scan NAS folder','index-nas')+`<div class="panel"><div class="panel-head"><div><div class="panel-title">Document index</div><div class="panel-sub">The application does not open, change or upload the original files.</div></div>${pill(state.settings?.nas_configured?'NAS path configured':'No NAS mount',state.settings?.nas_configured?'good':'warn')}</div>${state.docs.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Document</th><th>Type</th><th>Relative NAS path</th><th>Size</th></tr></thead><tbody>${state.docs.map(d=>`<tr><td><strong>${esc(d.name)}</strong></td><td>${pill(d.doc_type||'file','gray')}</td><td><span class="code">${esc(d.relative_path)}</span></td><td>${(d.size_bytes/1024).toFixed(0)} KB</td></tr>`).join('')}</tbody></table></div>`:empty('▥','No documents indexed','Configure STUDIOOS_NAS_ROOT and run Scan NAS folder.')}</div><div class="info-card section-gap"><div class="tip-icon">ⓘ</div><h3>How NAS indexing works</h3><p>Mount your firm's projects folder read-only in Docker. The scanner stores names, relative paths, types, and sizes. Native DWG, SKP and Revit files are not interpreted by this prototype.</p></div>`;}
function activity(){return head('Activity Log','An audit trail of confirmed changes across StudioOS.')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">All recorded changes</div><div class="panel-sub">A production release should add named employee identities and tamper-evident logging.</div></div></div><div class="panel-body">${activityList(80)}</div></section>`;}
function settings(){const s=state.settings||{provider:'demo',providers:[]};const names={demo:'Offline Demo Parser',openai:'OpenAI',claude:'Anthropic Claude',gemini:'Google Gemini'};const descriptions={demo:'No API key needed. Recognizes limited sample phrases.',openai:'Uses OPENAI_API_KEY configured on the server.',claude:'Uses ANTHROPIC_API_KEY configured on the server.',gemini:'Uses GEMINI_API_KEY configured on the server.'};return head('AI Provider Settings','The business database stays unchanged when you switch AI providers.')+`<div class="mb-18"><a class="btn btn-secondary" href="/api/export" download="studioos-export.json">↓ Export business records (JSON)</a></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Select your intelligence engine</div><div class="panel-sub">Keys stay on the server and are never sent to the browser.</div></div></div><div class="panel-body">${s.providers.map(p=>`<div class="provider-row"><div><div class="provider-title"><span class="status-dot ${p.configured?'on':''}"></span>${names[p.id]}</div><div class="provider-desc">${descriptions[p.id]}</div></div>${p.id===s.provider?pill('Active','good'):`<button class="btn btn-secondary btn-sm" data-action="switch-provider" data-provider="${p.id}" ${p.configured?'':'disabled title="API key not configured"'}>Select</button>`}</div>`).join('')}<p class="muted">To enable another provider, set its environment variable and restart the application. Provider switching requires no data migration.</p></div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">Architecture principles</div><div class="panel-sub">Designed to minimize vendor lock-in</div></div></div><div class="panel-body"><div class="info-card"><h3>Permanent</h3><p>PostgreSQL (or SQLite during local development), projects, costs, tasks, staff inputs and audit history.</p></div><div class="info-card"><h3>Replaceable</h3><p>OpenAI, Claude and Gemini adapters; prompts and model settings; document intelligence.</p></div><div class="info-card"><h3>Not yet production ready</h3><p>Stage 1 has login and role-based access. It still requires production security review, reliable backups and full construction accounting before rollout.</p></div></div></section></div>`;}
function assistant(){return head('AI Project Assistant','Describe work naturally. AI drafts ticket items; no AI proposal can directly save business records.')+`<div class="mb-14"><button class="btn btn-secondary" data-action="new-conversation">+ Start new conversation</button> <button class="btn btn-secondary" data-view="newtypes">Open New Data Inbox</button></div><div class="chat-shell"><section class="panel chat-panel"><div class="panel-head panel-head-rule"><div><div class="panel-title">StudioOS AI</div><div class="panel-sub">${state.settings?.provider==='demo'?'Demo interpreter — limited offline language support':`Provider: ${esc(state.settings?.provider||'loading')}`}</div></div><div class="chat-messages" id="chatMessages">${state.messages.length?state.messages.map(chatBubble).join(''):`<div class="chat-welcome"><div class="welcome-icon">✦</div><h3>Your firm's command centre.</h3><p>Create tasks, log purchases, ask about budgets and see exactly what was saved — all through conversation.</p><div class="chips"><button class="chip" data-prompt="Show all projects">Show all projects</button><button class="chip" data-prompt="What happened today?">What happened today?</button><button class="chip" data-prompt="Create project Villa A with budget ₹20 lakh">Create a sample project</button><button class="chip" data-prompt="Show the budget summary">Budget summary</button></div></div>`}</div><div class="chat-bottom"><form class="chat-form" id="chatForm"><textarea class="chat-input" id="chatInput" rows="1" placeholder="Ask anything about your projects, budgets or team..." required></textarea><button class="send-btn" type="submit" id="chatSend" aria-label="Send message">↑</button></form><label class="file-hint" for="chatFiles">Attach files/photos to quarantine unchanged (Stage A only)</label><input class="newtype-file-input" type="file" id="chatFiles" multiple accept="image/*,.pdf,.txt,.csv" /><div class="chat-hint">AI-created business changes are saved only after a ticket reviewer approves them. Manual forms still use their existing paths.</div></div></section><aside><div class="info-card"><div class="tip-icon">✦</div><h3>Try these examples</h3><ul><li>“Create project Villa A with budget ₹20 lakh”</li><li>“Create task: Review drawings for Villa A”</li><li>“Purchased 25 bags of cement for Villa A”</li><li>“What is the budget for Villa A?”</li><li>“Show pending tasks”</li></ul></div><div class="info-card"><div class="tip-icon">◈</div><h3>Data protection by design</h3><p>AI creates tickets. Only authorized item approval and a ticket commit can update business records. Payments do not duplicate costs.</p></div></aside></div>`;}
function evidenceGrid(i){
 const data=i.after||{}, source=i.field_evidence||{};
 const keys=[...new Set([...Object.keys(data),...Object.keys(source)])].filter(k=>k!=='idempotency_key'&&k!=='request_key');   // internal request keys are not for people
 return `<div class="preview-fields">${keys.map(k=>{
  const value=data[k], e=source[k]||{marker: value==null||value===''?'missing':'guessed'};
  const status=e.marker||'guessed', sourceText=e.source_words?`<small>Source: “${esc(e.source_words)}”</small>`:'<small>No exact source phrase located</small>';
  const v=value===null||value===undefined||value===''?'— missing —':(k.endsWith('_paise')&&Number.isInteger(value))?inr(value/100):typeof value==='object'?JSON.stringify(value):String(value);
  return `<div class="preview-field"><div class="field-key">${esc(k)} <span class="source-chip ${esc(status)}">${esc(status)}</span></div><div class="field-value">${esc(v)}</div>${sourceText}<button class="field-edit" data-action="edit-ticket-field" data-id="${Number(i.id)}" data-field="${esc(k)}">Edit field</button></div>`;
 }).join('')}</div>`;
}
function previewCard(preview){if(!preview?.items?.length)return '';
 return `<section class="ticket-preview" aria-label="Uncommitted ticket preview"><div class="preview-title">Ticket #${Number(preview.id)} · Review before saving <span class="tag warn">DRAFT</span></div>
 ${preview.items.map(i=>`<div class="preview-item"><strong>${esc(i.item_type.replaceAll('_',' '))}</strong> · ${esc(i.status)}${evidenceGrid(i)}
 ${(i.flags||[]).map(f=>`<div class="preview-flag">⚑ ${esc(f)}</div>`).join('')}</div>`).join('')}
 <button class="btn btn-primary preview-open" data-action="open-ticket" data-id="${Number(preview.id)}">Open full review</button></section>`;}
function chatBubble(m){
 const link=m.ticket_id?`<div class="chat-actions"><button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(m.ticket_id)}">Review ticket #${Number(m.ticket_id)}</button></div>`:'';
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
  else if(f.control==='json-editor')field='<textarea disabled rows="2" placeholder="Flexible JSON"></textarea>';
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
 return `<section class="newtype-card" aria-label="Stage A new-data preview">
 <div class="newtype-card-head"><strong>Holding inbox #${Number(h.id)} · ${esc(h.state)}</strong>${pill(fit.decision||'parked','warn')}</div>
 <p class="newtype-source"><strong>Your original words:</strong> ${esc(h.raw_payload?.text||'')}</p>
 <p class="muted">Checked ${Number(fit.inspected_tables||0)} tables and ${Number(fit.inspected_fields||0)} fields. No dynamic table has been created.</p>
 ${(fit.near_fits||[]).length?`<p><strong>Possible existing fits:</strong> ${fit.near_fits.map(x=>esc(x.table)).join(', ')}</p>`:''}
 ${design.table_name?`<h4>Minimal proposal: ${esc(design.table_name)}</h4><p>${esc(design.description||'')}</p>
 <p class="muted">Physical SQL constraints are proposed, not installed in Stage A.</p>
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
 return `<section class="panel section-gap" id="newTypeReview"><div class="panel-head"><div><div class="panel-title">Holding item #${Number(h.id)} · ${esc(h.state)}</div><div class="panel-sub">The raw source cannot be changed. Approval records a design only.</div></div><button class="btn btn-secondary" data-action="close-new-type">Close</button></div>
 <div class="panel-body">${newTypeCard(h)}
 ${h.state==='proposed'?`<div class="req-try"><h3>Preview a hypothetical record — no save</h3><p class="muted">Try example field values as JSON. Missing and unknown fields are highlighted above; no business record is created.</p>
 <form id="previewRequirementForm" data-id="${Number(h.id)}"><textarea name="record" rows="4" spellcheck="false" placeholder='{ "project_id": 1, "area": "Kitchen", "description": "Cracked tile" }'></textarea>
 <label>Check required fields at <select name="phase"><option value="draft">Draft</option><option value="approve" selected>Approval</option><option value="close">Closure</option></select></label>
 <button type="submit" class="btn btn-secondary">Check field requirements</button></form></div>`:''}
 ${design.capability_blueprint?`<div class="capability-operations"><button class="btn btn-secondary" data-action="diagnose-new-type" data-id="${Number(h.id)}">Analyze problem with selected AI</button>${h.state==='approved_design_only'?`<button class="btn btn-secondary" data-action="dashboard-new-type" data-id="${Number(h.id)}">Load live dashboards</button>`:''}</div>${evolutionDiagnosisUI(fit)}${state.newTypeDashboard?.id===h.id?evolutionDashboardsUI(state.newTypeDashboard):''}${h.state==='approved_design_only'?`<form class="capability-check-form" id="capabilityCheckWorkflow" data-id="${Number(h.id)}"><h3>Evaluate lifecycle policy (read-only)</h3><label>Existing record ID <input name="record_id" inputmode="numeric" type="number" min="1" required></label><label>Requested stage <select name="destination"><option value="active">Draft → Active</option><option value="closed">Active → Closed</option></select></label><button type="submit" class="btn btn-secondary">Check eligibility</button><p class="muted">No status change or ticket is created.</p></form>${state.newTypeWorkflowResult?.id===h.id?`<div class="capability-advice-item"><strong>${state.newTypeWorkflowResult.allowed?'Eligible for review':'Not eligible'}</strong><p>Missing: ${(state.newTypeWorkflowResult.missing||[]).map(esc).join(', ')||'None'}. No record changed.</p></div>`:''}`:''}`:''}
 <details class="newtype-advanced"><summary>Advanced: full structure and evidence (JSON)</summary><pre class="newtype-json">${esc(JSON.stringify({fit,design},null,2))}</pre></details>
 ${h.state==='proposed'?`<h3>Answer only what is missing</h3><form id="newTypeAnswers" data-id="${Number(h.id)}" class="newtype-questions">${(h.questions||[]).map(q=>`<label>${esc(q.text)}<textarea rows="2" name="${esc(q.id)}" placeholder="Leave blank if unknown">${esc(h.answers?.[q.id]||'')}</textarea></label>`).join('')}<button type="submit" class="btn btn-primary">Update proposed design</button></form>
 <div class="approval-buttons">${isAdmin()?`<button class="btn btn-primary" data-action="approve-new-type" data-id="${Number(h.id)}">Approve structure (design only)</button>`:''}<button class="btn btn-secondary" data-action="edit-new-type" data-id="${Number(h.id)}">Edit proposal JSON</button><button class="btn btn-secondary" data-action="keep-new-type" data-id="${Number(h.id)}">Keep in inbox only</button><button class="btn btn-danger" data-action="reject-new-type" data-id="${Number(h.id)}">Reject proposal</button></div>`:''}
 </div></section>`;
}
function newTypesView(){let rows=state.newTypes||[];return head('New Data Inbox','Unmatched information is parked here; Admin alone can approve schema designs.')+
 `<section class="panel"><div class="panel-head"><div><div class="panel-title">Holding inbox</div><div class="panel-sub">Raw words and attachments are retained. No migration runs in Stage A.</div></div></div>
 ${rows.length?rows.map(h=>`<div class="approval-card ticket-list-row"><div><strong>Holding #${Number(h.id)}</strong> ${pill(h.state,h.state==='approved_design_only'?'good':'warn')}<p>${esc((h.raw_payload?.text||'').slice(0,150))}</p><small>${esc(h.match_review?.decision||'')} · ${(h.attachments||[]).length} attachments</small></div><button class="btn btn-primary" data-action="open-new-type" data-id="${Number(h.id)}">Review</button></div>`).join(''):empty('▧','Inbox is empty','Describe a new type of information in chat to park it here.')}</section>
 ${state.newTypeDetail?newTypeDetail(state.newTypeDetail):''}`;}

function tickets(){let rows=state.tickets||[];return head('Ticket Inbox','Review each proposed change, then commit the approved items atomically.')+`<section class="panel"><div class="panel-head"><div><div class="panel-title">Conversation tickets</div><div class="panel-sub">Admin is the owner. Financial approvals remain separate.</div></div></div>${rows.length?rows.map(t=>`<div class="approval-card ticket-list-row"><div><strong>Ticket #${t.id}</strong> ${pill(t.status,t.status==='committed'?'good':'warn')}<p>${esc(t.summary)}</p><small>${t.items.length} item(s) · ${time(t.created_at)}</small></div><button class="btn btn-primary" data-action="open-ticket" data-id="${t.id}">Review ticket</button></div>`).join(''):empty('◇','No tickets yet','Send a business update in chat to create a review ticket.')}</section><div class="g-actions"><button class="btn btn-secondary" data-action="ticket-page" data-offset="${Math.max(0,(state.ticketPageOffset||0)-100)}" ${(state.ticketPageOffset||0)===0?'disabled':''}>Newer tickets</button><span>Showing ${(state.ticketPageOffset||0)+1}–${(state.ticketPageOffset||0)+rows.length}</span><button class="btn btn-secondary" data-action="ticket-page" data-offset="${(state.ticketPageOffset||0)+100}" ${rows.length<100?'disabled':''}>Older tickets</button></div>${state.ticketDetail?ticketDetail(state.ticketDetail):''}`;}
function bankBatchReview(t){
 if(['committed','reversed'].includes(t.status)||!t.items?.length||t.items.some(i=>i.item_type!=='finance_reconcile_bank'||!['pending','approved'].includes(i.status))||!hasFinance())return '';
 if(Number(t.submitter_id)===Number(state.user?.id)&&!isAdmin())return '<p class="muted">Another approver must review and save these bank matches.</p>';
 return `<section class="panel section-gap"><div class="panel-body"><h3>Review bank matches</h3><p>Check every proposed match below against the statement. Each match keeps its own approval record. Saving rechecks the evidence and exact bank amount; a failure rolls back the whole ticket.</p><label><input type="checkbox" id="bankBatchChecked"> I checked every proposed match against the statement.</label><button class="btn btn-primary" data-action="approve-bank-batch" data-id="${Number(t.id)}">Approve and save bank matches</button></div></section>`;
}
function ticketDetail(t){return `<section class="panel section-gap ticket-review" id="ticketReview"><div class="panel-head"><div><div class="panel-title">Ticket #${t.id} — ${esc(t.status)}</div><div class="panel-sub">${esc(t.summary)}</div></div><button class="btn btn-secondary" data-action="close-ticket">Close</button></div><div class="panel-body"><h3>Before / after changes and evidence</h3>${bankBatchReview(t)}${t.items.map(i=>`<div class="approval-card"><strong>Item #${i.id}: ${esc(i.item_type.replaceAll('_',' '))}</strong> ${pill(i.status,i.status==='approved'?'good':i.status==='rejected'?'critical':'warn')}${evidenceGrid(i)}<details><summary>Show before → after JSON</summary><div class="ticket-diff"><pre>${esc(JSON.stringify(i.before,null,2)||'null')}</pre><pre>${esc(JSON.stringify(i.after,null,2))}</pre></div></details>${(i.flags||[]).map(f=>`<p class="preview-flag">⚑ ${esc(f)}</p>`).join('')}<div class="approval-buttons">${['committed','reversed'].includes(t.status)?'':`<button class="btn btn-primary" data-action="approve-ticket-item" data-id="${i.id}">Approve item</button><button class="btn btn-secondary" data-action="edit-ticket-item" data-id="${i.id}">Edit full item</button><button class="btn btn-danger" data-action="reject-ticket-item" data-id="${i.id}">Reject item</button>`}</div></div>`).join('')}<h3>Original conversation</h3><div class="ticket-transcript">${(t.conversation||[]).map(m=>`<p><strong>${esc(m.speaker)}:</strong> ${esc(m.text)}</p>`).join('')}</div>${t.status==='committed'?`<button class="btn btn-danger" data-action="reverse-ticket" data-id="${t.id}">Reverse ticket (soft delete)</button>`:t.status==='reversed'?'<p>This ticket is reversed. Audit history is retained.</p>':`<button class="btn btn-primary" data-action="commit-ticket" data-id="${t.id}">Commit all approved items</button>`}<p class="muted">Two separate actions protect against accidental writes: review each item, then commit the entire ticket. A failed commit rolls back every approved item.</p></div></section>`;}
function approvals(){let x=state.approvals||{costs:[],payments:[]};return head('Approval Queue','Review financial submissions before they enter approved records.')+`<div class="approval-grid"><section><div class="panel-head"><div><div class="panel-title">Pending costs and purchase orders</div><div class="panel-sub">Approval affects the budget dashboard</div></div></div>${x.costs.length?x.costs.map(c=>`<div class="approval-card"><strong>#${c.id} · ${esc(c.title)}</strong><p>${esc(c.kind)} · ${inr(c.amount)}</p><div class="approval-buttons"><button class="btn btn-primary btn-sm" data-action="approve-cost" data-id="${c.id}">Approve</button><button class="btn btn-danger btn-sm" data-action="reject-cost" data-id="${c.id}">Reject</button></div></div>`).join(''):empty('✓','All caught up','No costs awaiting approval.')}</section><section><div class="panel-head"><div><div class="panel-title">Pending vendor payments</div><div class="panel-sub">Approve before counting as paid</div></div></div>${x.payments.length?x.payments.map(c=>`<div class="approval-card"><strong>Payment #${c.id}</strong><p>Cost #${c.cost_id} · ${inr(c.amount)}</p><div class="approval-buttons"><button class="btn btn-primary btn-sm" data-action="approve-payment" data-id="${c.id}">Approve</button><button class="btn btn-danger btn-sm" data-action="reject-payment" data-id="${c.id}">Reject</button></div></div>`).join(''):empty('✓','All caught up','No payments awaiting approval.')}</section></div>`;}
function projectNames(ids){const names=Object.fromEntries((state.projects||[]).map(p=>[p.id,p.name]));return (ids||[]).map(id=>names[id]||('#'+id)).join(', ');}
function peopleButton(p){return isAdmin()?`<button class="btn btn-secondary btn-sm" data-action="project-members" data-id="${Number(p.id)}">People</button>`:'';}
function userActions(x){if(x.role==='admin'||x.id===state.user?.id)return '<span class="muted">Owner</span>';
 return `<div class="row-actions"><button class="btn btn-secondary btn-sm" data-action="user-toggle" data-id="${Number(x.id)}" data-active="${x.active?'1':'0'}">${x.active?'Deactivate':'Reactivate'}</button>`+
  `<button class="btn btn-secondary btn-sm" data-action="reset-password" data-id="${Number(x.id)}">Reset password</button>`+
  (x.two_factor?`<button class="btn btn-secondary btn-sm" data-action="user-reset-2fa" data-id="${Number(x.id)}">Reset two-factor</button>`:'')+`</div>`;}
function team(){const me=state.user||{};return head('Team & Roles','Create logins, control access and assign people to projects.','Add employee','user')+
 (isAdmin()&&!me.two_factor?`<div class="notice warn">Your Admin account has no two-factor login yet. <button class="btn btn-secondary btn-sm" data-view="account">Set it up</button></div>`:'')+
 `<section class="panel"><div class="panel-head"><div><div class="panel-title">Team accounts</div><div class="panel-sub">Admin, managers and accounts see every project. Everyone else sees only projects you assign (Projects → People).</div></div></div><div class="table-wrap"><table class="data-table team-table"><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Projects</th><th>Two-factor</th><th>Status</th><th>Actions</th></tr></thead><tbody>${state.users.map(x=>`<tr><td data-label="Name"><strong>${esc(x.display_name)}</strong></td><td data-label="Username">${esc(x.username)}</td><td data-label="Role">${pill(x.role.replaceAll('_',' '),'gray')}</td><td data-label="Projects">${x.sees_all_projects?'All projects':esc(projectNames(x.project_ids)||'None assigned')}</td><td data-label="Two-factor">${x.two_factor?pill('On','good'):pill('Off','gray')}</td><td data-label="Status">${x.active?'Active':pill('Deactivated','critical')}</td><td data-label="Actions">${userActions(x)}</td></tr>`).join('')}</tbody></table></div></section>`;}
function accountField(form,label,name,type='password',autocomplete='off',extra=''){return `<div class="field"><label for="${form}-${name}">${label}</label><input class="form-input" id="${form}-${name}" name="${name}" type="${type}" autocomplete="${autocomplete}" required ${extra}></div>`;}
function codeField(form){return accountField(form,'6-digit code from your app (or a recovery code)','code','text','one-time-code','inputmode="numeric" minlength="6" maxlength="40"');}
function twoFactorBody(){const t=state.twoFactor||{},setup=state.twoFactorSetup,codes=state.recoveryCodes;
 if(codes)return `<p><strong>Save these recovery codes now.</strong> Each one works once if you lose your phone. They will not be shown again.</p><ol class="recovery-codes">${codes.map(c=>`<li><code>${esc(c)}</code></li>`).join('')}</ol><button class="btn btn-primary" data-action="dismiss-codes">I have saved these codes</button>`;
 if(setup){const key=(setup.secret||'').match(/.{1,4}/g)?.join(' ')||'';
  return `<ol class="steps"><li>Install an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy or 1Password).</li><li>On your phone, tap <a class="btn btn-secondary btn-sm" href="${esc(setup.otpauth_uri)}">Add to authenticator app</a>, or choose “enter a setup key” in the app and type this key:<div class="secret-key"><code>${esc(key)}</code></div></li><li>Enter the 6-digit code the app shows.</li></ol>
  <form id="twoFactorEnableForm" class="form-grid">${accountField('tfe','6-digit code','code','text','one-time-code','inputmode="numeric" minlength="6" maxlength="6"')}<div class="row-actions"><button class="btn btn-primary" type="submit">Turn on two-factor login</button><button class="btn btn-secondary" type="button" data-action="cancel-2fa-setup">Cancel</button></div></form>`;}
 if(!t.enabled)return `<p class="muted">After you turn this on, signing in needs your password and a 6-digit code from your phone. ${t.required?'<strong>Required for the Admin account.</strong>':'Strongly recommended for the Admin and anyone who approves money.'}</p><form id="twoFactorSetupForm" class="form-grid">${accountField('tfs','Confirm your password','password','password','current-password')}<button class="btn btn-primary" type="submit">Set up two-factor login</button></form>`;
 return `<p>Two-factor login is on. Recovery codes left: <strong>${Number(t.recovery_codes_left||0)}</strong>.</p>
  <details class="account-more"><summary>Moving to a new phone</summary><p class="muted">Set up again: the new phone replaces the old one once you enter its first code.</p><form id="twoFactorSetupForm" class="form-grid">${accountField('tfr','Confirm your password','password','password','current-password')}<button class="btn btn-secondary" type="submit">Set up on a new phone</button></form></details>
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


function agents(){const a=state.agents||{agents:[],hooks:[],write_events:0,chat_messages:0,context_summaries:0};return head('Specialist agents & hooks','Editable Markdown roles. Enforced safety checks remain in the backend.')+`<div class="stats"><div class="stat"><div class="stat-top">Defined specialist agents</div><div class="stat-value">${a.agents?.length||0}</div></div><div class="stat"><div class="stat-top">Enabled lifecycle hooks</div><div class="stat-value">${a.hooks?.filter(h=>h.status==='enabled').length||0}</div></div><div class="stat"><div class="stat-top">Journalled business changes</div><div class="stat-value">${a.write_events||0}</div></div><div class="stat"><div class="stat-top">Retained chat messages</div><div class="stat-value">${a.chat_messages||0}</div></div></div><div class="grid-2"><section class="panel"><div class="panel-head"><div><div class="panel-title">Specialist agents</div><div class="panel-sub">Policy definitions stored as Markdown in /agents</div></div></div><div class="panel-body">${(a.agents||[]).map(x=>`<div class="provider-row"><div><div class="provider-title">${esc(x.name)}</div><div class="provider-desc">${esc(x.definition_file)}</div><div class="provider-desc">${esc(x.permissions)}</div></div>${pill(x.defined?'Defined':'Missing',x.defined?'good':'critical')}</div>`).join('')}</div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">Automatic lifecycle hooks</div><div class="panel-sub">Safe allowlisted handlers; no arbitrary scripts</div></div></div><div class="panel-body">${(a.hooks||[]).map(x=>`<div class="provider-row"><div><div class="provider-title">${esc(x.event.replaceAll('_',' '))}</div><div class="provider-desc">${esc(x.handler)}</div></div>${pill(x.status,'good')}</div>`).join('')}<div class="info-card"><h3>Lossless conversation history</h3><p>Context summaries: ${a.context_summaries||0}. Original messages are always retained and chat write events point to the original instruction.</p></div><div class="info-card"><h3>Schema migration guard</h3><p>Every upgrade involving existing records must create a verified database snapshot before DDL begins. The migration stops if backup fails.</p></div></div></section></div><section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Schema reviewer — try an idea</div><div class="panel-sub">Advisory review only. Never applies migrations.</div></div></div><div class="panel-body"><form id="agentReviewForm" class="chat-form"><textarea id="agentReviewInput" class="chat-input" rows="2" placeholder="e.g. Add vendor GSTIN field and track subcontractor advances" required></textarea><button class="btn btn-primary" type="submit">Review</button></form><div id="agentReviewResult" class="muted mt-12">No proposed change has been reviewed in this session.</div></div></section>`;}

function showLogin(){state.user=null;state.mustSetup2fa=false;state.twoFactorSetup=null;state.recoveryCodes=null;state.sessionId='';sessionStorage.removeItem('studioos-chat-id');$('loginLayer').classList.remove('hidden');}
function updateIdentity(){
 $('sampleBadge').hidden=!state.settings?.sample_data;
 const env=state.settings?.environment||'development';
 $('envLabel').dataset.env=env;document.body.dataset.env=env;$('envText').textContent=({production:'LIVE DATA',test:'TEST COPY · NOT LIVE',development:'DEVELOPMENT'})[env]||'DEVELOPMENT';
 $('safetyBadge').hidden=!(isAdmin()&&state.safety&&state.safety.overall==='fail');
 const fin=hasFinance(),approver=isApprover(),admin=isAdmin();
 document.querySelectorAll('.finance-only').forEach(x=>x.classList.toggle('allowed',fin));
 document.querySelectorAll('.approver-only').forEach(x=>x.classList.toggle('allowed',approver));
 document.querySelectorAll('.admin-only').forEach(x=>x.classList.toggle('allowed',admin));
 $('userDisplay').textContent=state.user?.display_name||state.user?.username||'StudioOS';
 $('userRole').textContent=state.user?.role?.replaceAll('_',' ')||'employee';
 $('approvalBadge').textContent=(state.approvals?.costs?.length||0)+(state.approvals?.payments?.length||0);
}
function signedIn(r){state.user=r.user;state.mustSetup2fa=!!r.two_factor_setup_required;if(state.mustSetup2fa)state.view='account';$('loginLayer').classList.add('hidden');}
async function initialize(){try{let r=await api('/api/auth/me');signedIn(r);await refresh();}catch(err){showLogin();}}
$('loginForm').addEventListener('submit',async e=>{
 e.preventDefault();$('loginError').textContent='';
 try{let r=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:$('loginUsername').value,password:$('loginPassword').value,otp:$('loginOtp').value})});
  $('loginPassword').value='';$('loginOtp').value='';$('otpField').hidden=true;state.view='assistant';signedIn(r);await refresh();}
 catch(err){if(err.data?.otp_required){$('otpField').hidden=false;$('loginOtp').focus();}$('loginError').textContent=err.message;}
});
$('logoutBtn').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'});}catch(e){}showLogin();});
function render(){updateIdentity();const views={overview,assistant,tickets,newtypes:newTypesView,universal:universalView,ledger:ledgerView,projects,tasks,budget:budgets,site,documents,activity,settings,approvals,team,agents,account,safety:safetyView};if(state.mustSetup2fa)state.view='account';$('mainContent').innerHTML=(views[state.view]||overview)();$('breadcrumb').textContent=({overview:'Overview',assistant:'Chat',tickets:'Ticket Inbox',newtypes:'New Data Inbox',universal:'Universal Types',ledger:'Accounting Ledger',projects:'Projects',tasks:'Tasks',budget:'Budgets & Costs',site:'Site Reports',documents:'NAS Documents',activity:'Activity Log',settings:'AI Providers',approvals:'Approvals',team:'Team & Roles',agents:'Agents & Hooks',account:'My account',safety:'Data safety'})[state.view];document.querySelectorAll('.nav-link').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));if(state.view==='assistant'){const m=$('chatMessages');if(m)m.scrollTop=m.scrollHeight;}}
function switchView(v){state.view=v;document.body.classList.toggle('chat-mode',v==='assistant');render();$('sidebar').classList.remove('open');window.scrollTo(0,0);}
function optionsHtml(){return state.projects.length?state.projects.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join(''):'<option disabled>No projects — create one first</option>';}
function amountEcho(text){const t=String(text||'').trim().replace(/^(?:₹|rs\.?|inr)\s*/i,'');if(!/^[0-9][0-9,]*(\.[0-9]{1,2})?$/.test(t))return '';const whole=t.split('.')[0];if(whole.includes(',')&&!/^(?:[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}|[0-9]{1,3}(?:,[0-9]{3})+)$/.test(whole))return 'Check the commas, e.g. 1,25,000';const n=Number(t.replace(/,/g,''));if(!isFinite(n)||n<=0)return '';const words=n>=1e7?' ('+(n/1e7).toLocaleString('en-IN',{maximumFractionDigits:2})+' crore)':n>=1e5?' ('+(n/1e5).toLocaleString('en-IN',{maximumFractionDigits:2})+' lakh)':'';return inr(n)+words;}   // says the amount back as you type
const field=(label,name,type='text',placeholder='',required=true)=>`<div class="field"><label for="f-${name}">${label}</label><${type==='textarea'?'textarea':'input'} class="form-input" id="f-${name}" name="${name}" ${type==='amount'?'type="text" inputmode="decimal" autocomplete="off"':type!=='textarea'?`type="${type}"`:''} ${required?'required':''} placeholder="${esc(placeholder)}" ${type==='number'?'step="0.01" min="0"':''}>${type==='textarea'?'</textarea>':''}${type==='amount'?`<small class="muted amount-echo" data-amount-for="${name}" aria-live="polite"></small>`:''}</div>`;
function formMarkup(type){const projectSelect=`<div class="field"><label for="f-project_id">Project</label><select name="project_id" class="form-input" id="f-project_id" required>${optionsHtml()}</select></div>`;
 if(type==='project')return field('Project name','name','text','e.g. Villa A')+field('Client (optional)','client','text','Client name',false)+field('Approved budget (₹)','budget','amount','e.g. 20,00,000',false);
 if(type==='task')return projectSelect+field('Task title','title','text','e.g. Issue revised flooring drawings')+field('Assigned to','assignee','text','e.g. Ravi',false)+field('Due date','due_date','date','',false);
 if(type==='cost')return projectSelect+`<div class="field"><label for="f-kind">Type</label><select name="kind" class="form-input" id="f-kind"><option value="expense">Incurred expense</option><option value="commitment">Purchase order / commitment</option></select></div>`+field('Description','title','text','e.g. Cement supply')+field('Amount (₹)','amount','amount','e.g. 9,500')+field('Vendor / supplier','vendor','text','e.g. ABC Traders',false);
 if(type==='payment')return `<div class="field"><label for="f-cost_id">Related expense or purchase</label><select name="cost_id" class="form-input" id="f-cost_id" required>${state.costs.filter(c=>c.status==='approved'&&Number(c.outstanding)-Number(c.payment_pending||0)>0).map(c=>`<option value="${c.id}">#${c.id} – ${esc(c.title)} (${inr(c.outstanding)} outstanding)</option>`).join('')}</select></div>`+field('Payment amount (₹)','amount','amount','e.g. 5,000');
 if(type==='user')return field('Username','username','text','e.g. ravi')+field('Display name','display_name','text','Ravi')+field('Password (12+ characters)','password','password','Secure unique password')+`<div class="field"><label>Role</label><select name="role" class="form-input"><option value="architect">Architect</option><option value="site_engineer">Site engineer</option><option value="accounts">Accounts</option><option value="manager">Manager</option><option value="viewer">Viewer</option></select></div>`;
 if(type==='site')return projectSelect+field('Site report','note','textarea','Describe work completed, delays, issues and observations.');return '';
}
async function peopleModal(projectId){const r=await api('/api/projects/'+Number(projectId)+'/members');const members=new Set(r.members.map(m=>m.user_id));
 const staff=(state.users||[]).filter(u=>!u.sees_all_projects&&u.active);const project=(state.projects||[]).find(p=>p.id===Number(projectId));
 const d=$('entryDialog');d.dataset.type='members';d.dataset.target=String(Number(projectId));$('modalTitle').textContent='People on '+(project?.name||'project');
 $('modalFields').innerHTML=`<p class="muted">${esc(r.note)}</p>`+(staff.length?`<div class="checkbox-list">${staff.map(u=>`<label class="checkbox-row"><input type="checkbox" name="user_ids" value="${Number(u.id)}" ${members.has(u.id)?'checked':''}> <span><strong>${esc(u.display_name)}</strong> · ${esc(u.role.replaceAll('_',' '))}</span></label>`).join('')}</div>`:'<p>No staff accounts need assigning yet. Add architects or site engineers in Team &amp; Roles.</p>');
 $('saveEntry').textContent='Save people';d.showModal();}
function resetPasswordModal(userId){const u=(state.users||[]).find(x=>x.id===Number(userId));const d=$('entryDialog');d.dataset.type='reset-password';d.dataset.target=String(Number(userId));
 $('modalTitle').textContent='Reset password for '+(u?.display_name||'employee');
 $('modalFields').innerHTML=`<p class="muted">They will be signed out everywhere and must use the new password. Tell them in person or by phone, not in a group chat.</p><div class="form-grid">${accountField('rp','New password (12+ characters)','new_password','password','new-password','minlength="12"')}</div>`;$('saveEntry').textContent='Reset password';d.showModal();}
function formRequestKey(){return 'form-'+crypto.randomUUID();}   // one per opened form, so a double tap or retry reuses it
function modal(type){if(type==='index-nas'){scanNas();return;}if(!['project','task','cost','payment','site','user'].includes(type))return;if(!['project','user'].includes(type)&&!state.projects.length){notify('Create a project first.',true);switchView('projects');return;}if(type==='payment'&&!state.costs.some(c=>c.status==='approved'&&Number(c.outstanding)-Number(c.payment_pending||0)>0)){notify('No approved cost has money left to pay yet.',true);return;}const d=$('entryDialog');d.dataset.type=type;d.dataset.requestKey=formRequestKey();$('saveEntry').disabled=false;$('modalTitle').textContent=({project:'New project',task:'New task',cost:'Record expense or purchase',payment:'Record payment',site:'New site report',user:'Add employee'})[type];$('modalFields').innerHTML=`<div class="form-grid">${formMarkup(type)}</div>`;$('saveEntry').textContent='Save entry';d.showModal();}
async function submitModal(e){e.preventDefault();const d=$('entryDialog'),type=d.dataset.type,form=$('entryForm'),values=Object.fromEntries(new FormData(form).entries());
 if(type==='members'||type==='reset-password'){try{
   if(type==='members'){const ids=new FormData(form).getAll('user_ids').map(Number);await api('/api/projects/'+Number(d.dataset.target)+'/members',{method:'PUT',body:JSON.stringify({user_ids:ids})});notify('Project people updated.');}
   else{await api('/api/users/'+Number(d.dataset.target)+'/reset-password',{method:'POST',body:JSON.stringify({new_password:values.new_password})});notify('Password reset. They have been signed out everywhere.');}
   d.close();await refresh();}catch(err){notify(err.message,true);}return;}const map={project:'/api/projects',task:'/api/tasks',cost:'/api/costs',payment:'/api/payments',site:'/api/site-reports',user:'/api/users'};for(let k of ['project_id','cost_id'])if(values[k])values[k]=Number(values[k]);if(!d.dataset.requestKey)d.dataset.requestKey=formRequestKey();if(type==='payment')values.idempotency_key=d.dataset.requestKey;else if(type!=='user')values.request_key=d.dataset.requestKey;const saveButton=$('saveEntry');if(saveButton.disabled)return;saveButton.disabled=true;try{const saved=await api(map[type],{method:'POST',body:JSON.stringify(values)});d.close();notify(saved.ticket_id?'Draft sent for approval.':(type==='cost'||type==='payment'?'Submitted for manager approval.':'Entry saved successfully.'));await refresh();}catch(err){notify(err.message,true);}finally{saveButton.disabled=false;}}
async function scanNas(){try{const r=await api('/api/documents/index-nas',{method:'POST'});notify(`Scanned NAS metadata. ${r.added} new documents indexed.`);await refresh();}catch(err){notify(err.message,true);}}
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
  }else r=await api('/api/chat',{method:'POST',body:JSON.stringify({message:v,session_id:state.sessionId})});
  state.sessionId=r.session_id;sessionStorage.setItem('studioos-chat-id',state.sessionId);
  state.messages.push({role:'assistant',reply:r.reply,proposal:r.proposal,ticket_id:r.ticket_id,preview:r.preview,holding_item:r.holding_item});
  if(r.ticket_id||r.changed||r.holding_item)await refresh();else render();
 }catch(err){state.messages.push({role:'assistant',reply:'Error: '+err.message});render();}
}
// Delegated listeners survive rerenders.
document.addEventListener('click',async e=>{let b=e.target.closest('[data-view],[data-action],[data-prompt]');if(!b)return;if(b.dataset.view){switchView(b.dataset.view);return;}if(b.dataset.prompt){switchView('assistant');sendChat(b.dataset.prompt);return;}const a=b.dataset.action;
 if(['diagnose-new-type','dashboard-new-type'].includes(a)){
  try{
   const id=Number(b.dataset.id);
   if(a==='diagnose-new-type'){
    if(!confirm('Analyze source information using the selected AI provider? A live provider may incur API charges. Nothing will be approved or executed.'))return;
    await api(`/api/new-types/${id}/diagnose`,{method:'POST',body:'{}'});
    state.newTypeDetail=await api('/api/new-types/'+id);
   }else{
    const charts=await Promise.all([0,1].map(idx=>api(`/api/new-types/${id}/dashboard/${idx}`)));
    state.newTypeDashboard={id,charts};
   }
   render();document.querySelector('#newTypeReview')?.scrollIntoView({block:'start'});
  }catch(err){notify(err.message,true);}return;
 }
 if(['open-new-type','close-new-type','approve-new-type','edit-new-type','keep-new-type','reject-new-type'].includes(a)){
  try{
   if(a==='close-new-type'){state.newTypeDetail=null;render();return;}
   if(a==='open-new-type'){state.newTypeDetail=await api('/api/new-types/'+Number(b.dataset.id));switchView('newtypes');document.querySelector('#newTypeReview')?.scrollIntoView({behavior:'smooth'});return;}
   const id=Number(b.dataset.id);
   if(a==='approve-new-type'){
    if(!confirm('Admin approval saves ONLY the schema design. No business table will be created. Proceed?'))return;
    await api(`/api/new-types/${id}/approve-structure`,{method:'POST',body:JSON.stringify({note:'Reviewed by Admin; Stage A design approval only'})});
   }else if(a==='edit-new-type'){
    const h=state.newTypeDetail||await api('/api/new-types/'+id);
    const edited=prompt('Edit the proposed design JSON (no migration will run):',JSON.stringify(h.proposal||{},null,2));
    if(edited===null)return;
    await api(`/api/new-types/${id}/proposal`,{method:'PATCH',body:JSON.stringify({design:JSON.parse(edited),recompile:true})});
   }else{
    let action=a==='keep-new-type'?'keep':'reject';
    await api(`/api/new-types/${id}/${action}`,{method:'POST',body:JSON.stringify({note:'Reviewed in Stage A UI'})});
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
   const reason=prompt(a==='user-toggle'?(b.dataset.active==='1'?'Reason for deactivating this account:':'Reason for reactivating this account:'):'Reason for resetting their two-factor login (e.g. lost phone):','');
   if(reason===null)return;if(reason.trim().length<5)throw new Error('Please give a reason of at least 5 characters.');
   if(a==='user-toggle'){await api('/api/users/'+Number(b.dataset.id)+'/active',{method:'PATCH',body:JSON.stringify({active:b.dataset.active!=='1',reason})});notify(b.dataset.active==='1'?'Account deactivated and signed out.':'Account reactivated.');}
   else{await api('/api/users/'+Number(b.dataset.id)+'/reset-2fa',{method:'POST',body:JSON.stringify({reason})});notify('Two-factor login reset; they have been signed out.');}
   await refresh();
  }catch(err){notify(err.message,true);}return;
 }
 if(a==='new-conversation'){state.sessionId='';state.messages=[];sessionStorage.removeItem('studioos-chat-id');render();return;}
 if(a==='ticket-page'){state.ticketPageOffset=Math.max(0,Number(b.dataset.offset)||0);state.ticketDetail=null;await refresh();return;}
 if(['open-ticket','close-ticket','approve-ticket-item','reject-ticket-item','edit-ticket-item','edit-ticket-field','reverse-ticket','commit-ticket','approve-bank-batch'].includes(a)){
  try{
   if(a==='close-ticket'){state.ticketDetail=null;render();return;}
   if(a==='open-ticket'){state.ticketDetail=await api('/api/tickets/'+b.dataset.id);render();document.getElementById('ticketReview')?.scrollIntoView({behavior:'smooth'});return;}
   if(a==='approve-bank-batch'){
    if(!document.getElementById('bankBatchChecked')?.checked)throw new Error('Check every proposed match against the statement first.');
    if(!confirm('Approve and save every reviewed bank match in this ticket? Any failed check rolls back the entire ticket.'))return;
    await api('/api/tickets/'+b.dataset.id+'/approve-and-save',{method:'POST',body:JSON.stringify({confirmed:[],note:'Reviewed every proposed bank match against the independent statement'})});
    state.ticketDetail=await api('/api/tickets/'+b.dataset.id);await refresh();notify('Reviewed bank matches saved.');return;
   }
   if(a==='reverse-ticket'){
    const reason=prompt('Reason for reversing this committed ticket (minimum 10 characters):','');
    if(reason===null)return;
    const draft=await api('/api/tickets/'+b.dataset.id+'/reverse',{method:'POST',body:JSON.stringify({reason})});
    state.ticketDetail=await api('/api/tickets/'+draft.ticket_id);await refresh();notify('Reversal ticket #'+draft.ticket_id+' opened. Review and approve it to undo the saved change.');return;
   }
   if(a==='edit-ticket-field'){
    const item=state.ticketDetail?.items?.find(x=>String(x.id)===String(b.dataset.id))||state.messages.map(m=>m.preview?.items||[]).flat().find(x=>String(x.id)===String(b.dataset.id));
    if(!item)throw new Error('Open the ticket before editing this field.');
    const key=b.dataset.field;const value=item.after?.[key];
    const entered=prompt('Edit '+key+' (you will need to reapprove the item):',value==null?'':typeof value==='object'?JSON.stringify(value):String(value));
    if(entered===null)return;
    const update={...item.after};
    if(value===null||typeof value==='number'){
      if(!/^\d+$/.test(entered.trim()))throw new Error('This field expects a whole number.');
      update[key]=Number(entered);
    }else if(typeof value==='object'){update[key]=JSON.parse(entered);}else{update[key]=entered;}
    await api('/api/tickets/items/'+item.id,{method:'PATCH',body:JSON.stringify({after:update,note:'Edited field '+key+' from mobile review'})});
    state.ticketDetail=await api('/api/tickets/'+(state.ticketDetail?.id||item.ticket_id||state.messages.find(m=>m.ticket_id)?.ticket_id));
    await refresh();notify('Field edited. Reapproval required.');return;
   }
   if(a==='commit-ticket'){
    if(!confirm('Commit all APPROVED ticket items in ONE transaction? Rejected items will be skipped.'))return;
    await api('/api/tickets/'+b.dataset.id+'/commit',{method:'POST'});notify('Ticket committed atomically.');state.ticketDetail=await api('/api/tickets/'+b.dataset.id);await refresh();return;
   }
   let itemId=b.dataset.id;
   if(a==='edit-ticket-item'){
    let item=state.ticketDetail?.items?.find(x=>String(x.id)===String(itemId));
    const raw=prompt('Edit proposed AFTER fields as JSON. The item must be reapproved.',JSON.stringify(item?.after||{},null,2));
    if(raw===null)return;
    let after=JSON.parse(raw);
    await api('/api/tickets/items/'+itemId,{method:'PATCH',body:JSON.stringify({after,note:'Edited in ticket review'})});
   } else {
    const op=a==='approve-ticket-item'?'approve':'reject';
    const note=prompt(op==='reject'?'Reason for rejection (optional)':'Reviewer note (optional)','');
    if(note===null)return;
    await api('/api/tickets/items/'+itemId+'/'+op,{method:'POST',body:JSON.stringify({note})});
   }
   state.ticketDetail=await api('/api/tickets/'+state.ticketDetail.id);await refresh();notify('Ticket item reviewed.');
  }catch(err){notify(err.message,true);}return;
 }
 if(['project' ,'task','cost','payment','site','user','index-nas'].includes(a)){modal(a);return;}if(['approve-cost','approve-payment','reject-cost','reject-payment'].includes(a)){
  let reason='';if(a.startsWith('reject')){reason=prompt('Reason for rejecting this entry (at least 10 characters):')||'';if(reason.length<10)return;}
  try{let kind=a.endsWith('cost')?'costs':'payments';let op=a.startsWith('approve')?'approve':'reject';
   const draft=await api('/api/'+kind+'/'+b.dataset.id+'/'+op,{method:'POST',body:JSON.stringify(op==='reject'?{reason}:{} )});
   notify('Ticket #'+draft.ticket_id+' opened. Review it in Ticket Inbox to save this decision.');await refresh();
  }catch(err){notify(err.message,true);}return;
 }
 if(a==='recognize'){if(!confirm('Confirm this purchase order has been invoiced? It will be converted to incurred cost without double-counting.'))return;try{const draft=await api('/api/costs/'+b.dataset.id+'/recognize',{method:'PATCH'});notify('Ticket #'+draft.ticket_id+' opened. Review it to recognize this purchase.');await refresh();}catch(err){notify(err.message,true);}return;}if(a==='complete'){try{const draft=await api('/api/tasks/'+b.dataset.id+'/complete',{method:'PATCH'});await refresh();notify('Task completion ticket #'+draft.ticket_id+' opened. Review it in Ticket Inbox to save the change.');}catch(err){notify(err.message,true);}return;}if(a==='switch-provider'){try{await api('/api/settings/provider',{method:'POST',body:JSON.stringify({provider:b.dataset.provider})});notify('AI provider changed; project data is untouched.');await refresh();}catch(err){notify(err.message,true);}return;}});
async function accountSubmit(form){const v=Object.fromEntries(new FormData(form).entries());
 try{
  if(form.id==='changePasswordForm'){if(v.new_password!==v.repeat_password)throw new Error('The two new passwords do not match.');
   const r=await api('/api/auth/change-password',{method:'POST',body:JSON.stringify({current_password:v.current_password,new_password:v.new_password})});form.reset();notify('Password changed.'+(r.other_sessions_ended?' Other devices were signed out.':''));return;}
  if(form.id==='twoFactorSetupForm'){state.twoFactorSetup=await api('/api/auth/2fa/setup',{method:'POST',body:JSON.stringify({password:v.password})});render();return;}
  if(form.id==='twoFactorEnableForm'){const r=await api('/api/auth/2fa/enable',{method:'POST',body:JSON.stringify({code:v.code})});state.twoFactorSetup=null;state.recoveryCodes=r.recovery_codes;
   const wasLocked=state.mustSetup2fa;state.mustSetup2fa=false;state.user={...state.user,two_factor:true};await refresh();notify(wasLocked?'Two-factor login is on. StudioOS is unlocked.':'Two-factor login is on.');return;}
  if(form.id==='twoFactorCodesForm'){const r=await api('/api/auth/2fa/recovery-codes',{method:'POST',body:JSON.stringify({password:v.password,code:v.code})});state.recoveryCodes=r.recovery_codes;render();return;}
  if(form.id==='twoFactorDisableForm'){if(!confirm('Turn off two-factor login? Signing in will need only your password.'))return;
   await api('/api/auth/2fa/disable',{method:'POST',body:JSON.stringify({password:v.password,code:v.code})});state.user={...state.user,two_factor:false};await refresh();notify('Two-factor login is off.');return;}
 }catch(err){notify(err.message,true);}}
document.addEventListener('submit',e=>{
 if(['changePasswordForm','twoFactorSetupForm','twoFactorEnableForm','twoFactorCodesForm','twoFactorDisableForm'].includes(e.target.id)){e.preventDefault();accountSubmit(e.target);return;}
 if(e.target.id==='previewRequirementForm'){
 e.preventDefault();const form=e.target;
 let record;
 try{record=JSON.parse(new FormData(form).get('record')||'{}');}
 catch(err){notify('Record must be valid JSON',true);return;}
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
$('cancelModal').addEventListener('click',()=>$('entryDialog').close());
$('refreshBtn').addEventListener('click',()=>refresh().then(()=>notify('Dashboard refreshed.')));
$('menuBtn').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
initialize();
document.addEventListener('input',e=>{const el=e.target;if(!el||el.tagName!=='INPUT'||el.getAttribute('inputmode')!=='decimal')return;const out=el.form&&el.form.querySelector('[data-amount-for="'+el.name+'"]');if(out)out.textContent=amountEcho(el.value);});
