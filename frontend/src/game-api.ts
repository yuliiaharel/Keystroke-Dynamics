/**
 * Client for /api/game/* -- the anonymous party game's backend
 * (see api/game.py). Party identity rides the session cookie; this
 * module never tracks a party or player id as something to prove
 * ownership of, only as an opaque value to pass back.
 */

import type { CapturedEvent } from "./capture";

export type Level = "word" | "sentence" | "long";
export type Mode = "attack" | "self" | "disguise" | "replay";
export type TargetKind = "player" | "sample" | "target";

export interface NoteView {
  ch: string;
  start_ms: number;
  dur_ms: number;
}

export interface PlayerView {
  id: string;
  name: string;
  color: number;
  threshold: number;
  notes: NoteView[];
  kind: TargetKind;
}

export interface AttemptView {
  id: string;
  typist_name: string;
  target_id: string;
  target_name: string;
  mode: Mode;
  distance: number | null;
  threshold: number;
  ratio: number | null;
  word: string;
  counted: boolean;
  passed: boolean | null;
}

export interface PartyView {
  id: string;
  level: Level;
  phrase: string;
  players: PlayerView[];
  targets: PlayerView[];
  attempts: AttemptView[];
}

export interface AttemptResponse {
  attempt: AttemptView;
  verdict_text: string;
}

export interface ReplayResponse {
  attempt: AttemptView;
  verdict_text: string;
  notes: NoteView[];
}

export interface ApiError {
  status: number;
  detail: string;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw { status: response.status, detail: await response.text() } satisfies ApiError;
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** True if `error` (from a rejected game-api call) means the party is
 * simply gone -- expired, or the process restarted -- rather than a
 * real failure. Callers use this to show "your party disappeared"
 * instead of a generic error. */
export function isPartyGone(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as ApiError).status === 404;
}

export function createParty(level: Level): Promise<PartyView> {
  return request("POST", "/api/game/party", { level });
}

export function getParty(): Promise<PartyView> {
  return request("GET", "/api/game/party");
}

export function resetParty(): Promise<void> {
  return request("POST", "/api/game/party/reset");
}

export function createPlayer(
  name: string | null,
  trainingLines: CapturedEvent[][],
): Promise<PlayerView> {
  return request("POST", "/api/game/players", { name, training_lines: trainingLines });
}

export function renamePlayer(id: string, name: string): Promise<PlayerView> {
  return request("PATCH", `/api/game/players/${encodeURIComponent(id)}`, { name });
}

export function deletePlayer(id: string): Promise<void> {
  return request("DELETE", `/api/game/players/${encodeURIComponent(id)}`);
}

export function submitAttempt(params: {
  typistId: string | null;
  targetId: string;
  mode: "attack" | "self" | "disguise";
  events: CapturedEvent[];
  clientAttemptId: string;
}): Promise<AttemptResponse> {
  return request("POST", "/api/game/attempts", {
    typist_id: params.typistId,
    target_id: params.targetId,
    mode: params.mode,
    events: params.events,
    client_attempt_id: params.clientAttemptId,
  });
}

export function submitReplay(targetId: string): Promise<ReplayResponse> {
  return request("POST", "/api/game/replay", { target_id: targetId });
}
