'use strict';

const SALES_VIEWS = {sales: 'Sales', receipts: 'Receipts & retainers'};
const SALES_STATES = {
  '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh',
  '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan',
  '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh',
  '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura',
  '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand',
  '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat',
  '26': 'Dadra and Nagar Haveli and Daman and Diu', '27': 'Maharashtra', '29': 'Karnataka',
  '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry',
  '35': 'Andaman and Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh',
};
const salesMoney = paise => '₹' + (paise / 100).toLocaleString('en-IN', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const salesOption = (value, label, selected) =>
  `<option value="${esc(value)}"${String(value) === String(selected) ? ' selected' : ''}>${esc(label)}</option>`;
const salesOptions = (rows, selected) => rows.map(row => salesOption(row.id, row.name, selected)).join('');
const salesBook = () => state.sales ||= {tab: 'quotes', companyId: null, clientId: null, form: null};
const salesCompany = book => book.options.companies.find(row => row.id === book.companyId);
const salesProject = (book, id) => book.options.projects.find(row => Number(row.id) === Number(id));
function salesFormCompany(book, form) {
  const project = salesProject(book, form.elements.project_id?.value);
  return book.options.companies.find(row => row.id === project?.company_id) || salesCompany(book);
}
const salesName = (rows, id) => rows.find(row => row.id === id)?.name || '—';
const salesButton = (action, text, id = null, primary = false) =>
  `<button type="button" class="btn btn-${primary ? 'primary' : 'secondary'}" data-sales-action="${action}"${id === null ? '' : ` data-id="${Number(id)}"`}>${esc(text)}</button>`;
const salesSelect = (name, label, choices, required = true, disabled = false) =>
  `<div class="field"><label for="sales-field-${name}">${esc(label)}</label>
    <select class="form-input" id="sales-field-${name}" name="${name}"${required ? ' required' : ''}${disabled ? ' disabled' : ''}>${choices}</select></div>`;
const salesInput = (name, label, value = '', type = 'text', attributes = ' required') =>
  `<label class="field"><span>${esc(label)}</span><input class="form-input" name="${name}" type="${type}" value="${esc(value)}"${attributes}></label>`;
const salesAmount = (name, label, value = '', required = true) => salesInput(name, label, value,
  'text', ` inputmode="decimal" autocomplete="off"${required ? ' required' : ''}`);

function salesCurrent(book, view) {
  return state.sales === book && state.view === view && hasFinance() && !state.mustSetup2fa;
}

async function salesLoad(book, view) {
  const request = {};
  book.request = request;
  const current = () => salesCurrent(book, view) && book.request === request;
  try {
    if (!book.options || !book.options.companies?.length) book.options = await api('/api/sales/options');
    if (!current()) return;
    book.companyId ??= book.options.companies[0]?.id;
    if (!book.companyId) return;
    const entity = `?entity_id=${book.companyId}`;
    if (view === 'sales') {
      const [quotes, invoices, summary] = await Promise.all([
        api('/api/sales/quotes' + entity), api('/api/sales/invoices' + entity),
        api('/api/sales/summary' + entity),
      ]);
      if (!current()) return;
      Object.assign(book, {quotes: quotes.quotes, invoices: invoices.invoices, summary});
    } else if (book.clientId) {
      const statement = await api(`/api/sales/clients/${book.clientId}/statement` + entity);
      if (current()) book.statement = statement;
    }
  } catch (error) {
    if (current()) book.error = error.message;
  } finally {
    if (current()) {
      book.request = null;
      book.loaded = true;
      render();
    }
  }
}

function salesTable(headings, rows, emptyText) {
  if (!rows.length) return `<p class="muted">${esc(emptyText)}</p>`;
  return `<div class="w-table-wrap"><table class="w-table">
    <thead><tr>${headings.map(label => `<th scope="col">${esc(label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>`;
}

function salesPanel(title, content) {
  return `<section class="panel section-gap"><div class="panel-head"><h2 class="panel-title">${esc(title)}</h2></div><div class="panel-body">${content}</div></section>`;
}

function salesTiles(entries) {
  return `<div class="v-tiles section-gap">${entries.map(([label, amount, count]) => `<div class="v-tile">
    <div class="v-tile-value">${esc(salesMoney(amount))}</div>
    <div class="v-tile-label">${esc(label)}${count === undefined ? '' : ` · ${count}`}</div></div>`).join('')}</div>`;
}

function salesQuoteGroups(quotes) {
  const groups = new Map();
  for (const quote of quotes) {
    const group = groups.get(quote.quote_number) || {};
    if (!group.latest || quote.version > group.latest.version) group.latest = quote;
    if (quote.accepted) group.accepted = quote;
    groups.set(quote.quote_number, group);
  }
  return groups;
}

function salesRegister(book) {
  const groups = salesQuoteGroups(book.quotes);
  const open = [...groups.values()].filter(group => !group.accepted && group.latest.valid_until >= book.options.today)
    .map(group => group.latest);
  const unpaid = book.invoices.filter(invoice => invoice.owed_paise > 0);
  const sum = (rows, field) => rows.reduce((total, row) => total + row[field], 0);
  const stats = salesTiles([
    ['Open quotes', sum(open, 'total_paise'), open.length],
    ['Unpaid invoices', sum(unpaid, 'owed_paise'), unpaid.length],
    ['Collected this month', book.summary.collected_paise],
    ['Unallocated client retainers', book.summary.unallocated_advance_paise],
  ]);
  const tabs = `<div class="row-actions section-gap" aria-label="Sales register">
    <button type="button" class="btn btn-secondary" data-sales-action="quotes" aria-pressed="${book.tab === 'quotes'}">Quotes</button>
    <button type="button" class="btn btn-secondary" data-sales-action="invoices" aria-pressed="${book.tab === 'invoices'}">Invoices</button>
    ${salesButton(book.tab === 'quotes' ? 'quote' : 'invoice', book.tab === 'quotes' ? 'New quote' : 'New tax invoice', null, true)}
    ${salesButton('credit', 'Credit note')}</div>`;
  if (book.tab === 'quotes') {
    const rows = book.quotes.map(quote => {
      const group = groups.get(quote.quote_number);
      const active = !group.accepted && group.latest.id === quote.id;
      const actions = quote.accepted ? salesButton('convert', 'Turn into invoice', quote.id) : active
        ? salesButton('revise', 'Revise', quote.id) + ' ' + salesButton('accept', 'Mark accepted', quote.id) : '';
      return `<tr><th scope="row">${esc(quote.quote_number)}</th>
        <td>${esc(salesName(book.options.clients, quote.client_id))}</td>
        <td>${esc(salesName(book.options.projects, quote.project_id))}</td>
        <td>v${Number(quote.version)}</td><td>${esc(quote.valid_until)}</td>
        <td class="num">${esc(salesMoney(quote.total_paise))}</td>
        <td>${pill(quote.accepted ? 'Accepted' : active ? 'Draft' : 'Earlier version', quote.accepted ? 'success' : '')}</td>
        <td>${actions}</td></tr>`;
    });
    return stats + tabs + salesPanel('Quotes', salesTable(
      ['Quote', 'Client', 'Project', 'Version', 'Valid until', 'Total', 'Status', 'Actions'], rows, 'No quotes for this company yet.'));
  }
  const rows = book.invoices.map(invoice => `<tr><th scope="row">${esc(invoice.invoice_number)}</th>
    <td>${esc(invoice.client_name)}</td><td>${esc(invoice.invoice_date)}</td><td>${esc(invoice.due_date)}</td>
    <td class="num">${esc(salesMoney(invoice.total_paise))}</td><td class="num">${esc(salesMoney(invoice.owed_paise))}</td>
    <td>${pill(invoice.reversed ? 'Reversed' : 'Posted', invoice.reversed ? '' : 'success')}</td>
    <td><a href="/api/sales/invoices/${Number(invoice.id)}/pdf" target="_blank" rel="noopener" class="cx-link">Download PDF</a></td></tr>`);
  return stats + tabs + salesPanel('Invoices', salesTable(
    ['Invoice', 'Client', 'Date', 'Due date', 'Total', 'Still owed', 'Status', 'PDF'], rows, 'No invoices for this company yet.'));
}

function salesStatement(book) {
  const statement = book.statement;
  const clientPicker = salesSelect('statement_client', 'Client',
    salesOption('', 'Choose a client', book.clientId) + salesOptions(book.options.clients, book.clientId), false);
  if (!statement) return salesPanel('Customer statement', clientPicker);
  const invoices = statement.invoices.map(row => `<tr><th scope="row">${esc(row.invoice_number)}</th>
    <td>${esc(row.invoice_date)}</td><td>${esc(row.due_date)}</td><td class="num">${esc(salesMoney(row.total_paise))}</td>
    <td class="num">${esc(salesMoney(row.owed_paise))}</td></tr>`);
  const canApply = statement.invoices.some(row => row.owed_paise > 0);
  const advances = statement.advances.map(row => `<tr><th scope="row">${esc(row.reference)}</th><td>${esc(row.receipt_date)}</td>
    <td class="num">${esc(salesMoney(row.remaining_paise))}</td>
    <td>${canApply && row.remaining_paise > 0 ? salesButton('apply', 'Apply retainer', row.id) : ''}</td></tr>`);
  return salesPanel('Customer statement', clientPicker + salesTiles([
    ['Open receivable', statement.receivable_paise], ['Unallocated retainers', statement.unallocated_advance_paise],
  ]) + '<h3 class="w-sub">Invoices</h3>' + salesTable(['Invoice', 'Date', 'Due date', 'Total', 'Still owed'], invoices, 'No invoices for this client.')
    + '<h3 class="w-sub">Retainers</h3>' + salesTable(['Reference', 'Date', 'Available', 'Actions'], advances, 'No retainers for this client.'));
}

function salesView(view) {
  const title = SALES_VIEWS[view];
  if (!hasFinance()) return head(title, 'This screen is for the owner, Managers, and Accounts.');
  const book = salesBook();
  if (!book.loaded && !book.request) salesLoad(book, view);
  const titleHtml = head(title, '');
  if (book.error) return titleHtml + salesPanel('Could not load', `<p role="alert">${esc(book.error)}</p>` + salesButton('retry', 'Try again'));
  if (!book.loaded) return titleHtml + '<div class="loading" role="status">Loading…</div>';
  if (!book.companyId) return titleHtml + salesPanel('No company set up', '<p>Set up a company in Books to continue.</p>');
  const companyPicker = salesSelect('sales_company', 'Company', salesOptions(book.options.companies, book.companyId));
  const content = view === 'sales' ? salesRegister(book) :
    `<div class="row-actions section-gap">${salesButton('receipt', 'Record client payment', null, true)}
      ${salesButton('advance', 'Record client retainer')}</div>${salesStatement(book)}`;
  return titleHtml + `<div class="sales-screen" data-sales-screen>${companyPicker}${book.form ? salesForm(book) : ''}${content}</div>`;
}

function salesLine(line = {}) {
  return `<fieldset class="sales-line section-gap" data-sales-line><legend>Item</legend><div class="form-grid">
    ${salesInput('description', 'Description', line.description, 'text', ' required maxlength="250"')}
    <label class="field"><span>SAC or HSN</span><input class="form-input" name="sac_hsn" list="sales-sac" maxlength="20" placeholder="Choose or type SAC/HSN" value="${esc(line.sac_hsn || '')}"></label>
    ${salesInput('quantity', 'Quantity', line.quantity || 1, 'number', ' required min="1" step="1"')}
    ${salesAmount('rate', 'Rate (₹)', line.rate_paise ? (line.rate_paise / 100).toFixed(2) : '')}
    ${salesInput('gst', 'GST (%)', (line.tax_rate_bps ?? 1800) / 100, 'number', ' required min="0" max="28" step="0.01"')}
    </div>${salesButton('remove-line', 'Remove item')}</fieldset>`;
}

const SALES_FORM_TITLES = {
  quote: 'New quote', revise: 'Revise quote', accept: 'Mark quote accepted', invoice: 'New tax invoice',
  credit: 'Credit note', receipt: 'Record client payment', advance: 'Record client retainer', apply: 'Apply retainer',
};
const SALES_MESSAGES = {
  quote: 'Quote', revise: 'Quote revision', accept: 'Quote acceptance', invoice: 'Invoice',
  credit: 'Credit note', receipt: 'Payment', advance: 'Retainer', apply: 'Retainer allocation',
};

function salesForm(book) {
  const {type, id, key} = book.form;
  const {options, statement} = book;
  const company = salesCompany(book);
  const quote = book.quotes?.find(row => row.id === id);
  const today = options.today;
  const client = (selected = book.clientId, locked = false) => salesSelect('client_id', 'Client',
    salesOption('', 'Choose a client', selected) + salesOptions(options.clients, selected), true, locked);
  const project = (selected, locked = false) => salesSelect('project_id', 'Project',
    salesOption('', 'No project', selected) + salesOptions(options.projects.filter(row => row.company_id), selected), false, locked);
  const deposit = () => salesSelect('deposit_account_id', 'Received into',
    salesOption('', 'Choose a bank or cash account', null) + salesOptions(company.deposit_accounts));
  const invoicePicker = rows => salesSelect('invoice_id', 'Unpaid invoice', salesOption('', 'Choose an invoice', null) +
    rows.filter(row => row.owed_paise > 0).map(row =>
      salesOption(row.id, `${row.invoice_number} · ${salesMoney(row.owed_paise)} due`, null)).join(''));
  let fields;
  let items = '';
  if (['quote', 'revise', 'invoice'].includes(type)) {
    const invoice = type === 'invoice';
    const linked = invoice && Boolean(quote);
    fields = client(quote?.client_id ?? book.clientId, linked) + project(quote?.project_id, linked) +
      salesInput('number', invoice ? 'Invoice number' : 'Quote number', invoice ? '' : quote?.quote_number, 'text',
        ' required maxlength="80"' + (type === 'revise' ? ' readonly' : '')) +
      salesInput('date', invoice ? 'Invoice date' : 'Quote date', today, 'date') +
      salesInput('until', invoice ? 'Due date' : 'Valid until', invoice ? today : quote?.valid_until || '', 'date');
    if (invoice) {
      const stateOptions = Object.entries(SALES_STATES).sort((a, b) => a[1].localeCompare(b[1]))
        .map(([code, name]) => salesOption(code, `${name} (${code})`, company.state_code)).join('');
      fields += salesSelect('site_state', 'Site state', stateOptions);
    }
    fields += salesInput('note', 'Note (optional)', quote?.note, 'text', ' maxlength="400"');
    items = `<datalist id="sales-sac"><option value="998391">Interior design</option><option value="9954">Turnkey works</option></datalist>
      <div data-sales-lines>${(quote?.lines || [{}]).map(salesLine).join('')}</div>
      ${salesButton('add-line', 'Add item')}`;
  } else if (type === 'accept') {
    fields = `<p>Accept quote <strong>${esc(quote.quote_number)}</strong>, version ${Number(quote.version)}. Approved acceptance locks this quote.</p>` +
      salesInput('date', 'Accepted on', today, 'date') + salesInput('note', 'Note (optional)', '', 'text', ' maxlength="300"');
  } else if (type === 'receipt') {
    fields = client() + `<div data-sales-invoice-picker>${invoicePicker(statement?.invoices || [])}</div>` +
      salesAmount('amount', 'Received from client (₹)') + salesAmount('tds', 'TDS deducted by client (₹)', '', false) +
      deposit() + salesInput('date', 'Payment date', today, 'date') +
      salesInput('reference', 'Payment reference', '', 'text', ' required maxlength="120"');
  } else if (type === 'advance') {
    fields = client() + project() + deposit() + salesAmount('amount', 'Amount received (₹)') +
      salesInput('date', 'Payment date', today, 'date') + salesInput('reference', 'Payment reference', '', 'text', ' required maxlength="120"');
  } else if (type === 'apply') {
    const advance = statement.advances.find(row => row.id === id);
    fields = `<p>Available to apply <strong>${esc(salesMoney(advance.remaining_paise))}</strong></p>` +
      invoicePicker(statement.invoices) + salesAmount('amount', 'Amount to apply (₹)') + salesInput('date', 'Apply on', today, 'date');
  } else {
    const vendor = book.form.vendor;
    const parties = vendor ? options.vendors : options.clients;
    const taxAccounts = vendor ? company.input_tax_accounts : company.output_tax_accounts;
    fields = salesSelect('credit_kind', 'Credit for', salesOption('client', 'Client', vendor ? 'vendor' : 'client') +
      salesOption('vendor', 'Vendor', vendor ? 'vendor' : 'client')) +
      salesSelect('party_id', vendor ? 'Vendor' : 'Client', salesOption('', 'Choose a contact', null) + salesOptions(parties)) +
      project() + salesInput('number', 'Credit note number', '', 'text', ' required maxlength="80"') +
      salesInput('date', 'Credit note date', today, 'date') + salesAmount('amount', 'Taxable amount (₹)') +
      salesAmount('tax', 'GST amount (₹)', '', false) +
      salesSelect('tax_account_id', 'GST account (if GST applies)', salesOption('', 'Choose a GST account', null) + salesOptions(taxAccounts), false) +
      (vendor ? '' : salesSelect('income_account_id', 'Income account',
        salesOption('', 'Choose an income account', null) + salesOptions(company.income_accounts, company.accounts.income))) +
      salesInput('reason', 'Reason', '', 'text', ' required minlength="3" maxlength="300"');
  }
  return salesPanel(SALES_FORM_TITLES[type], `<form data-sales-form="${type}" data-key="${esc(key)}">
    <p class="muted" aria-live="polite" data-sales-project-company hidden></p>
    <div class="form-grid">${fields}</div>${items}<p class="muted" aria-live="polite" data-sales-total></p>
    <div class="notice fail" role="alert" data-sales-error hidden></div>
    <div class="row-actions"><button type="submit" class="btn btn-primary">Send for approval</button>
    ${salesButton('close', 'Cancel')}</div></form>`);
}

function salesDocumentTotals(lines, supplyType = '') {
  let subtotal = 0n, tax = 0n, cgst = 0n;
  for (const line of lines) {
    const base = BigInt(line.quantity) * BigInt(line.rate_paise);
    const lineTax = (base * BigInt(line.tax_rate_bps) + 5000n) / 10000n;
    subtotal += base;
    tax += lineTax;
    cgst += lineTax / 2n;
  }
  const raw = subtotal + tax;
  const total = supplyType ? (raw + 50n) / 100n * 100n : raw;
  if ([raw, total].some(value => value > BigInt(Number.MAX_SAFE_INTEGER))) throw new Error('The total is too large.');
  return {subtotal: Number(subtotal), tax: Number(tax), cgst: Number(cgst), sgst: Number(tax - cgst),
    total: Number(total), rounding: Number(total - raw)};
}

function salesReadLines(form) {
  return [...form.querySelectorAll('[data-sales-line]')].map(row => {
    const value = name => row.querySelector(`[name="${name}"]`).value.trim();
    const quantity = Number(value('quantity'));
    const rate = rupeesToPaise(value('rate'));
    const gst = Math.round(Number(value('gst')) * 100);
    if (!Number.isSafeInteger(quantity) || quantity < 1 || !Number.isSafeInteger(rate) || rate < 1 ||
        !Number.isInteger(gst) || gst < 0 || gst > 2800) throw new Error('Check the quantity, rate, and GST on each item.');
    return {description: value('description'), sac_hsn: value('sac_hsn'), quantity, rate_paise: rate, tax_rate_bps: gst};
  });
}

function salesReadAmount(data, name, allowZero = false) {
  const amount = rupeesToPaise(data.get(name));
  if (!Number.isSafeInteger(amount) || amount < (allowZero ? 0 : 1)) {
    throw new Error('Enter a valid amount in rupees.');
  }
  return amount;
}

function salesAvailable(invoice, advance, amount, tds = 0) {
  if (!invoice) throw new Error('Choose an unpaid invoice.');
  const available = Math.min(invoice.owed_paise, advance?.remaining_paise ?? invoice.owed_paise);
  if (amount + tds > available) throw new Error(`This exceeds the ${salesMoney(available)} available to apply.`);
  return invoice.owed_paise - amount - tds;
}

function salesPreview(form, book) {
  const output = form.querySelector('[data-sales-total]');
  const type = form.dataset.salesForm;
  const data = new FormData(form);
  try {
    if (['quote', 'revise', 'invoice'].includes(type)) {
      const site = data.get('site_state');
      const supply = site ? (site === salesFormCompany(book, form).state_code ? 'intra' : 'inter') : '';
      const totals = salesDocumentTotals(salesReadLines(form), supply);
      const taxes = supply === 'intra' ? `CGST ${salesMoney(totals.cgst)} + SGST ${salesMoney(totals.sgst)}` :
        `${supply === 'inter' ? 'IGST' : 'GST'} ${salesMoney(totals.tax)}`;
      output.textContent = `Subtotal ${salesMoney(totals.subtotal)} + ${taxes}${supply ? ` · Rounding ${salesMoney(totals.rounding)}` : ''} · Total ${salesMoney(totals.total)}`;
    } else if (type === 'receipt' || type === 'apply') {
      const invoice = book.statement?.invoices.find(row => row.id === Number(data.get('invoice_id')));
      const advance = type === 'apply' ? book.statement.advances.find(row => row.id === book.form.id) : null;
      const remaining = salesAvailable(invoice, advance, salesReadAmount(data, 'amount', true), salesReadAmount(data, 'tds', true));
      output.textContent = `Remaining after this payment ${salesMoney(remaining)}`;
    } else if (type === 'advance' || type === 'credit') {
      output.textContent = 'Total ' + salesMoney(salesReadAmount(data, 'amount', true) + salesReadAmount(data, 'tax', true));
    }
  } catch (error) {
    const anyRate = ['quote', 'revise', 'invoice'].includes(type) && [...form.querySelectorAll('input[name="rate"]')].some(el => el.value.trim());
    output.textContent = type === 'receipt' || type === 'apply' ? error.message : anyRate ? 'Check the amounts to see the total.' : 'Total ₹0.00';
  }
}

function syncSalesProject(form, book) {
  const projectField = form.elements.project_id;
  if (!projectField) return;
  const project = salesProject(book, projectField.value);
  const company = salesFormCompany(book, form);
  const note = form.querySelector('[data-sales-project-company]');
  note.hidden = !project;
  if (project) note.textContent = 'Company from the project: ' + company.name;
  const registerCompany = form.closest('[data-sales-screen]')?.querySelector('[name="sales_company"]');
  if (registerCompany) registerCompany.disabled = Boolean(project);
  const credit = form.dataset.salesForm === 'credit';
  const client = credit && !book.form.vendor ? form.elements.party_id : form.elements.client_id;
  if (client && !projectField.disabled) {
    if (project?.client_id) {
      if (!client.disabled) client.dataset.manualClient = client.value;
      client.value = String(project.client_id);
      client.disabled = true;
    } else if (client.disabled) {
      client.disabled = false;
      client.value = client.dataset.manualClient || '';
      delete client.dataset.manualClient;
    }
  }
  const refreshSelect = (field, choices, placeholder, fallback = null) => {
    if (!field) return;
    const previous = Number(field.value);
    const picked = choices.some(choice => choice.id === previous) ? previous : fallback;
    field.innerHTML = salesOption('', placeholder, picked) + salesOptions(choices, picked);
  };
  refreshSelect(form.elements.deposit_account_id, company.deposit_accounts, 'Choose a bank or cash account');
  refreshSelect(form.elements.tax_account_id, book.form.vendor ? company.input_tax_accounts : company.output_tax_accounts, 'Choose a GST account');
  refreshSelect(form.elements.income_account_id, company.income_accounts, 'Choose an income account', company.accounts.income);
}
function salesNeedAccount(id, label) {
  if (!id) throw new Error(`Ask Accounts to set up the ${label} account for this company.`);
  return id;
}

function salesDraft(form, book) {
  const type = form.dataset.salesForm;
  const company = salesFormCompany(book, form);
  const accounts = company.accounts;
  const data = new FormData(form);
  const value = name => String(data.get(name) ?? form.elements[name]?.value ?? '').trim();
  const id = name => Number(value(name)) || null;
  const date = value('date');
  const shared = {entity_id: company.id, client_id: id('client_id'), project_id: id('project_id')};
  const receivable = client => salesNeedAccount(company.client_accounts[client] || accounts.receivable, 'accounts receivable');
  const payable = vendor => salesNeedAccount(company.vendor_accounts[vendor] || accounts.payable, 'accounts payable');
  const key = form.dataset.key;
  if (type === 'accept') return [`quotes/${book.form.id}/accept`, {accepted_date: date, note: value('note'), request_key: key}];
  if (type === 'quote' || type === 'revise') return ['quotes', {...shared, quote_number: value('number'),
    quote_date: date, valid_until: value('until'), lines: salesReadLines(form), note: value('note'), request_key: key}];
  if (type === 'invoice') {
    const linkedQuote = book.quotes.find(row => row.id === book.form.id);
    if (linkedQuote) Object.assign(shared, {client_id: linkedQuote.client_id, project_id: linkedQuote.project_id});
    const site = value('site_state');
    const supply = site === company.state_code ? 'intra' : 'inter';
    const lines = salesReadLines(form).map(line => ({...line, income_account_id: salesNeedAccount(
      (line.sac_hsn.startsWith('9954') ? accounts.turnkey_income : line.sac_hsn === '998391' ? accounts.design_income : null) ||
      accounts.income, 'sales income')}));
    const total = salesDocumentTotals(lines, supply);
    return ['invoices', {...shared, quote_id: book.form.id, invoice_number: value('number'), invoice_date: date,
      due_date: value('until'), place_of_supply: `${SALES_STATES[site]} (${site})`.slice(0, 40), supply_type: supply,
      ar_account_id: receivable(shared.client_id),
      cgst_account_id: total.cgst && supply === 'intra' ? salesNeedAccount(accounts.cgst, 'output CGST') : null,
      sgst_account_id: total.sgst && supply === 'intra' ? salesNeedAccount(accounts.sgst, 'output SGST') : null,
      igst_account_id: total.tax && supply === 'inter' ? salesNeedAccount(accounts.igst, 'output IGST') : null,
      rounding_account_id: total.rounding ? salesNeedAccount(accounts.rounding, 'rounding') : null,
      lines, note: value('note'), request_key: key}];
  }
  const amount = salesReadAmount(data, 'amount');
  if (type === 'credit') {
    const tax = salesReadAmount(data, 'tax', true);
    const common = {entity_id: company.id, project_id: id('project_id'), note_number: value('number'), note_date: date,
      taxable_paise: amount, tax_paise: tax, tax_account_id: tax ? salesNeedAccount(id('tax_account_id'), 'GST') : null,
      reason: value('reason'), request_key: key};
    return book.form.vendor ? ['vendor-credits', {...common, supplier_id: id('party_id'),
      ap_account_id: payable(id('party_id')),
      expense_account_id: salesNeedAccount(accounts.expense, 'expense')}] :
      ['credit-notes', {...common, client_id: id('party_id'),
        ar_account_id: receivable(id('party_id')),
        income_account_id: salesNeedAccount(id('income_account_id') || accounts.income, 'sales income')}];
  }
  if (type === 'advance') return ['advances', {...shared, receipt_date: date, amount_paise: amount,
    deposit_account_id: id('deposit_account_id'), advance_account_id: salesNeedAccount(accounts.client_advance, 'client retainers'),
    reference: value('reference'), request_key: key}];
  const invoice = book.statement?.invoices.find(row => row.id === id('invoice_id'));
  if (type === 'apply') {
    const advance = book.statement.advances.find(row => row.id === book.form.id);
    salesAvailable(invoice, advance, amount);
    return ['advances/allocate', {advance_id: advance.id, invoice_id: invoice.id, amount_paise: amount,
      allocation_date: date, request_key: key}];
  }
  const tds = salesReadAmount(data, 'tds', true);
  salesAvailable(invoice, null, amount, tds);
  return ['receipts', {invoice_id: invoice.id, deposit_account_id: id('deposit_account_id'), amount_paise: amount, tds_paise: tds,
    tds_account_id: tds ? salesNeedAccount(accounts.tds_receivable, 'TDS receivable') : null,
    receipt_date: date, reference: value('reference'), request_key: key}];
}

const salesPreviousRender = render;
render = function () {
  const label = SALES_VIEWS[state.view];
  if (!label || state.mustSetup2fa) return salesPreviousRender();
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = salesView(state.view);
  $('breadcrumb').textContent = label;
};

const salesPreviousSwitchView = switchView;
switchView = function (view) {
  if (SALES_VIEWS[state.view] && view !== state.view && state.sales) {
    Object.assign(state.sales, {loaded: false, request: null, form: null, error: null, statement: null});
  }
  return salesPreviousSwitchView(view);
};
const salesPreviousRefresh = refresh;
refresh = async function () {
  if (state.sales) Object.assign(state.sales, {options: null, loaded: false, request: null, error: null});
  return salesPreviousRefresh();
};

document.addEventListener('click', event => {
  const button = event.target.closest('[data-sales-action]');
  if (!button || !SALES_VIEWS[state.view] || !hasFinance()) return;
  const action = button.dataset.salesAction;
  const book = salesBook();
  const form = button.closest('[data-sales-form]');
  if (action === 'add-line' || action === 'remove-line') {
    const box = form.querySelector('[data-sales-lines]');
    if (action === 'add-line' && box.children.length < 100) {
      box.insertAdjacentHTML('beforeend', salesLine());
      box.lastElementChild.querySelector('input').focus();
    } else if (action === 'remove-line' && box.children.length > 1) {
      button.closest('[data-sales-line]').remove();
      form.querySelector('[data-sales-action="add-line"]').focus();
    }
    salesPreview(form, book);
    return;
  }
  if (action === 'retry') {
    Object.assign(book, {error: null, loaded: false});
  } else if (action === 'quotes' || action === 'invoices') {
    book.tab = action;
    book.form = null;
  } else if (action === 'close') {
    book.form = null;
  } else {
    book.form = {type: action === 'convert' ? 'invoice' : action, id: Number(button.dataset.id) || null, key: formRequestKey()};
  }
  render();
  const opened = document.querySelector('[data-sales-form]');
  if (opened) {
    syncSalesProject(opened, book);
    opened.querySelector('input, select')?.focus();
    salesPreview(opened, book);
  }
});

document.addEventListener('change', async event => {
  if (!SALES_VIEWS[state.view] || !hasFinance() || !event.target.closest('[data-sales-screen]')) return;
  const book = salesBook();
  const field = event.target;
  const form = field.closest('[data-sales-form]');
  if (field.name === 'project_id' && form) {
    syncSalesProject(form, book);
    salesPreview(form, book);
  } else if (field.name === 'sales_company' || field.name === 'statement_client') {
    book[field.name === 'sales_company' ? 'companyId' : 'clientId'] = Number(field.value) || null;
    Object.assign(book, {statement: null, form: null, loaded: false, request: null, error: null});
    render();
  } else if (field.name === 'credit_kind' && form) {
    book.form.vendor = field.value === 'vendor';
    render();
    document.querySelector('[name="credit_kind"]')?.focus();
  } else if (field.name === 'client_id' && form?.dataset.salesForm === 'receipt') {
    const clientId = Number(field.value) || null;
    book.clientId = clientId;
    book.statement = null;
    const picker = form.querySelector('[data-sales-invoice-picker]');
    picker.textContent = clientId ? 'Loading invoices…' : 'Choose a client to see unpaid invoices.';
    if (!clientId) return;
    const active = () => salesCurrent(book, 'receipts') && book.clientId === clientId && form.isConnected;
    try {
      const statement = await api(`/api/sales/clients/${clientId}/statement?entity_id=${book.companyId}`);
      if (!active()) return;
      book.statement = statement;
      const rows = statement.invoices.filter(row => row.owed_paise > 0);
      picker.innerHTML = rows.length ? salesSelect('invoice_id', 'Unpaid invoice',
        salesOption('', 'Choose an invoice', null) + rows.map(row => salesOption(row.id,
          `${row.invoice_number} · ${salesMoney(row.owed_paise)} due`, null)).join('')) : '<p>No unpaid invoices for this client.</p>';
    } catch (error) {
      if (active()) picker.textContent = error.message;
    }
  }
});

document.addEventListener('input', event => {
  const form = event.target.closest('[data-sales-form]');
  if (form && SALES_VIEWS[state.view] && hasFinance()) salesPreview(form, salesBook());
});

document.addEventListener('submit', async event => {
  const form = event.target.closest('[data-sales-form]');
  if (!form || !SALES_VIEWS[state.view] || !hasFinance()) return;
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  if (submit.disabled) return;
  const errorBox = form.querySelector('[data-sales-error]');
  const book = salesBook();
  const view = state.view;
  const active = () => salesCurrent(book, view) && form.isConnected;
  submit.disabled = true;
  errorBox.hidden = true;
  try {
    const [endpoint, data] = salesDraft(form, book);
    const result = await api('/api/sales/' + endpoint, {method: 'POST', body: JSON.stringify(data)});
    if (!active()) return;
    book.form = null;
    book.loaded = false;
    notify(`${SALES_MESSAGES[form.dataset.salesForm]} draft #${result.ticket_id} sent for approval.`);
    render();
    refresh();
  } catch (error) {
    if (!active()) return;
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submit.disabled = false;
  }
});
