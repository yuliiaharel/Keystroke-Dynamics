import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  COALESCE_MS,
  POLL_HIDDEN_MS,
  POLL_VISIBLE_MS,
  STREAM_RETRY_MS,
  STREAM_SILENCE_MS,
  watchRoom,
} from "./live";
import type { EventStream, LiveRoom } from "./live";

interface Room {
  version: number;
}

class FakeStream implements EventStream {
  readyState = 0;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }
  say(signal: unknown): void {
    this.onmessage?.({ data: typeof signal === "string" ? signal : JSON.stringify(signal) });
  }
  /** The connection dropped; the browser is reconnecting by itself. */
  drop(): void {
    this.readyState = 0;
    this.onerror?.();
  }
  /** The server answered with an error; the browser has given up. */
  refuse(): void {
    this.readyState = 2;
    this.onerror?.();
  }
}

class FakeDoc {
  visibilityState: DocumentVisibilityState = "visible";
  private listeners = new Set<() => void>();

  addEventListener(_type: string, listener: unknown): void {
    this.listeners.add(listener as () => void);
  }
  removeEventListener(_type: string, listener: unknown): void {
    this.listeners.delete(listener as () => void);
  }
  setVisibility(state: DocumentVisibilityState): void {
    this.visibilityState = state;
    this.listeners.forEach((listener) => listener());
  }
  get listenerCount(): number {
    return this.listeners.size;
  }
}

const GONE = { status: 404, detail: "no active room" };

/** One watcher, with the server and the browser both faked. */
function setup(options: { noEventSource?: boolean } = {}) {
  const world = {
    serverVersion: 0,
    onScreen: 0 as number | null,
    fetches: 0,
    rooms: [] as Room[],
    gone: 0,
    fetchError: null as unknown,
    streams: [] as FakeStream[],
    doc: new FakeDoc(),
    live: null as unknown as LiveRoom,
    get stream(): FakeStream {
      return this.streams[this.streams.length - 1]!;
    },
  };
  world.live = watchRoom<Room>({
    fetchRoom: async () => {
      world.fetches++;
      if (world.fetchError !== null) throw world.fetchError;
      return { version: world.serverVersion };
    },
    currentVersion: () => world.onScreen,
    onRoom: (room) => {
      world.rooms.push(room);
      world.onScreen = room.version;
    },
    onGone: () => {
      world.gone++;
    },
    isGone: (error) => (error as { status?: number }).status === 404,
    openStream: () => {
      if (options.noEventSource) return null;
      const stream = new FakeStream();
      world.streams.push(stream);
      return stream;
    },
    doc: world.doc as unknown as Document,
  });
  return world;
}

const advance = (ms: number): Promise<void> => vi.advanceTimersByTimeAsync(ms).then(() => undefined);

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("watchRoom with a working stream", () => {
  it("makes no request when the stream opens at the version already on screen", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    await advance(POLL_HIDDEN_MS * 3);
    expect(w.fetches).toBe(0);
    expect(w.rooms).toEqual([]);
  });

  it("fetches the room when the stream reports a new version", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.serverVersion = 1;
    w.stream.say({ version: 1 });
    await advance(COALESCE_MS);
    expect(w.fetches).toBe(1);
    expect(w.rooms).toEqual([{ version: 1 }]);
  });

  it("catches up when it reconnects to a version it missed", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.stream.drop();
    w.serverVersion = 4;
    w.stream.say({ version: 4 }); // the first thing a reopened stream sends
    await advance(COALESCE_MS);
    expect(w.rooms).toEqual([{ version: 4 }]);
  });

  it("combines signals that arrive close together into one request", async () => {
    const w = setup();
    for (let version = 1; version <= 5; version++) {
      w.serverVersion = version;
      w.stream.say({ version });
      await advance(COALESCE_MS / 10);
    }
    await advance(COALESCE_MS);
    expect(w.fetches).toBe(1);
    expect(w.rooms).toEqual([{ version: 5 }]);
  });

  it("never has two requests in flight: a signal during one means one more after", async () => {
    let finish: ((room: Room) => void) | null = null;
    let fetches = 0;
    let onScreen = 0;
    const stream = new FakeStream();
    watchRoom<Room>({
      fetchRoom: () => {
        fetches++;
        return new Promise<Room>((resolve) => {
          finish = resolve;
        });
      },
      currentVersion: () => onScreen,
      onRoom: (room) => {
        onScreen = room.version;
      },
      onGone: () => undefined,
      isGone: () => false,
      openStream: () => stream,
      doc: new FakeDoc() as unknown as Document,
    });

    stream.say({ version: 1 });
    await advance(COALESCE_MS);
    expect(fetches).toBe(1);

    stream.say({ version: 2 });
    stream.say({ version: 3 });
    await advance(COALESCE_MS * 5);
    expect(fetches).toBe(1); // still waiting on the first

    finish!({ version: 1 });
    await advance(0);
    expect(fetches).toBe(2);
    finish!({ version: 3 });
    await advance(COALESCE_MS * 5);
    expect(fetches).toBe(2);
    expect(onScreen).toBe(3);
  });

  it("does not hand over a room the page already has", async () => {
    const w = setup();
    w.serverVersion = 1;
    w.stream.say({ version: 1 });
    w.onScreen = 1; // the page's own action already fetched it
    await advance(COALESCE_MS);
    expect(w.rooms).toEqual([]);
  });

  it("does not poll while the stream is delivering", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    await advance(POLL_VISIBLE_MS * 10);
    expect(w.fetches).toBe(0);
  });

  it("asks for the room when the stream sends something unreadable", async () => {
    const w = setup();
    w.serverVersion = 2;
    w.stream.say("not json");
    await advance(COALESCE_MS);
    expect(w.rooms).toEqual([{ version: 2 }]);
  });
});

