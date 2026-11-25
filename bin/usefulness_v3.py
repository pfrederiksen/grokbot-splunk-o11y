#!/usr/bin/env python3
"""Build action-first Grok Bot dashboard definitions (v3 usefulness layout).

This module is the source of the exported JSON under dashboards/. It uses
placeholder object IDs and app.<REALM>.signalfx.com links so the files stay
generic. Metric names are grokbot.*.

    python3 bin/usefulness_v3.py --export

does not need credentials and overwrites dashboards/*.json plus the manifest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "dashboards"

UI = "https://app.<REALM>.signalfx.com/#/dashboard"
UI_GROUP = "https://app.<REALM>.signalfx.com/#/dashboard-group/<GROUP_ID>"
UI_APM = "https://app.<REALM>.signalfx.com/#/apm"

IDS = {
    "Overview": "<DASHBOARD_ID_OVERVIEW_MISSION_CONTROL>",
    "Bot Ops": "<DASHBOARD_ID_BOT_OPS>",
    "Golf": "<DASHBOARD_ID_GOLF>",
    "Trading": "<DASHBOARD_ID_TRADING>",
    "Birds": "<DASHBOARD_ID_BIRDS>",
    "Home": "<DASHBOARD_ID_HOME>",
    "Ops": "<DASHBOARD_ID_OPS>",
}
DET = {
    "Emitter silent": "<DETECTOR_ID_EMITTER_SILENT>",
    "Box disk high": "<DETECTOR_ID_BOX_DISK_HIGH>",
    "Box memory high": "<DETECTOR_ID_BOX_MEMORY_HIGH>",
    "HA down": "<DETECTOR_ID_HA_DOWN>",
    "UniFi watchdog failing": "<DETECTOR_ID_UNIFI_WATCHDOG_FAILING>",
    "Backup failed or stale": "<DETECTOR_ID_BACKUP_FAILED_OR_STALE>",
    "Email sync stale": "<DETECTOR_ID_EMAIL_SYNC_STALE>",
    "Birds sync stale": "<DETECTOR_ID_BIRDS_SYNC_STALE>",
    "Pipeline overdue": "<DETECTOR_ID_PIPELINE_OVERDUE>",
    "Emitter collector failing": "<DETECTOR_ID_EMITTER_COLLECTOR_FAILING>",
}

G, Y, RED, BL, OR, TL, PR = 14, 17, 16, 1, 5, 15, 11


def scale_open(*bands: tuple) -> list[dict]:
    out = []
    for lo, hi, pal in bands:
        item: dict[str, Any] = {"paletteIndex": pal}
        if lo is None and hi is not None:
            item["lt"] = hi
        elif lo is not None and hi is None:
            item["gte"] = lo
        else:
            item["gte"] = lo
            item["lt"] = hi
        out.append(item)
    return out


def plo(label: str, display: str | None = None, prefix: str | None = None,
        suffix: str | None = None, pal: int | None = None, y: int = 0,
        plot: str | None = None) -> dict:
    item: dict[str, Any] = {"label": label, "yAxis": y}
    if display:
        item["displayName"] = display
    if prefix:
        item["valuePrefix"] = prefix
    if suffix:
        item["valueSuffix"] = suffix
    if pal is not None:
        item["paletteIndex"] = {16: 8, 17: 6, 18: 6, 19: 14, 20: 14}.get(pal, pal)
        if item["paletteIndex"] > 15:
            item["paletteIndex"] = pal % 16
    if plot:
        item["plotType"] = plot
    return item


def sv(name: str, program: str, *, precision: int = 0, viz: str = "Sparkline",
       scale: list | None = None, prefix: str | None = None, suffix: str | None = None,
       label: str = "v") -> dict:
    opts: dict[str, Any] = {
        "type": "SingleValue",
        "secondaryVisualization": viz,
        "maximumPrecision": precision,
        "refreshInterval": 0,
        "timestampHidden": False,
        "unitPrefix": "Metric",
        "publishLabelOptions": [plo(label, name, prefix, suffix)],
    }
    if scale:
        opts["colorBy"] = "Scale"
        opts["colorScale2"] = scale
    else:
        opts["colorBy"] = "Dimension"
    return {"name": name, "programText": program, "options": opts}


def ts(name: str, program: str, *, plot: str = "LineChart", stacked: bool = False,
       precision: int = 1, pubs: list | None = None, zero: bool = True,
       events: bool = True, left: str | None = None, right: str | None = None) -> dict:
    opts: dict[str, Any] = {
        "type": "TimeSeriesChart",
        "defaultPlotType": plot,
        "stacked": stacked,
        "includeZero": zero,
        "axisPrecision": precision,
        "showEventLines": events,
        "unitPrefix": "Metric",
    }
    if pubs:
        opts["publishLabelOptions"] = pubs
    if left is not None or right is not None:
        opts["axes"] = [{"label": left or ""}, {"label": right or ""}]
    return {"name": name, "programText": program, "options": opts}


def listc(name: str, program: str, *, scale: list | None = None, suffix: str | None = None,
          label: str = "v", precision: int = 0) -> dict:
    opts: dict[str, Any] = {
        "type": "List",
        "secondaryVisualization": "Sparkline",
        "maximumPrecision": precision,
        "refreshInterval": 0,
        "unitPrefix": "Metric",
        "publishLabelOptions": [plo(label, name, suffix=suffix)],
    }
    if scale:
        opts["colorBy"] = "Scale"
        opts["colorScale2"] = scale
    else:
        opts["colorBy"] = "Dimension"
    return {"name": name, "programText": program, "options": opts}


def heatmap(name: str, program: str, *, scale: list | None = None, group: list | None = None) -> dict:
    opts: dict[str, Any] = {
        "type": "Heatmap",
        "timestampHidden": True,
        "unitPrefix": "Metric",
        "groupBy": group or ["pipeline"],
    }
    if scale:
        opts["colorBy"] = "Scale"
        opts["colorScale2"] = scale
    else:
        opts["colorBy"] = "Range"
        opts["colorRange"] = {"min": 0, "max": 86400}
    return {"name": name, "programText": program, "options": opts}


def table(name: str, program: str, *, group: list | None = None, pubs: list | None = None) -> dict:
    opts: dict[str, Any] = {
        "type": "TableChart",
        "maximumPrecision": 1,
        "timestampHidden": False,
        "unitPrefix": "Metric",
        "groupBy": group or [],
    }
    if pubs:
        cleaned = []
        for pub in pubs:
            cleaned.append({k: v for k, v in pub.items() if k != "yAxis"})
        opts["publishLabelOptions"] = cleaned
    return {"name": name, "programText": program, "options": opts}


def text(name: str, markdown: str) -> dict:
    return {"name": name, "programText": "", "options": {"type": "Text", "markdown": markdown}}


def eventc(name: str, program: str) -> dict:
    return {"name": name, "programText": program, "options": {"type": "Event"}}


def C(defn: dict, w: int, h: int) -> tuple[dict, int, int]:
    return defn, w, h


def overlay(search: str, detector_id: str | None, color: int) -> dict:
    sig: dict[str, Any] = {"eventSearchText": search, "eventType": "detectorEvents"}
    if detector_id:
        sig["detectorId"] = detector_id
    return {"eventLine": True, "eventColorIndex": color, "eventSignal": sig, "label": None, "sources": []}


def metric(name: str, pipeline: str | None = None, collector: str | None = None) -> str:
    if pipeline:
        return f"data('{name}', filter=filter('pipeline', '{pipeline}'))"
    if collector:
        return f"data('{name}', filter=filter('collector', '{collector}'))"
    return f"data('{name}')"


def d1(name: str) -> str:
    return f"{metric(name)}.publish('v')"


# Color scales used across the boards
RATIO = scale_open((None, 75, G), (75, 100, Y), (100, None, RED))
RATIO_C = scale_open((None, 75, G), (75, 100, Y), (100, None, RED))
ZERO_GOOD = scale_open((None, 1, G), (1, None, RED))
ZERO_WARN = scale_open((None, 1, G), (1, None, Y))
ONE_GOOD = scale_open((None, 1, RED), (1, None, G))
DISK = scale_open((None, 70, G), (70, 85, Y), (85, None, RED))
MEM = scale_open((None, 80, G), (80, 90, Y), (90, None, RED))
GAP = scale_open((None, 75, G), (75, 130, Y), (130, None, RED))
BAK = scale_open((None, 20, G), (20, 25, Y), (25, None, RED))
POS_GOOD = scale_open((None, 0, RED), (0, None, G))
NEG_GOOD = scale_open((None, 0, G), (0, 0.5, Y), (0.5, None, RED))
DAY_HEAD = scale_open((None, 150, RED), (150, 400, Y), (400, None, G))
WEEK_HEAD = scale_open((None, 300, RED), (300, 800, Y), (800, None, G))
STREAK = scale_open((None, 2, G), (2, 4, Y), (4, None, RED))
WIN = scale_open((None, 40, RED), (40, 55, Y), (55, None, G))
AVGR = scale_open((None, 0, RED), (0, 0.3, Y), (0.3, None, G))
HWM = scale_open((None, 10, G), (10, 20, Y), (20, None, RED))
TONER = scale_open((None, 15, RED), (15, 30, Y), (30, None, G))
NAS_VOL = scale_open((None, 75, G), (75, 85, Y), (85, None, RED))
NAS_T = scale_open((None, 113, G), (113, 122, Y), (122, None, RED))
UNIFI_MEM = scale_open((None, 85, G), (85, 93, Y), (93, None, RED))
BATT = scale_open((None, 20, RED), (20, 50, Y), (50, None, G))
# Minutes since the Home Assistant status file was written; red after 10h (covers an overnight gap).
SCALE_HA_AGE = scale_open((None, 270, G), (270, 600, Y), (600, None, RED))


def ratio_tile(title: str, pipeline: str) -> dict:
    return sv(title, f"({metric('grokbot.pipeline.age_ratio', pipeline)} * 100).publish('v')", suffix="%", scale=RATIO)


def sorted_list(name: str, program: str, *, scale=None, suffix=None, precision: int = 1, sort: str = "-value") -> dict:
    chart = listc(name, program, scale=scale, suffix=suffix, precision=precision)
    chart["options"]["sortBy"] = sort
    return chart


def nav(title: str, blurb: str, current: str) -> str:
    order = ["Overview", "Bot Ops", "Trading", "Golf", "Birds", "Home", "Ops"]
    links = [f"**{name}**" if name == current else f"[{name}]({UI}/{IDS[name]})" for name in order]
    return (
        f"# {title}\n\n{blurb}\n\n{' · '.join(links)}\n\n"
        "Colors: green = fine, gold = watch (75% of budget used), red = act now. "
        "Tile titles say what to do."
    )


# Schedule text is sample data that matches bin/emit.py pipeline_specs().
PIPE_ROWS = [
    ("email", "every 2h, 6:04a-10:04p", "1.5h", "rerun the email refresh routine"),
    ("calendar", "every 2h, 6:04a-10:04p", "1.5h", "rerun the calendar refresh routine"),
    ("birds", "hourly", "1.25h", "rerun the bird-detection sync"),
    ("backup", "nightly ~2:00a", "5h", "check the latest backup log and rerun the backup routine"),
    ("finance", "daily ~6:00a", "2.5h", "rerun the finance refresh routine"),
    ("home", "6:20a, then every 4h to 10:20p", "2h", "rerun the home-status refresh (read-only)"),
    ("jobs", "~7:45a and ~2:45p", "3h", "wait for the next job scan or rerun it"),
    ("trader", "every 15m in market hours (NYSE days)", "1h", "check the trading heartbeat file during regular hours"),
    ("ls_trading", "hourly :15, 6a-10p", "1h", "rerun the trading status sync"),
    ("ebay", "fixed 9h budget", "-", "rerun the sales sync routine"),
    ("golf", "fixed 8-day budget", "-", "refresh handicap data after a posted round"),
]


def runbook_md() -> str:
    lines = ["| Pipeline | Schedule (PT) | Allowance | If red |", "|---|---|---|---|"]
    for name, sched, allow, fix in PIPE_ROWS:
        lines.append(f"| {name} | {sched} | {allow} | {fix} |")
    return "\n".join(lines)


APM_MD = (
    "**Traces:** every hourly run is one trace in Splunk APM, service **grokbot-emitter**: "
    "a SERVER `emit` span plus one child span per collector with `source.ok`, "
    "`source.points` and `source.error_type`. Open [APM](" + UI_APM + ") → service "
    "grokbot-emitter → Traces, and filter on errors to see which collector failed. "
    "The collector charts above come from the same timings, emitted as `grokbot.collector.*`."
)


def specs() -> dict[str, dict]:
    S: dict[str, dict] = {}
    S["Overview"] = dict(
        name="Overview / Mission Control",
        description="What needs attention right now, pipeline freshness against schedule, and headline numbers.",
        overlays=[
            overlay("Pipeline overdue", DET["Pipeline overdue"], RED),
            overlay("HA down", DET["HA down"], RED),
            overlay("Emitter silent", DET["Emitter silent"], RED),
            overlay("Backup failed or stale", DET["Backup failed or stale"], OR),
        ],
        rows=[
            [C(text("Overview header", nav("Mission Control",
                "Top row = needs attention (anything not green is a to-do). Second block = every pipeline's age as a % of its schedule budget: "
                "100% means the latest run that should have finished has not landed. Bottom = headline numbers. "
                "HA up can be blank when the home status file is stale; the status-age tile is the one to act on.", "Overview")), 12, 1)],
            [C(sv("Overdue pipelines → open Bot Ops", d1("grokbot.pipeline.overdue_count"), scale=ZERO_GOOD), 2, 1),
             C(sv("HA status age (min; red after 10h, then home refresh)", d1("grokbot.home.status.age_minutes"), scale=SCALE_HA_AGE), 2, 1),
             C(sv("Collector errors → dry-run emit.py", d1("grokbot.collector.failed_count"), scale=ZERO_GOOD), 2, 1),
             C(sv("Minutes since previous emit (>130 = missed run)", d1("grokbot.emitter.gap_minutes"), scale=GAP), 2, 1),
             C(sv("Home Assistant up (0 → home refresh)", d1("grokbot.home.ha.up"), scale=ONE_GOOD), 2, 1),
             C(sv("Box disk % (>85 → clear caches)", d1("grokbot.box.disk.pct"), suffix="%", scale=DISK), 2, 1)],
            [C(ratio_tile("Email sync — budget used", "email"), 3, 1),
             C(ratio_tile("Birds sync — budget used", "birds"), 3, 1),
             C(ratio_tile("Backup — budget used", "backup"), 3, 1),
             C(ratio_tile("Finance refresh — budget used", "finance"), 3, 1)],
            [C(ratio_tile("Trading status sync — budget used", "ls_trading"), 3, 1),
             C(ratio_tile("Home / HA status — budget used", "home"), 3, 1),
             C(ratio_tile("Jobs status — budget used (3h scan lag allowed)", "jobs"), 3, 1),
             C(sv("Emitter — runs in last 3h (expect 3)", "data('grokbot.emitter.ok').sum(over='3h').publish('v')",
                  scale=scale_open((None, 2, RED), (2, 3, Y), (3, None, G))), 3, 1)],
            [C(sv("Trading: account value", d1("grokbot.trade.account_value"), prefix="$", scale=POS_GOOD), 3, 1),
             C(sv("Trading: daily-loss headroom", d1("grokbot.trade.day_loss_headroom_usd"), prefix="$", scale=DAY_HEAD), 3, 1),
             C(sv("Golf: handicap index", d1("grokbot.golf.handicap_index"), precision=1), 2, 1),
             C(sv("Birds: today vs typical by now", "(data('grokbot.birds.detections.today') - data('grokbot.birds.typical_by_now_14d')).publish('v')", scale=POS_GOOD), 2, 1),
             C(sv("Home: storage healthy (1 = yes)", d1("grokbot.home.nas.ok"), scale=ONE_GOOD), 2, 1)],
            [C(sorted_list("All pipelines: % of schedule budget used (sorted)", "(data('grokbot.pipeline.age_ratio') * 100).publish('v')", scale=RATIO_C, suffix="%", precision=0), 6, 2),
             C(eventc("Detector incidents", "events(eventType='*').publish('all')"), 6, 2)],
        ],
    )
    S["Bot Ops"] = dict(
        name="Bot Ops",
        description="Routine and pipeline health vs schedule, emit.py collectors (duration, errors), traces, box resources, and the runbook.",
        overlays=[
            overlay("Pipeline overdue", DET["Pipeline overdue"], RED),
            overlay("Emitter collector failing", DET["Emitter collector failing"], OR),
            overlay("Emitter silent", DET["Emitter silent"], RED),
        ],
        rows=[
            [C(text("Bot Ops header", nav("Bot Ops",
                "**Budget** = time since the latest scheduled run that should have finished, plus that pipeline's allowance. "
                "**Age ratio** = hours since last success ÷ budget; ≥100% means a run was missed. The *Pipeline overdue* detector fires after 2 overdue hourly samples "
                "(calendar, finance, home, jobs, trader, ls_trading); email, birds and backup have their own detectors.\n\n" + runbook_md(), "Bot Ops")), 12, 3)],
            [C(sv("Overdue pipelines", d1("grokbot.pipeline.overdue_count"), scale=ZERO_GOOD), 2, 1),
             C(sv("Near budget (≥75%)", d1("grokbot.pipeline.warn_count"), scale=ZERO_WARN), 2, 1),
             C(sv("Collector errors this run", d1("grokbot.collector.failed_count"), scale=ZERO_GOOD), 2, 1),
             C(sv("Minutes since previous emit", d1("grokbot.emitter.gap_minutes"), scale=GAP), 2, 1),
             C(sv("Emit duration (ms)", "data('grokbot.emitter.duration_ms').publish('v')",
                  scale=scale_open((None, 3000, G), (3000, 10000, Y), (10000, None, RED))), 2, 1),
             C(sv("Datapoints per batch", d1("grokbot.emitter.datapoints")), 2, 1)],
            [C(table("Pipeline freshness: hours since success, budget hours, % used",
                     "A = data('grokbot.pipeline.age_hours').publish('Age h')\n"
                     "B = data('grokbot.pipeline.budget_hours').publish('Budget h')\n"
                     "C = (data('grokbot.pipeline.age_ratio') * 100).publish('% used')",
                     group=["pipeline"],
                     pubs=[plo("Age h", "Hours since success"), plo("Budget h", "Budget (h)"), plo("% used", "% of budget", suffix="%")]), 6, 3),
             C(heatmap("Budget used by pipeline (red ≥100%)", "(data('grokbot.pipeline.age_ratio') * 100).publish('v')", scale=RATIO_C, group=["pipeline"]), 6, 3)],
            [C(ts("Age ratio by pipeline over time (line at 100% = overdue)",
                  "(data('grokbot.pipeline.age_ratio') * 100).publish('ratio')\nconst(100).publish('overdue line')", precision=0), 12, 2)],
            [C(sorted_list("Slowest collectors this run (ms)", "data('grokbot.collector.duration_ms').publish('v')", precision=0,
                           scale=scale_open((None, 1000, G), (1000, 5000, Y), (5000, None, RED))), 4, 2),
             C(heatmap("Collector status (red = error)", "data('grokbot.collector.ok').publish('v')",
                       scale=scale_open((None, 1, RED), (1, None, G)), group=["collector"]), 4, 2),
             C(ts("Emit duration vs 6h p95 (ms)",
                  "d = data('grokbot.emitter.duration_ms')\nd.publish('run')\nd.percentile(95, over='6h').publish('6h p95')", precision=0), 4, 2)],
            [C(sv("Box CPU %", d1("grokbot.box.cpu.pct"), suffix="%", scale=DISK), 3, 1),
             C(sv("Box memory % (>90 → find runaway process)", d1("grokbot.box.mem.pct"), suffix="%", scale=MEM), 3, 1),
             C(sv("Box disk %", d1("grokbot.box.disk.pct"), suffix="%", scale=DISK), 3, 1),
             C(sv("Load 1m", d1("grokbot.box.load.1"), precision=2), 3, 1)],
            [C(ts("Box CPU / memory / disk %",
                  "data('grokbot.box.cpu.pct').publish('CPU')\ndata('grokbot.box.mem.pct').publish('Memory')\ndata('grokbot.box.disk.pct').publish('Disk')", precision=0), 6, 2),
             C(eventc("Bot detector events", "events(eventType='*').publish('all')"), 6, 2)],
            [C(text("APM traces", APM_MD), 12, 1)],
        ],
    )
    S["Trading"] = dict(
        name="Trading",
        description="Trading account risk headroom and P&L. Read-only sample of action-first tiles.",
        overlays=[],
        rows=[
            [C(text("Trading header", nav("Trading",
                "Lead numbers: account value, dollars of daily-loss headroom, and dollars of weekly-loss headroom. "
                "Wire these to whatever trading snapshot your bot already writes.", "Trading")), 12, 1)],
            [C(sv("Account value", d1("grokbot.trade.account_value"), prefix="$", precision=2), 3, 1),
             C(sv("Day P&L ($)", d1("grokbot.trade.day_pnl_usd"), prefix="$", precision=2, scale=POS_GOOD), 3, 1),
             C(sv("Daily-loss headroom", d1("grokbot.trade.day_loss_headroom_usd"), prefix="$", precision=0, scale=DAY_HEAD), 3, 1),
             C(sv("Weekly-loss headroom", d1("grokbot.trade.week_loss_headroom_usd"), prefix="$", precision=0, scale=WEEK_HEAD), 3, 1)],
            [C(sv("New entries allowed (1 = yes)", d1("grokbot.trade.entries_allowed"), scale=ONE_GOOD), 2, 1),
             C(sv("Full-loss streak", d1("grokbot.trade.full_loss_streak"), scale=STREAK), 2, 1),
             C(sv("Week P&L ($)", d1("grokbot.trade.week_pnl_usd"), prefix="$", precision=2, scale=POS_GOOD), 2, 1),
             C(sv("Drawdown from high-water mark", d1("grokbot.trade.drawdown_from_hwm_pct"), suffix="%", precision=1, scale=HWM), 2, 1),
             C(sv("Open risk ($)", d1("grokbot.trade.open_risk_usd"), prefix="$", precision=0), 2, 1),
             C(sv("Open positions", d1("grokbot.trade.positions.count"),
                  scale=scale_open((None, 4, G), (4, 5, Y), (5, None, RED))), 2, 1)],
            [C(ts("Account value", "data('grokbot.trade.account_value').publish('Account')", precision=0, zero=False), 8, 2),
             C(ts("Loss headroom: daily vs weekly ($)",
                  "data('grokbot.trade.day_loss_headroom_usd').publish('Daily')\ndata('grokbot.trade.week_loss_headroom_usd').publish('Weekly')", precision=0), 4, 2)],
            [C(sv("Scorecard win rate", "(data('grokbot.trade.scorecard.win_rate') * 100).publish('v')", suffix="%", scale=WIN), 3, 1),
             C(sv("Scorecard average R", d1("grokbot.trade.scorecard.avg_r"), precision=2, scale=AVGR), 3, 1),
             C(sv("This week: expectancy (R)", d1("grokbot.trade.week_expectancy_r"), precision=2, scale=AVGR), 3, 1),
             C(sv("Cash", d1("grokbot.trade.cash"), prefix="$", precision=0), 3, 1)],
            [C(ts("Exposure: cash vs options / equity / crypto ($)",
                  "data('grokbot.trade.cash').publish('Cash')\ndata('grokbot.trade.options_value').publish('Options')\ndata('grokbot.trade.equity_value').publish('Equity')\ndata('grokbot.trade.crypto_value').publish('Crypto')",
                  plot="AreaChart", stacked=True, precision=0), 12, 2)],
        ],
    )
    S["Golf"] = dict(
        name="Golf",
        description="Handicap trend and what score lowers it (best 8 of the last 20 differentials).",
        overlays=[],
        rows=[
            [C(text("Golf header", nav("Golf",
                "**Diff to beat** = the 8th-best differential in the last 20 rounds: post a lower one and it counts. **Gross to beat** converts that at the last course's rating/slope. "
                "**Oldest round counts = 1** means the next posted round pushes out a counting score, so the index can rise.", "Golf")), 12, 1)],
            [C(sv("Handicap index", d1("grokbot.golf.handicap_index"), precision=1), 3, 1),
             C(sv("Index change, 30 days (negative = better)", d1("grokbot.golf.hi_change_30d"), precision=1, scale=NEG_GOOD), 3, 1),
             C(sv("Differential to beat (8th best of 20)", d1("grokbot.golf.diff_to_beat"), precision=1), 3, 1),
             C(sv("Gross to beat at last course", d1("grokbot.golf.gross_to_beat"), precision=0), 3, 1)],
            [C(sv("Oldest of last 20 counts (1 = index may rise)", d1("grokbot.golf.oldest_counting"), scale=ZERO_WARN), 3, 1),
             C(sv("Index change, 90 days", d1("grokbot.golf.hi_change_90d"), precision=1, scale=NEG_GOOD), 3, 1),
             C(sv("Last differential minus index", d1("grokbot.golf.last.diff_minus_hi"), precision=1, scale=NEG_GOOD), 3, 1),
             C(sv("Rounds posted, last 30 days", d1("grokbot.golf.rounds_30d")), 3, 1)],
            [C(ts("Handicap index, low index, and differential to beat",
                  "data('grokbot.golf.handicap_index').publish('Index')\ndata('grokbot.golf.low_hi').publish('Low index')\ndata('grokbot.golf.diff_to_beat').publish('Diff to beat')",
                  precision=1, zero=False), 6, 2),
             C(sv("Low index (12-month)", d1("grokbot.golf.low_hi"), precision=1), 3, 2),
             C(sv("20-round avg putts", d1("grokbot.golf.avg20.putts"), precision=1), 3, 2)],
            [C(sv("20-round avg GIR %", d1("grokbot.golf.avg20.gir_pct"), suffix="%", precision=0), 3, 1),
             C(sv("20-round avg fairways %", d1("grokbot.golf.avg20.fir_pct"), suffix="%", precision=0), 3, 1),
             C(sv("Last round GIR %", d1("grokbot.golf.last.gir_pct"), suffix="%", precision=0), 3, 1),
             C(sv("Last round putts", d1("grokbot.golf.last.putts")), 3, 1)],
        ],
    )
    S["Birds"] = dict(
        name="Birds",
        description="Is activity ahead of a typical day, anything new or rare, and is the sync healthy.",
        overlays=[overlay("Birds sync stale", DET["Birds sync stale"], Y)],
        rows=[
            [C(text("Birds header", nav("Birds",
                "**Typical by now** = average detections up to this hour over the previous 14 days. **Rare** = species with under 10 detections ever, heard today. "
                "**Hours since last detection** is normally high overnight; a large value in daylight means the station or mic is down, not the sync.", "Birds")), 12, 1)],
            [C(sv("Detections today", d1("grokbot.birds.detections.today")), 2, 1),
             C(sv("Typical by now (14-day avg)", d1("grokbot.birds.typical_by_now_14d")), 2, 1),
             C(sv("Species today", d1("grokbot.birds.species.today")), 2, 1),
             C(sv("Rare species today", d1("grokbot.birds.rare_species_today"), scale=scale_open((None, 1, BL), (1, None, G))), 2, 1),
             C(sv("New species, last 7 days", d1("grokbot.birds.new_species_7d"), scale=scale_open((None, 1, BL), (1, None, G))), 2, 1),
             C(sv("At-risk species today", d1("grokbot.birds.at_risk_species_today")), 2, 1)],
            [C(ts("Today vs typical by this hour",
                  "data('grokbot.birds.detections.today').publish('Today')\ndata('grokbot.birds.typical_by_now_14d').publish('Typical by now')", precision=0), 6, 2),
             C(ratio_tile("Sync — budget used", "birds"), 3, 2),
             C(sv("Hours since last detection", d1("grokbot.birds.last_detection_age_hours"), precision=1), 3, 2)],
            [C(sv("Yesterday's detections", d1("grokbot.birds.detections.yesterday")), 4, 1),
             C(sv("Detections, last 7 days", d1("grokbot.birds.detections.7d")), 4, 1),
             C(sv("Species this year", d1("grokbot.birds.species.ytd")), 4, 1)],
            [C(eventc("Birds detector events", "events(eventType='Birds sync stale').publish('stale')"), 12, 1)],
        ],
    )
    S["Home"] = dict(
        name="Home",
        description="Read-only house health: Home Assistant, storage, network, cameras, batteries, and an EV pack.",
        overlays=[overlay("HA down", DET["HA down"], RED), overlay("UniFi watchdog failing", DET["UniFi watchdog failing"], OR)],
        rows=[
            [C(text("Home header", nav("Home",
                "Monitoring only (no Home Assistant commands). Values refresh with the home-status routine (6:20a, then every 4h in the sample schedule). "
                "If Home Assistant reads as blank, the status file is older than 30 minutes and a down reading is unverified — use the status-age tile, then rerun the home-status refresh.", "Home")), 12, 1)],
            [C(sv("Home Assistant up", d1("grokbot.home.ha.up"), scale=ONE_GOOD), 2, 1),
             C(sv("HA status age (min; red after 10h)", d1("grokbot.home.status.age_minutes"), scale=SCALE_HA_AGE), 2, 1),
             C(sv("Storage healthy", d1("grokbot.home.nas.ok"), scale=ONE_GOOD), 2, 1),
             C(sv("Volume used", d1("grokbot.home.nas.volume_used_pct"), suffix="%", precision=1, scale=NAS_VOL), 2, 1),
             C(sv("Cameras offline", d1("grokbot.home.camera.offline_count"), scale=ZERO_GOOD), 2, 1),
             C(sv("Open alerts", d1("grokbot.home.alerts.count"), scale=ZERO_WARN), 2, 1)],
            [C(sv("Network watchdog ok", d1("grokbot.home.unifi.watchdog_ok"), scale=ONE_GOOD), 2, 1),
             C(sv("Firmware update (1 = available)", d1("grokbot.home.unifi.fw_update_available"), scale=ZERO_WARN), 2, 1),
             C(sv("Router memory", d1("grokbot.home.unifi.mem_pct"), suffix="%", scale=UNIFI_MEM), 2, 1),
             C(sv("Low batteries", d1("grokbot.home.battery_low_count"), scale=ZERO_WARN), 2, 1),
             C(sv("Storage temp °F", d1("grokbot.home.nas.temp_f"), precision=1, scale=NAS_T), 2, 1),
             C(sv("Printer toner", d1("grokbot.home.printer.toner_pct"), suffix="%", scale=TONER), 2, 1)],
            [C(sv("EV battery", d1("grokbot.home.rivian.battery_pct"), suffix="%", scale=BATT), 3, 1),
             C(sv("EV energy left (kWh)", d1("grokbot.home.rivian.remaining_kwh"), precision=1), 3, 1),
             C(sv("EV range (mi)", d1("grokbot.home.rivian.range_mi")), 3, 1),
             C(sv("Charging now", d1("grokbot.home.rivian.charging")), 3, 1)],
            [C(ts("Health: HA up, storage ok, network watchdog (1 = ok)",
                  "data('grokbot.home.ha.up').publish('HA')\ndata('grokbot.home.nas.ok').publish('Storage')\ndata('grokbot.home.unifi.watchdog_ok').publish('Watchdog')",
                  plot="LineChart", precision=0), 6, 2),
             C(ts("Storage and router temperatures (°F)",
                  "data('grokbot.home.nas.temp_f').publish('Storage')\ndata('grokbot.home.nas.disk_temp_f').publish('Disks')\ndata('grokbot.home.unifi.temp_f').publish('Router')",
                  precision=0, zero=False), 6, 2)],
            [C(ts("EV battery % and energy left (kWh)",
                  "data('grokbot.home.rivian.battery_pct').publish('Battery %')\ndata('grokbot.home.rivian.remaining_kwh').publish('kWh left')", precision=0), 6, 2),
             C(ts("Thermostat temperatures (°F)", "data('grokbot.home.ecobee.temp_f').publish('Temp')", precision=1, zero=False), 6, 2)],
            [C(eventc("Home detector events", "events(eventType='*').publish('all')"), 12, 1)],
        ],
    )
    S["Ops"] = dict(
        name="Ops",
        description="Admin queues: mail needing a reply, calendar, jobs, sales, and backup trend.",
        overlays=[
            overlay("Backup failed or stale", DET["Backup failed or stale"], OR),
            overlay("Email sync stale", DET["Email sync stale"], Y),
        ],
        rows=[
            [C(text("Ops header", nav("Ops",
                "Queues that need a human: mail flagged for attention, orders to ship, new job matches, calendar errors. Freshness for these feeds is on Overview and Bot Ops.", "Ops")), 12, 1)],
            [C(sv("Mail needing attention (14d)", d1("grokbot.email.attention_count"), scale=ZERO_WARN), 2, 1),
             C(sv("Inbox unseen", d1("grokbot.email.inbox_unseen")), 2, 1),
             C(sv("Orders awaiting shipment", d1("grokbot.ebay.awaiting_shipment"), scale=ZERO_GOOD), 2, 1),
             C(sv("New job matches (last run)", d1("grokbot.jobs.new_matches"), scale=scale_open((None, 1, BL), (1, None, G))), 2, 1),
             C(sv("Calendar events today", d1("grokbot.cal.events_today")), 2, 1),
             C(sv("Calendar sync errors", d1("grokbot.cal.errors"), scale=ZERO_GOOD), 2, 1)],
            [C(sv("Listings with bids", d1("grokbot.ebay.with_bids")), 2, 1),
             C(sv("Active listings", d1("grokbot.ebay.active_listings")), 2, 1),
             C(sv("Listed value", d1("grokbot.ebay.current_value"), prefix="$"), 2, 1),
             C(sv("Jobs: interested", d1("grokbot.jobs.tracker.interested")), 2, 1),
             C(sv("Jobs: applied", d1("grokbot.jobs.tracker.applied")), 2, 1),
             C(sv("Backup age (h)", d1("grokbot.backup.age_hours"), precision=1, scale=BAK), 2, 1)],
            [C(ts("Mail pile: attention, inbox unseen, unread",
                  "data('grokbot.email.attention_count').publish('Attention')\ndata('grokbot.email.inbox_unseen').publish('Inbox unseen')\ndata('grokbot.email.unread_total').publish('Unread')",
                  precision=0), 6, 2),
             C(ts("Backup: duration (s) and data sent (bytes)",
                  "data('grokbot.backup.duration_seconds').publish('Duration s')\ndata('grokbot.backup.bytes_sent').publish('Sent bytes')",
                  precision=0), 6, 2)],
            [C(ts("Job pipeline: interested, applied, still fits",
                  "data('grokbot.jobs.tracker.interested').publish('Interested')\ndata('grokbot.jobs.tracker.applied').publish('Applied')\ndata('grokbot.jobs.tracker.still_fits').publish('Still fits')",
                  precision=0), 6, 2),
             C(eventc("Ops detector events", "events(eventType='*').publish('all')"), 6, 2)],
        ],
    )
    return S


SLUGS = {
    "Overview": "overview_mission_control",
    "Bot Ops": "bot_ops",
    "Trading": "trading",
    "Golf": "golf",
    "Birds": "birds",
    "Home": "home",
    "Ops": "ops",
}


def _layout_from_rows(rows: list[list[tuple[str, int, int]]]) -> list[dict]:
    layouts = []
    row_num = 0
    for row in rows:
        col = 0
        height = 1
        for chart_id, width, h in row:
            layouts.append({"chartId": chart_id, "column": col, "height": h, "row": row_num, "width": width})
            col += width
            height = max(height, h)
        row_num += height
    return layouts


def _existing_chart_ids(dest: Path) -> dict[str, str]:
    """Map dashboard/chart name -> existing placeholder id so exports stay stable."""
    mapping: dict[str, str] = {}
    for path in dest.glob("*.json"):
        if path.name in {"all.json", "usefulness_v3_manifest.json"}:
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        dash_name = data.get("description")  # not this
        # Prefer the filename slug later; use chart names which are unique per board
        # Key as "{file.stem}::{chart name}" and also bare chart name when unique.
        for entry in data.get("charts") or []:
            chart = entry.get("chart") or {}
            name = chart.get("name")
            cid = (entry.get("layout") or {}).get("chartId") or chart.get("id")
            if name and cid:
                mapping[f"{path.stem}::{name}"] = cid
        for i, ov in enumerate(data.get("eventOverlays") or [], start=1):
            oid = ov.get("overlayId")
            if oid:
                mapping[f"{path.stem}::overlay::{ov.get('eventSignal', {}).get('eventSearchText') or i}"] = oid
    return mapping


def _next_placeholder(existing: set[str], prefix: str) -> str:
    n = 1
    while f"<{prefix}_{n}>" in existing:
        n += 1
    token = f"<{prefix}_{n}>"
    existing.add(token)
    return token


def export_definitions(dest: Path | None = None) -> dict[str, Any]:
    """Write redacted dashboard JSON and a safe manifest. Returns the manifest."""
    dest = dest or DEST
    dest.mkdir(parents=True, exist_ok=True)
    stale = dest / "bot_health.json"
    if stale.exists():
        stale.unlink()

    prior = _existing_chart_ids(dest)
    used_ids = set(prior.values())

    export = {
        "group": {"id": "<GROUP_ID>", "name": "Grok Bot"},
        "realm": "<REALM>",
        "dashboards": {},
    }
    manifest = {"dashboards": {}, "notes": "Placeholder IDs only. Re-apply by name in your own org."}

    overlay_used = {v for k, v in prior.items() if "::overlay::" in k}

    for key, spec in specs().items():
        slug = SLUGS[key]
        charts_out = []
        built_rows = []
        made = []
        for row in spec["rows"]:
            built = []
            for defn, width, height in row:
                name = defn["name"]
                cid = prior.get(f"{slug}::{name}")
                if not cid or not str(cid).startswith("<CHART_ID_"):
                    cid = _next_placeholder(used_ids, "CHART_ID")
                body = {
                    "name": name,
                    "programText": defn.get("programText") or "",
                    "options": defn.get("options") or {},
                    "description": defn.get("description"),
                    "id": cid,
                }
                charts_out.append({"layout": None, "chart": body})
                built.append((cid, width, height, len(charts_out) - 1))
                made.append({
                    "id": cid,
                    "name": name,
                    "type": (defn.get("options") or {}).get("type"),
                    "programText": defn.get("programText") or "",
                })
            built_rows.append(built)
        layouts = _layout_from_rows([[(cid, w, h) for cid, w, h, _ in row] for row in built_rows])
        flat_idx = 0
        for row in built_rows:
            for cid, w, h, idx in row:
                charts_out[idx]["layout"] = layouts[flat_idx]
                flat_idx += 1

        overlays = []
        for item in spec.get("overlays") or []:
            search = (item.get("eventSignal") or {}).get("eventSearchText") or ""
            oid = prior.get(f"{slug}::overlay::{search}")
            if not oid or not str(oid).startswith("<OVERLAY_ID_"):
                oid = _next_placeholder(overlay_used, "OVERLAY_ID")
            entry = dict(item)
            entry["overlayId"] = oid
            overlays.append(entry)

        dash = {
            "id": IDS[key],
            "url": f"{UI}/{IDS[key]}",
            "description": spec["description"],
            "filters": None,
            "eventOverlays": overlays,
            "charts": charts_out,
        }
        export["dashboards"][spec["name"]] = dash
        (dest / f"{slug}.json").write_text(json.dumps(dash, indent=2) + "\n")
        manifest["dashboards"][key] = {
            "id": IDS[key],
            "url": dash["url"],
            "name": spec["name"],
            "charts": made,
        }

    (dest / "all.json").write_text(json.dumps(export, indent=2) + "\n")
    (dest / "usefulness_v3_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest



def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export v3 usefulness dashboard JSON (placeholder IDs).")
    parser.add_argument("--export", action="store_true", help="Write dashboards/*.json and the manifest (default).")
    parser.add_argument("--dest", default=None, help="Destination directory (default: dashboards/).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dest = Path(args.dest) if args.dest else DEST
    man = export_definitions(dest)
    ncharts = sum(len(v["charts"]) for v in man["dashboards"].values())
    print(f"exported {len(man['dashboards'])} dashboards, {ncharts} charts → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
