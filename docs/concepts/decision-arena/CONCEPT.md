# Decision Arena

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)
> **Issue:** Issue#382

## The idea

Jev made a splash, and within weeks there were a dozen alternative Jevs. The
reason is that a decision model is the old idea made new again: a pretrained
model reads the input once, a small head on top scores a fixed set of
answers, and nothing is generated. It is BERT's shape with a modern
multimodal LLM underneath, and it is fast and cheap.

I want one of them running on my laptop, as a peer of my ollama: the
**decision arena**. Any decision model we run sits in the arena, behind an
nginx/haproxy layer -- the same LMDE proxy layer the Ollama Gateway puts in
front of the laptop -- so it can be reached locally and, through a
cloudflared gateway, from off the laptop the way ollama is.

Pick one model to start -- whatever we can actually run that gives valuable
results -- and prove it on real work. The first real work is the ocrinator:
analyzing the scanned PDFs in `~/gamestuff/two-to-the-fifth/`, where every
page today is judged by a generative model that is slow, gives no
probability, and disagrees with itself about page boundaries.

The arena is also a reason to think differently at architecture time. When a
design needs a bounded judgement -- yes or no, one of a few options, a score
on a rubric -- a decision model should be on the table next to rules and
next to a generative LLM, and an agent naming seams should know it is there.

## Story sets

| File | Theme |
|---|---|
| STORIES.asking.md | the callers who put a question to the arena, and what they get back |
| STORIES.choosing.md | the agent or human deciding whether a judgement belongs in the arena at all |

## Notes

**Settled in session (Todd's words):**

- The name is the decision arena.
- Decision models go on the LMDE radar at Trial.
- Any decision model we run goes behind an nginx/haproxy layer, so local
  inference can go through a cloudflared gateway, as it does for ollama.
- Start with one model, whatever we can run that will give valuable results.
- The first use is the ocrinator, for analyzing the PDFs.
- No installs and no model downloads yet.

**Recommended, not yet confirmed:** Clef-flash (Cloudflare, Apache-2.0) as the
first model. It is the only Clef variant the reference laptop can hold
(18.8 GB bf16 against Clef's 55.6 GB), and it reads images, which the
ocrinator needs. Whether it gives valuable results is exactly what the
ocrinator measurement is for.

**Leans on:** the Ollama Gateway (`docs/design/OLLAMA-GATEWAY.DESIGN.md`, at
REVIEW) for the proxy layer and the cloudflared road; neither is built.
Issue#382 records how the arena's needs should reach that design while it is
still in review.

**Still open (nobody's yet):**

- Whether the arena shares the gateway's hostname or has its own.
- Whether the arena runs inside the same sandbox as the external ollama.
- Whether the model runs well enough on Apple silicon; it was tested on CUDA.
- Whether hosted Jev is kept as a baseline to measure against.
