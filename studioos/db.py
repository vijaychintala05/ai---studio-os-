"""Portable SQL schema: PostgreSQL in deployment, SQLite for an instant local demo."""
from __future__ import annotations
import os
import re
import weakref
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.dialects.postgresql import JSONB
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Integer, BigInteger, ForeignKey, Text, Boolean, DateTime, JSON, event, CheckConstraint, UniqueConstraint, Index
from sqlalchemy import text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session


def now():
    from .runtime_clock import utc_now
    return utc_now()

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/studioos.db")
if DB_URL.startswith("sqlite:///./"):
    Path(DB_URL.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}, pool_pre_ping=True)
if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_fk(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

class Base(DeclarativeBase): pass

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    client: Mapped[str] = mapped_column(String(200), default="")
    stage: Mapped[str] = mapped_column(String(100), default="Planning")
    budget_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    client_phone: Mapped[str] = mapped_column(String(10),default='')
    location: Mapped[str] = mapped_column(String(200),default='')
    start_date: Mapped[str] = mapped_column(String(30),default='')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(400))
    assignee: Mapped[str] = mapped_column(String(150), default="")
    due_date: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)

class Cost(Base):
    __tablename__ = "costs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20)) # 'expense' incurred cost or 'commitment' PO not yet invoiced
    title: Mapped[str] = mapped_column(String(400))
    vendor: Mapped[str] = mapped_column(String(200), default="")
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    vendor_phone: Mapped[str] = mapped_column(String(10),default='')
    payment_mode: Mapped[str] = mapped_column(String(25), default='')
    expense_date: Mapped[str] = mapped_column(String(30), default='')
    gst_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category: Mapped[str] = mapped_column(String(120),default='')
    # v0.9.4 (review C2): who entered it, so nobody but the Admin approves their own money entry.
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    cost_id: Mapped[int] = mapped_column(ForeignKey("costs.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    idempotency_key: Mapped[str | None] = mapped_column(String(100),unique=True,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    # v0.9.4 (review C2, H2)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    payment_mode: Mapped[str] = mapped_column(String(25), default='')
    paid_date: Mapped[str] = mapped_column(String(30), default='')

class SiteReport(Base):
    __tablename__ = "site_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    report_date: Mapped[str] = mapped_column(String(30), default='')   # v0.9.4 (review H2): the date the person gave

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    relative_path: Mapped[str] = mapped_column(String(1500), unique=True)
    doc_type: Mapped[str] = mapped_column(String(32), default="file")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100), default="prototype_user")
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(700))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    chain_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # v0.9.0 tamper evidence

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String(70), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    pending: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Party(Base):
    """Business contacts separate from project/expense free-text fields."""
    __tablename__='parties'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True) # client or vendor
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(10), default='')
    gstin: Mapped[str] = mapped_column(String(15), default='')
    trade: Mapped[str] = mapped_column(String(120), default='')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class FlexibleRecord(Base):
    """Reference-only proposed business record; NOT posted to the accounting ledger."""
    __tablename__='flexible_records'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(60), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class Config(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    _legacy_value: Mapped[str] = mapped_column("value", String(500), default="")
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    @hybrid_property
    def value(self):
        return self.value_text if self.value_text is not None else self._legacy_value

    @value.setter
    def value(self, value):
        self.value_text = value
        if len(value) <= 500:
            self._legacy_value = value
        elif self._legacy_value is None:
            self._legacy_value = ""

    @value.expression
    def value(cls):
        return func.coalesce(cls.value_text, cls._legacy_value)

class SchemaSuggestion(Base):
    __tablename__ = "schema_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    idea: Mapped[str] = mapped_column(String(700))
    status: Mapped[str] = mapped_column(String(40), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def init_db():
    """v0.16.0: with STUDIOOS_DB_ROLE=app the app connects as a role that owns nothing and cannot
    change the schema. The owner runs the upgrades first (python -m studioos.migrate); the app only
    checks that the schema is the version it expects."""
    from .migrations import apply_migrations, LATEST_VERSION
    if os.getenv('STUDIOOS_DB_ROLE', 'owner').strip().lower() == 'app':
        from sqlalchemy import text as _text
        with engine.connect() as conn:
            try:
                version = int(conn.execute(_text('SELECT COALESCE(MAX(version),0) FROM schema_migrations')).scalar() or 0)
            except Exception:
                version = 0
        if version < LATEST_VERSION:
            raise RuntimeError(f'The database schema is v{version}; this version needs v{LATEST_VERSION}. '
                               'Run the upgrade step as the database owner (python -m studioos.migrate, '
                               'which ops/start.sh and ops/upgrade.sh do) before starting the app.')
        return
    apply_migrations(engine)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100),unique=True,index=True)
    display_name: Mapped[str] = mapped_column(String(150),default='')
    role: Mapped[str] = mapped_column(String(30),default='viewer')
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean,default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # v0.6.3 two-factor login (TOTP, RFC 6238). Secrets never leave the server
    # except once, at setup, to the account owner.
    totp_enabled: Mapped[bool] = mapped_column(Boolean,default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64),nullable=True)
    totp_pending_secret: Mapped[str | None] = mapped_column(String(64),nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger,nullable=True)
    recovery_code_hashes: Mapped[list | None] = mapped_column(JSON,nullable=True)

class ProjectMember(Base):
    """v0.6.3: which staff may see and work on which project. Admin, manager and
    accounts roles see every project; other roles see only projects listed here."""
    __tablename__ = 'project_members'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'),index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    added_by: Mapped[str] = mapped_column(String(100),default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','user_id',name='ux_project_member'),)

class LoginAttempt(Base):
    """v0.6.3: failed sign-ins, kept in the database so limits survive restarts."""
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    key_type: Mapped[str] = mapped_column(String(10),index=True)   # 'user' or 'ip'
    key: Mapped[str] = mapped_column(String(120),index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now,index=True)

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    # v0.6.2: last request time, for the idle timeout (STUDIOOS_IDLE_MINUTES).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True,default=now)

