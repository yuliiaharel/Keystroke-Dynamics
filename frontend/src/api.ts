import type { CapturedEvent } from "./capture";

export type Decision = "match" | "no_match" | "insufficient_data";

export interface TypingResult {
  decision: Decision;
  score: number | null;
  compared_features: number;
}

export interface LoginResponse {
  typing_result: TypingResult | null;
}

export interface ApiError {
  status: number;
  detail: string;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw { status: response.status, detail } satisfies ApiError;
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export function register(username: string, password: string): Promise<void> {
  return postJson("/api/register", { username, password });
}

export function login(
  username: string,
  password: string,
  sample?: CapturedEvent[],
): Promise<LoginResponse> {
  return postJson("/api/login", { username, password, sample: sample ?? null });
}

export function logout(): Promise<void> {
  return postJson("/api/logout", undefined);
}

export function addSample(events: CapturedEvent[]): Promise<{ sample_count: number }> {
  return postJson("/api/profile/samples", { events });
}

export function verifySample(events: CapturedEvent[]): Promise<TypingResult> {
  return postJson("/api/profile/verify", { events });
}

export async function deleteProfile(): Promise<void> {
  const response = await fetch("/api/profile", { method: "DELETE" });
  if (!response.ok) {
    throw { status: response.status, detail: await response.text() } satisfies ApiError;
  }
}
