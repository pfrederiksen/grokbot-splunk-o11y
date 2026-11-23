# Concepts

This page is the vocabulary you need before sending a single datapoint.

## Realms

Every Observability Cloud organization lives in a **realm** — a short id such
as `us0`, `us1`, `eu0`, or `jp0`. You can read it from the app URL or from
**Settings → Organizations**.

This sample posts to the classic SignalFx hostnames, with the realm substituted
in:

| Use | URL |
| --- | --- |
| Ingest (datapoints) | `https://ingest.<REALM>.signalfx.com/v2/datapoint` |
| API (dashboards, detectors) | `https://api.<REALM>.signalfx.com` |
| UI | `https://app.<REALM>.signalfx.com` |

Newer `*.<REALM>.observability.splunkcloud.com` hostnames exist as well. The
scripts here default to the `signalfx.com` ingest and API URLs constructed from
`SPLUNK_O11Y_REALM`. You can override them with `SPLUNK_O11Y_INGEST_URL` and
`SPLUNK_O11Y_API_URL` if your realm expects the newer hosts. The scripts never
guess a realm; if the variable is missing they refuse to send.

Official references:

- [View your realm and API endpoints](https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization)
- [Send data using REST APIs](https://help.splunk.com/en/splunk-observability-cloud/manage-data/other-data-ingestion-methods/other-data-ingestion-methods/send-data-using-rest-apis)
- [Organization access tokens](https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens)

## Tokens: ingest vs API

Create **two** organization access tokens, not one shared secret and not a
user session token.

| Token | Scope | Used by | Why it is separate |
| --- | --- | --- | --- |
| Ingest | **INGEST** only | `bin/run_emit.sh` / `bin/emit.py` | Least privilege for a 5-minute job that only POSTs datapoints |
| API | **API** (with a role that can create dashboards and detectors) | `bin/apply_dashboards.py` | The emitter never needs this; do not put it on the routine's host if you can avoid it |

A user "Show API Access Token" session token from your profile can often list
or edit dashboards, but **cannot ingest**. An ingest token cannot create
detectors. Keep them apart so a leaked routine credential cannot change
alerting.

Set the expiration explicitly when you create each token:

- The **default expiry is 30 days**. If you leave it, the emitter goes silent
  when the token lapses — which is exactly what the "Emitter silent" detector
  is for, but it is still a surprise.
- The **maximum expiry is one year**. Record the expiry date (not the secret)
  on a calendar and rotate before then.

Store the values as `chmod 600` files or environment variables. Never `echo`,
`print`, or log them. See [Setup](setup.md).

## Free Edition and custom metrics

The [Free Edition](https://www.splunk.com/en_us/blog/observability/splunk-observability-cloud-free-edition.html)
is a standing, no-credit-card tier: **up to 15 hosts**, no published time
limit, with platform features included. Confirm your exact entitlements under
**Settings → Subscription Usage** after you sign in — especially the
**custom metric** cap, which is not something this tutorial invents a number
for.

Datapoints you POST to `/v2/datapoint` generally count as **custom metrics**.
A default OpenTelemetry collector, APM, RUM, or synthetics can consume host
slots or custom metric time series (MTS) in ways that are easy to underestimate.
Start with this small emitter; add a collector only after you have watched
usage for a few days.

## Metric time series (MTS)

An MTS is one metric name plus one unique set of dimension key/value pairs.
`grokbot.box.disk.pct` with `{host: example-box}` is one MTS. Adding a
dimension that varies per file, person, ticker, course, or species multiplies
the series — and your custom-metric bill or cap — by that cardinality.

This sample uses a single low-cardinality dimension, `host`, and a short,
stable catalog of `grokbot.*` gauges. See the budget table in
[Best practices](best-practices.md).

## The ingest request

One run of the emitter sends **one** HTTP POST:

- URL: `https://ingest.<REALM>.signalfx.com/v2/datapoint`
- Header: `X-SF-TOKEN: <INGEST_TOKEN>`
- Header: `Content-Type: application/json`
- Body (gauges, timestamp in milliseconds):

```json
{
  "gauge": [
    {
      "metric": "grokbot.box.disk.pct",
      "value": 42.0,
      "dimensions": { "host": "example-box" },
      "timestamp": 1700000000000
    }
  ]
}
```

Treat HTTP 200 and 204 as success. Do not retry in a tight loop on 401, 403,
or 429 — fix the token, the realm, or the catalog instead.
