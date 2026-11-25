/* Client portal screens. Plain text only: every value from the server is shown with textContent, never as HTML. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var state = { ident: '', lastMsg: 0, timer: null, sending: false };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|; )studioos_portal_csrf=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function api(path, method, body) {
    var opts = { method: method || 'GET', credentials: 'same-origin', headers: {} };
    if (opts.method !== 'GET') {
      opts.headers['X-CSRF-Token'] = csrf();
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body || {});
    }
    return fetch('/portal-api' + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail)) detail = 'Please check what you typed and try again.';
          var e = new Error(detail || 'Something went wrong. Please try again.');
          e.status = r.status;
          throw e;
        }
        return data;
      });
    });
  }
  function show(id, on) { $(id).hidden = !on; }
  function say(id, text, ok) {
    var n = $(id);
    n.textContent = text || '';
    n.className = 'msg' + (ok ? ' ok' : '');
    n.hidden = !text;
  }
  function fail(e, id) {
    if (e && e.status === 401 && $('main') && !$('main').hidden) { toLogin('Please sign in again.'); return; }
    say(id, e && e.message ? e.message : 'Something went wrong.');
  }
  function when(iso) { try { return new Date(iso).toLocaleString(); } catch (e) { return ''; } }
  function size(n) {
    if (!n && n !== 0) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return Math.round(n / 1024) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  /* ---------- sign in ---------- */
  function toLogin(note) {
    stopPolling();
    show('loading', false); show('main', false); show('login', true);
    show('ask-form', true); show('code-form', false);
    say('login-msg', note || '');
  }
  $('ask-form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var ident = $('ident').value.trim();
    if (!ident) { say('login-msg', 'Enter your phone number or email address.'); return; }
    state.ident = ident;
    var btn = ev.target.querySelector('button'); btn.disabled = true;
    api('/login/request', 'POST', { identifier: ident }).then(function (r) {
      say('login-msg', '');
      $('sent-note').textContent = r.message || 'If that matches, a code has been sent.';
      show('ask-form', false); show('code-form', true); $('code').value = ''; $('code').focus();
    }).catch(function (e) { say('login-msg', e.message); }).then(function () { btn.disabled = false; });
  });
  $('code-form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var btn = ev.target.querySelector('button[type=submit]'); btn.disabled = true;
    api('/login/verify', 'POST', { identifier: state.ident, code: $('code').value }).then(function () {
      say('login-msg', ''); start();
    }).catch(function (e) { say('login-msg', e.message); }).then(function () { btn.disabled = false; });
  });
  $('back-btn').addEventListener('click', function () { say('login-msg', ''); show('code-form', false); show('ask-form', true); $('ident').focus(); });
  $('logout-btn').addEventListener('click', function () {
    api('/logout', 'POST').catch(function () {}).then(function () { toLogin(''); });
  });

  /* ---------- main ---------- */
  function start() {
    api('/me').then(function (me) {
      $('who').textContent = 'Signed in as ' + me.name;
      $('project-name').textContent = me.project;
      document.title = me.project + ' · Client portal';
      show('loading', false); show('login', false); show('main', true);
      loadFiles(); loadChat(true); startPolling();
    }).catch(function (e) {
      if (e.status === 401) toLogin(''); else { show('loading', false); toLogin(e.message); }
    });
  }
  function selectTab(name) {
    ['files', 'agreed', 'chat'].forEach(function (n) {
      $('tab-' + n).setAttribute('aria-selected', String(n === name));
      show('panel-' + n, n === name);
    });
    if (name === 'chat') { var t = $('thread'); t.scrollTop = t.scrollHeight; window.scrollTo(0, document.body.scrollHeight); }
    if (name === 'agreed') loadAgreed();
  }
  $('tab-files').addEventListener('click', function () { selectTab('files'); });
  $('tab-agreed').addEventListener('click', function () { selectTab('agreed'); });
  $('tab-chat').addEventListener('click', function () { selectTab('chat'); });

  /* ---------- files and approvals ---------- */
  function statusTag(a) {
    if (a.state === 'approved') return el('span', 'tag ok', 'You approved this');
    if (a.state === 'changes_requested') return el('span', 'tag warn', 'You asked for changes');
    return el('span', 'tag warn', 'Waiting for your answer');
  }
  function approvalBlock(item) {
    var a = item.approval;
    var box = el('div', 'approval');
    box.appendChild(statusTag(a));
    if (a.earlier_version) box.appendChild(el('p', 'note', 'This was updated after your last answer, so we need your answer again.'));
    if (a.by && a.at) box.appendChild(el('p', 'note', a.by + ' · ' + when(a.at) + (a.comment ? ' — “' + a.comment + '”' : '')));
    var msg = el('p', 'msg', ''); msg.hidden = true; msg.setAttribute('role', 'alert');
    var buttons = el('div', 'buttons');
    var approve = el('button', 'btn primary', a.state === 'approved' ? 'Approved' : 'Approve'); approve.type = 'button';
    var change = el('button', 'btn', 'Ask for changes'); change.type = 'button';
    var form = el('div', ''); form.hidden = true;
    var ta = el('textarea', ''); ta.rows = 3; ta.maxLength = 2000; ta.setAttribute('aria-label', 'What would you like changed?');
    var send = el('button', 'btn primary', 'Send to my design team'); send.type = 'button';
    form.appendChild(ta); form.appendChild(send);
    function submit(decision, comment, buttonsToLock) {
      buttonsToLock.forEach(function (b) { b.disabled = true; });
      api('/deliverables/' + item.id + '/decision', 'POST', { decision: decision, comment: comment }).then(function () {
        loadFiles();
      }).catch(function (e) {
        msg.textContent = e.status === 401 ? 'Please sign in again.' : e.message; msg.hidden = false;
        if (e.status === 401) toLogin('Please sign in again.');
      }).then(function () { buttonsToLock.forEach(function (b) { b.disabled = false; }); });
    }
    approve.addEventListener('click', function () { if (a.state !== 'approved') submit('approved', '', [approve, change]); });
    change.addEventListener('click', function () { form.hidden = !form.hidden; if (!form.hidden) ta.focus(); });
    send.addEventListener('click', function () {
      if (ta.value.trim().length < 3) { msg.textContent = 'Please say what you would like changed.'; msg.hidden = false; return; }
      submit('changes_requested', ta.value, [send, approve, change]);
    });
    buttons.appendChild(approve); buttons.appendChild(change);
    box.appendChild(buttons); box.appendChild(form); box.appendChild(msg);
    return box;
  }
  function loadFiles() {
    api('/deliverables').then(function (r) {
      var ul = $('files'); ul.textContent = '';
      show('files-empty', r.items.length === 0);
      r.items.forEach(function (it) {
        var li = el('li', 'item'); li.id = 'file-' + it.id;
        li.appendChild(el('h2', '', it.title));
        var row = el('div', 'row');
        row.appendChild(el('span', 'tag', it.kind));
        if (it.added) row.appendChild(el('span', 'muted', 'Added ' + when(it.added)));
        li.appendChild(row);
        if (it.note) li.appendChild(el('p', '', it.note));
        var dl = el('a', 'btn', 'Download ' + it.file_name + (it.size_bytes ? ' (' + size(it.size_bytes) + ')' : ''));
        dl.href = '/portal-api/deliverables/' + it.id + '/file';
        li.appendChild(dl);
        if (it.approval) li.appendChild(approvalBlock(it));
        li.appendChild(askButton(it.title));
        ul.appendChild(li);
      });
      say('main-msg', '');
    }).catch(function (e) { fail(e, 'main-msg'); });
  }

  /* ---------- ask about something: opens the chat with a starting line; the client can ask anything ---------- */
  function askAbout(topic) {
    selectTab('chat');
    var ta = $('chat-body');
    if (!ta.value.trim()) ta.value = 'About “' + topic + '”: ';
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
  function askButton(topic, label) {
    var b = el('button', 'btn quiet', label || 'Ask a question about this'); b.type = 'button';
    b.addEventListener('click', function () { askAbout(topic); });
    return b;
  }

  /* ---------- what we agreed: records of conversations, with proof ---------- */
  function actionRow(a) {
    var li = el('li', 'todo');
    var head = el('div', 'row');
    head.appendChild(el('span', a.state === 'Done' ? 'tag ok' : 'tag warn', a.state === 'Done' ? 'Done' : 'To do'));
    head.appendChild(el('strong', '', a.text));
    li.appendChild(head);
    var meta = [];
    if (a.owner) meta.push('With ' + a.owner);
    if (a.due_date) meta.push('Due ' + a.due_date);
    if (meta.length) li.appendChild(el('p', 'muted', meta.join(' · ')));
    if (a.note) li.appendChild(el('p', '', a.note));
    if (a.file) {
      var f = el('a', 'btn', 'Download ' + a.file.name);
      f.href = '/portal-api/conversations/actions/' + a.id + '/file';
      li.appendChild(f);
    }
    li.appendChild(askButton(a.text));
    if (a.deliverable) {
      var b = el('button', 'btn', 'See “' + a.deliverable.title + '” in Files'); b.type = 'button';
      b.addEventListener('click', function () {
        selectTab('files');
        var target = $('file-' + a.deliverable.id);
        if (target) { target.scrollIntoView(); }
      });
      li.appendChild(b);
    }
    return li;
  }
  function loadAgreed() {
    api('/conversations').then(function (r) {
      var ul = $('agreed'); ul.textContent = '';
      show('agreed-empty', r.records.length === 0);
      r.records.forEach(function (rec) {
        var li = el('li', 'item');
        li.appendChild(el('h2', '', rec.title));
        if (rec.created) li.appendChild(el('p', 'muted', when(rec.created) + (rec.updated ? ' · Updated ' + when(rec.updated) : '')));
        li.appendChild(el('p', '', rec.summary));
        if (rec.actions.length) {
          var open = rec.actions.filter(function (a) { return a.state !== 'Done'; }).length;
          li.appendChild(el('p', 'muted', rec.actions.length + ' item' + (rec.actions.length === 1 ? '' : 's') + ' · ' + open + ' still to do'));
          var todo = el('ul', 'list');
          rec.actions.forEach(function (a) { todo.appendChild(actionRow(a)); });
          li.appendChild(todo);
        }
        var good = rec.messages.length > 0 && rec.messages.every(function (m) { return m.verified; });
        var det = el('details', 'proof');
        det.appendChild(el('summary', '', 'Proof: ' + rec.messages.length + ' message' + (rec.messages.length === 1 ? '' : 's') + ' from our conversation'
          + (good ? ' (verified)' : ' (could not be verified)')));
        rec.messages.forEach(function (m) {
          var q = el('div', 'quote');
          q.appendChild(el('span', 'meta', (m.from === 'client' ? 'You' : m.author) + ' · ' + when(m.at) + ' · ' + (m.verified ? 'verified' : 'NOT verified')));
          q.appendChild(document.createTextNode(m.body));
          det.appendChild(q);
        });
        li.appendChild(det);
        li.appendChild(askButton(rec.title));
        ul.appendChild(li);
      });
    }).catch(function (e) { fail(e, 'main-msg'); });
  }

  /* ---------- messages ---------- */
  function addBubble(m) {
    var li = el('li', 'bubble ' + (m.from === 'client' ? 'client' : 'staff'));
    li.appendChild(el('span', 'meta', (m.from === 'client' ? 'You' : m.author) + ' · ' + when(m.at)));
    li.appendChild(document.createTextNode(m.body));
    $('thread').appendChild(li);
    state.lastMsg = Math.max(state.lastMsg, m.id);
  }
  function loadChat(initial) {
    api('/chat?after=' + (initial ? 0 : state.lastMsg)).then(function (r) {
      var t = $('thread');
      if (initial) { t.textContent = ''; state.lastMsg = 0; }
      var nearEnd = t.scrollHeight - t.scrollTop - t.clientHeight < 80;
      r.messages.forEach(addBubble);
      show('chat-empty', t.children.length === 0);
      if (initial || nearEnd) window.requestAnimationFrame(function () { t.scrollTop = t.scrollHeight; });
    }).catch(function (e) { if (e.status === 401) toLogin('Please sign in again.'); });
  }
  $('chat-form').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var ta = $('chat-body'), body = ta.value.trim();
    if (!body || state.sending) return;
    state.sending = true;
    var btn = ev.target.querySelector('button'); btn.disabled = true;
    api('/chat', 'POST', { body: body }).then(function () { ta.value = ''; say('main-msg', ''); loadChat(false); })
      .catch(function (e) { fail(e, 'main-msg'); })
      .then(function () { state.sending = false; btn.disabled = false; });
  });
  function startPolling() {
    stopPolling();
    state.timer = window.setInterval(function () { if (!document.hidden) { loadChat(false); } }, 20000);
  }
  function stopPolling() { if (state.timer) { window.clearInterval(state.timer); state.timer = null; } }

  start();
})();