class FinancialAdjustment(Base):
    __tablename__ = 'financial_adjustments'
    id: Mapped[int] = mapped_column(primary_key=True)
    cost_id: Mapped[int] = mapped_column(ForeignKey('costs.id'),index=True)
    delta_paise: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class PaymentReversal(Base):
    __tablename__ = 'payment_reversals'
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payments.id'),unique=True)
    reason: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class ChatMessage(Base):
    """Lossless chat history; original input is never replaced by compaction."""
    __tablename__ = 'chat_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'),index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    speaker: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    chain_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # v0.9.0 tamper evidence

class ContextSummary(Base):
    """A derived digest, not the authoritative record."""
    __tablename__ = 'context_summaries'
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'),index=True)
    through_message_id: Mapped[int] = mapped_column(ForeignKey('chat_messages.id'))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class WriteJournal(Base):
    __tablename__ = 'write_journal'
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(180),default='system')
    original_chat_message_id: Mapped[int | None] = mapped_column(ForeignKey('chat_messages.id'),nullable=True,index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer,nullable=True)
    operation: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class SchemaMigration(Base):
    __tablename__ = 'schema_migrations'
    version: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ApprovalTicket(Base):
    """Exactly one review ticket per chat session. No business state is stored here."""
    __tablename__ = 'approval_tickets'
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'),unique=True,index=True)
    submitter_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    summary: Mapped[str] = mapped_column(Text,default='')
    status: Mapped[str] = mapped_column(String(24),default='draft')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    # v0.9.0: the conversation as it stood when the ticket was saved ends at this message.
    committed_through_message_id: Mapped[int | None] = mapped_column(Integer,nullable=True)

class ApprovalTicketItem(Base):
    __tablename__ = 'approval_ticket_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'),index=True)
    item_type: Mapped[str] = mapped_column(String(40))
    before_data: Mapped[dict | None] = mapped_column(JSON,nullable=True)
    after_data: Mapped[dict] = mapped_column(JSON)
    flags: Mapped[list] = mapped_column(JSON,default=list)
    field_evidence: Mapped[dict] = mapped_column(JSON,default=dict)
    status: Mapped[str] = mapped_column(String(24),default='pending')
    decided_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    review_note: Mapped[str] = mapped_column(Text,default='')
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey('chat_messages.id'),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class TicketRecordLink(Base):
    __tablename__ = 'ticket_record_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'),index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('approval_ticket_items.id'),index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('entity_type','entity_id',name='ux_ticket_record_entity'),)


class TicketRecordEvent(Base):
    """Repeatable provenance for creations, edits and reversals."""
    __tablename__='ticket_record_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'),index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey('approval_ticket_items.id'),nullable=True,index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class NewTypeInbox(Base):
    """Quarantined source evidence. Never treated as a business record or executed."""
    __tablename__ = 'new_type_inbox'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('chat_sessions.id'), index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey('approval_tickets.id'), nullable=True, index=True)
    source_message_id: Mapped[int] = mapped_column(ForeignKey('chat_messages.id'))
    raw_payload: Mapped[dict] = mapped_column(JSON_TYPE)  # source exact, immutable by API
    attachments: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    match_review: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    answers: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    questions: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    proposed_design: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default='parked')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class DataDictionaryEntry(Base):
    __tablename__ = 'data_dictionary_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_name: Mapped[str] = mapped_column(String(120), index=True)
    field_name: Mapped[str] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    design_id: Mapped[int | None] = mapped_column(ForeignKey('schema_designs.id'), nullable=True)
    __table_args__ = (UniqueConstraint('entity_name', 'field_name', name='ux_dictionary_entity_field'),)

class ConnectorToken(Base):
    """v0.9.3: a personal access key for an AI connector (Claude, ChatGPT) to reach
    StudioOS through the MCP endpoint, acting as that person with their access only.
    Only a fingerprint of the key is stored; the key itself is shown once."""
    __tablename__ = 'connector_tokens'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(20), default='read')        # read | read_draft
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class McpCall(Base):
    """v0.9.3: every connector request, for the Admin's review and for rate limits."""
    __tablename__ = 'mcp_calls'
    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int | None] = mapped_column(ForeignKey('connector_tokens.id'), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    method: Mapped[str] = mapped_column(String(60), default='')
    tool: Mapped[str] = mapped_column(String(60), default='')
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(String(300), default='')
    ip: Mapped[str] = mapped_column(String(120), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class RecordType(Base):
    """v0.9.0: a new kind of information, built from an Admin-approved design.
    Its records live in flexible_records (record_type = key) and are checked
    against the design on every save. No database structure is created."""
    __tablename__ = 'record_types'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    design: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(20), default='active')   # active | retired
    source_inbox_id: Mapped[int | None] = mapped_column(ForeignKey('new_type_inbox.id'), nullable=True)
    activated_by: Mapped[str] = mapped_column(String(100), default='')
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SchemaDesign(Base):
    """Stage A: approved DESIGN ONLY. Nothing here runs SQL migrations."""
    __tablename__ = 'schema_designs'
    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_id: Mapped[int] = mapped_column(ForeignKey('new_type_inbox.id'), unique=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    item_id: Mapped[int] = mapped_column(ForeignKey('approval_ticket_items.id'))
    design: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(32), default='approved_design_only')
    approved_by_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

# ---- v0.9.8 universal runtime engine (one engine migration, no per-type DDL) ----
class UniversalRelationshipType(Base):
    __tablename__ = 'universal_relationship_types'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    # v0.11.0: a record type key, or 'system.task' / 'system.user' (links that start at a task or a
    # staff member), so this is no longer a foreign key to record_types; the engine checks it.
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)  # record key, system.project, system.supplier
    inverse_label: Mapped[str] = mapped_column(String(120), default='')
    cardinality: Mapped[str] = mapped_column(String(10), default='many')  # one / many targets per source
    status: Mapped[str] = mapped_column(String(20), default='active')
    definition: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

