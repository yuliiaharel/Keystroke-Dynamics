/**
 * Which kind of device this browser plays on
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 4). A phone taps
 * the on-page keyboard; a computer types on its physical one. The
 * server never compares the two, so a room is one or the other and
 * this is what the browser reports when it creates or joins one.
 *
 * A touchscreen laptop is a computer unless its user asks for the
 * on-page keyboard (the plan's open decision 2). That choice lasts
 * for the page, not across reloads: once a room exists, the server's
 * own record of this member is what counts.
 */

export type DeviceType = "keyboard" | "touch";

let onScreenKeyboard = false;

/** The primary pointer is a finger: a phone or a tablet. */
export function isPhone(): boolean {
  return window.matchMedia?.("(pointer: coarse)").matches ?? false;
}

/** A computer that also has a touchscreen, so it could use either. */
export function canChooseKeyboard(): boolean {
  return !isPhone() && (navigator.maxTouchPoints ?? 0) > 0;
}

export function deviceType(): DeviceType {
  return isPhone() || onScreenKeyboard ? "touch" : "keyboard";
}

export function chooseOnScreenKeyboard(on: boolean): void {
  onScreenKeyboard = on;
}

/** Sent with a touch room's create and join requests. The server
 * keeps only a size bucket (game/screen.py), never the width. */
export function viewportWidth(): number {
  return Math.max(1, Math.round(window.innerWidth));
}

/** Key shape changes where taps land, so a phone must be upright
 * while typing. A laptop using the on-page keyboard is always wide,
 * and is left alone. */
export function mustTurnUpright(): boolean {
  return isPhone() && (window.matchMedia?.("(orientation: landscape)").matches ?? false);
}
