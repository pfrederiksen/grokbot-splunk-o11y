# Ideas

Optional extensions. **None of these are implemented in the sample emitter.**
They are metric designs and Grok Bot prompts you can adapt to your own local
files. Every number below is fictional.

The same rules apply: `grokbot.*` names, low cardinality, no unbounded
dimensions, fail-soft collectors, one batched POST, no secrets in output.

## Golf

Useful gauges, all without a course, club, hole, or player dimension:

| Metric | Fake example | Notes |
| --- | --- | --- |
| `grokbot.golf.handicap_index` | 18.2 | Latest index only |
| `grokbot.golf.last.score` | 94 | Last 18-hole round |
| `grokbot.golf.last.putts` | 34 | |
| `grokbot.golf.last.fir_pct` | 43 | Fairways in regulation |
| `grokbot.golf.last.gir_pct` | 28 | Greens in regulation |

Do not dimension by course name, tee, or playing partner. If you want a
trend, emit a rolling average as its own metric (`grokbot.golf.avg20.putts`)
rather than one series per round.

Sample routine prompt:

```text
Once a day, read a local file such as ./data/golf.json (a list of rounds
you maintain). Compute the latest handicap index, plus the last 18-hole
score, putt count, fairways-in-regulation percent, and greens-in-regulation
percent. Do not include course or club names in metrics, dimensions,
logs, or messages. Emit those five gauges with the same grokbot.* batched
POST pattern as bin/emit.py. Stay silent unless two consecutive runs fail.
Never print secrets. Use only fictional-looking summaries in alerts
(metric names and numbers, no venues).
```

## Birds

Keep this to counts and freshness, never a station identifier and never a
species dimension:

| Metric | Fake example |
| --- | --- |
| `grokbot.birds.detections.today` | 17 |
| `grokbot.birds.species.today` | 6 |
| `grokbot.birds.detections.7d` | 91 |
| `grokbot.birds.sync.age_seconds` | 900 |

Sample routine prompt:

```text
On a 15-minute or hourly schedule, read a local detections database or
JSON export (for example ./data/birds.json). Emit counts for detections
today, distinct species today, detections in the last 7 days, and seconds
since the last successful sync. Do not emit per-species series or any
station id. Stay silent unless two consecutive runs fail.
```

## Home automation

Aggregate only. A "controller up" flag, a total entity count, and how many
cameras are online — not one metric per device.

| Metric | Fake example |
| --- | --- |
| `grokbot.home.controller_up` | 1 |
| `grokbot.home.entity_count` | 214 |
| `grokbot.home.cameras_online` | 3 |

If the controller is down, emit `controller_up=0` and skip stale device
gauges rather than repeating old temperatures.

Sample routine prompt:

```text
Every 5 minutes, read a local status snapshot such as ./data/home.json.
Emit grokbot.home.controller_up (1 or 0), entity_count, and an aggregate
cameras_online count. Do not dimension by camera, room, or hostname. If
the controller looks down, emit up=0 and omit stale device values. Stay
silent unless two consecutive runs fail.
```

## Email and calendar freshness

The valuable signal is often "is the sync fresh?", not the content of any
message.

| Metric | Fake example |
| --- | --- |
| `grokbot.email.unread_total` | 12 |
| `grokbot.email.sync.age_seconds` | 900 |
| `grokbot.cal.events_today` | 4 |
| `grokbot.cal.sync.age_seconds` | 600 |

Do not use email addresses, sender names, or calendar names as dimensions.

Sample routine prompt:

```text
Every 15 minutes, read local summary files such as ./data/email_summary.json
and ./data/calendar_summary.json. Emit unread_total, events_today, and a
sync age in seconds for each source. Never include addresses or calendar
names in dimensions or logs. Stay silent unless two consecutive runs fail.
```

## Adding a collector later

Once the core seven MTS have been stable for a day or two and Subscription
Usage looks comfortable, you can extend `bin/emit.py` with one more
fail-soft `safe_collect(...)` source that reads **your** local files and
returns extra gauges. Keep the batch as a single POST. Rehearse with
`--dry-run` and count the new MTS before enabling the live routine.