# v0.10.0: exactly one kind of target per link; a system target names its kind and id together.
EDGE_TARGET_CHECK=('(CASE WHEN target_record_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_project_id IS NULL THEN 0 ELSE 1 END'
    ' + CASE WHEN target_party_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_system_id IS NULL THEN 0 ELSE 1 END) = 1'
    ' AND ((target_system IS NULL) = (target_system_id IS NULL))')

EDGE_SOURCE_CHECK=('(CASE WHEN source_id IS NULL THEN 0 ELSE 1 END + CASE WHEN source_system_id IS NULL THEN 0 ELSE 1 END) = 1'
    ' AND ((source_system IS NULL) = (source_system_id IS NULL))')

class UniversalEdge(Base):
    __tablename__ = 'universal_edges'
    id: Mapped[int] = mapped_column(primary_key=True)
    relation_key: Mapped[str] = mapped_column(ForeignKey('universal_relationship_types.key'))
    source_id: Mapped[int | None] = mapped_column(ForeignKey('flexible_records.id'), nullable=True)
    # v0.11.0: a link may start at a task or a staff member ('task' | 'user' + its id) instead of a record.
    source_system: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_system_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_record_id: Mapped[int | None] = mapped_column(ForeignKey('flexible_records.id'), nullable=True)
    target_project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True)
    target_party_id: Mapped[int | None] = mapped_column(ForeignKey('parties.id'), nullable=True)
    # v0.10.0: staff, tasks and files as link targets ('user' | 'task' | 'document' + its id).
    target_system: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_system_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # v0.10.0: a link is removed by an approved ticket and kept for history, never deleted.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_ticket_id: Mapped[int | None] = mapped_column(ForeignKey('approval_tickets.id'), nullable=True)
    __table_args__ = (CheckConstraint(EDGE_TARGET_CHECK,name='ck_universal_edge_target'),
                      CheckConstraint(EDGE_SOURCE_CHECK,name='ck_universal_edge_source'),
                      UniqueConstraint('relation_key','source_id','target_record_id','target_project_id','target_party_id',name='ux_universal_edge'),)

Index('ux_edge_rec',UniversalEdge.relation_key,UniversalEdge.source_id,UniversalEdge.target_record_id,
      unique=True,sqlite_where=UniversalEdge.target_record_id.is_not(None),
      postgresql_where=UniversalEdge.target_record_id.is_not(None))
Index('ux_edge_project',UniversalEdge.relation_key,UniversalEdge.source_id,UniversalEdge.target_project_id,
      unique=True,sqlite_where=UniversalEdge.target_project_id.is_not(None),
      postgresql_where=UniversalEdge.target_project_id.is_not(None))
Index('ux_edge_party',UniversalEdge.relation_key,UniversalEdge.source_id,UniversalEdge.target_party_id,
      unique=True,sqlite_where=UniversalEdge.target_party_id.is_not(None),
      postgresql_where=UniversalEdge.target_party_id.is_not(None))
Index('ux_edge_system',UniversalEdge.relation_key,UniversalEdge.source_id,UniversalEdge.target_system,UniversalEdge.target_system_id,
      unique=True,sqlite_where=UniversalEdge.target_system_id.is_not(None),
      postgresql_where=UniversalEdge.target_system_id.is_not(None))

# v0.11.0: uniqueness for links that start at a task or a staff member (one index per target kind).
for _name,_col in (('rec',UniversalEdge.target_record_id),('project',UniversalEdge.target_project_id),
                   ('party',UniversalEdge.target_party_id)):
    Index(f'ux_edge_ssrc_{_name}',UniversalEdge.relation_key,UniversalEdge.source_system,UniversalEdge.source_system_id,_col,
          unique=True,sqlite_where=(UniversalEdge.source_system_id.is_not(None)&_col.is_not(None)),
          postgresql_where=(UniversalEdge.source_system_id.is_not(None)&_col.is_not(None)))
Index('ux_edge_ssrc_system',UniversalEdge.relation_key,UniversalEdge.source_system,UniversalEdge.source_system_id,
      UniversalEdge.target_system,UniversalEdge.target_system_id,unique=True,
      sqlite_where=(UniversalEdge.source_system_id.is_not(None)&UniversalEdge.target_system_id.is_not(None)),
      postgresql_where=(UniversalEdge.source_system_id.is_not(None)&UniversalEdge.target_system_id.is_not(None)))

class UniversalMetadataVersion(Base):
    __tablename__ = 'universal_metadata_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    type_key: Mapped[str] = mapped_column(ForeignKey('record_types.key'))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('type_key','version',name='ux_universal_type_version'),)

class UniversalRecordRevision(Base):
    __tablename__ = 'universal_record_revisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey('flexible_records.id'))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_data: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    after_data: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('record_id','version',name='ux_universal_record_version'),)

# Protected deterministic INR ledger: all money stored as integer paise.
class AccountingEntity(Base):
    __tablename__ = 'accounting_entities'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True)
    base_currency: Mapped[str] = mapped_column(String(3), default='INR')
    created_ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))

class GLAccount(Base):
    __tablename__ = 'gl_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(24))  # bank, expense, payable
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    posting_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__=(UniqueConstraint('entity_id','code',name='ux_gl_code_entity'),)

class AccountingPolicy(Base):
    __tablename__ = 'accounting_policies'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'), unique=True)
    expense_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    payable_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    approval_ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))

class RegisteredBank(Base):
    __tablename__ = 'registered_banks'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    display_name: Mapped[str] = mapped_column(String(150))
    masked_identifier: Mapped[str] = mapped_column(String(40), default='')
    gl_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'), unique=True)
    __table_args__=(UniqueConstraint('entity_id','display_name',name='ux_bank_name_entity'),)

