# OCR on Demand

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

Copilot and Codex review quota keeps running out. I want Alibaba's Open Code
Review (`ocr`) as a GitHub Action I can trigger on a PR whenever I want it --
or whenever an LLM working on that PR wants it -- in repos on both of my
GitHub owners, 9atatimer and Nine-At-A-Time-Media. The review should run
against the model on my own laptop's ollama, so it costs no hosted-model
quota.

How a review on GitHub reaches the laptop's model is its own idea:
[ollama-gateway](../ollama-gateway/CONCEPT.md), part of the LMDE. This
concept is the review; that one is the road to the model.

The work is done when I can trigger an `ocr` run on GitHub, it hits my local
ollama model, and its review lands on the PR -- on demand, by me or by an
LLM.

Working label `ocr-on-demand`; the name is open.

## Story sets

| File | Theme |
|---|---|
| STORIES.triggering.md | who asks for a review, and how |
| STORIES.reviewing.md | what the review is, where it lands, and how it fails |

Who may reach the model, and what the model may do on the laptop, are
stories of [ollama-gateway](../ollama-gateway/CONCEPT.md).

## Notes

**Settled in session (Todd's words):**

- Delivery is a GitHub Action, on both the 9atatimer and Nine-At-A-Time-Media
  owners.
- Triggering is manual -- by Todd, or by an LLM -- whenever wanted.
- The laptop is always awake and ollama is always running -- true in spirit,
  but the tunnel can be down, the internet off, or the laptop asleep while
  Todd is on the road. A review that cannot reach the model fails fast and
  loud in the POC and MVP; that is what handling it gracefully means here.
- The `ocr` code is not trusted. It never runs on the laptop, except
  containerized, and running it containerized is out of scope for the POC
  and MVP. (A native install was tried and torn out on 2026-10-01, issue
  #362.)
- The first repos are Nine-At-A-Time-Media/GammaGo, 9atatimer/iae and
  9atatimer/jengris.
- The model is a detail: whatever gets it done to start with -- the best
  model that fits on the laptop. Gemma was named as a candidate.
- An `ocr` review on GitHub may count as a gate reviewer in place of
  Copilot.
- The work follows the SDLC process as documented in the skills.

**Still open (nobody's yet):**

- The name.

**Leans on:** [ollama-gateway](../ollama-gateway/CONCEPT.md); the
self-review skill and the Open Code Review Trial row (9atatimer/Skills PR
#77); the reusable-workflow pattern of `review-settled.yml`.
