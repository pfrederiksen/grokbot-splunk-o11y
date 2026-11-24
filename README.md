![A friendly robot beside abstract observability charts](docs/images/header.png)

# Grok Bot + Splunk Observability Cloud

A small, unofficial tutorial for sending **basic Grok Bot metrics** to
[Splunk Observability Cloud](https://www.splunk.com/en_us/products/observability.html)
(historically SignalFx): box health, a routine heartbeat, and a silent-emitter
detector. It is a community sample, not affiliated with Splunk or xAI.

You will end up with:

- A Python emitter that sends one batched set of `grokbot.*` gauges every hour
  via OpenTelemetry OTLP/HTTP (optional stdlib-only `--protocol signalfx` fallback)
- A wrapper script that loads tokens from `chmod 600` files and never prints them
- A Grok Bot routine that stays quiet unless **two consecutive** runs fail
- A **Bot Health** starter dashboard plus detectors (emitter silent, disk high, memory
  high, stale sync), applied as code
- Exported v3 "usefulness" dashboards under [dashboards/](dashboards/) (Overview, Bot Ops, and topic boards) plus pipeline-overdue and collector-failing detectors; `bin/apply_dashboards.py` remains the small Bot Health starter
- Pipeline freshness gauges (`grokbot.pipeline.age_hours`, `budget_hours`, `age_ratio`, plus overdue/warn counts) described in [Pipeline freshness](docs/pipeline-freshness.md)

## Prerequisites

- Python 3.10 or newer. The default OTLP path needs `pip install -r requirements-otel.txt` (a repo `.venv` is recommended). The legacy `--protocol signalfx` path is stdlib-only.
- A Splunk Observability Cloud organization, including the [Free Edition](https://www.splunk.com/en_us/blog/observability/splunk-observability-cloud-free-edition.html) (up to 15 hosts)
- An org **INGEST** token for the emitter and a separate org **API** token for dashboards

## Quickstart

1. Create two org tokens in **Settings → Access Tokens**. Extend the expiry
   (the default is 30 days; the maximum is one year). See [Concepts](docs/concepts.md).
2. Store them as `chmod 600` files or environment variables. Never `echo` them.

       mkdir -p ~/.config/grokbot-splunk-o11y/secrets
       chmod 700 ~/.config/grokbot-splunk-o11y/secrets
       # write INGEST_TOKEN, API_TOKEN, and REALM into that directory, then:
       chmod 600 ~/.config/grokbot-splunk-o11y/secrets/*

   Or export `SPLUNK_O11Y_REALM`, `SPLUNK_O11Y_INGEST_TOKEN`, and
   `SPLUNK_O11Y_API_TOKEN`. Copy [.env.example](.env.example) as a reminder,
   but keep the real file out of git.
3. Dry-run the emitter (no network, no token required):

       python3 bin/emit.py --dry-run

4. Send a real batch (the wrapper loads secret files if the env vars are unset):

       bin/run_emit.sh

   A successful run prints a single line such as:

       o11y emit: ingest=200 points=7 mts~7 ms=42 sources_fail=none err=ok alert=no

5. Inspect the dashboard and detector JSON, then apply it:

       python3 bin/apply_dashboards.py --dry-run
       python3 bin/apply_dashboards.py --notify-email alerts@example.com

   Replace `alerts@example.com` with an address you control before a live apply.
6. Schedule an **hourly** Grok Bot routine (for example around :07) using the sample prompt in
   [Setup](docs/setup.md#sample-grok-bot-routine). Install the OTel SDK first (`pip install -r requirements-otel.txt`, preferably into `.venv`).


## Pipeline freshness and action-first dashboards

Each scheduled job reports how stale it is as a fraction of its *schedule
budget*: hours since last success divided by (time since the latest run that
should have finished, plus an allowance). `grokbot.pipeline.age_ratio` ≥ 1
means a run was missed; 0.75 is the gold "watch" threshold.
`grokbot.pipeline.overdue_count` and `grokbot.pipeline.warn_count` roll those
up for the Overview needs-attention row. The **Pipeline overdue** detector
watches calendar, finance, home, jobs, trader, and trading-status pipelines
for 1 hour 15 minutes; **Emitter collector failing** fires when
`grokbot.collector.ok` stays below 1 for the same window. Email, birds, and
backup keep their own stale detectors.

The Bot Ops dashboard header includes a runbook table (schedule, allowance,
and what to rerun). Optional hobby sources live under `GROKBOT_DATA_ROOT`
(default `data/`) and are skipped when the files are missing, so a fresh
clone stays quiet. Details, including NYSE holiday and early-close handling
for the trader heartbeat, are in [Pipeline freshness](docs/pipeline-freshness.md).

## OpenTelemetry architecture

Production ingest is **OpenTelemetry OTLP/HTTP**. The emitter sends the same
`grokbot.*` gauges (same names, same `host` dimension) to
`https://ingest.<realm>.signalfx.com/v2/datapoint/otlp` with the org **INGEST**
token in the `X-SF-TOKEN` header. Do not also POST to `/v2/datapoint` — that
would double custom MTS. The silent-emitter detector is tuned for an
**hourly** heartbeat (no data for 2 hours 15 minutes), not a 5-minute one.

```text
collectors -> bin/emit.py  (default --protocol otlp)
                 |-- OTLP/HTTP metrics  ->  /v2/datapoint/otlp
                 |-- OTLP/HTTP traces   ->  /v2/trace/otlp
                 |                      (one trace per run, span per collector)
                 `-- optional local collector: otel/collector.yaml
                     (localhost :4318, filter ^grokbot\\..*)
```

Install the SDK, preferably into a repo virtualenv that is not a cache dir:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-otel.txt
bin/run_emit.sh --dry-run
bin/run_emit.sh
```

`--protocol signalfx` remains only as a legacy fallback. A collector is
optional; the default path talks to Splunk ingest directly. Full write-up:
[docs/otel.md](docs/otel.md).

Do not enable a default host-metrics collector on a Free or host-based plan
until you have watched Subscription Usage. Resource attributes are kept off
the metric payload (only the original dimensions, typically `host`) so MTS
identities stay stable.

## Guides

| Guide | What it covers |
| --- | --- |
| [Concepts](docs/concepts.md) | Realms, ingest vs API tokens, expiry, Free Edition limits, MTS |
| [Setup](docs/setup.md) | Token files, the emitter, the hourly routine prompt |
| [Dashboards and detectors](docs/dashboards-and-detectors.md) | Bot Health as code, SignalFlow, `--dry-run`, v3 export |
| [Best practices](docs/best-practices.md) | Cardinality, naming, heartbeats, token hygiene, MTS budget |
| [Ideas](docs/ideas.md) | Optional hobby metrics (golf, birds, home, email) with fake data |
| [Pipeline freshness](docs/pipeline-freshness.md) | Schedule budgets, age ratio, overdue/warn counts, NYSE slots, new detectors |
| [OpenTelemetry](docs/otel.md) | Optional OTLP/HTTP path and example collector config |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

CI runs the same tests on Python 3.10 through 3.13 and runs gitleaks on the
history. OTLP helper tests run without the SDK installed. A live emit needs `requirements-otel.txt`.

## License

[MIT](LICENSE). Copyright (c) 2026 pfrederiksen.