describe("watchRoom when the room is over", () => {
  it("closes the stream and reports the room gone once the server confirms it", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.fetchError = GONE;
    w.stream.say({ ended: true });
    await advance(0);
    expect(w.stream.closed).toBe(true);
    expect(w.gone).toBe(1);

    // Nothing keeps running afterwards.
    await advance(STREAM_RETRY_MS * 3);
    expect(w.fetches).toBe(1);
    expect(w.streams.length).toBe(1);
    expect(w.gone).toBe(1);
    expect(w.doc.listenerCount).toBe(0);
  });

  it("reports the room gone when a poll finds it missing", async () => {
    const w = setup();
    w.stream.refuse();
    w.fetchError = GONE;
    await advance(POLL_VISIBLE_MS);
    expect(w.gone).toBe(1);
    await advance(POLL_VISIBLE_MS * 5);
    expect(w.fetches).toBe(1);
  });

  it("keeps going through a failure that isn't 'gone'", async () => {
    const w = setup();
    w.stream.refuse();
    w.fetchError = { status: 500, detail: "oops" };
    await advance(POLL_VISIBLE_MS);
    expect(w.gone).toBe(0);

    w.fetchError = null;
    w.serverVersion = 1;
    await advance(POLL_VISIBLE_MS);
    expect(w.rooms).toEqual([{ version: 1 }]);
  });
});

describe("watchRoom falling back to polling", () => {
  it("polls every 5 seconds while visible when the stream is refused", async () => {
    const w = setup();
    w.stream.refuse();
    await advance(POLL_VISIBLE_MS - 1);
    expect(w.fetches).toBe(0);

    w.serverVersion = 1;
    await advance(1);
    expect(w.rooms).toEqual([{ version: 1 }]);

    w.serverVersion = 2;
    await advance(POLL_VISIBLE_MS);
    expect(w.rooms).toEqual([{ version: 1 }, { version: 2 }]);
    expect(w.fetches).toBe(2);
  });

  it("polls when there is no EventSource at all", async () => {
    const w = setup({ noEventSource: true });
    w.serverVersion = 1;
    await advance(POLL_VISIBLE_MS);
    expect(w.rooms).toEqual([{ version: 1 }]);
  });

  it("treats a stream that opens but stays silent as blocked", async () => {
    const w = setup();
    await advance(STREAM_SILENCE_MS);
    expect(w.stream.closed).toBe(true);

    w.serverVersion = 1;
    await advance(POLL_VISIBLE_MS);
    expect(w.rooms).toEqual([{ version: 1 }]);
  });

  it("polls while a dropped stream reconnects, and stops once it speaks again", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.stream.drop();
    expect(w.stream.closed).toBe(false); // the browser is retrying it

    w.serverVersion = 1;
    await advance(POLL_VISIBLE_MS);
    expect(w.rooms).toEqual([{ version: 1 }]);

    w.stream.say({ version: 1 });
    const before = w.fetches;
    await advance(POLL_VISIBLE_MS * 5);
    expect(w.fetches).toBe(before);
  });

  it("tries the stream again a minute after it was refused", async () => {
    const w = setup();
    w.stream.refuse();
    await advance(STREAM_RETRY_MS - 1);
    expect(w.streams.length).toBe(1);
    await advance(1);
    expect(w.streams.length).toBe(2);

    w.stream.say({ version: w.onScreen });
    const before = w.fetches;
    await advance(POLL_VISIBLE_MS * 5);
    expect(w.fetches).toBe(before);
  });

  it("slows to every 30 seconds while the page is hidden", async () => {
    const w = setup();
    w.stream.refuse();
    w.doc.setVisibility("hidden");
    await advance(POLL_HIDDEN_MS - 1);
    expect(w.fetches).toBe(0);
    await advance(1);
    expect(w.fetches).toBe(1);
    await advance(POLL_HIDDEN_MS);
    expect(w.fetches).toBe(2);
  });

  it("asks at once when the page becomes visible again, then every 5 seconds", async () => {
    const w = setup();
    w.stream.refuse();
    w.doc.setVisibility("hidden");
    await advance(1_000);
    w.serverVersion = 1;

    w.doc.setVisibility("visible");
    await advance(0);
    expect(w.rooms).toEqual([{ version: 1 }]);

    await advance(POLL_VISIBLE_MS);
    expect(w.fetches).toBe(2);
  });

  it("a visibility change starts no polling while the stream works", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.doc.setVisibility("hidden");
    w.doc.setVisibility("visible");
    // The stream opened on the way back works too.
    w.stream.say({ version: 0 });
    await advance(POLL_HIDDEN_MS * 2);
    // One request, made on coming back, and no polling after it.
    expect(w.fetches).toBe(1);
  });
});

