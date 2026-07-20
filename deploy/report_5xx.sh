#!/usr/bin/env bash
# Count HTTP 5xx responses in the last 5 minutes of gunicorn access
# logs (journald) and publish them as a CloudWatch metric. Run by
# morseweb-5xx.timer; a CloudWatch alarm on morseWeb/Http5xx emails
# the operator when the app starts erroring.

set -euo pipefail

COUNT=$(journalctl -u morseweb --since "-5 minutes" --no-pager 2>/dev/null \
    | grep -cE 'HTTP/[0-9.]+" 5[0-9][0-9] ' || true)
aws cloudwatch put-metric-data \
    --namespace morseWeb \
    --metric-name Http5xx \
    --value "${COUNT:-0}" \
    --unit Count \
    --region "${AWS_REGION:-us-east-1}"
