# Pipeline freshness

The sample emitter can report how stale each scheduled job is *relative to
its own calendar*, not just a raw age. That is what the Overview and Bot Ops
dashboards use for the needs-attention row and the "% of budget used" tiles.

## Metrics

Each pipeline gets a `pipeline` dimension (for example `email`, `backup`,
`trader`) and three gauges:

| Metric | Meaning |
| --- | --- |
| `grokbot.pipeline.age_hours` | Hours since that pipeline's last success |
| `grokbot.pipeline.budget_hours` | Maximum healthy age right now |
| `grokbot.pipeline.age_ratio` | `age_hours ÷ budget_hours` (≥ 1 means a run was missed) |

Two rollups are also emitted, without a `pipeline` dimension:

| Metric | Meaning |
| --- | --- |
| `grokbot.pipeline.overdue_count` | Number of pipelines with `age_ratio >= 1` |
| `grokbot.pipeline.warn_count` | Number of pipelines with `0.75 <= age_ratio < 1` |

`grokbot.routine.failing_count` is kept as an alias of `overdue_count` so
older charts keep working. `grokbot.emitter.gap_minutes` is the time since
the previous successful emit, so a skipped hourly run is visible even if
individual pipelines look healthy.

A source that is not configured (the optional file under `GROKBOT_DATA_ROOT`
is missing) is skipped and does not count as overdue. A fresh clone stays
quiet until you drop data files in place.

## How the budget is calculated

For a **fixed-budget** pipeline (the sample uses 9 hours for sales sync and
8 days for a handicap refresh) `budget_hours` is just that constant.

For a **scheduled** pipeline the budget is:

> time since the latest run that should already have finished, plus that
> pipeline's allowance.

The allowance is slack so a job that started on time but ran long does not
flip red immediately. Example: email is scheduled every two hours at :04
from 6:04 through 22:04 Pacific, with a 1.5 hour allowance. At 10:04, the
latest run that should have finished is the 8:04 slot (10:04 minus 1.5
hours lands at 8:34, so 8:04 is the last completed slot). The budget is
then (10:04 − 8:04) + 1.5 hours = 3.5 hours.

The sample schedules, allowances, and file paths live in
`emit.pipeline_specs()` and are also printed in the Bot Ops runbook. Point
`GROKBOT_DATA_ROOT` at your own tree (default `data/`) rather than hardcoding
host paths.

## NYSE days (trader heartbeat)

The `trader` pipeline uses regular-trading-hours slots in Pacific time:
every 15 minutes from 6:30 to 13:00 on a normal weekday. Weekends and the
dates in `emit.MARKET_CLOSED` have no slots. Dates in `emit.MARKET_EARLY`
end at 10:00 PT (a 1:00 p.m. Eastern early close). The budget lookback
walks previous days, so Monday morning still has a budget that reaches
back to Friday's last slot, including across a Thursday holiday and a
Friday early close.

The calendar in `emit.py` is a static sample for 2026–2027. It is not
loaded from a live exchange feed; update it when you copy the sample.

## Detectors

| Name | Condition |
| --- | --- |
| Pipeline overdue | `grokbot.pipeline.age_ratio >= 1` for 1 hour 15 minutes, limited to `calendar`, `finance`, `home`, `jobs`, `trader`, and `ls_trading` |
| Emitter collector failing | `grokbot.collector.ok < 1` for 1 hour 15 minutes |

Email, birds, and backup keep their own stale/failed detectors rather than
sharing the overdue detector. Definitions are in `bin/detectors_v3.py` and
the exported JSON under `dashboards/detectors/`. Run
`python3 bin/detectors_v3.py --export` (no credentials) to regenerate them
with `alerts@example.com`.
