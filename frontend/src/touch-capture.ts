/**
 * Turns a raw log of pointer events on the on-page touch keyboard into
 * taps, and reports anything a phone browser lost or delivered out of
 * order (MOBILE_PLAN.md Phase 0).
 *
 * Pure: no DOM access, so the same checks run in unit tests and on a
 * real phone. Used only by the debug capture test page for now.
 */

export type PointerPhase = "down" | "up" | "cancel";

/**
 * What a landing meant for the line being typed: the expected key, a
 * different key, the gap between keys, or a tap after the line ended.
 */
export type TapOutcome = "ok" | "wrong" | "between" | "idle";

export interface PointerRecord {
  phase: PointerPhase;
  pointerId: number;
  pointerType: string;
  /** `event.timeStamp`, in milliseconds. */
  t: number;
  trusted: boolean;
  /** Down only: the on-page key under the finger, or null between keys. */
  code: string | null;
  /** Down only: offset from the key's center, in letter-key widths/heights. */
  dx: number | null;
  dy: number | null;
  /** Down only. */
  outcome: TapOutcome | null;
}

export interface Tap {
  index: number;
  code: string | null;
  outcome: TapOutcome | null;
  pointerId: number;
  pointerType: string;
  downT: number;
  /** Null when the finger never lifted, or the touch was canceled. */
  upT: number | null;
  canceled: boolean;
  holdMs: number | null;
  /** Time since the previous tap landed. Null for the first tap. */
  gapMs: number | null;
  dx: number | null;
  dy: number | null;
  /** 2 for a complete tap (down, then up or cancel); 1 when the end never arrived. */
  events: number;
  /** Landed while an earlier finger was still down (two-thumb rollover). */
  overlapped: boolean;
}

export type ProblemKind = "missing_up" | "up_without_down" | "time_went_backwards" | "untrusted";

export interface Problem {
  kind: ProblemKind;
  /** Index into the record log. */
  at: number;
  detail: string;
}

export interface Analysis {
  taps: Tap[];
  problems: Problem[];
}

export function analyze(records: readonly PointerRecord[]): Analysis {
  const taps: Tap[] = [];
  const problems: Problem[] = [];
  const held = new Map<number, Tap>();
  let previousT: number | null = null;
  let previousDownT: number | null = null;

  records.forEach((r, at) => {
    if (previousT !== null && r.t < previousT) {
      problems.push({
        kind: "time_went_backwards",
        at,
        detail: `${r.phase} at ${r.t.toFixed(1)} ms arrived after an event at ${previousT.toFixed(1)} ms`,
      });
    }
    previousT = r.t;
    if (!r.trusted) {
      problems.push({ kind: "untrusted", at, detail: `${r.phase} was not a trusted event` });
    }

    if (r.phase === "down") {
      const stale = held.get(r.pointerId);
      if (stale) {
        // The browser reused a pointer id without ending the earlier
        // touch, so that tap's lift is lost for good.
        problems.push({
          kind: "missing_up",
          at,
          detail: `tap ${stale.index + 1} never lifted before pointer ${r.pointerId} landed again`,
        });
      }
      const tap: Tap = {
        index: taps.length,
        code: r.code,
        outcome: r.outcome,
        pointerId: r.pointerId,
        pointerType: r.pointerType,
        downT: r.t,
        upT: null,
        canceled: false,
        holdMs: null,
        gapMs: previousDownT === null ? null : r.t - previousDownT,
        dx: r.dx,
        dy: r.dy,
        events: 1,
        // A stale entry for this same pointer id isn't a second finger.
        overlapped: held.size - (stale ? 1 : 0) > 0,
      };
      previousDownT = r.t;
      taps.push(tap);
      held.set(r.pointerId, tap);
      return;
    }

    const tap = held.get(r.pointerId);
    if (!tap) {
      problems.push({
        kind: "up_without_down",
        at,
        detail: `${r.phase} for pointer ${r.pointerId} had no matching down`,
      });
      return;
    }
    held.delete(r.pointerId);
    tap.events = 2;
    if (r.phase === "cancel") {
      tap.canceled = true;
    } else {
      tap.upT = r.t;
      tap.holdMs = r.t - tap.downT;
    }
  });

  held.forEach((tap) => {
    problems.push({
      kind: "missing_up",
      at: records.length,
      detail: `tap ${tap.index + 1} never lifted`,
    });
  });

  return { taps, problems };
}

export interface Spread {
  n: number;
  min: number;
  median: number;
  max: number;
  mean: number;
}

/** Null for an empty list, so a caller can't mistake "no data" for zeros. */
export function spread(values: readonly number[]): Spread | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
  return {
    n: sorted.length,
    min: sorted[0]!,
    median,
    max: sorted[sorted.length - 1]!,
    mean: sorted.reduce((a, b) => a + b, 0) / sorted.length,
  };
}

/**
 * The smallest non-zero step between any two event timestamps: how
 * finely this browser reports time. Null with fewer than two distinct
 * timestamps.
 */
export function timestampStep(records: readonly PointerRecord[]): number | null {
  const times = [...new Set(records.map((r) => r.t))].sort((a, b) => a - b);
  let step: number | null = null;
  for (let i = 1; i < times.length; i++) {
    const d = times[i]! - times[i - 1]!;
    if (step === null || d < step) step = d;
  }
  return step;
}