class FinancePurchaseOrder(Base):
    __tablename__ = 'finance_purchase_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    supplier_id: Mapped[int] = mapped_column(ForeignKey('parties.id'))
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    po_number: Mapped[str] = mapped_column(String(120))
    amount_paise: Mapped[int] = mapped_column(BigInteger, CheckConstraint('amount_paise > 0', name='ck_po_positive'))
    status: Mapped[str] = mapped_column(String(20), default='approved')
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('entity_id','po_number',name='ux_po_number_entity'),)

class FinanceSupplierBill(Base):
    __tablename__ = 'finance_supplier_bills'
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey('finance_purchase_orders.id'))
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    supplier_id: Mapped[int] = mapped_column(ForeignKey('parties.id'))
    invoice_number: Mapped[str] = mapped_column(String(120))
    amount_paise: Mapped[int] = mapped_column(BigInteger, CheckConstraint('amount_paise > 0', name='ck_bill_positive'))
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'), nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('entity_id','supplier_id','invoice_number',name='ux_bill_supplier_invoice'),)

class FinanceSupplierPayment(Base):
    __tablename__ = 'finance_supplier_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey('finance_supplier_bills.id'))
    bank_id: Mapped[int] = mapped_column(ForeignKey('registered_banks.id'))
    amount_paise: Mapped[int] = mapped_column(BigInteger, CheckConstraint('amount_paise > 0',name='ck_supplier_payment_positive'))
    payment_reference: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'), nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    bank_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__=(UniqueConstraint('bank_id','payment_reference',name='ux_bank_payment_reference'),)

class GLJournal(Base):
    __tablename__ = 'gl_journals'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    source_event: Mapped[str] = mapped_column(String(45))
    event_key: Mapped[str] = mapped_column(String(220), unique=True)
    source_id: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(20), default='posted')

class GLLine(Base):
    __tablename__ = 'gl_lines'
    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('gl_journals.id'))
    account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    side: Mapped[str] = mapped_column(String(6), CheckConstraint("side IN ('debit','credit')",name='ck_gl_side'))
    amount_paise: Mapped[int] = mapped_column(BigInteger, CheckConstraint('amount_paise > 0',name='ck_gl_line_positive'))
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey('parties.id'), nullable=True)

class ClosedAccountingPeriod(Base):
    __tablename__ = 'closed_accounting_periods'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    year_month: Mapped[str] = mapped_column(String(7))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('entity_id','year_month',name='ux_closed_entity_month'),)

# v0.9.9: bounded runtime views and approved notification-only workflow rules.
# No user-defined Python, SQL, JS, shell, HTTP actions or accounting events.
class UniversalSavedView(Base):
    __tablename__ = 'universal_saved_views'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    type_key: Mapped[str] = mapped_column(ForeignKey('record_types.key'))
    title: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

# v0.9.11: one-time engine metadata tables; no new tables for quotations,
# reports, formulas or new business vocabularies thereafter.
class UniversalCalculation(Base):
    __tablename__ = 'universal_calculations'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    type_key: Mapped[str] = mapped_column(ForeignKey('record_types.key'), index=True)
    title: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class UniversalDocumentTemplate(Base):
    __tablename__ = 'universal_document_templates'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    type_key: Mapped[str] = mapped_column(ForeignKey('record_types.key'), index=True)
    title: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

# v0.9.12: append-only definition history and issued/withdrawn document events.
# Ordinary new document types/templates remain approved metadata, not new SQL tables.
class UniversalDocumentDefinitionRevision(Base):
    __tablename__ = 'universal_document_definition_revisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(ForeignKey('universal_document_templates.key'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('template_key','version',name='ux_document_definition_version'),
                      CheckConstraint('version >= 2',name='ck_document_definition_revision'))

class UniversalDocumentIssue(Base):
    """Frozen revision events. Previous snapshots are never modified or deleted."""
    __tablename__ = 'universal_document_issues'
    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(ForeignKey('universal_document_templates.key'),index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'),index=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))  # issued or withdrawn
    snapshot: Mapped[dict] = mapped_column(JSON_TYPE)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    source_digest: Mapped[str] = mapped_column(String(64))
    previous_event_id: Mapped[int | None] = mapped_column(ForeignKey('universal_document_issues.id'),nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('template_key','project_id','revision',name='ux_document_issue_revision'),
                      CheckConstraint('revision > 0',name='ck_document_issue_revision'),
                      CheckConstraint("state IN ('issued','withdrawn')",name='ck_document_issue_state'))

class UniversalWorkflow(Base):
    __tablename__ = 'universal_workflows'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    type_key: Mapped[str] = mapped_column(ForeignKey('record_types.key'))
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class UniversalWorkflowNotice(Base):
    __tablename__ = 'universal_workflow_notices'
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_key: Mapped[str] = mapped_column(ForeignKey('universal_workflows.key'))
    record_id: Mapped[int] = mapped_column(ForeignKey('flexible_records.id'))
    record_version: Mapped[int] = mapped_column(Integer)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    message: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    # v0.10.0: a rule may address its notice to the staff member a record names.
    for_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    __table_args__=(UniqueConstraint('workflow_key','record_id','record_version',name='ux_workflow_notice_once'),)


class UniversalReport(Base):
    """v0.10.0: an approved report definition (base type, filters, groups, measures). Data, never SQL."""
    __tablename__ = 'universal_reports'
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    base: Mapped[str] = mapped_column(String(60))
    definition: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    pack_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UniversalPackInstall(Base):
    """v0.10.0: append-only record of a business pack installed by an approved Admin ticket."""
    __tablename__ = 'universal_pack_installs'
    id: Mapped[int] = mapped_column(primary_key=True)
    pack_key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    contents: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    actor: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('pack_key','version',name='ux_pack_install_once'),)

