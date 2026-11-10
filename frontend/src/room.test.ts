import { describe, expect, it } from "vitest";

import { formatCode, joinFailure, roomCodeFromPath, roomLink, roomPath, sameCode } from "./room";

describe("roomCodeFromPath", () => {
  it.each([
    ["/r/ABCDEFGH", "ABCDEFGH"],
    ["/r/abcd-efgh", "abcd-efgh"],
    ["/r/ABCDEFGH/", "ABCDEFGH"],
    ["/r/ABCD%20EFGH", "ABCD EFGH"],
    ["/r/nonsense", "nonsense"],
    ["/r/%E0%A4%A", "%E0%A4%A"],
  ])("reads %s as %s", (path, code) => {
    expect(roomCodeFromPath(path)).toBe(code);
  });

  it.each(["/", "/party", "/r", "/r/", "/r/ABCDEFGH/extra", "/x/r/ABCDEFGH"])(
    "says %s is not a room link",
    (path) => {
      expect(roomCodeFromPath(path)).toBeNull();
    },
  );
});

describe("codes", () => {
  it.each([
    ["ABCDEFGH", "abcd-efgh", true],
    ["ABCDEFGH", " abcd efgh ", true],
    ["ABCDEFGH", "ABCDEFGJ", false],
    ["ABCDEFGH", "ABCDEFG", false],
  ])("sameCode(%s, %s) is %s", (a, b, same) => {
    expect(sameCode(a, b)).toBe(same);
  });

  it("shows a code with a dash in the middle", () => {
    expect(formatCode("ABCDEFGH")).toBe("ABCD-EFGH");
    expect(formatCode("abcd-efgh")).toBe("ABCD-EFGH");
  });

  it("leaves something that isn't 8 characters alone", () => {
    expect(formatCode("ABC")).toBe("ABC");
  });

  it("builds the link without the dash", () => {
    expect(roomPath("abcd-efgh")).toBe("/r/ABCDEFGH");
    expect(roomLink("https://typingtwin.com", "ABCDEFGH")).toBe("https://typingtwin.com/r/ABCDEFGH");
  });
});

describe("joinFailure", () => {
  it.each([
    [404, "gone"],
    [423, "locked"],
    [409, "full"],
    [429, "rate-limited"],
    [500, "failed"],
    [null, "failed"],
  ] as const)("status %s is %s", (status, failure) => {
    expect(joinFailure(status)).toBe(failure);
  });
});
