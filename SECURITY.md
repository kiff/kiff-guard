# Security Policy

## Scope

kiff-guard is a client SDK and collection of framework adapters. Security issues
relevant to this repo include:

- Bypass of the fail-safe: a code path that allows a withheld decision to
  proceed in enforce mode
- Trust-boundary violation: an adapter or core function that injects or forwards
  an authority/roles field to the KIFF API
- Dependency vulnerabilities in the optional adapter extras
- Credential or secret leakage in cookbook recipes or test fixtures

Issues in the KIFF Cloud runtime or the KIFF framework (`kiffhq/kiff`) should
be reported to those repos respectively.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report privately via GitHub's security advisory feature:
**[Report a vulnerability](https://github.com/kiffhq/kiff-guard/security/advisories/new)**

Or email: **security@kiff.dev**

Include:
- A description of the issue and its impact
- Steps to reproduce or a minimal proof of concept
- The version(s) affected

We aim to acknowledge reports within 48 hours and provide a fix timeline within
7 days for confirmed issues.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✓ current |

## Disclosure policy

We follow coordinated disclosure. Once a fix is available we will publish a
GitHub Security Advisory and credit the reporter (unless anonymity is requested).