describe("watchRoom when the page comes back", () => {
  it("fetches the room at once, even with a stream that looked fine", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.doc.setVisibility("hidden");
    // A locked phone: the room moved on, and the stream never said so.
    w.serverVersion = 3;

    w.doc.setVisibility("visible");
    await advance(0);
    expect(w.rooms).toEqual([{ version: 3 }]);
  });

  it("replaces the stream with a fresh one", async () => {
    const w = setup();
    const old = w.stream;
    old.say({ version: 0 });
    w.doc.setVisibility("hidden");

    w.doc.setVisibility("visible");
    expect(old.closed).toBe(true);
    expect(w.streams).toHaveLength(2);

    // The new stream is the one being listened to.
    w.serverVersion = 1;
    w.stream.say({ version: 1 });
    await advance(COALESCE_MS);
    expect(w.rooms).toEqual([{ version: 1 }]);
  });

  it("does nothing when the page is hidden", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.doc.setVisibility("hidden");
    await advance(0);
    expect(w.fetches).toBe(0);
    expect(w.streams).toHaveLength(1);
    expect(w.stream.closed).toBe(false);
  });

  it("falls back to polling when the fresh stream is refused", async () => {
    const w = setup();
    w.stream.say({ version: 0 });
    w.doc.setVisibility("hidden");
    w.doc.setVisibility("visible");
    await advance(0);
    expect(w.fetches).toBe(1);

    w.stream.refuse();
    await advance(POLL_VISIBLE_MS);
    expect(w.fetches).toBe(2);
  });

  it("opens a stream early when one was refused and waiting to be retried", async () => {
    const w = setup();
    w.stream.refuse();
    expect(w.streams).toHaveLength(1);
    w.doc.setVisibility("hidden");

    w.doc.setVisibility("visible");
    expect(w.streams).toHaveLength(2);
    // The retry that was pending doesn't open a third.
    w.stream.say({ version: 0 });
    await advance(STREAM_RETRY_MS);
    expect(w.streams).toHaveLength(2);
  });

  it("stays stopped after stop()", async () => {
    const w = setup();
    w.live.stop();
    w.doc.setVisibility("hidden");
    w.doc.setVisibility("visible");
    await advance(POLL_HIDDEN_MS);
    expect(w.fetches).toBe(0);
    expect(w.streams).toHaveLength(1);
  });
});

describe("watchRoom stopped", () => {
  it("closes the stream and makes no further requests", async () => {
    const w = setup();
    w.stream.refuse();
    w.live.stop();
    await advance(STREAM_RETRY_MS * 3);
    expect(w.fetches).toBe(0);
    expect(w.streams.length).toBe(1);
    expect(w.doc.listenerCount).toBe(0);
  });

  it("ignores a room request that was already in flight", async () => {
    const w = setup();
    w.serverVersion = 1;
    w.stream.say({ version: 1 });
    await vi.advanceTimersByTimeAsync(COALESCE_MS - 1);
    vi.advanceTimersByTime(1); // the request starts, but hasn't resolved
    w.live.stop();
    await advance(0);
    expect(w.fetches).toBe(1);
    expect(w.rooms).toEqual([]);
    expect(w.stream.closed).toBe(true);
  });
});
