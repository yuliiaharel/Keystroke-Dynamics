/**
 * One line tapped on the on-page keyboard: which key is expected
 * next, what each finger did, and the events to send for scoring
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 2).
 *
 * Pure: no DOM, so the rules are unit-tested here and the page only
 * feeds it pointer events (touch-keyboard.ts). Like capture.ts, it
 * records key codes and timing, plus where on the key each finger
 * landed -- never text from an input.
 */

import type { GameEvent } from "./game-api";

export const codeFor = (ch: string): string => (ch === " " ? "Space" : `Key${ch.toUpperCase()}`);

export interface Tap {
  ch: string;
  code: string;
  /** `event.timeStamp` of the landing and the lift, in milliseconds. */
  down: number;
  up: number | null;
  /** Offset from the key's center, in letter-key widths and heights. */
  dx: number;
  dy: number;
  /** The tap before this one was a wrong key. */
  afterError: boolean;
}

export type DownResult = "ok" | "wrong" | "ignored";

export class TapLine {
  readonly phrase: string;
  readonly taps: Tap[] = [];
  errors = 0;
  /** A recorded tap's touch was canceled by the browser, so its hold
   * is unknown and the line can't be scored. */
  broken = false;
  private pendingError = false;
  /** Fingers currently down. Null for one that landed on a wrong key. */
  private readonly held = new Map<number, Tap | null>();

  constructor(phrase: string) {
    this.phrase = phrase;
  }

  /** How many characters of the line have been tapped. */
  get index(): number {
    return this.taps.length;
  }

  /** Every character tapped and every finger lifted: nothing more can
   * change, and each down event has its up. */
  get complete(): boolean {
    return !this.broken && this.index === this.phrase.length && this.taps.every((t) => t.up !== null);
  }

  /** A finger landed. `code` is the key under it, or null between keys. */
  down(pointerId: number, code: string | null, t: number, dx: number, dy: number): DownResult {
    if (this.broken || this.index === this.phrase.length) return "ignored";
    const ch = this.phrase[this.index]!;
    const expected = codeFor(ch);
    // A key that's still held can't be pressed again: the scorer pairs
    // each down with the next up for the same key.
    const alreadyHeld = [...this.held.values()].some((tap) => tap !== null && tap.code === code);
    if (code !== expected || alreadyHeld) {
      this.errors += 1;
      this.pendingError = true;
      this.held.set(pointerId, null);
      return "wrong";
    }
    const tap: Tap = { ch, code: expected, down: t, up: null, dx, dy, afterError: this.pendingError };
    this.pendingError = false;
    this.taps.push(tap);
    this.held.set(pointerId, tap);
    return "ok";
  }

  /** A finger lifted. */
  up(pointerId: number, t: number): void {
    const tap = this.held.get(pointerId);
    this.held.delete(pointerId);
    // Never earlier than its own landing, whatever the browser reports.
    if (tap) tap.up = Math.max(t, tap.down);
  }

  /** The browser took a touch away (a system gesture, a notification).
   * A recorded tap that ends this way has no usable hold. */
  cancel(pointerId: number): void {
    const tap = this.held.get(pointerId);
    this.held.delete(pointerId);
    if (tap) this.broken = true;
  }

  /** The line as the game API takes it: times relative to the first
   * landing, in time order. Only meaningful once `complete`. */
  events(): GameEvent[] {
    const first = this.taps[0];
    if (!first) return [];
    const events: GameEvent[] = [];
    for (const tap of this.taps) {
      events.push({ code: tap.code, action: "down", t_ms: tap.down - first.down, dx: tap.dx, dy: tap.dy });
      if (tap.up !== null) events.push({ code: tap.code, action: "up", t_ms: tap.up - first.down });
    }
    // Overlapping thumbs lift out of landing order. A stable sort keeps
    // a down ahead of its own up when both carry the same time.
    return events.sort((a, b) => a.t_ms - b.t_ms);
  }
}
