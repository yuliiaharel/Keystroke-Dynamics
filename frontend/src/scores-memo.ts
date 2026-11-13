/**
 * The fine-print notice that this site saves a few numbers about each
 * result. Information only: scores are saved for every attempt, so
 * there is nothing to tick or press.
 *
 * A material change to this wording goes with a bump of
 * NOTICE_VERSION in src/keystroke_dynamics/scores/recording.py, which
 * is stamped on every stored row.
 */

export const SCORES_MEMO_TEXT =
  "This site saves a few numbers about each result: pace, how close it came to the limit, and whether it passed. Never your name, your keystrokes, or your IP address. Your attempts in this party are grouped under a random ID that isn't linked to your name.";

/** The same notice for a touch room, whose stored rows also hold the
 * Rhythm and Place scores and a rough screen size
 * (scores/recording.py), and never a tap. */
export const TOUCH_SCORES_MEMO_TEXT =
  "This site saves a few numbers about each result: pace, the Rhythm and Place scores, how close it came to the limit, whether it passed, whether it was tapped on the target's own phone, and a rough screen size. Never your name, your taps, where or when they landed, or your IP address. Your attempts in this room are grouped under a random ID that isn't linked to your name.";

/** Empty unless the server says score collection is on
 * (PartyView.scores_enabled), so the text matches what the server
 * does: with no scores database, nothing is saved. */
export function scoresMemoHTML(scoresEnabled: boolean, touch = false): string {
  if (!scoresEnabled) return "";
  return `<p class="small muted" id="scores-memo" style="max-width:60ch">${touch ? TOUCH_SCORES_MEMO_TEXT : SCORES_MEMO_TEXT}</p>`;
}
