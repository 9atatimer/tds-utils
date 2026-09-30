// framing.ts -- contract v1 framing on the socket hop: a uint32
// little-endian length, then that many bytes of UTF-8 JSON (contract v1
// README, "Framing").

// --- Pure helpers ---

/** One frame for `message`. */
export function encodeFrame(message: unknown): Buffer {
  const body = Buffer.from(JSON.stringify(message), 'utf8');
  const header = Buffer.alloc(4);
  header.writeUInt32LE(body.length, 0);
  return Buffer.concat([header, body]);
}

// --- The decoder ---

/** Accumulates socket bytes and yields each complete frame's parsed JSON. */
export class FrameDecoder {
  private buffered = Buffer.alloc(0);

  push(chunk: Buffer): unknown[] {
    this.buffered = Buffer.concat([this.buffered, chunk]);
    const frames: unknown[] = [];
    while (this.buffered.length >= 4) {
      const length = this.buffered.readUInt32LE(0);
      if (this.buffered.length < 4 + length) break;
      frames.push(JSON.parse(this.buffered.subarray(4, 4 + length).toString('utf8')) as unknown);
      this.buffered = this.buffered.subarray(4 + length);
    }
    return frames;
  }
}
