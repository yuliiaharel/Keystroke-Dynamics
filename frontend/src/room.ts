/**
 * Room links and codes (docs/plans/active/ROOMS_PLAN.md Phase 3). Pure
 * helpers, kept apart from pages/party.ts so they can be tested
 * without a page. The server decides what a valid code is
 * (game/codes.py); nothing here is a security check.
 */

const ROOM_PATH = /^\/r\/([^/]+)\/?$/;

/** The code in a room link's path, exactly as written there, or null
 * when the path isn't a room link. */
export function roomCodeFromPath(path: string): string | null {
  const match = ROOM_PATH.exec(path);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]!);
  } catch {
    // A malformed escape can't be a code; the server says "not found"
    // to whatever this is, like any other wrong link.
    return match[1]!;
  }
}

/** A code the way the server stores it: upper case, with no dash or
 * spaces. Only for comparing two codes -- the server does its own
 * normalizing and is the one that decides what's valid. */
export function normalizeCode(code: string): string {
  return code.toUpperCase().replace(/[-\s]/g, "");
}

export function sameCode(a: string, b: string): boolean {
  return normalizeCode(a) === normalizeCode(b);
}

/** `ABCDEFGH` shown as `ABCD-EFGH`, which is easier to read aloud. */
export function formatCode(code: string): string {
  const c = normalizeCode(code);
  return c.length === 8 ? `${c.slice(0, 4)}-${c.slice(4)}` : c;
}

export function roomPath(code: string): string {
  return `/r/${normalizeCode(code)}`;
}

export function roomLink(origin: string, code: string): string {
  return `${origin}${roomPath(code)}`;
}

/** Why a room link couldn't be opened, from the join request's HTTP
 * status (null: no answer at all). The server also uses 409 for
 * "you're in another room"; pages/party.ts asks about that before it
 * ever sends a join, so here 409 is a full room. */
export type JoinFailure = "gone" | "locked" | "full" | "rate-limited" | "failed";

export function joinFailure(status: number | null): JoinFailure {
  if (status === 404) return "gone";
  if (status === 423) return "locked";
  if (status === 409) return "full";
  if (status === 429) return "rate-limited";
  return "failed";
}
