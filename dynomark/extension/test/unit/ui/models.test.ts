// models.test.ts -- Security Considerations, "Cloud model egress": the user
// can see when page text or questions leave the machine. Both models reach
// the user's data (the completion model every question, the embedding model
// every query and every page's text), so the chat surface and the options
// page name both, each with its own mark (issue #411).

import { describe, expect, it } from 'vitest';
import { modelText, modelsText } from '../../../src/ui/models.js';

describe('Cloud model egress -- both models are shown with their local mark', () => {
  it('Given a local embedding model and a cloud completion model, When the chat line is made, Then it names both and marks the completion cloud', () => {
    const text = modelsText({
      embedding: { id: 'ollama:nomic-embed-text', local: true },
      completion: { id: 'ollama:gpt-oss:120b-cloud', local: false },
    });
    expect(text).toContain('ollama:nomic-embed-text (local)');
    expect(text).toContain('ollama:gpt-oss:120b-cloud (cloud)');
  });

  it('Given both models cloud, When the chat line is made, Then it says page text and questions leave this machine', () => {
    const text = modelsText({ embedding: { id: 'ollama:e', local: false }, completion: { id: 'ollama:c', local: false } });
    expect(text).toMatch(/leave this machine/);
  });

  it.each([
    { cloud: 'completion', embedding: true, completion: false },
    { cloud: 'embedding', embedding: false, completion: true },
  ])(
    'Given only the $cloud model cloud, When the chat line is made, Then it still says page text and questions leave this machine',
    ({ embedding, completion }) => {
      const text = modelsText({ embedding: { id: 'ollama:e', local: embedding }, completion: { id: 'ollama:c', local: completion } });
      expect(text).toMatch(/Page text and questions leave this machine\.$/);
    },
  );

  it('Given both models local, When the chat line is made, Then it does not say anything leaves the machine', () => {
    const text = modelsText({ embedding: { id: 'ollama:e', local: true }, completion: { id: 'ollama:c', local: true } });
    expect(text).not.toMatch(/leave/);
  });

  it('Given one model, When its options row is made, Then it carries its id and mark', () => {
    expect(modelText({ id: 'ollama:llama3.1:8b', local: true })).toBe('ollama:llama3.1:8b (local)');
    expect(modelText({ id: 'ollama:llama3.1:cloud', local: false })).toBe('ollama:llama3.1:cloud (cloud)');
  });
});
