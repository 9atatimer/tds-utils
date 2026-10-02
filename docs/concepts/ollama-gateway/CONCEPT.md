# Ollama Gateway

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

A further evolution of our use of ollama: a road from outside the laptop to
a model on it. The first traveller is [ocr-on-demand](../ocr-on-demand/CONCEPT.md)
-- a review running on a GitHub runner that needs my laptop's model -- but
the road is its own thing, part of the LMDE, not part of the review.

The road is a cloudflared tunnel protected by Cloudflare Access, and the
credentials that let a caller through. It is its own domain: who may use
it, and what a caller can make the far end do.

It is also a security domain. The ollama at the end of this road is not my
everyday ollama; it is an external-facing one, and it runs in a sandbox so
that nothing arriving over the road -- `ocr` included, and the tool calls
it makes -- can reach my user credentials or carry anything off the laptop.
`ocr` itself never runs open on my laptop.

## Story sets

| File | Theme |
|---|---|
| STORIES.access.md | who may reach the model, and who may not |
| STORIES.sandbox.md | what a caller can make the laptop do, and what it never can |

## Notes

**Settled in session (Todd's words):**

- The tunnel and the service-account credentials are their own domain, a
  sub-component of the LMDE, torn off from ocr-on-demand.
- The tunnel and the Access credentials are provisioned in tds-internal, as
  all IaC is. All credentials are managed as IaC in tds-internal.
- The cloudflared daemon on the laptop is part of the tds-utils LMDE
  ecosystem, and cloudflared goes on the radar at Trial.
- The external ollama runs in a sandbox, starting with the basic macOS
  sandbox. This is treated as a security domain.
- The first cut uses a single service account and a single service token
  for both GitHub owners, with the credential lookup resolving per owner so
  the owners can be split onto separate credentials later.
- An outage -- tunnel down, internet off, laptop asleep on the road -- is
  normal, and the callers fail fast and loud on it.

**Still open (nobody's yet):**

- The hostname, and whether a nonprod tier means anything for one laptop.
- The cloudflared daemon needs its tunnel credential on the laptop at run
  time; where that copy lives so the daemon still starts while 1Password is
  locked.
- Which models the external ollama serves, and whether it shares model
  files with the everyday one.
- Whether the first caller -- `ocr`, which is untrusted -- ever holds the
  credential that opens the road. If it does, it can carry the credential
  off, and then anyone holding it reaches the laptop, which the access
  stories forbid. (Raised by codex review on PR #364.)
- The name.

**Leans on:** the Access service-token pattern in tds-internal
(`ops/terraform/quillmap-smoketest`); the LMDE's launchd daemon pattern;
the LMDE design's "never routable" non-goal, which this idea deliberately
crosses for exactly one road.
