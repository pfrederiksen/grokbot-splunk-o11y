#!/usr/bin/env python3
"""v3 detectors: pipeline overdue + collector failing, plus action hints on every detector.

Notification email defaults to alerts@example.com. Tokens, if used for a live
apply, come only from SPLUNK_O11Y_API_TOKEN and SPLUNK_O11Y_REALM. This script
exports JSON by default and does not need credentials.

    python3 bin/detectors_v3.py --export
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "dashboards" / "detectors"

PLACEHOLDERS = {
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

SLUGS = {
    "Emitter silent": "emitter_silent",
    "Box disk high": "box_disk_high",
    "Box memory high": "box_memory_high",
    "HA down": "ha_down",
    "UniFi watchdog failing": "unifi_watchdog_failing",
    "Backup failed or stale": "backup_failed_or_stale",
    "Email sync stale": "email_sync_stale",
    "Birds sync stale": "birds_sync_stale",
    "Pipeline overdue": "pipeline_overdue",
    "Emitter collector failing": "emitter_collector_failing",
}

EXAMPLE_EMAIL = "alerts@example.com"


def notify(email: str = EXAMPLE_EMAIL) -> list[dict[str, Any]]:
    return [{"type": "Email", "email": email, "cc": [], "bcc": []}]


def rule(label: str, subject: str, body: str, severity: str, email: str = EXAMPLE_EMAIL) -> dict[str, Any]:
    return {
        "detectLabel": label,
        "disabled": False,
        "notifications": notify(email),
        "parameterizedSubject": subject,
        "parameterizedBody": body,
        "severity": severity,
    }


def detector_definitions(email: str = EXAMPLE_EMAIL) -> list[dict[str, Any]]:
    return [
        {
            "id": PLACEHOLDERS["Emitter silent"],
            "name": "Emitter silent",
            "description": "No grokbot.emitter.ok datapoints for 2 hours 15 minutes (hourly emitter around :07; one missed run plus slack).",
            "programText": "from signalfx.detectors.not_reporting import not_reporting\n"
            "not_reporting.detector(data('grokbot.emitter.ok'), '2h15m').publish('Emitter silent')\n",
            "rules": [rule(
                "Emitter silent",
                "Grok Bot emitter silent",
                "No grokbot.emitter.ok points for 2 hours 15 minutes, so the hourly emit routine has stopped or its export failed. "
                "Fix: run bin/run_emit.sh and read the one-line summary; confirm the routine is enabled and the OpenTelemetry SDK is installed.",
                "Critical",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Box disk high"],
            "name": "Box disk high",
            "description": "Root (or GROKBOT_DISK_PATH) disk used percent stayed above 85 for 1 hour 15 minutes.",
            "programText": "disk = data('grokbot.box.disk.pct').publish('signal')\n"
            "detect(when(disk > 85, lasting='1h15m')).publish('Box disk high')\n",
            "rules": [rule(
                "Box disk high",
                "Grok Bot box disk high",
                "Box disk is {{inputs.signal.value}}% (>85%). Fix: find large rebuildable caches and clear them; do not delete source data.",
                "Major",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Box memory high"],
            "name": "Box memory high",
            "description": "Memory used percent stayed above 90 for 1 hour 15 minutes.",
            "programText": "mem = data('grokbot.box.mem.pct').publish('signal')\n"
            "detect(when(mem > 90, lasting='1h15m')).publish('Box memory high')\n",
            "rules": [rule(
                "Box memory high",
                "Grok Bot box memory high",
                "Box memory is {{inputs.signal.value}}% (>90%). Fix: look for runaway processes (for example leftover browsers or pollers).",
                "Major",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["HA down"],
            "name": "HA down",
            "description": "Home Assistant reachability (grokbot.home.ha.up) stayed at 0 for 1 hour 15 minutes. A down reading is omitted when the status file is older than 30 minutes, so a stale file does not fire this detector.",
            "programText": "up = data('grokbot.home.ha.up').publish('signal')\n"
            "detect(when(up < 1, lasting='1h15m')).publish('HA down')\n",
            "rules": [rule(
                "HA down",
                "Grok Bot Home Assistant down",
                "Home Assistant reports down for 2 hourly samples. Fix: rerun the home-status refresh; this detector is monitoring only and never sends Home Assistant commands. "
                "If grokbot.home.status.age_minutes is also high, refresh the status file first — a stale file is not treated as down.",
                "Major",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["UniFi watchdog failing"],
            "name": "UniFi watchdog failing",
            "description": "Network extras-poller watchdog (grokbot.home.unifi.watchdog_ok) stayed at 0 for 1 hour 15 minutes.",
            "programText": "ok = data('grokbot.home.unifi.watchdog_ok').publish('signal')\n"
            "detect(when(ok < 1, lasting='1h15m')).publish('UniFi watchdog failing')\n",
            "rules": [rule(
                "UniFi watchdog failing",
                "Grok Bot network watchdog failing",
                "The network extras-poller watchdog is not ok. Fix: check the watchdog status file and restart the loop if it has stopped.",
                "Warning",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Backup failed or stale"],
            "name": "Backup failed or stale",
            "description": "Backup age (grokbot.backup.age_hours) stayed above 25 hours for 1 hour 15 minutes.",
            "programText": "age = data('grokbot.backup.age_hours').publish('signal')\n"
            "detect(when(age > 25, lasting='1h15m')).publish('Backup failed or stale')\n",
            "rules": [rule(
                "Backup failed or stale",
                "Grok Bot backup failed or stale",
                "The nightly backup failed or is older than 25h. Fix: read the newest backup log and rerun the backup routine.",
                "Major",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Email sync stale"],
            "name": "Email sync stale",
            "description": "Email sync age exceeded 9 hours for 1 hour 15 minutes.",
            "programText": "age = data('grokbot.email.sync.age_seconds').publish('signal')\n"
            "detect(when(age > 32400, lasting='1h15m')).publish('Email sync stale')\n",
            "rules": [rule(
                "Email sync stale",
                "Grok Bot email sync stale",
                "Email sync is older than 9h. Fix: rerun the email refresh routine; transient mailbox errors usually clear on retry.",
                "Warning",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Birds sync stale"],
            "name": "Birds sync stale",
            "description": "Bird-detection sync stayed stale for two hourly samples.",
            "programText": "age = data('grokbot.birds.sync.age_seconds').publish('signal')\n"
            "detect(when(age > 7200, lasting='1h15m')).publish('Birds sync stale')\n",
            "rules": [rule(
                "Birds sync stale",
                "Grok Bot birds sync stale",
                "Bird-detection sync is older than 2h for 2 samples. Fix: rerun the hourly sync and check that its environment is intact.",
                "Warning",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Pipeline overdue"],
            "name": "Pipeline overdue",
            "description": (
                "A scheduled pipeline (calendar, finance, home, jobs, trader heartbeat, trading status sync) "
                "has missed its schedule: hours since last success exceed the schedule budget (latest run that should "
                "have finished + allowance) for 2 hourly samples. Email, birds and backup have their own detectors."
            ),
            "programText": (
                "r = data('grokbot.pipeline.age_ratio', filter=filter('pipeline', 'calendar', 'finance', 'home', 'jobs', 'trader', 'ls_trading'))\n"
                "detect(when(r >= 1, lasting='1h15m')).publish('Pipeline overdue')\n"
            ),
            "rules": [rule(
                "Pipeline overdue",
                "Grok Bot pipeline overdue: {{dimensions.pipeline}}",
                "{{dimensions.pipeline}} is overdue ({{inputs.r.value}}x its schedule budget). "
                "See the Bot Ops dashboard runbook: calendar, finance, home, jobs, trader, and ls_trading each have a refresh step.",
                "Warning",
                email,
            )],
        },
        {
            "id": PLACEHOLDERS["Emitter collector failing"],
            "name": "Emitter collector failing",
            "description": "One emit.py collector raised an error on 2 consecutive hourly runs (its source file is missing or malformed). Other collectors keep reporting.",
            "programText": (
                "c = data('grokbot.collector.ok')\n"
                "detect(when(c < 1, lasting='1h15m')).publish('Emitter collector failing')\n"
            ),
            "rules": [rule(
                "Emitter collector failing",
                "Grok Bot emit collector failing: {{dimensions.collector}}",
                "Collector {{dimensions.collector}} failed on consecutive emits. Fix: run python3 bin/emit.py --dry-run and look at sources_fail; "
                "the error type is on the collector span in APM (service grokbot-emitter).",
                "Minor",
                email,
            )],
        },
    ]


def _finalize(defn: dict[str, Any]) -> dict[str, Any]:
    out = dict(defn)
    out.setdefault("maxDelay", 0)
    out.setdefault("minDelay", None)
    out.setdefault("timezone", None)
    out.setdefault("tags", [])
    out.setdefault("detectorOrigin", "Standard")
    return out


def export_definitions(dest: Path | None = None, email: str = EXAMPLE_EMAIL) -> dict[str, Any]:
    dest = dest or DEST
    dest.mkdir(parents=True, exist_ok=True)
    detectors = [_finalize(d) for d in detector_definitions(email)]
    payload = {"detectors": {d["name"]: d for d in detectors}}
    for det in detectors:
        (dest / f"{SLUGS[det['name']]}.json").write_text(json.dumps(det, indent=2) + "\n")
    (dest / "all.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export v3 detector JSON (placeholder IDs, example.com email).")
    parser.add_argument("--export", action="store_true", help="Write dashboards/detectors/*.json (default).")
    parser.add_argument("--notify-email", default=EXAMPLE_EMAIL, help="Notification address in the exported JSON.")
    parser.add_argument("--dest", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    email = args.notify_email
    if email != EXAMPLE_EMAIL and not str(email).endswith("@example.com"):
        # Keep the committed export on example.com; live apply can pass a real address
        # when the user is ready, but do not refuse --notify-email for local export.
        pass
    payload = export_definitions(Path(args.dest) if args.dest else DEST, email=email)
    print(f"exported {len(payload['detectors'])} detectors → {args.dest or DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
