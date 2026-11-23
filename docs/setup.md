# Setup

A walkthrough from empty tokens to a quiet 5-minute Grok Bot routine.

## 1. Create the tokens

In the Observability Cloud UI:

1. Open **Settings → Access Tokens → New Token**.
2. Create `grokbot-ingest` with the **INGEST** scope only. Set the expiry
   yourself (up to one year). The default is 30 days.
3. Create `grokbot-api` with the **API** scope and a role that can create
   dashboards and detectors. Set the expiry yourself.
4. Copy each secret once. You will not see it again.
5. Copy your realm id (`us0`, `eu0`, …) from the app URL or
   **Settings → Organizations**.

See [Concepts](concepts.md) for why these are two tokens, not one.

## 2. Store them safely

Prefer files with tight permissions, or environment variables. Do not put
real values in git, chat, or dashboard descriptions.

```bash
mkdir -p ~/.config/grokbot-splunk-o11y/secrets
chmod 700 ~/.config/grokbot-splunk-o11y/secrets

# Paste each value with your editor. The files contain only the secret (or the realm id).
# chmod 600 afterwards.
#   ~/.config/grokbot-splunk-o11y/secrets/INGEST_TOKEN
#   ~/.config/grokbot-splunk-o11y/secrets/API_TOKEN
#   ~/.config/grokbot-splunk-o11y/secrets/REALM
chmod 600 ~/.config/grokbot-splunk-o11y/secrets/*
```

Equivalent environment variables, if you would rather not use files:

| Variable | Required for |
| --- | --- |
| `SPLUNK_O11Y_REALM` | Emitter and dashboard tool |
| `SPLUNK_O11Y_INGEST_TOKEN` | Emitter |
| `SPLUNK_O11Y_API_TOKEN` | `bin/apply_dashboards.py` only |

Optional: `GROKBOT_HOST` (default `example-box`), `GROKBOT_DISK_PATH` (default
`/`), `GROKBOT_STATE_FILE` (default `.state/emit-status.json`),
`GROKBOT_O11Y_SECRETS_DIR` (default `~/.config/grokbot-splunk-o11y/secrets`).

The wrapper reads a secret file only when the matching environment variable is
unset, using a silent `tr` + `printf -v` — it never `echo`s the value. See
[.env.example](../.env.example) for the full list of names. `.gitignore`
already excludes `.secrets/`, `.env`, `*.token`, and `.state/`.

## 3. Run the emitter

From the repository root:

```bash
python3 bin/emit.py --dry-run
bin/run_emit.sh
```

`--dry-run` builds the payload and prints a one-line summary without posting
and without needing a token. A live run always exits 0 so a scheduler does
not treat a single blip as a crash. The only output is one summary line:

```text
o11y emit: ingest=200 points=7 mts~7 ms=42 sources_fail=none err=ok alert=no
```

| Field | Meaning |
| --- | --- |
| `ingest` | HTTP status, `dry-run`, or `err` |
| `points` | Gauges in the batch |
| `mts` | Unique metric+dimension combinations |
| `ms` | Runtime |
| `sources_fail` | Collectors that threw (`disk`, `mem`, `load`, `freshness`) or `none` |
| `err` | `ok` or a short token such as `missing_ingest_token`, `missing_realm`, `http_401`, `url_error` — never a secret |
| `alert` | `yes` only after **two consecutive** failed live runs |

Collectors are fail-soft: a problem reading memory does not block disk or
load. HTTP status is printed in this line only; it is not sent as a datapoint
(the silent detector watches `grokbot.emitter.ok`, which is part of the batch
itself — if the POST fails, those points never land).

The first successful ingest has no `grokbot.routine.age_seconds` point yet,
because freshness is measured from the **previous** success. Later runs emit
the age in seconds.

On missing token or realm, the wrapper and the emitter still exit 0 and report
`missing_ingest_token` or `missing_realm`.

## 4. Apply the dashboard (optional, but recommended)

```bash
python3 bin/apply_dashboards.py --dry-run
python3 bin/apply_dashboards.py --notify-email alerts@example.com
```

Replace the placeholder address before a live apply. The tool looks up the
dashboard group, charts, dashboard, and detectors by name and creates or
updates them. Details are in [Dashboards and detectors](dashboards-and-detectors.md).

## Sample Grok Bot routine

Paste a prompt like the following into a Grok Bot routine scheduled every
**five minutes**. Daily is too slow for a heartbeat; the silent detector is
tuned to 20 minutes, which is four missed 5-minute runs.

```text
You run the grokbot-splunk-o11y emitter on a 5-minute schedule.

Working directory: the grokbot-splunk-o11y checkout.
Command: bin/run_emit.sh
Do not pass tokens on the command line. The wrapper loads them from
chmod 600 files or from the environment. Never print, log, or paste
token values, file contents of the secrets directory, or environment
values that look like secrets.

Stay silent on success.
Stay silent on a single failed run.
If two consecutive scheduled runs fail (the summary line contains
alert=yes, or you have now seen two failures in a row yourself), send
me one short message with the one-line summary and the err= token only.
Do not include secrets, file paths to tokens, or a stack trace.

After any successful run, treat the failure count as reset (the script
also resets its own state file).
If the command is missing or the checkout is gone, that counts as a
failure, with err=missing_emitter.
```

The emitter persists `consecutive_failures` in `.state/emit-status.json`
(mode 600). `alert=yes` means the script itself has already reached the
threshold of two consecutive failures.
