# OCR on Demand

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

Copilot and Codex review quota keeps running out. I want Alibaba's Open Code
Review (`ocr`) as a GitHub Action I can trigger on a PR whenever I want it --
or whenever an LLM working on that PR wants it -- in repos on both of my
GitHub owners, 9atatimer and Nine-At-A-Time-Media. The review should run
against the model on my own laptop's ollama, reached through a cloudflared
tunnel and protected by Cloudflare Access, so it costs no hosted-model quota.

The work is done when I can trigger an `ocr` run on GitHub, it hits my local
ollama model, and its review lands on the PR -- on demand, by me or by an
LLM.

Working label `ocr-on-demand`; the name is open.

## Story sets

| File | Theme |
|---|---|
| STORIES.triggering.md | who asks for a review, and how |
| STORIES.reviewing.md | what the review is, and where it lands |
| STORIES.access.md | who may reach the laptop's model, and who may not |

## Notes

**Settled in session (Todd's words):**

- Delivery is a GitHub Action, on both the 9atatimer and Nine-At-A-Time-Media
  owners.
- The model is the laptop's local ollama, reached through a cloudflared
  tunnel, protected by Access.
- Triggering is manual -- by Todd, or by an LLM -- whenever wanted.
- The laptop is always awake and ollama is always running.
- `ocr` must not run natively on the laptop with host privileges. A native
  install was tried and torn out on 2026-10-01 (issue #362).
- The first cut uses a single service account and a single service token for
  both owners, with the credential lookup resolving per owner so the owners
  can be split onto separate credentials later without reworking the
  workflow.
- The full SDLC applies: concept, design, architecture, behaviors,
  implementation, release.

**Still open (nobody's yet):**

- The hostname, and whether a nonprod tier means anything for one laptop.
- Which repos get it first.
- Where the tunnel's own credential lives on the laptop, so it runs while
  1Password is locked.
- The model.
- Whether an `ocr` review on GitHub ever counts as a gate reviewer in place
  of Copilot, or stays an on-demand opinion.

**Leans on:** the self-review skill and the Open Code Review Trial row
(9atatimer/Skills PR #77); the existing Access service-token pattern in
tds-internal; the reusable-workflow pattern of `review-settled.yml`.
