"""The posted ledger portion of the owner’s portable JSON export."""
from sqlalchemy import select

from .db import AccountingEntity, FinanceReversal, GLAccount, GLJournal, GLLine, Party


def posted_ledger(db):
    # Pull the journal, lines and link to the original journal from one snapshot.
    query = (select(GLJournal, GLLine, GLAccount, AccountingEntity, Party.name, FinanceReversal.original_journal_id)
             .select_from(GLJournal).join(AccountingEntity, AccountingEntity.id == GLJournal.entity_id)
             .outerjoin(GLLine, GLLine.journal_id == GLJournal.id)
             .outerjoin(GLAccount, GLAccount.id == GLLine.account_id)
             .outerjoin(Party, Party.id == GLLine.supplier_id)
             .outerjoin(FinanceReversal, FinanceReversal.reversal_journal_id == GLJournal.id)
             .where(GLJournal.status == 'posted').order_by(GLJournal.id, GLLine.id))
    companies, accounts, vendors, journals = {}, {}, {}, {}
    for journal, line, account, company, supplier_name, original_id in db.execute(query).yield_per(1000):
        companies[company.id] = {'id': company.id, 'name': company.name, 'currency': company.base_currency}
        if journal.id not in journals:
            journals[journal.id] = {
                'id': journal.id, 'entity_id': journal.entity_id, 'source_event': journal.source_event,
                'source_id': journal.source_id, 'ticket_id': journal.ticket_id, 'policy_version': journal.policy_version,
                'posted_at': journal.posted_at.isoformat(), 'reverses_journal_id': original_id, 'lines': [],
            }
        if account is not None:
            accounts[account.id] = {'id': account.id, 'entity_id': account.entity_id, 'code': account.code,
                                    'name': account.name, 'kind': account.kind}
        if line is not None:
            if supplier_name is not None:
                vendors[line.supplier_id] = {'id': line.supplier_id, 'name': supplier_name}
            journals[journal.id]['lines'].append({
                'id': line.id, 'account_id': line.account_id, 'side': line.side, 'amount_paise': line.amount_paise,
                'project_id': line.project_id, 'supplier_id': line.supplier_id,
            })
    return {'companies': list(companies.values()), 'accounts': list(accounts.values()),
            'vendors': list(vendors.values()), 'journals': list(journals.values())}
