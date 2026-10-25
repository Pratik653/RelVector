# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

Security fixes are released as new patch versions.

## Reporting a vulnerability

**Please do not open a public issue for a vulnerability.**

Use GitHub's private vulnerability reporting for this repository
(**Security → Report a vulnerability**). If that is unavailable, open a minimal public issue
asking for a private contact, without technical details.

Please include a minimal reproduction with synthetic data, what you expected and what
happened, and the RelVector, SQLAlchemy, database and Python versions.

We aim to acknowledge reports within 5 working days and to agree a disclosure date with you.

## Scope

In scope:

* Any write, DDL or non-`SELECT` statement reaching the source database.
* Columns that are not mapped (or are excluded) being read, embedded or stored.
* A sensitive-looking column being embedded without `allow_sensitive`.
* Source text going to a provider marked `sends_data_externally` without
  `allow_external_embeddings=True`.
* Code execution when opening an index file.
* SQL injection through mapping identifiers or metadata filters.
* Credentials appearing in `repr()`, errors or logs.
* An optional SQL validator being bypassed after it has denied a query.
* Records deleted by a run that did not complete or no longer owns the checkpoint.

Out of scope, because these are documented limitations (see the README):

* Index files are not encrypted, and anyone who can read the file can read the stored text
  and metadata.
* There is no row-level or tenant isolation inside an index.
* Name-based sensitivity detection misses columns with innocuous names.
* An `engine=` supplied by the caller is used as given.

RelVector is a trusted-developer library. It relies on the database's own permissions; use a
read-only database role for indexing.
