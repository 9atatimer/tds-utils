/// <reference types="node" />
// golden.test.ts -- the extension's zod schemas against contract v1's golden files.
//
// Contract v1 README, "Validation": the extension's zod schemas MUST accept
// every file in examples/valid/ and reject every file in examples/invalid/.
// Reading those files is the one fixture I/O the suite allows.

import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import type { z } from 'zod';
import { EventSchema, MessageSchema, RequestSchema, ResponseSchema } from '../../src/wire/messages.js';

// --- Constants ---

const CONTRACT = fileURLToPath(new URL('../../../contract/v1/', import.meta.url));
const VALID_DIR = `${CONTRACT}examples/valid/`;
const INVALID_DIR = `${CONTRACT}examples/invalid/`;

interface InvalidRule {
  readonly keyword: string;
  readonly path: string;
  readonly rule: string;
}

/**
 * Invalid examples the extension is NOT expected to reject, each with the
 * reason from examples/invalid-rules.json: rules that only the daemon side
 * or check.py enforces. Empty today -- every v1 invalid example breaks a
 * rule zod states. An entry here must name a real invalid file, and that
 * file must in fact be accepted, so the list cannot rot.
 */
const ENFORCED_ELSEWHERE: Readonly<Record<string, string>> = {};

// --- Helpers ---

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8')) as unknown;
}

function jsonFiles(dir: string): string[] {
  return readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .sort();
}

/** JSON pointers of every issue; an unknown key is located at the key itself, as JSON Schema reports it. */
function issuePointers(error: z.ZodError): string[] {
  return error.issues.flatMap((issue) => {
    const base = issue.path.map((p) => `/${String(p)}`).join('');
    return issue.code === 'unrecognized_keys' ? issue.keys.map((k) => `${base}/${k}`) : [base];
  });
}

/** True when an issue sits at the rule's instance path or below it. */
function isAtOrBelow(pointer: string, rulePath: string): boolean {
  return pointer === rulePath || pointer.startsWith(`${rulePath}/`);
}

interface SchemaDef {
  readonly properties?: Readonly<Record<string, { readonly const?: unknown }>>;
}

interface ContractSchema {
  readonly oneOf: readonly { readonly $ref: string }[];
  readonly $defs: Readonly<Record<string, SchemaDef>>;
}

/** The contract's message types, each with the direction its envelope field implies. */
function contractMessageTypes(): Map<string, 'request' | 'response' | 'event'> {
  const schema = readJson(`${CONTRACT}messages.schema.json`) as ContractSchema;
  const out = new Map<string, 'request' | 'response' | 'event'>();
  for (const { $ref } of schema.oneOf) {
    const props = schema.$defs[$ref.replace('#/$defs/', '')]?.properties ?? {};
    const direction = 'id' in props ? 'request' : 'event_id' in props ? 'event' : 'response';
    out.set(String(props['type']?.const), direction);
  }
  return out;
}

// --- Tests ---

const RULES = readJson(`${CONTRACT}examples/invalid-rules.json`) as Readonly<Record<string, InvalidRule>>;

describe('contract v1 valid examples', () => {
  it.each(jsonFiles(VALID_DIR))('Given valid/%s, When the extension parses it, Then it is accepted', (file) => {
    const result = MessageSchema.safeParse(readJson(`${VALID_DIR}${file}`));
    expect(result.error?.issues).toBeUndefined();
  });
});

describe('contract v1 invalid examples', () => {
  const rejected = jsonFiles(INVALID_DIR).filter((f) => !(f in ENFORCED_ELSEWHERE));

  it.each(rejected)('Given invalid/%s, When the extension parses it, Then it is rejected at the rule the contract names', (file) => {
    const rule = RULES[file];
    expect(rule, `invalid-rules.json names ${file}`).toBeDefined();
    const result = MessageSchema.safeParse(readJson(`${INVALID_DIR}${file}`));
    expect(result.success).toBe(false);
    const pointers = result.error ? issuePointers(result.error) : [];
    expect(
      pointers.some((p) => isAtOrBelow(p, rule?.path ?? '')),
      `${rule?.rule}: issues at ${pointers.join(', ')}`,
    ).toBe(true);
  });

  it('Given the allowlist of rules enforced elsewhere, When checked, Then each entry names an invalid file the extension accepts', () => {
    for (const file of Object.keys(ENFORCED_ELSEWHERE)) {
      expect(RULES[file]).toBeDefined();
      expect(MessageSchema.safeParse(readJson(`${INVALID_DIR}${file}`)).success).toBe(true);
    }
  });
});

describe('contract v1 message set', () => {
  it("Given the contract schema, When its message types are compared with the zod union's, Then the sets are equal", () => {
    const zodTypes = MessageSchema.options.map((o) => o.shape.type.value);
    expect(new Set(zodTypes)).toEqual(new Set(contractMessageTypes().keys()));
    expect(zodTypes).toHaveLength(new Set(zodTypes).size);
  });

  it('Given the contract schema, When each message is classified by its envelope, Then the zod request, response and event unions match', () => {
    const byDirection = (d: string): Set<string> =>
      new Set([...contractMessageTypes()].filter(([, dir]) => dir === d).map(([type]) => type));
    expect(new Set(RequestSchema.options.map((o) => o.shape.type.value))).toEqual(byDirection('request'));
    expect(new Set(ResponseSchema.options.map((o) => o.shape.type.value))).toEqual(byDirection('response'));
    expect(new Set(EventSchema.options.map((o) => o.shape.type.value))).toEqual(byDirection('event'));
  });
});
