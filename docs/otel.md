# OpenTelemetry architecture

The sample has two ingest paths and **one** metric set (`grokbot.*` gauges
with a `host` dimension). Pick one path per organization.

```text
                    +----------------------+
  collectors -----> |  bin/emit.py         |
  (disk, mem,       |  stdlib, fail-soft,  |
   load, freshness) |  one batch per run   |
                    +----------+-----------+
                               |
              default          |           optional
         --protocol signalfx   |      --protocol otlp
                               |
               +---------------v----------------+
               |                                |
               v                                v
  POST /v2/datapoint                    OTLP/HTTP (protobuf)
  ingest.<realm>.signalfx.com           ingest.<realm>.signalfx.com
                                        /v2/datapoint/otlp
                                               |
                                               |  or
                                               v
                                        local collector
                                        (otel/collector.yaml)
                                        receivers: otlp :4318
                                        exporters: otlphttp/splunk
```

## When to use which

- **OTLP/HTTP (default).** Install `requirements-otel.txt`, then
  `bin/run_emit.sh`. Metric names stay `grokbot.*`. Auth is the org
  **INGEST** token in `X-SF-TOKEN`. Schedule the routine **hourly**;
  the silent detector is 2h15m (one missed hour plus slack).
- **SignalFx `/v2/datapoint` (legacy only).** `--protocol signalfx`.
  Do not combine this with OTLP against the same org.
  The org **INGEST** token still goes in `X-SF-TOKEN`. Realm is still
  required unless you set `SPLUNK_O11Y_OTLP_URL`.
- **Local collector.** Start a contrib or Splunk distribution of the
  collector with [otel/collector.yaml](../otel/collector.yaml). Point the
  emitter at `http://127.0.0.1:4318/v1/metrics`. The sample config binds
  to localhost only, filters to `^grokbot\..*` metrics, and does **not**
  enable a hostmetrics receiver (those can surprise a Free / host-based
  plan).

## What this sample does not turn on

APM, RUM, synthetics, and a default host-metrics collector are out of
scope. Add them later only after you have watched Subscription Usage and
custom MTS for a day or two.

## Tokens and secrets

Same rules as the default path. Use the org **INGEST** token for OTLP,
never the API token, and never print or commit it. Collector env vars
are `SPLUNK_ACCESS_TOKEN` and `SPLUNK_REALM` in the example config —
provide them from the environment, not from a file in git.
