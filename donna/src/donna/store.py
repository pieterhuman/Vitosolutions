"""The ledger: schema and repository.

Invariants enforced here, not in callers:
- ItemEvent is APPEND-ONLY. This module exposes no update/delete for it,
  and a SQLAlchemy listener rejects any UPDATE/DELETE statement that
  targets the table. Production Postgres adds a trigger on top
  (infra/sql/001_item_event_append_only.sql).
- Every OpenItem state change writes an ItemEvent in the same transaction.
- OpenItem is unique on (principal_id, kind, internet_message_id), which
  is what makes a full delta resync after 410 Gone idempotent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import event

from . import states
from .telemetry import get_logger

log = get_logger(__name__)

metadata = sa.MetaData()

principal = sa.Table(
    "principal", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("upn", sa.String(320), nullable=False, unique=True),
    sa.Column("display_name", sa.String(200), nullable=False),
    sa.Column("is_ceo", sa.Boolean, nullable=False, default=False),
    sa.Column("active", sa.Boolean, nullable=False, default=True),
)

delta_cursor = sa.Table(
    "delta_cursor", metadata,
    sa.Column("principal_id", sa.Integer, sa.ForeignKey("principal.id"),
              primary_key=True),
    sa.Column("folder_kind", sa.String(16), primary_key=True),  # inbox|sentitems
    sa.Column("delta_link", sa.Text, nullable=False),
    sa.Column("updated_utc", sa.DateTime(timezone=True), nullable=False),
)

open_item = sa.Table(
    "open_item", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("principal_id", sa.Integer, sa.ForeignKey("principal.id"),
              nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("conversation_id", sa.String(256), nullable=False),
    sa.Column("internet_message_id", sa.String(512), nullable=False),
    sa.Column("subject", sa.Text, nullable=False, default=""),
    sa.Column("counterparty_smtp", sa.String(320), nullable=False),
    sa.Column("counterparty_name", sa.String(200), nullable=False, default=""),
    sa.Column("anchor_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("threshold_hours", sa.Integer, nullable=False),
    sa.Column("state", sa.String(24), nullable=False, default=states.OPEN),
    sa.Column("state_reason", sa.String(200), nullable=False, default=""),
    sa.Column("closed_by_upn", sa.String(320), nullable=True),
    sa.Column("closed_utc", sa.DateTime(timezone=True), nullable=True),
    sa.Column("first_seen_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_eval_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("urgent_alerted_utc", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("principal_id", "kind", "internet_message_id",
                        name="uq_item_principal_kind_msgid"),
)

item_event = sa.Table(
    "item_event", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("item_id", sa.Integer, sa.ForeignKey("open_item.id"),
              nullable=False),
    sa.Column("from_state", sa.String(24), nullable=False),
    sa.Column("to_state", sa.String(24), nullable=False),
    sa.Column("evidence", sa.Text, nullable=False, default=""),
    sa.Column("actor_upn", sa.String(320), nullable=True),
    sa.Column("occurred_utc", sa.DateTime(timezone=True), nullable=False),
)

vip_contact = sa.Table(
    "vip_contact", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("smtp", sa.String(320), nullable=True),
    sa.Column("domain_pattern", sa.String(320), nullable=True),
    sa.Column("label", sa.String(120), nullable=False),
    sa.Column("threshold_hours", sa.Integer, nullable=False, default=3),
)

exclusion_rule = sa.Table(
    "exclusion_rule", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("kind", sa.String(24), nullable=False),
    # sender | domain | header | subject_regex
    sa.Column("pattern", sa.String(512), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False, default=True),
)

config = sa.Table(
    "config", metadata,
    sa.Column("key", sa.String(120), primary_key=True),
    sa.Column("value", sa.Text, nullable=False),
)

job_run = sa.Table(
    "job_run", metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("job_name", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # success|failure
    sa.Column("run_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("detail", sa.Text, nullable=False, default=""),
)


class AppendOnlyViolation(Exception):
    pass


@event.listens_for(sa.engine.Engine, "before_execute", retval=False)
def _guard_item_event(conn, clauseelement, multiparams, params,
                      execution_options):
    if isinstance(clauseelement, (sa.Update, sa.Delete)):
        table = getattr(clauseelement, "table", None)
        if table is not None and table.name == "item_event":
            raise AppendOnlyViolation(
                "item_event is append-only; UPDATE/DELETE is forbidden"
            )


CONFIG_DEFAULTS = {
    "threshold_inbound_hours": "24",
    "threshold_sent_awaiting_hours": "72",
    "vip_default_threshold_hours": "3",
    "quiet_hours_utc": "18:00-04:00",
    "teams_webhook_url": "",
    "service_mailbox_upn": "donna@familyoffice.example",
    "internal_domains": "familyoffice.example",
    "close_base_url": "https://localhost/api",
    "heartbeat_window_hours": "11",
    "digest_dry_run": "0",
    "dry_run_output_dir": "out",
}


@dataclass
class ItemRow:
    """Detached snapshot of an open_item row."""
    id: int
    principal_id: int
    kind: str
    conversation_id: str
    internet_message_id: str
    subject: str
    counterparty_smtp: str
    counterparty_name: str
    anchor_utc: datetime
    threshold_hours: int
    state: str
    state_reason: str
    closed_by_upn: str | None
    closed_utc: datetime | None
    first_seen_utc: datetime
    last_eval_utc: datetime
    urgent_alerted_utc: datetime | None


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; normalise reads back to aware UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_item(row) -> ItemRow:
    return ItemRow(
        id=row.id, principal_id=row.principal_id, kind=row.kind,
        conversation_id=row.conversation_id,
        internet_message_id=row.internet_message_id,
        subject=row.subject, counterparty_smtp=row.counterparty_smtp,
        counterparty_name=row.counterparty_name,
        anchor_utc=_utc(row.anchor_utc),
        threshold_hours=row.threshold_hours, state=row.state,
        state_reason=row.state_reason, closed_by_upn=row.closed_by_upn,
        closed_utc=_utc(row.closed_utc),
        first_seen_utc=_utc(row.first_seen_utc),
        last_eval_utc=_utc(row.last_eval_utc),
        urgent_alerted_utc=_utc(row.urgent_alerted_utc),
    )


class Store:
    def __init__(self, engine: sa.Engine):
        self.engine = engine

    @classmethod
    def from_url(cls, url: str) -> "Store":
        return cls(sa.create_engine(url, future=True))

    def ensure_schema(self) -> None:
        metadata.create_all(self.engine)

    # -- principals ------------------------------------------------------
    def add_principal(self, upn: str, display_name: str,
                      is_ceo: bool = False, active: bool = True) -> int:
        with self.engine.begin() as cx:
            return cx.execute(
                principal.insert().values(
                    upn=upn.casefold(), display_name=display_name,
                    is_ceo=is_ceo, active=active)
            ).inserted_primary_key[0]

    def active_principals(self) -> list[sa.Row]:
        with self.engine.begin() as cx:
            return list(cx.execute(
                sa.select(principal).where(principal.c.active == True)  # noqa: E712
                .order_by(principal.c.id)))

    def principal_by_id(self, pid: int) -> sa.Row | None:
        with self.engine.begin() as cx:
            return cx.execute(
                sa.select(principal).where(principal.c.id == pid)
            ).first()

    def principal_by_upn(self, upn: str) -> sa.Row | None:
        with self.engine.begin() as cx:
            return cx.execute(
                sa.select(principal).where(principal.c.upn == upn.casefold())
            ).first()

    def monitored_upns(self) -> set[str]:
        return {p.upn for p in self.active_principals()}

    # -- delta cursors ---------------------------------------------------
    def get_cursor(self, principal_id: int, folder_kind: str) -> str | None:
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(delta_cursor.c.delta_link).where(
                delta_cursor.c.principal_id == principal_id,
                delta_cursor.c.folder_kind == folder_kind)).first()
            return row.delta_link if row else None

    def set_cursor(self, principal_id: int, folder_kind: str,
                   delta_link: str, now: datetime) -> None:
        with self.engine.begin() as cx:
            updated = cx.execute(delta_cursor.update().where(
                delta_cursor.c.principal_id == principal_id,
                delta_cursor.c.folder_kind == folder_kind,
            ).values(delta_link=delta_link, updated_utc=now)).rowcount
            if not updated:
                cx.execute(delta_cursor.insert().values(
                    principal_id=principal_id, folder_kind=folder_kind,
                    delta_link=delta_link, updated_utc=now))

    def drop_cursor(self, principal_id: int, folder_kind: str) -> None:
        with self.engine.begin() as cx:
            cx.execute(delta_cursor.delete().where(
                delta_cursor.c.principal_id == principal_id,
                delta_cursor.c.folder_kind == folder_kind))

    # -- items -----------------------------------------------------------
    def create_item_if_new(self, *, principal_id: int, kind: str,
                           conversation_id: str, internet_message_id: str,
                           subject: str, counterparty_smtp: str,
                           counterparty_name: str, anchor_utc: datetime,
                           threshold_hours: int, now: datetime,
                           ) -> ItemRow | None:
        """Insert an item in state=open plus its creation ItemEvent, in one
        transaction. Returns None when the (principal, kind, msgid) already
        exists — that is the 410-resync dedupe path."""
        with self.engine.begin() as cx:
            dup = cx.execute(sa.select(open_item.c.id).where(
                open_item.c.principal_id == principal_id,
                open_item.c.kind == kind,
                open_item.c.internet_message_id == internet_message_id,
            )).first()
            if dup:
                return None
            item_id = cx.execute(open_item.insert().values(
                principal_id=principal_id, kind=kind,
                conversation_id=conversation_id,
                internet_message_id=internet_message_id,
                subject=subject, counterparty_smtp=counterparty_smtp,
                counterparty_name=counterparty_name, anchor_utc=anchor_utc,
                threshold_hours=threshold_hours, state=states.OPEN,
                state_reason="created", first_seen_utc=now,
                last_eval_utc=now,
            )).inserted_primary_key[0]
            cx.execute(item_event.insert().values(
                item_id=item_id, from_state="none", to_state=states.OPEN,
                evidence=f"msgid_hash={_hash(internet_message_id)}",
                actor_upn=None, occurred_utc=now))
            row = cx.execute(sa.select(open_item).where(
                open_item.c.id == item_id)).first()
            return _row_to_item(row)

    def get_item(self, item_id: int) -> ItemRow | None:
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(open_item).where(
                open_item.c.id == item_id)).first()
            return _row_to_item(row) if row else None

    def items(self, *, principal_id: int | None = None,
              kind: str | None = None,
              item_states: tuple[str, ...] | None = None,
              conversation_id: str | None = None) -> list[ItemRow]:
        stmt = sa.select(open_item)
        if principal_id is not None:
            stmt = stmt.where(open_item.c.principal_id == principal_id)
        if kind is not None:
            stmt = stmt.where(open_item.c.kind == kind)
        if item_states is not None:
            stmt = stmt.where(open_item.c.state.in_(item_states))
        if conversation_id is not None:
            stmt = stmt.where(open_item.c.conversation_id == conversation_id)
        stmt = stmt.order_by(open_item.c.anchor_utc)
        with self.engine.begin() as cx:
            return [_row_to_item(r) for r in cx.execute(stmt)]

    def transition(self, item_id: int, to_state: str, *, reason: str,
                   evidence: str, actor_upn: str | None,
                   now: datetime) -> ItemRow:
        """Move an item to a new state; ItemEvent written in the same
        transaction. Raises IllegalTransition on a disallowed move."""
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(open_item).where(
                open_item.c.id == item_id).with_for_update()).first()
            if row is None:
                raise KeyError(f"item {item_id} not found")
            states.check_transition(row.state, to_state)
            values: dict = {
                "state": to_state, "state_reason": reason,
                "last_eval_utc": now,
            }
            if to_state in (states.CLOSED_EVIDENCE, states.CLOSED_HUMAN,
                            states.CLOSED_EXCLUDED):
                values["closed_by_upn"] = actor_upn
                values["closed_utc"] = now
            cx.execute(open_item.update().where(
                open_item.c.id == item_id).values(**values))
            cx.execute(item_event.insert().values(
                item_id=item_id, from_state=row.state, to_state=to_state,
                evidence=evidence, actor_upn=actor_upn, occurred_utc=now))
            fresh = cx.execute(sa.select(open_item).where(
                open_item.c.id == item_id)).first()
            return _row_to_item(fresh)

    def touch_eval(self, item_id: int, now: datetime) -> None:
        with self.engine.begin() as cx:
            cx.execute(open_item.update().where(
                open_item.c.id == item_id).values(last_eval_utc=now))

    def mark_urgent_alerted(self, item_id: int, now: datetime) -> None:
        with self.engine.begin() as cx:
            cx.execute(open_item.update().where(
                open_item.c.id == item_id).values(urgent_alerted_utc=now))

    def events_for(self, item_id: int) -> list[sa.Row]:
        with self.engine.begin() as cx:
            return list(cx.execute(sa.select(item_event).where(
                item_event.c.item_id == item_id).order_by(item_event.c.id)))

    # -- vip / exclusions --------------------------------------------------
    def add_vip(self, *, smtp: str | None = None,
                domain_pattern: str | None = None, label: str,
                threshold_hours: int = 3) -> None:
        with self.engine.begin() as cx:
            cx.execute(vip_contact.insert().values(
                smtp=smtp.casefold() if smtp else None,
                domain_pattern=domain_pattern.casefold() if domain_pattern else None,
                label=label, threshold_hours=threshold_hours))

    def vips(self) -> list[sa.Row]:
        with self.engine.begin() as cx:
            return list(cx.execute(sa.select(vip_contact)))

    def vip_match(self, smtp: str) -> sa.Row | None:
        smtp = smtp.casefold()
        domain = smtp.rsplit("@", 1)[-1]
        for v in self.vips():
            if v.smtp and v.smtp == smtp:
                return v
            if v.domain_pattern and (domain == v.domain_pattern
                                     or domain.endswith("." + v.domain_pattern)):
                return v
        return None

    def add_exclusion(self, kind: str, pattern: str,
                      enabled: bool = True) -> None:
        with self.engine.begin() as cx:
            cx.execute(exclusion_rule.insert().values(
                kind=kind, pattern=pattern, enabled=enabled))

    def exclusions(self) -> list[sa.Row]:
        with self.engine.begin() as cx:
            return list(cx.execute(sa.select(exclusion_rule).where(
                exclusion_rule.c.enabled == True)))  # noqa: E712

    # -- config ------------------------------------------------------------
    def config_get(self, key: str) -> str:
        with self.engine.begin() as cx:
            row = cx.execute(sa.select(config.c.value).where(
                config.c.key == key)).first()
        if row is not None:
            return row.value
        if key in CONFIG_DEFAULTS:
            return CONFIG_DEFAULTS[key]
        raise KeyError(key)

    def config_set(self, key: str, value: str) -> None:
        with self.engine.begin() as cx:
            updated = cx.execute(config.update().where(
                config.c.key == key).values(value=value)).rowcount
            if not updated:
                cx.execute(config.insert().values(key=key, value=value))

    # -- job runs ------------------------------------------------------------
    def record_job_run(self, job_name: str, status: str, now: datetime,
                       detail: str = "") -> None:
        with self.engine.begin() as cx:
            cx.execute(job_run.insert().values(
                job_name=job_name, status=status, run_utc=now, detail=detail))

    def last_success_utc(self, job_name: str) -> datetime | None:
        with self.engine.begin() as cx:
            row = cx.execute(
                sa.select(job_run.c.run_utc)
                .where(job_run.c.job_name == job_name,
                       job_run.c.status == "success")
                .order_by(job_run.c.run_utc.desc()).limit(1)).first()
            return _utc(row.run_utc) if row else None


def _hash(value: str) -> str:
    from .telemetry import hash_text
    return hash_text(value)
