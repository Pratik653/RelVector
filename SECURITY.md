# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

**Please do not open a public issue for a bypass or vulnerability.**

Use GitHub's private vulnerability reporting for this repository
(**Security → Report a vulnerability**). If that is unavailable, open a minimal public issue
asking for a private contact, without technical details.

Please include:

* the SQL (or a minimal reproduction), dialect, policy excerpt, role and context;
* the decision you expected and the decision you got;
* the SQLGuard Ninja and sqlglot versions.

We aim to acknowledge reports within 5 working days and to agree a disclosure date with you.
Confirmed bypasses are fixed with a regression case added to the benchmark corpus and are
credited in the changelog unless you prefer otherwise.

## Scope

In scope: policy bypasses (an unsafe query is allowed), fail-open behaviour on malformed
input, approval or context forgery in the integrations, secrets or literals leaking into
audit events, and CI action injection.

Out of scope: issues that need a compromised application or authentication layer, the
documented limitations in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md), and denial of
service against the database that a `statement_timeout` would stop.

SQLGuard Ninja is a defence-in-depth control. See the
[threat model](docs/security/THREAT_MODEL.md) for what it does and does not guarantee.
