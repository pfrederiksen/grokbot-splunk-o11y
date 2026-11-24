# Best practices

These rules are the difference between a quiet, cheap catalog and a surprise
custom-metric bill.

## Keep dimensions low-cardinality

An MTS is a metric name plus a unique dimension set. The sample emitter uses
one dimension, `host`, with a single value such as `example-box`.

Do **not** add dimensions that grow with your data:

- per item, file, listing, or job id
- per person or email address
- per ticker or symbol
- per golf course, hole, or club
- per bird species
- per camera, container, or device id

Closed sets of two or three values (for example a `role` of `bot` or
`worker`) can be acceptable if you count the MTS before you ship them. When in
doubt, put the detail in a log or a local file and emit an aggregate gauge
instead.

## Name metrics with a stable `grokbot.*` prefix

| Metric | Unit | Meaning |
| --- | --- | --- |
| `grokbot.box.disk.pct` | percent | Root filesystem used |
| `grokbot.box.mem.pct` | percent | Memory used |
| `grokbot.box.load.1` | load average | One-minute load |
| `grokbot.routine.age_seconds` | seconds | Time since last successful ingest |
| `grokbot.emitter.ok` | 0/1 | Batch produced (heartbeat) |
| `grokbot.emitter.duration_ms` | milliseconds | Emitter runtime |
| `grokbot.emitter.datapoints` | count | Points in the batch |

Put the unit in the name (`pct`, `seconds`, `ms`) so charts do not have to
guess. Do not rename metrics casually — a rename is a new MTS and a dead
chart.

## Heartbeat plus a silent detector

A gauge that is "usually 1" does not alert when the process dies, because no
new 0 is ever sent. Always emit a heartbeat (`grokbot.emitter.ok`) and pair it
with a detector that fires when the series is **missing** for a few schedule
intervals (2 hours 15 minutes here, with an hourly routine).

## Token least privilege and rotation

- Ingest token: INGEST scope only, used by the routine.
- API token: API scope only, used when you apply dashboards. Keep it off the
  scheduled path if you can.
- Default expiry is 30 days; maximum is one year. Record the expiry date, not
  the secret, and rotate before it lapses.
- If a token may have leaked, rotate it immediately and treat the old value as
  compromised.

## Cost / MTS budget

The sample catalog, with a single `host` dimension, is:

| Area | Series | MTS |
| --- | --- | --- |
| Box health | disk, memory, load | 3 |
| Freshness | routine age (after the first successful ingest) | 1 |
| Emitter | ok, duration, datapoints | 3 |
| **Core total** |  | **7** |

A conservative working ceiling for a tutorial like this is "tens to low
hundreds of custom MTS, and well under whatever **Settings → Subscription
Usage** shows for your org." Seven series leaves plenty of room for a few
carefully designed hobby gauges later (see [Ideas](ideas.md)). It does not
leave room for a per-species or per-ticker dimension.

Host and default collector metrics are often classified differently from
custom `/v2/datapoint` gauges. Do not assume a published per-host custom
allowance until you have read it on your own Subscription Usage page. Free
Edition includes up to 15 hosts; this sample is meant to use one.

## Secret hygiene

- `chmod 700` on the secrets directory, `chmod 600` on the files.
- Never `echo`, `print`, or log a token. The emitter's one-line summary uses
  short error tokens (`http_401`, `missing_ingest_token`) instead.
- Do not put secrets in dashboards, detector descriptions, backup logs, or
  issue trackers.
- Ignore `.secrets/`, `.env`, `*.token`, and `.state/` (already in `.gitignore`).
- Rotate on suspicion; do not "just rewrite history" and assume the secret is
  safe.

## Idempotent dashboard creation

Look up dashboards, charts, and detectors **by name**, then create or update
in place. The apply tool does this and supports `--dry-run` so you can read
the JSON first. Renaming an object in the org without renaming it in code
will create a duplicate on the next apply.
