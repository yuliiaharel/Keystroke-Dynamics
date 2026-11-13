/**
 * Keeps a room on screen current without a refresh
 * (docs/plans/active/ROOMS_PLAN.md Phase 2).
 *
 * The event stream (GET /api/game/room/events) only ever says "the
 * room is at version N" or "this is over for you". Everything shown
 * comes from an ordinary room request made in response, so the
 * server's access checks apply to it like any other.
 *
 * If the stream fails, is refused, or opens but stays silent (a proxy
 * holding it back), this polls the room instead: every 5 seconds
 * while the page is visible, every 30 while it's hidden. Polling
 * stops again as soon as the stream delivers something.
 *
 * A phone that's locked, or a browser sent to the background, can lose
 * its stream without the page ever being told
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 4). So whenever
 * the page becomes visible again, it fetches the room and opens a
 * fresh stream, rather than trusting the old one.
 */

/** Signals this close together become one room request. */
export const COALESCE_MS = 100;
export const POLL_VISIBLE_MS = 5_000;
export const POLL_HIDDEN_MS = 30_000;
/** A working stream sends the room's version the moment it opens. */
export const STREAM_SILENCE_MS = 5_000;
/** How long to leave a stream that was refused or silent before trying again. */
export const STREAM_RETRY_MS = 60_000;

const EVENTS_PATH = "/api/game/room/events";
const CLOSED = 2; // EventSource.CLOSED

/** The part of EventSource this module uses, so tests can stand in for it. */
export interface EventStream {
  readyState: number;
  onmessage: ((event: { data: string }) => void) | null;
  onerror: (() => void) | null;
  close(): void;
}

export interface LiveRoomOptions<Room extends { version: number }> {
  fetchRoom: () => Promise<Room>;
  /** The version already on screen, so a signal about it costs no request. */
  currentVersion: () => number | null;
  /** Called with a room whose version differs from the one on screen. */
  onRoom: (room: Room) => void;
  /** Called once, when the room turns out to be gone for this browser. */
  onGone: () => void;
  isGone: (error: unknown) => boolean;
  /** Returns null where there is no EventSource at all. */
  openStream?: () => EventStream | null;
  doc?: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
}

export interface LiveRoom {
  stop(): void;
}

function openEventSource(): EventStream | null {
  if (typeof EventSource === "undefined") return null;
  // EventSource's handlers are typed to receive full DOM events;
  // this module only ever assigns narrower ones, which is safe.
  return new EventSource(EVENTS_PATH) as unknown as EventStream;
}

export function watchRoom<Room extends { version: number }>(options: LiveRoomOptions<Room>): LiveRoom {
  const doc = options.doc ?? document;
  const openStream = options.openStream ?? openEventSource;

  let stopped = false;
  let stream: EventStream | null = null;
  let fetching = false;
  let fetchAgain = false;
  let coalesceTimer: ReturnType<typeof setTimeout> | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let silenceTimer: ReturnType<typeof setTimeout> | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const clear = (timer: ReturnType<typeof setTimeout> | null): null => {
    if (timer !== null) clearTimeout(timer);
    return null;
  };

  function stop(): void {
    stopped = true;
    closeStream();
    coalesceTimer = clear(coalesceTimer);
    pollTimer = clear(pollTimer);
    retryTimer = clear(retryTimer);
    doc.removeEventListener("visibilitychange", onVisibilityChange);
  }

  /** One request at a time. A signal that lands mid-request means one
   * more afterwards, never two in flight. */
  async function refresh(): Promise<void> {
    if (stopped) return;
    if (fetching) {
      fetchAgain = true;
      return;
    }
    fetching = true;
    try {
      const room = await options.fetchRoom();
      if (!stopped && room.version !== options.currentVersion()) options.onRoom(room);
    } catch (error) {
      if (!stopped && options.isGone(error)) {
        stop();
        options.onGone();
      }
      // Anything else is a passing failure: the next signal or poll
      // asks again.
    } finally {
      fetching = false;
    }
    if (fetchAgain) {
      fetchAgain = false;
      void refresh();
    }
  }

  function refreshSoon(): void {
    if (stopped || coalesceTimer !== null) return;
    coalesceTimer = setTimeout(() => {
      coalesceTimer = null;
      void refresh();
    }, COALESCE_MS);
  }

  /* ---------- polling ---------- */

  function schedulePoll(): void {
    pollTimer = clear(pollTimer);
    pollTimer = setTimeout(
      () => {
        void refresh();
        schedulePoll();
      },
      doc.visibilityState === "visible" ? POLL_VISIBLE_MS : POLL_HIDDEN_MS,
    );
  }

  function startPolling(): void {
    if (!stopped && pollTimer === null) schedulePoll();
  }

  function stopPolling(): void {
    pollTimer = clear(pollTimer);
  }

  function onVisibilityChange(): void {
    if (doc.visibilityState === "visible") {
      // Coming back shouldn't mean waiting out a 30-second timer, or
      // trusting a stream that may have died while nobody was looking.
      void refresh();
      reconnect();
    }
    if (pollTimer !== null) schedulePoll();
  }

  /* ---------- the stream ---------- */

  function closeStream(): void {
    silenceTimer = clear(silenceTimer);
    if (stream === null) return;
    stream.onmessage = null;
    stream.onerror = null;
    stream.close();
    stream = null;
  }

  function giveUpOnStreamForNow(): void {
    closeStream();
    startPolling();
    retryTimer = clear(retryTimer);
    retryTimer = setTimeout(() => {
      retryTimer = null;
      connect();
    }, STREAM_RETRY_MS);
  }

  function connect(): void {
    if (stopped) return;
    const opened = openStream();
    if (opened === null) {
      startPolling();
      return;
    }
    stream = opened;
    silenceTimer = setTimeout(giveUpOnStreamForNow, STREAM_SILENCE_MS);

    opened.onmessage = (event) => {
      silenceTimer = clear(silenceTimer);
      stopPolling();
      let signal: { version?: number; ended?: boolean };
      try {
        signal = JSON.parse(event.data) as { version?: number; ended?: boolean };
      } catch {
        // Not something this server sends. Ask for the room rather
        // than guess what it meant.
        refreshSoon();
        return;
      }
      if (signal.ended) {
        // The server hangs up next. Close first, so the browser
        // doesn't reconnect, then let the room request confirm it.
        closeStream();
        startPolling();
        void refresh();
      } else if (signal.version !== options.currentVersion()) {
        refreshSoon();
      }
    };

    opened.onerror = () => {
      if (opened.readyState === CLOSED) {
        // Refused outright (a cap, or no room): the browser won't retry.
        giveUpOnStreamForNow();
      } else {
        // Dropped: the browser reconnects by itself. Poll until the
        // stream speaks again.
        startPolling();
      }
    };
  }

  /** Drops the stream, whatever state it's in, and opens a new one.
   * The new one says the room's version as it opens, like any other. */
  function reconnect(): void {
    closeStream();
    retryTimer = clear(retryTimer);
    connect();
  }

  doc.addEventListener("visibilitychange", onVisibilityChange);
  connect();
  return { stop };
}
