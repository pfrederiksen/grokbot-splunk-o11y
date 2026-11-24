# OpenTelemetry path (optional)

The default Grok Bot emitter already sends OTLP/HTTP straight to Splunk
ingest (`bin/emit.py` / `bin/run_emit.sh`). This folder is an optional local
collector if you want to proxy those same `grokbot.*` gauges.

Do not run both paths into the same organization at once. Each gauge would
be counted twice against the custom MTS budget.

See the [OpenTelemetry architecture](../README.md#opentelemetry-architecture)
section in the root README and [docs/otel.md](../docs/otel.md).