# ---- v0.11.0 AI reader: call log, corrections, approved aliases (schema v22) ----
class AiCallLog(Base):
    """Append-only: one row per model call attempt (or refusal). Never holds prompts, replies or keys."""
    __tablename__ = 'ai_call_log'
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    purpose: Mapped[str] = mapped_column(String(40), default='reader')
    provider: Mapped[str] = mapped_column(String(30), default='')
    model: Mapped[str] = mapped_column(String(100), default='')
    prompt_bytes: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)       # estimated
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)  # estimated, rounded up
    outcome: Mapped[str] = mapped_column(String(30), default='')        # ok | invalid | error | blocked_cap | off | no_price
    masked: Mapped[bool] = mapped_column(Boolean, default=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

class AiCorrection(Base):
    """Append-only: what the reader proposed for one detail and what the person chose instead."""
    __tablename__ = 'ai_corrections'
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type_key: Mapped[str] = mapped_column(String(60), default='')
    field_name: Mapped[str] = mapped_column(String(60), default='')
    field_type: Mapped[str] = mapped_column(String(20), default='')
    target: Mapped[str] = mapped_column(String(60), default='')
    source_text: Mapped[str] = mapped_column(Text, default='')
    proposed: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    chosen: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    ticket_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

class NameAlias(Base):
    """Append-only: an Admin-approved other name ("Ravi bhai" -> a staff member, "Tower" -> a project)."""
    __tablename__ = 'name_aliases'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))           # staff | project | client | supplier | option
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type_key: Mapped[str] = mapped_column(String(60), default='')
    field_name: Mapped[str] = mapped_column(String(60), default='')
    option: Mapped[str] = mapped_column(String(70), default='')
    alias: Mapped[str] = mapped_column(String(80))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('kind','type_key','field_name','alias',name='ux_name_alias'),)

# ---- v0.12.0 saved dashboards and per-type layouts (schema v23) ----
class UniversalViewDefinition(Base):
    """Append-only: every approved version of a dashboard or a per-type layout. The newest version
    of a (kind, key) is the one in use; older ones stay as history."""
    __tablename__ = 'universal_view_definitions'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))            # dashboard | layout
    key: Mapped[str] = mapped_column(String(60))             # dashboard key, or the type key for a layout
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('kind','key','version',name='ux_view_definition_version'),)

# ---- v0.13.0 safe restructuring (schema v24) ----
class UniversalTypeChange(Base):
    """Append-only: one approved type change (or its undo) with every object exactly as it was
    before and after, so the undo can put back the same bytes."""
    __tablename__ = 'universal_type_changes'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    type_key: Mapped[str] = mapped_column(String(60), index=True)
    op: Mapped[str] = mapped_column(String(30))
    change: Mapped[dict] = mapped_column(JSON_TYPE)
    # text, not JSONB: PostgreSQL's JSONB reorders keys, and the undo must write back the same bytes
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)
    impact: Mapped[dict] = mapped_column(JSON_TYPE)
    undo_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

# ---- v0.14.0 intake (schema v25) ----
class IntakeItem(Base):
    """One thing that arrived (a file, a WhatsApp or e-mail message, a voice note). The original file
    is kept read-only on disk under its fingerprint; only the status and the draft link change."""
    __tablename__ = 'intake_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))                 # upload | whatsapp | email | voice
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)   # message id: the same message once
    sender: Mapped[str] = mapped_column(String(300), default='')
    sender_kind: Mapped[str] = mapped_column(String(20), default='')   # staff | client | supplier | '' (unknown)
    sender_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='new', index=True)
    filename: Mapped[str] = mapped_column(String(200), default='')
    media_type: Mapped[str] = mapped_column(String(100), default='')
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default='')
    stored_path: Mapped[str] = mapped_column(String(500), default='')
    scan: Mapped[str] = mapped_column(String(20), default='')
    text: Mapped[str] = mapped_column(Text, default='')
    unsure_words: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    engine: Mapped[str] = mapped_column(String(30), default='')
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey('approval_tickets.id'), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class IntakeImport(Base):
    """Append-only: the fingerprints of rows an approved import created (a re-import skips them)."""
    __tablename__ = 'intake_imports'
    id: Mapped[int] = mapped_column(primary_key=True)
    intake_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type_key: Mapped[str] = mapped_column(String(60), index=True)
    row_keys: Mapped[list] = mapped_column(JSON_TYPE)
    record_ids: Mapped[list] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

# ---- v0.15.0 self-improvement (schema v26) ----
class ImproveSuggestion(Base):
    """A weekly suggestion with its evidence. Only status changes (open -> proposed / dismissed);
    a dismissed fingerprint is never suggested again."""
    __tablename__ = 'improve_suggestions'
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    evidence: Mapped[dict] = mapped_column(JSON_TYPE)
    proposal: Mapped[dict] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    week: Mapped[str] = mapped_column(String(10))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey('approval_tickets.id'), nullable=True)
    decided_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AskedQuestion(Base):
    """Append-only: a question someone asked and the report definition it became (for "asked often")."""
    __tablename__ = 'asked_questions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(String(300))
    report: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class JobRun(Base):
    """Append-only: every scheduled job run, for the self-check."""
    __tablename__ = 'job_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default='ok')
    detail: Mapped[str] = mapped_column(String(500), default='')

class SummaryDelivery(Base):
    """Append-only: one summary prepared for one person (the in-app copy and where else it went)."""
    __tablename__ = 'summary_deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    summary_key: Mapped[str] = mapped_column(String(60), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    period: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    channels: Mapped[dict] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__=(UniqueConstraint('summary_key','user_id','period',name='ux_summary_once'),)

class FinanceReversal(Base):
    """Append-only link between original and balanced corrective GL journals."""
    __tablename__ = 'finance_reversals'
    id: Mapped[int] = mapped_column(primary_key=True)
    original_journal_id: Mapped[int] = mapped_column(ForeignKey('gl_journals.id'),unique=True)
    reversal_journal_id: Mapped[int] = mapped_column(ForeignKey('gl_journals.id'),unique=True)
    reason: Mapped[str] = mapped_column(String(400))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

