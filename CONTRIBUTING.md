# Contributing

Thanks for taking the time to improve this tutorial.

## Development

- Python 3.10 or newer. The sample code uses the standard library only; please
  do not add third-party dependencies unless there is a discussion first.
- Run the tests before opening a change:

      python3 -m unittest discover -s tests -v

- `bin/emit.py --dry-run` and `bin/apply_dashboards.py --dry-run` should work
  without credentials.

## Docs

Keep the documentation excellent and scannable. Depth belongs in `docs/`. If
you change behavior, update the relevant guide and the README quickstart.

The README header image lives at `docs/images/header.png`. Leave it in place
unless you are replacing it with another text-free, logo-free banner.

## Hard rules

- No personal data: no names, emails, addresses, account numbers, course or
  club names, station IDs, hostnames, tailnet names, or private IP addresses.
  Use placeholders such as `<REALM>`, `<INGEST_TOKEN>`, and `example.com`.
- No secrets in the tree, in tests, or in CI logs.
- Keep metric cardinality low. Do not add per-item, per-person, or other
  unbounded dimensions to the sample emitter.
- Tests must stay offline (no network).

## License

Contributions are accepted under the MIT license.
