"""Outbound email for morseWeb.

Two backends, chosen by MORSEWEB_EMAIL_BACKEND:

- console (default): prints messages to the server console, so in dev
  the verification and password-reset links are copy-pastable from the
  terminal.
- ses: sends through Amazon SES. Requires boto3 (deploy/requirements-
  prod.txt), MORSEWEB_EMAIL_FROM, and an instance role or credentials
  with ses:SendEmail. Region comes from MORSEWEB_SES_REGION or the
  default AWS config.

Tests read `outbox` to grab tokens out of sent messages.
"""

import os

outbox = []
OUTBOX_LIMIT = 20

_ses_client = None


def _send_console(to, subject, body):
    print(
        f"\n=== morseWeb email to {to} ===\n{subject}\n\n{body}\n=== end email ===\n",
        flush=True,
    )


def _get_ses_client():
    global _ses_client
    if _ses_client is None:
        import boto3
        region = os.environ.get("MORSEWEB_SES_REGION")
        _ses_client = boto3.client("ses", region_name=region) if region else boto3.client("ses")
    return _ses_client


def _send_ses(to, subject, body):
    _get_ses_client().send_email(
        Source=os.environ["MORSEWEB_EMAIL_FROM"],
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )


def send_message(to, subject, body):
    if os.environ.get("MORSEWEB_EMAIL_BACKEND") == "ses":
        _send_ses(to, subject, body)
    else:
        _send_console(to, subject, body)


def send_email(to, subject, body):
    outbox.append({"to": to, "subject": subject, "body": body})
    del outbox[:-OUTBOX_LIMIT]
    send_message(to, subject, body)
