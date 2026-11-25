
'use strict';
/* StudioOS: when a private chat message is really about a project, the answer carries an offer to send it to that project's team chat.
   Nothing is sent unless the person taps the button; the message is posted as theirs, as written. Loaded after app.js and chat.js. */

let chatOffer = null;
const _offerApi = api;
api = async function (path, opts) {
  const r = await _offerApi(path, opts);
  if (String(path).split('?')[0] === '/api/chat' && r && r.team_chat_offer) chatOffer = r.team_chat_offer;
  return r;
};

function offerPaint() {
  const box = document.getElementById('chatMessages');
  if (!box || !chatOffer || document.getElementById('teamOffer')) return;
  const el = document.createElement('div');
  el.id = 'teamOffer';
  el.className = 'notice';
  el.innerHTML = `<span>This is about <strong>${esc(chatOffer.name)}</strong>. Send it to the team chat so the team sees it?</span>` +
    `<span><button type="button" class="btn btn-primary btn-sm" data-offer="send">Send to team chat</button> <button type="button" class="btn btn-secondary btn-sm" data-offer="keep">Keep private</button></span>`;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

const _offerRender = render;
render = function () { _offerRender(); setTimeout(offerPaint, 0); };
document.addEventListener('click', async e => {
  if (e.target.closest('[data-action="new-conversation"], [data-action="cx-open-session"]')) {
    chatOffer = null;
    document.getElementById('teamOffer')?.remove();
    return;
  }
  const b = e.target.closest('[data-offer]');
  if (!b) return;
  const offer = chatOffer;
  chatOffer = null;
  document.getElementById('teamOffer')?.remove();
  if (b.dataset.offer !== 'send' || !offer) return;
  try {
    await api(`/api/projects/${Number(offer.project_id)}/chat`, {method: 'POST', body: JSON.stringify({body: offer.body})});
    notify(`Sent to the ${offer.name} team chat.`);
  } catch (err) { notify(err.message, true); }
});
