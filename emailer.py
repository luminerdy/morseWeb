"""Outbound email for morseWeb.

The default backend prints messages to the server console, so in dev
the verification and password-reset links are copy-pastable from the
terminal. Phase 3 replaces send_message with an SES call; nothing else
changes.

Tests read `outbox` to grab tokens out of sent messages.
"""

outbox = []
OUTBOX_LIMIT = 20


def send_message(to, subject, body):
    print(
        f"\n=== morseWeb email to {to} ===\n{subject}\n\n{body}\n=== end email ===\n",
        flush=True,
    )


def send_email(to, subject, body):
    outbox.append({"to": to, "subject": subject, "body": body})
    del outbox[:-OUTBOX_LIMIT]
    send_message(to, subject, body)
