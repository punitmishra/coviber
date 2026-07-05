# Security Policy

CoViber is local-first by design: no cloud egress, no telemetry, no account.
The only network call in the entire codebase is the `webscrape` loader fetching
a URL **you** configure. Records, the work graph, and embeddings live on your
local disk under the data dir you choose.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** for this repository
(Security tab → "Report a vulnerability"). Do **not** open a public issue for
security reports. You can expect an initial response within 7 days.

## Scope notes

- The `webscrape` loader fetches user-configured URLs with `urllib` — treat any
  scrape config from an untrusted source as untrusted input.
- The MCP server (`coviber serve`) speaks stdio to a local client only; it
  binds no network ports.
- Everything ingested ends up in plaintext JSONL under your data dir. Protect
  that directory as you would your inbox.
