"""Gmail access for the vicky@ mailbox: IMAP read (reply detection) and
SMTP send (approved replies, calendar invites, daily summary).

Uses an app password (GMAIL_APP_PASSWORD) — no OAuth dance required.
Sequence emails are NOT sent here; they go through Apollo. This module
only handles 1:1 replies after a human approves them, and internal
reporting.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Config

log = logging.getLogger("vicky.mailer")


class Mailer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.address = cfg.sender_email
        self.password = cfg.gmail_app_password
        if not self.password:
            raise RuntimeError("GMAIL_APP_PASSWORD is not set")

    # ------------------------------------------------------------- read ------
    def fetch_recent_inbound(self, lookback_days: int) -> list[dict]:
        """Return recent inbox messages as dicts:
        {message_id, from_email, subject, body, date}."""
        host = self.cfg.s("replies.gmail_imap_host", "imap.gmail.com")
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days))
        messages = []
        with imaplib.IMAP4_SSL(host) as imap:
            imap.login(self.address, self.password)
            imap.select("INBOX")
            _, data = imap.search(None, f'(SINCE "{since.strftime("%d-%b-%Y")}")')
            for num in data[0].split():
                _, msg_data = imap.fetch(num, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                from_email = email.utils.parseaddr(msg.get("From", ""))[1].lower()
                if from_email == self.address.lower():
                    continue
                messages.append({
                    "message_id": msg.get("Message-ID", "").strip(),
                    "from_email": from_email,
                    "subject": _decode(msg.get("Subject", "")),
                    "body": _extract_body(msg),
                    "date": msg.get("Date", ""),
                })
        return messages

    # ------------------------------------------------------------- send ------
    def send(self, to: str, subject: str, body: str,
             ics_attachment: str | None = None) -> None:
        host = self.cfg.s("replies.gmail_smtp_host", "smtp.gmail.com")
        port = self.cfg.s("replies.gmail_smtp_port", 587)
        msg = MIMEMultipart()
        msg["From"] = f"Vicky Steyn <{self.address}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if ics_attachment:
            part = MIMEText(ics_attachment, "calendar;method=REQUEST", "utf-8")
            part.add_header("Content-Disposition",
                            'attachment; filename="invite.ics"')
            msg.attach(part)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.address, self.password)
            smtp.sendmail(self.address, [to], msg.as_string())
        log.info("sent email to %s: %s", to, subject)


def _decode(value: str) -> str:
    parts = decode_header(value)
    return "".join(
        p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
                    "attachment" not in str(part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8",
                                          errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8",
                              errors="replace")
    return str(msg.get_payload())