class FinanceAdvancePolicy(Base):
    __tablename__ = 'finance_advance_policies'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'),unique=True)
    advances_gl_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))

class FinanceSupplierAdvance(Base):
    __tablename__ = 'finance_supplier_advances'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    supplier_id: Mapped[int] = mapped_column(ForeignKey('parties.id'))
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    bank_id: Mapped[int] = mapped_column(ForeignKey('registered_banks.id'))
    amount_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('amount_paise > 0',name='ck_advance_positive'))
    payment_reference: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120),unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'),nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    bank_reconciled: Mapped[bool] = mapped_column(Boolean,default=False)
    __table_args__=(UniqueConstraint('bank_id','payment_reference',name='ux_advance_bank_ref'),)

class FinanceAdvanceAllocation(Base):
    __tablename__ = 'finance_advance_allocations'
    id: Mapped[int] = mapped_column(primary_key=True)
    advance_id: Mapped[int] = mapped_column(ForeignKey('finance_supplier_advances.id'))
    bill_id: Mapped[int] = mapped_column(ForeignKey('finance_supplier_bills.id'))
    amount_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('amount_paise > 0',name='ck_advance_allocation_positive'))
    idempotency_key: Mapped[str] = mapped_column(String(120),unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'),nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))

# v0.9.10: approved inventory/GRNI and independent bank-statement matching.
# Infrastructure is fixed and reusable; no SQL DDL occurs for a business material.
class FinanceInventoryPolicy(Base):
    __tablename__ = 'finance_inventory_policies'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'),unique=True)
    inventory_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    grni_account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))

class FinanceGoodsReceipt(Base):
    __tablename__ = 'finance_goods_receipts'
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey('finance_purchase_orders.id'),index=True)
    quantity: Mapped[int] = mapped_column(BigInteger,CheckConstraint('quantity > 0',name='ck_grn_quantity'))
    unit_cost_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('unit_cost_paise > 0',name='ck_grn_cost'))
    total_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('total_paise > 0',name='ck_grn_total'))
    receipt_reference: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120),unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'),nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('po_id','receipt_reference',name='ux_grn_ref_po'),)

class FinanceMaterialIssue(Base):
    __tablename__ = 'finance_material_issues'
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey('finance_purchase_orders.id'),index=True)
    quantity: Mapped[int] = mapped_column(BigInteger,CheckConstraint('quantity > 0',name='ck_issue_quantity'))
    amount_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('amount_paise > 0',name='ck_issue_amount'))
    issue_reference: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(120),unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'),nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('po_id','issue_reference',name='ux_issue_ref_po'),)

class FinanceBankStatementLine(Base):
    __tablename__ = 'finance_bank_statement_lines'
    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey('registered_banks.id'),index=True)
    # Positive bank statement amount means bank inflow; negative means outflow.
    signed_amount_paise: Mapped[int] = mapped_column(BigInteger,CheckConstraint('signed_amount_paise <> 0',name='ck_statement_nonzero'))
    booking_date: Mapped[str] = mapped_column(String(10))
    statement_reference: Mapped[str] = mapped_column(String(120))
    evidence_document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    __table_args__=(UniqueConstraint('bank_id','statement_reference',name='ux_stmt_bank_reference'),)

class FinanceBankReconciliation(Base):
    __tablename__ = 'finance_bank_reconciliations'
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_line_id: Mapped[int] = mapped_column(ForeignKey('finance_bank_statement_lines.id'),unique=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey('gl_journals.id'),unique=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)

# v0.9.14: chart of accounts in groups, approved posting recipes and text entries.
# Engine tables, created once: a new account, group or recipe is an approved ROW.
class GLAccountProfile(Base):
    """Where an account sits in the chart, and the words people use for it. Append-only:
    the newest row for an account is its current place, older rows are its history."""
    __tablename__ = 'gl_account_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey('gl_accounts.id'), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('gl_accounts.id'), nullable=True, index=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    nature: Mapped[str] = mapped_column(String(10), CheckConstraint("nature IN ('asset','liability','equity','income','expense')", name='ck_gl_profile_nature'))
    child_kind: Mapped[str] = mapped_column(String(24), default='')
    aliases: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    party_id: Mapped[int | None] = mapped_column(ForeignKey('parties.id'), nullable=True)
    standard_key: Mapped[str] = mapped_column(String(60), default='')
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FinanceStandardInstall(Base):
    __tablename__ = 'finance_standard_installs'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'))
    standard_key: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    definition_sha256: Mapped[str] = mapped_column(String(64))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('entity_id', 'standard_key', 'version', name='ux_standard_install_version'),)

class GLPostingRecipe(Base):
    """An approved mapping from a business event read from text to balanced journal lines.
    Validated as data (finance_text.check_standard); never executable code."""
    __tablename__ = 'gl_posting_recipes'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'), index=True)
    key: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    standard_key: Mapped[str] = mapped_column(String(60), default='')
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('entity_id', 'key', 'version', name='ux_posting_recipe_version'),)

