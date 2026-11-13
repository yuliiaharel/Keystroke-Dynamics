/**
 * The on-page keyboard a touch room is played on, taken from
 * design/typing-twin-touch.html, and the pointer events that feed it
 * (docs/plans/active/MOBILE_PLAN.md Phase 2 section 2).
 *
 * It's a set of plain elements, never a text input, so the phone's
 * own keyboard stays closed. What it reports is which key a finger
 * landed on, when, and where on the key -- as offsets in letter-key
 * widths and heights, so they don't depend on screen size.
 */

const ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"];

const codeOf = (ch: string): string => `Key${ch.toUpperCase()}`;

export function keyboardHTML(): string {
  const rows = ROWS.map(
    (row) =>
      `<div class="kb-row">${[...row].map((c) => `<div class="key" data-code="${codeOf(c)}">${c}</div>`).join("")}</div>`,
  ).join("");
  // Hidden from assistive technology: the keys measure where and when
  // a finger lands, which a screen reader's touch exploration replaces
  // with its own gestures. The page says so in words instead.
  return `<div class="kb" aria-hidden="true">${rows}<div class="kb-row"><div class="key space" data-code="Space">space</div></div></div>`;
}

export interface KeyboardHandlers {
  /** A finger landed. `code` is null when it landed between keys. */
  onDown(pointerId: number, code: string | null, t: number, dx: number, dy: number): void;
  onUp(pointerId: number, t: number): void;
  onCancel(pointerId: number): void;
  /** A mouse click, which isn't a touch signature. */
  onMouse(): void;
}

/**
 * Wires `keyboard` (already filled with keyboardHTML) to `handlers`.
 * Listens for the life of the page: the game has one keyboard element.
 */
export function attachKeyboard(
  keyboard: HTMLElement,
  handlers: KeyboardHandlers,
  options: { allowMouse: () => boolean },
): void {
  //: Which key each finger is lighting up, so a lift only clears its own.
  const lit = new Map<number, HTMLElement>();
  //: Fingers that landed on the keyboard. A lift anywhere else on the
  //: page (a button, a link) is none of this module's business.
  const landed = new Set<number>();

  keyboard.addEventListener("pointerdown", (e) => {
    // Stops text selection, the long-press callout, and focus moving
    // to something that would open the system keyboard.
    e.preventDefault();
    // Scripted events aren't someone's typing.
    if (!e.isTrusted) return;
    if (e.pointerType === "mouse" && !options.allowMouse()) {
      handlers.onMouse();
      return;
    }
    const key = e.target instanceof Element ? e.target.closest<HTMLElement>(".key") : null;
    const unit = keyboard.querySelector('.key[data-code="KeyA"]')?.getBoundingClientRect();
    let dx = 0;
    let dy = 0;
    if (key && unit && unit.width > 0 && unit.height > 0) {
      const box = key.getBoundingClientRect();
      dx = (e.clientX - (box.left + box.width / 2)) / unit.width;
      dy = (e.clientY - (box.top + box.height / 2)) / unit.height;
      key.classList.add("down");
      lit.set(e.pointerId, key);
    }
    try {
      // Absent on iOS, and never relied on.
      navigator.vibrate?.(6);
    } catch {
      /* Haptics are optional. */
    }
    landed.add(e.pointerId);
    handlers.onDown(e.pointerId, key?.dataset.code ?? null, e.timeStamp, dx, dy);
  });

  const release = (e: PointerEvent): void => {
    lit.get(e.pointerId)?.classList.remove("down");
    lit.delete(e.pointerId);
    if (!landed.delete(e.pointerId) || !e.isTrusted) return;
    if (e.type === "pointercancel") handlers.onCancel(e.pointerId);
    else handlers.onUp(e.pointerId, e.timeStamp);
  };
  // On the document, so a finger that slides off the keyboard still
  // ends its tap.
  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);

  // The long-press menu, and double-tap zoom where touch-action alone
  // doesn't stop it. Both only on the keyboard: the rest of the page
  // scrolls and zooms as usual.
  keyboard.addEventListener("contextmenu", (e) => e.preventDefault());
  keyboard.addEventListener("dblclick", (e) => e.preventDefault());
}

/** Lights a key for a replay, where no finger is involved. */
export function flashKey(keyboard: HTMLElement, code: string, ms: number): void {
  const key = keyboard.querySelector<HTMLElement>(`.key[data-code="${code}"]`);
  if (!key) return;
  key.classList.add("down");
  setTimeout(() => key.classList.remove("down"), Math.max(60, ms));
}
