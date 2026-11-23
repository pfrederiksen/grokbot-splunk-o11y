# Security policy

Please report vulnerabilities privately through GitHub's private vulnerability
reporting / security advisories on this repository. Do not open a public issue
that contains tokens, credentials, or other secrets.

## Secrets

- This project never needs to store your Observability Cloud tokens in git.
- Use `chmod 600` files or environment variables, as described in
  [docs/setup.md](docs/setup.md).
- If you accidentally paste a token into a ticket, chat, or commit, rotate it
  in **Settings → Access Tokens** and treat the old value as compromised.
- Please do not include tokens, org IDs, or personal data in bug reports.

## Scope

The sample emitter and dashboard tool talk only to the ingest and API endpoints
you configure. They do not bundle credentials.
