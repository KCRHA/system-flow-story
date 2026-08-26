import { useEffect, useRef, useState } from "react";

const NOISE_FLOOR = 4;
// Separate same-direction scroll *gestures* that land while blocked by the
// step cooldown (not raw wheel events — see GESTURE_GAP_MS) before we read
// that as "let me through" rather than "make me wait" and release the trap
// early.
const IMPATIENCE_THRESHOLD = 3;
// A wheel event arriving this long after the previous one starts a new
// physical gesture rather than continuing the last one. A single trackpad
// swipe/mouse spin fires a rapid, near-continuous stream of events as it
// decelerates — often for a second or more — so counting *events* blocked
// by the cooldown (the original approach) reliably blew past any
// impatience threshold within one swipe's momentum tail alone, releasing
// the trap after just one step. Counting distinct gestures instead means a
// single swipe, however long its momentum train, only ever counts once;
// only genuinely repeated attempts to scroll while blocked read as
// impatience.
const GESTURE_GAP_MS = 120;

/**
 * Pins a section in place and maps each wheel notch to one step of external
 * state (e.g. a month index), instead of letting the page scroll through it.
 * Trap releases automatically once the caller is at minIndex/maxIndex and
 * scrolls further in that direction, letting the page scroll on normally —
 * and re-engages immediately if the user reverses direction, even before
 * they've scrolled all the way out (see releasedDirRef below).
 *
 * Relies on `sectionRef`'s element being CSS-sticky and taller than its
 * sticky child (see .flow-scrubber-wrap/.flow-scrubber-sticky) — that
 * height difference is a scroll-position "buffer zone" that CSS alone
 * keeps visually pinned, which is what gives the trap room to engage
 * before a fast scroll could carry the page past it.
 */
export default function useScrollJack({
  sectionRef,
  activeIndex,
  minIndex = 0,
  maxIndex,
  onStep,
  cooldownMs = 550,
  enabled = true,
}) {
  const [isPinned, setIsPinned] = useState(false);
  const activeIndexRef = useRef(activeIndex);
  // 0 = trapping normally; 1 or -1 = the trap released while continuing in
  // that direction (still visually stuck via CSS, but letting the user
  // scroll on through). Reversing direction re-engages the trap instantly;
  // otherwise it clears once the buffer is fully exited (see check() below).
  const releasedDirRef = useRef(0);
  // -Infinity (not 0): performance.now() is relative to navigation start, so
  // it can still be a small number when the user's first scroll notch
  // arrives — comparing against 0 would wrongly cooldown-block that step.
  const lastStepAtRef = useRef(-Infinity);
  const impatientCountRef = useRef(0);
  const impatientDirRef = useRef(0);
  // Same -Infinity rationale as lastStepAtRef — and doubles as "no wheel
  // event seen yet" so the very first event is never mistaken for a
  // continuation of some prior gesture.
  const lastWheelAtRef = useRef(-Infinity);

  useEffect(() => {
    activeIndexRef.current = activeIndex;
  }, [activeIndex]);

  // Tracks whether we're within the sticky buffer zone at all (pure scroll
  // position) — this drives isPinned (CSS class / hint text), independent
  // of whether the trap is currently engaged or mid-release.
  useEffect(() => {
    if (!enabled) {
      setIsPinned(false);
      return;
    }
    const el = sectionRef.current;
    if (!el) return;

    let ticking = false;
    const check = () => {
      ticking = false;
      // Rounded: sub-pixel layout/scroll rounding can leave `top` a
      // fraction of a pixel off zero (e.g. 0.09) even when visually at
      // the boundary — a strict <= 0 would wrongly miss that.
      const top = Math.round(el.getBoundingClientRect().top);
      const buffer = Math.max(0, el.offsetHeight - window.innerHeight);
      const inBuffer = top <= 0 && top > -buffer;
      if (!inBuffer) releasedDirRef.current = 0; // fully exited; clean slate for next entry
      setIsPinned(inBuffer);
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(check);
    };

    check();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [sectionRef, enabled]);

  useEffect(() => {
    if (!enabled || !isPinned) return;

    const onWheel = (e) => {
      let deltaY = e.deltaY;
      if (e.deltaMode === 1) deltaY *= 16;
      else if (e.deltaMode === 2) deltaY *= window.innerHeight;

      if (Math.abs(deltaY) < NOISE_FLOOR) {
        if (releasedDirRef.current === 0) e.preventDefault();
        return;
      }

      const delta = deltaY > 0 ? 1 : -1;

      if (releasedDirRef.current !== 0) {
        if (delta === releasedDirRef.current) return; // still leaving — let it scroll
        releasedDirRef.current = 0; // reversed direction — re-engage below
      }

      const atUpperBound = delta > 0 && activeIndexRef.current >= maxIndex;
      const atLowerBound = delta < 0 && activeIndexRef.current <= minIndex;
      if (atUpperBound || atLowerBound) {
        // Release and let this event pass through natively so the page
        // starts scrolling in the same gesture, no dead scroll tick.
        releasedDirRef.current = delta;
        return;
      }

      if (delta !== impatientDirRef.current) {
        impatientDirRef.current = delta;
        impatientCountRef.current = 0;
      }

      e.preventDefault();

      const now = performance.now();
      const isNewGesture = now - lastWheelAtRef.current > GESTURE_GAP_MS;
      lastWheelAtRef.current = now;

      if (now - lastStepAtRef.current < cooldownMs) {
        if (!isNewGesture) return; // same swipe's momentum tail, not a new attempt
        impatientCountRef.current += 1;
        if (impatientCountRef.current >= IMPATIENCE_THRESHOLD) {
          // They've tried to scroll multiple separate times while blocked —
          // that's a request to skip ahead, not to sit through every step.
          releasedDirRef.current = delta;
          impatientCountRef.current = 0;
        }
        return;
      }
      impatientCountRef.current = 0;
      lastStepAtRef.current = now;
      onStep(delta);
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    return () => window.removeEventListener("wheel", onWheel);
  }, [enabled, isPinned, minIndex, maxIndex, cooldownMs, onStep]);

  return { isPinned };
}
