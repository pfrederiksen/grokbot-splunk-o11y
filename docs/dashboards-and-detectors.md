# Dashboards and detectors

`bin/apply_dashboards.py` defines a **Grok Bot** dashboard group, a **Bot Health**
dashboard, and four detectors, then creates or updates them by name.

## Dry-run first

```bash
python3 bin/apply_dashboards.py --dry-run
```

This prints a JSON report of the request bodies that would be sent. It does
not need credentials and does not use the network. Review the SignalFlow and
the notification address before a live apply.

```bash
export SPLUNK_O11Y_REALM=<REALM>
export SPLUNK_O11Y_API_TOKEN=<API_TOKEN>
python3 bin/apply_dashboards.py --notify-email alerts@example.com
```

Replace `alerts@example.com` with an address you control. Leaving the
placeholder would try to mail a fictional inbox.

## Idempotency

For each of `dashboardgroup`, `chart`, `dashboard`, and `detector`:

1. Look up an existing object with the same **name**.
2. If it exists, `PUT` the new body to its id.
3. If it does not, `POST` a new one.

Re-running the tool updates SignalFlow and chart layout in place rather than
duplicating objects. Names are part of the contract — rename them in the
script only if you also rename them in the org, or the next apply will create
a second copy.

The API base is `https://api.<REALM>.signalfx.com`. Override with
`SPLUNK_O11Y_API_URL` if needed. Auth is the `X-SF-TOKEN` header using the
**API** token, not the ingest token.

## Bot Health charts

Each chart is a simple SignalFlow `data('grokbot…')` time series:

| Chart | Metric |
| --- | --- |
| Disk used % | `grokbot.box.disk.pct` |
| Memory used % | `grokbot.box.mem.pct` |
| Load average (1m) | `grokbot.box.load.1` |
| Emitter heartbeat | `grokbot.emitter.ok` |
| Routine freshness | `grokbot.routine.age_seconds` |
| Emitter duration | `grokbot.emitter.duration_ms` |

Layout is a two-column, three-row grid.

## Detectors

| Name | Condition |
| --- | --- |
| Emitter silent | no `grokbot.emitter.ok` for 2 hours 15 minutes |
| Box disk high | `grokbot.box.disk.pct` > 85 for 1 hour 15 minutes |
| Box memory high | `grokbot.box.mem.pct` > 90 for 1 hour 15 minutes |
| Stale sync | `grokbot.routine.age_seconds` > 21600 (6 hours) for 1 hour 15 minutes |

Example SignalFlow for the heartbeat detector:

```text
ok = data('grokbot.emitter.ok').publish('ok')
not_reporting.detector(ok, '2h15m').publish('Emitter silent')
```

And for disk:

```text
disk = data('grokbot.box.disk.pct').publish('disk')
detect(when(disk > 85, lasting='1h15m')).publish('Box disk high')
```

The silent detector is the important one. If the routine stops, the token
expires, or ingest starts failing, **no new points arrive** — a threshold on
`grokbot.emitter.ok == 0` would never fire, because zero is never sent. Detect
**missing data** instead.

You can attach a notification integration other than email by editing the
`notifications` list in `detector_definitions()` (keep secrets out of the
repo). Definitions are in `bin/apply_dashboards.py` and are covered by
`tests/test_dashboards.py`.

## Richer dashboard snapshot

JSON under [`dashboards/`](../dashboards/) is an export of the v3 "usefulness" layout: an **Overview / Mission Control** board that leads with a needs-attention row, a **Bot Ops** board with the schedule runbook and collector traces, plus topic boards (Trading, Golf, Birds, Home, Ops). Charts use SingleValue sparklines, lists, heatmaps, tables, event feeds, and detector overlays. IDs and app URLs in the JSON are placeholders (`<DASHBOARD_ID_BOT_OPS>`, `https://app.<REALM>.signalfx.com/...`).

Regenerate the export (no credentials) with:

```bash
python3 bin/usefulness_v3.py --export
python3 bin/detectors_v3.py --export
```

`bin/apply_dashboards.py` is still the small, idempotent **Bot Health** starter covered by `tests/test_dashboards.py`. The exported Bot Ops board is the fuller operations view. Pipeline freshness and the two new detectors are documented in [Pipeline freshness](pipeline-freshness.md).

## Verifying live charts

`bin/verify_dashboards.py` looks up the **Grok Bot** dashboard group by name
(or `GROKBOT_DASHBOARD_GROUP` / `GROKBOT_DASHBOARD_GROUP_ID`), runs each
SignalFlow program, and reports OK / EMPTY / ERROR / WARN / SKIP. Golf
charts use a 7-day window; everything else uses 24 hours. Text charts and
event feeds are skipped. A last-value sanity check flags obviously broken
numbers (for example a percentage outside 0–110).

```bash
export SPLUNK_O11Y_REALM=<REALM>
export SPLUNK_O11Y_API_TOKEN=<API_TOKEN>
python3 bin/verify_dashboards.py
python3 bin/verify_dashboards.py --quiet --json /tmp/verify.json
```

The script never prints tokens and does not hardcode a realm. Override the
API base with `SPLUNK_O11Y_API_URL` if needed. `bin/verify_v3.py` remains a
smaller name-based check of the same boards.

## Home Assistant status age

Overview and Home include an **HA status age** tile (`grokbot.home.status.age_minutes`).
The sample emitter reads an optional `data/home/status.json` (or
`GROKBOT_DATA_ROOT/home/status.json`). Green is under 4.5 hours, gold
covers an overnight gap, and red starts at 10 hours. If the file is older
than 30 minutes, a "down" `grokbot.home.ha.up` reading is omitted so the
HA-down detector does not fire on a stale snapshot. Refresh the status
file, then look at HA up again.
