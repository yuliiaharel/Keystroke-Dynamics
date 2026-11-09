/**
 * The four descriptive stats on the party game's reveal screen,
 * calculated from a player's server-provided median timing
 * (PlayerView.notes) -- the same data the ring and roll are drawn
 * from, so they work for any player and after a reload. Display only,
 * never scored.
 */

import type { NoteView } from "./game-api";

export interface PairTiming {
  /** The two characters, in typing order. */
  pair: string;
  gapMs: number;
}

/** Each value is null when the notes can't support it. */
export interface Traits {
  wpm: number | null;
  typicalHoldMs: number | null;
  fastest: PairTiming | null;
  slowest: PairTiming | null;
}

function median(values: number[]): number | null {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)]! : null;
}

export function traitsFromNotes(notes: readonly NoteView[]): Traits {
  const first = notes[0];
  const last = notes[notes.length - 1];
  // First key down to last key down, at the usual five characters a word.
  const durationMs = first && last ? last.start_ms - first.start_ms : 0;
  const wpm =
    Number.isFinite(durationMs) && durationMs > 0
      ? Math.round(notes.length / 5 / (durationMs / 60000))
      : null;

  const hold = median(notes.map((n) => n.dur_ms));

  const gapsByPair = new Map<string, number[]>();
  notes.forEach((n, i) => {
    const prev = notes[i - 1];
    if (!prev) return;
    const pair = prev.ch + n.ch;
    const gaps = gapsByPair.get(pair) ?? [];
    gaps.push(n.start_ms - prev.start_ms);
    gapsByPair.set(pair, gaps);
  });
  const pairs: PairTiming[] = [];
  gapsByPair.forEach((gaps, pair) => {
    const gapMs = median(gaps);
    if (gapMs !== null) pairs.push({ pair, gapMs });
  });
  pairs.sort((a, b) => a.gapMs - b.gapMs);

  return {
    wpm,
    typicalHoldMs: hold === null ? null : Math.round(hold),
    fastest: pairs[0] ?? null,
    slowest: pairs[pairs.length - 1] ?? null,
  };
}
