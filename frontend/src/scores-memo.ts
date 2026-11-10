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

/** Empty unless the server says score collection is on
 * (PartyView.scores_enabled), so the text matches what the server
 * does: with no scores database, nothing is saved. */
export function scoresMemoHTML(scoresEnabled: boolean): string {
  if (!scoresEnabled) return "";
  return `<p class="small muted" id="scores-memo" style="max-width:60ch">${SCORES_MEMO_TEXT}</p>`;
}