class FinanceTextEntry(Base):
    """A business event typed as text, posted through an approved recipe.
    The journal is the accounting record; this row keeps what was said and decided."""
    __tablename__ = 'finance_text_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'), index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey('gl_posting_recipes.id'))
    slots: Mapped[dict] = mapped_column(JSON_TYPE)
    accounts: Mapped[dict] = mapped_column(JSON_TYPE)
    narration: Mapped[str] = mapped_column(String(300))
    total_paise: Mapped[int] = mapped_column(BigInteger, CheckConstraint('total_paise > 0', name='ck_text_entry_positive'))
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True, index=True)
    entry_date: Mapped[str] = mapped_column(String(10))
    reference: Mapped[str] = mapped_column(String(60), default='')
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    journal_id: Mapped[int | None] = mapped_column(ForeignKey('gl_journals.id'), nullable=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('approval_tickets.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

@event.listens_for(Session, 'before_flush')
def _protect_posted_journals(session, _context, _instances):
    # No service or generic API can ORM-edit/delete posted financial history.
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj,(GLJournal,GLLine,FinanceReversal,UniversalWorkflowNotice,FinanceAdvancePolicy,FinanceInventoryPolicy,FinanceBankStatementLine,FinanceBankReconciliation,GLAccountProfile,FinanceStandardInstall,GLPostingRecipe)):
            raise PermissionError('Posted journal history is immutable; use an approved reversing journal')
    for obj in list(session.deleted):
        if isinstance(obj,FinanceTextEntry):raise PermissionError('Text entries are never deleted; reverse the journal instead')
    for obj in list(session.dirty):
        if isinstance(obj,FinanceTextEntry) and session.is_modified(obj,include_collections=False):
            from sqlalchemy import inspect as _inspect
            changed={a.key for a in _inspect(obj).attrs if a.history.has_changes()}
            if changed-{'journal_id'} or any(x is not None for x in (_inspect(obj).attrs.journal_id.history.deleted or ())):
                raise PermissionError('A posted text entry cannot be changed; reverse it instead')

# Capture mutations of business tables in the SAME database transaction.
# Chat and auth/session updates are recorded separately. Failing the journal
# write rolls back the business mutation; no detached best-effort file logs.
_TRACKED = (Project, Task, Cost, Payment, SiteReport, Document, SchemaSuggestion, SchemaDesign,
            FinancialAdjustment, PaymentReversal, Party, FlexibleRecord, RecordType,
            UniversalRelationshipType, UniversalEdge, UniversalRecordRevision, UniversalMetadataVersion, AccountingEntity, GLAccount,
            AccountingPolicy, RegisteredBank, FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierPayment,
            GLJournal, GLLine, ClosedAccountingPeriod, FinanceReversal, UniversalSavedView, UniversalWorkflow, UniversalWorkflowNotice, UniversalCalculation, UniversalDocumentTemplate, UniversalDocumentDefinitionRevision, UniversalDocumentIssue, FinanceAdvancePolicy, FinanceSupplierAdvance, FinanceAdvanceAllocation, FinanceInventoryPolicy, FinanceGoodsReceipt, FinanceMaterialIssue, FinanceBankStatementLine, FinanceBankReconciliation,
            GLAccountProfile, FinanceStandardInstall, GLPostingRecipe, FinanceTextEntry, UniversalReport, UniversalPackInstall, NameAlias, UniversalViewDefinition, UniversalTypeChange, IntakeImport)

@event.listens_for(Session, 'before_flush')
def _prevent_unapproved_ai_business_writes(session, flush_context, instances):
    """Backend ORM gate: chat or AI sessions cannot mutate business rows.

    Even if an endpoint calls create_project() from an AI context, the flush is
    rejected unless an APPROVED ticket item is being committed. Manual forms
    use a different authenticated origin and remain operational.
    """
    origin=str(session.info.get('write_source',''))
    ai_origin=session.info.get('ai_origin') or origin.startswith(('chat','ai:'))
    if not ai_origin: return
    changed=[x for x in list(session.new)+list(session.dirty)+list(session.deleted)
             if isinstance(x,_TRACKED) and (x in session.new or x in session.deleted or session.is_modified(x,include_collections=False))]
    if not changed:return
    if not session.info.get('ticket_commit') or not session.info.get('ticket_item_id'):
        raise PermissionError('AI cannot mutate business records without an approved ticket item')
    item=session.get(ApprovalTicketItem,session.info['ticket_item_id'])
    if item is None or item.status!='approved' or item.ticket_id != session.info.get('ticket_id'):
        raise PermissionError('Ticket item approval missing or invalid')

_REPORT_INDEX_DDL=re.compile(
    r"\s*CREATE INDEX IF NOT EXISTS ix_fr_[0-9a-f]{20} ON flexible_records \((?:\(data ->> '[a-z][a-z0-9_]*'\)|json_extract\(data, '\$\.[a-z][a-z0-9_]*'\))\) WHERE record_type = '[a-z][a-z0-9_]*' AND deleted_at IS NULL\s*")

def _is_report_index_ddl(session,statement)->bool:
    """v0.15.2: the single backend-owned DDL shape (a report speed-up index), allowed only while the
    report-approval code holds the flag. Every other statement stays blocked by both SQL guards."""
    return session.info.get('report_index_ddl') is True and bool(_REPORT_INDEX_DDL.fullmatch(str(statement)))

@event.listens_for(Session, 'do_orm_execute')
def _guard_ai_sql_execution(orm_execute_state):
    """Also block session.execute() INSERT/UPDATE/DELETE bypassing ORM flush."""
    session=orm_execute_state.session
    origin=str(session.info.get('write_source',''))
    if not (session.info.get('ai_origin') or origin.startswith(('chat','ai:'))):return
    statement=orm_execute_state.statement
    # An approved ticket's ORMs use regular flush; no raw SQL writes are allowed.
    if orm_execute_state.is_insert or orm_execute_state.is_update or orm_execute_state.is_delete:
        raise PermissionError('AI session direct DML is forbidden; use approved ticket items')
    if isinstance(statement,TextClause) and not _is_report_index_ddl(session,statement) and re.search(r'\b(INSERT|UPDATE|DELETE|REPLACE|MERGE|CREATE|DROP|ALTER|TRUNCATE)\b',str(statement),re.I):
        raise PermissionError('AI session raw SQL writes and DDL are forbidden')

@event.listens_for(Session, 'after_begin')
def _bind_session_to_connection(session, transaction, connection):
    # Protect even Connection.exec_driver_sql() invoked from a Session transaction.
    connection.info['_studioos_active_session']=weakref.ref(session)

@event.listens_for(engine, 'before_cursor_execute')
def _block_ai_core_sql_writes(conn, cursor, statement, parameters, context, executemany):
    ref=conn.info.get('_studioos_active_session')
    session=ref() if ref else None
    if session is None or not session.in_transaction():return
    src=str(session.info.get('write_source',''))
    if not (session.info.get('ai_origin') or src.startswith(('ai:','chat'))):return
    ddl=re.match(r'^\s*(?:CREATE|DROP|ALTER|TRUNCATE)\b',statement,re.I)
    if ddl:
        # v0.15.1: the one exception is the report speed-up index, made by the approved-ticket code itself
        # (graph_query.ensure_report_indexes) from keys that passed the strict key check.
        if _is_report_index_ddl(session,statement):
            return
        raise PermissionError('AI context may not execute database DDL')
    change=re.match(r'^\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+["`]?([\w]+)',statement,re.I)
    tracked={'projects','tasks','costs','payments','site_reports','documents','schema_suggestions',
             'financial_adjustments','payment_reversals','parties','flexible_records','schema_designs','record_types',
             'universal_relationship_types','universal_edges','universal_record_revisions','universal_metadata_versions','universal_calculations','universal_document_templates','universal_document_definition_revisions','universal_document_issues','accounting_entities',
             'gl_accounts','accounting_policies','registered_banks','finance_purchase_orders',
             'finance_supplier_bills','finance_supplier_payments','gl_journals','gl_lines','closed_accounting_periods',
             'gl_account_profiles','finance_standard_installs','gl_posting_recipes','finance_text_entries','universal_reports','universal_pack_installs','name_aliases','universal_view_definitions','universal_type_changes','intake_imports'}
    if change and change.group(1).lower() in tracked:
        if not (session.info.get('ticket_commit') and session.info.get('ticket_item_id')):
            raise PermissionError('SQL-level gate: AI business write requires an approved ticket item')
        item=session.get(ApprovalTicketItem,session.info['ticket_item_id'])
        if not item or item.status!='approved' or item.ticket_id!=session.info.get('ticket_id'):
            raise PermissionError('SQL-level gate: unapproved ticket item')

@event.listens_for(Session, 'after_flush')
def _transactional_write_journal(session, flush_context):
    if session.info.get('_journal_in_progress'):
        return
    changes=[]
    for op,items in (('insert',session.new),('update',session.dirty),('delete',session.deleted)):
        for obj in list(items):
            if not isinstance(obj,_TRACKED): continue
            if op=='update' and not session.is_modified(obj,include_collections=False): continue
            changes.append((op,obj))
    if not changes:return
    session.info['_journal_in_progress']=True
    try:
        for op,obj in changes:
            session.add(WriteJournal(source=session.info.get('write_source','backend'),
                original_chat_message_id=session.info.get('source_message_id'),
                entity_type=obj.__class__.__name__.lower(),entity_id=getattr(obj,'id',None),operation=op))
    finally:
        session.info['_journal_in_progress']=False

def add_audit(db, action, entity_type, entity_id, description, actor='system'):
    db.add(Audit(actor=actor,action=action, entity_type=entity_type, entity_id=entity_id, description=description))


# ---- v0.9.0 tamper-evident chain on chat messages and audit entries ----------
from . import chain as _chain
_CHAINED_MODELS = {ChatMessage: 'chat_messages', Audit: 'audit_events'}

@event.listens_for(Session, 'before_flush')
def _chain_lock(session, flush_context, instances):
    """Serialize chained inserts on PostgreSQL so two writers never fork the chain."""
    if any(type(o) in _CHAINED_MODELS for o in session.new):
        conn = session.connection()
        if conn.dialect.name == 'postgresql':
            conn.exec_driver_sql('SELECT pg_advisory_xact_lock(46201905)')

@event.listens_for(Session, 'after_flush')
def _chain_collect(session, flush_context):
    # Only rows INSERTED by this flush are fingerprinted; older rows are never touched.
    new = [o for o in session.new if type(o) in _CHAINED_MODELS]
    if new:
        session.info.setdefault('_chain_new', []).extend(new)

@event.listens_for(Session, 'after_flush_postexec')
def _chain_hash(session, flush_context):
    pending = [o for o in session.info.pop('_chain_new', []) if o.chain_hash is None]
    if not pending:
        return
    conn = session.connection()
    for model, table in _CHAINED_MODELS.items():
        rows = sorted((o for o in pending if type(o) is model), key=lambda o: o.id)
        if not rows:
            continue
        previous = conn.execute(text(f'SELECT chain_hash FROM {table} WHERE id < :i AND chain_hash IS NOT NULL ORDER BY id DESC LIMIT 1'),
                                {'i': rows[0].id}).scalar()
        for o in rows:
            o.chain_hash = _chain.row_hash(table, previous, {k: getattr(o, k) for k in _chain.CHAINED[table]})
            previous = o.chain_hash

@event.listens_for(Session, 'before_flush')
def _chain_frozen(session, flush_context, instances):
    """A fingerprinted message or audit entry can never be edited afterwards."""
    from sqlalchemy import inspect as _inspect
    for o in session.dirty:
        table = _CHAINED_MODELS.get(type(o))
        if not table:
            continue
        state = _inspect(o)
        hashed = state.attrs.chain_hash.history
        was_hashed = (hashed.deleted and hashed.deleted[0]) or (not hashed.added and o.chain_hash)
        if not was_hashed:
            continue
        changed = [k for k in (*_chain.CHAINED[table], 'chain_hash') if state.attrs[k].history.has_changes()]
        if changed:
            raise PermissionError(f'{table} #{o.id} is part of the permanent record and cannot be changed ({", ".join(changed)})')

@event.listens_for(Session, 'before_flush')
def _chain_no_delete(session, flush_context, instances):
    for o in session.deleted:
        if type(o) in _CHAINED_MODELS:
            raise PermissionError('Conversation and audit history cannot be deleted')
