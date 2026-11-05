import type { ApiError } from "./api";
import type { TypingResult } from "./api";

/** Looks up a required element by id, throwing early (at page load,
 * not mid-handler) if a template and script ever drift apart. */
export function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`expected an element with id "${id}"`);
  }
  return element as T;
}

export function showError(el: HTMLElement, error: unknown): void {
  const message = isApiError(error) ? error.detail : String(error);
  el.textContent = message;
  el.hidden = false;
}

export function clearError(el: HTMLElement): void {
  el.textContent = "";
  el.hidden = true;
}

function isApiError(error: unknown): error is ApiError {
  return typeof error === "object" && error !== null && "status" in error && "detail" in error;
}

/**
 * Renders a typing result as a labelled state, never color alone:
 * each decision gets its own text label and a symbol prefix, plus the
 * numeric score and how many features were actually compared.
 */
export function renderTypingResult(el: HTMLElement, result: TypingResult): void {
  const labels: Record<TypingResult["decision"], { symbol: string; text: string }> = {
    match: { symbol: "✓", text: "MATCH" },
    no_match: { symbol: "✗", text: "NO MATCH" },
    insufficient_data: { symbol: "?", text: "INSUFFICIENT DATA" },
  };
  const label = labels[result.decision];
  const scoreText = result.score === null ? "n/a" : result.score.toFixed(4);

  el.className = `result result--${result.decision}`;
  el.textContent =
    `${label.symbol} ${label.text} ` +
    `(score: ${scoreText}, features compared: ${result.compared_features})`;
  el.hidden = false;
}
