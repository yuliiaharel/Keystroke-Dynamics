/**
 * Client for /api/game/* -- the anonymous party game's backend
 * (see api/game.py). Which room this browser is in, and which member
 * of it, rides the session cookie; this module never tracks a room,
 * member, or player id as something to prove ownership of, only as
 * an opaque value to pass back.
 */

import type { CapturedEvent } from "./capture";

export type Level = "sentence" | "long";
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
  /** The member (browser) that enrolled this player; equal to
   * PartyView.member_id when it's one of this browser's own. Null for
   * sample bots and the permanent target. */
  owner_member_id: string | null;
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
  /** This attempt's duration over the target's own usual duration,
   * where 1.0 is the same pace. Null exactly when distance is null. */
  pace: number | null;
  word: string;
  counted: boolean;
  passed: boolean | null;
  /** False when the typist's browser isn't the one the target was
   * enrolled on. Null where it doesn't apply: a bot target, a replay. */
  same_keyboard: boolean | null;
}

/** A room, as this browser's member sees it. */
export interface PartyView {
  id: string;
  /** 8 characters, no dash. The room's link is /r/<code>. */
  code: string;
  locked: boolean;
  /** This browser's own member id in the room. */
  member_id: string;
  is_host: boolean;
  member_count: number;
  /** Goes up on every change anyone in the room could see -- how
   * live.ts tells "the room changed" from a number alone. */
  version: number;
  level: Level;
  phrase: string;
  players: PlayerView[];
  targets: PlayerView[];
  attempts: AttemptView[];
  /** Whether the server saves scores. The score-saving memo and the
   * privacy text follow this -- never inferred any other way. */
  scores_enabled: boolean;
}

export interface AttemptResponse {
  attempt: AttemptView;
  verdict_text: string;
  /** One-line diagnosis (game/judge.py's _clue()) -- same
   * this-response-only treatment as verdict_text. Null exactly when
   * attempt.distance is null. */
  clue: string | null;
}

export interface ReplayResponse {
  attempt: AttemptView;
  verdict_text: string;
  clue: string | null;
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

/** The HTTP status of a rejected game-api call, or null for a failure
 * that never got an answer (offline, a dropped connection). */
export function errorStatus(error: unknown): number | null {
  const status = typeof error === "object" && error !== null ? (error as ApiError).status : undefined;
  return typeof status === "number" ? status : null;
}

/** True if `error` (from a rejected game-api call) means the room is
 * simply gone for this browser -- ended, expired, the process
 * restarted, or this member is no longer in it -- rather than a real
 * failure. Callers use this to show "this room has ended" instead of
 * a generic error. */
export function isRoomGone(error: unknown): boolean {
  return errorStatus(error) === 404;
}

/** Creates a room and joins it as host. A browser is in one room at a
 * time: the server takes it out of any room it was in. */
export function createRoom(level: Level): Promise<PartyView> {
  return request("POST", "/api/game/rooms", { level });
}

/** Joins by code -- any case, with or without the dash. Rejects with
 * 404 for a code that names no live room (never existed, ended, or
 * expired: the server answers all three alike), 423 for a locked
 * room, and 409 for a full one or, unless `leaveCurrent`, when this
 * browser is in another room. */
export function joinRoom(code: string, leaveCurrent: boolean): Promise<PartyView> {
  return request("POST", `/api/game/rooms/${encodeURIComponent(code)}/join`, {
    leave_current: leaveCurrent,
  });
}

export function getRoom(): Promise<PartyView> {
  return request("GET", "/api/game/room");
}

/** Takes this browser, and the players enrolled on it, out of its room. */
export function leaveRoom(): Promise<void> {
  return request("POST", "/api/game/rooms/leave");
}

/** Host only. */
export function lockRoom(locked: boolean): Promise<PartyView> {
  return request("POST", "/api/game/room/lock", { locked });
}

/** Host only: ends the room for everyone in it. */
export function endRoom(): Promise<void> {
  return request("POST", "/api/game/room/end");
}

/** A generated name no player in the room has yet. A suggestion
 * only: the server reserves nothing, and still checks the name that
 * createPlayer sends. */
export async function suggestName(): Promise<string> {
  const suggestion = await request<{ name: string }>("GET", "/api/game/room/name-suggestion");
  return suggestion.name;
}

export function createPlayer(
  name: string | null,
  trainingLines: CapturedEvent[][],
): Promise<PlayerView> {
  return request("POST", "/api/game/players", {
    name,
    training_lines: trainingLines,
  });
}

export function renamePlayer(id: string, name: string): Promise<PlayerView> {
  return request("PATCH", `/api/game/players/${encodeURIComponent(id)}`, { name });
}

/** One of this browser's own players, or any player for the host. */
export function deletePlayer(id: string): Promise<void> {
  return request("DELETE", `/api/game/room/players/${encodeURIComponent(id)}`);
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
