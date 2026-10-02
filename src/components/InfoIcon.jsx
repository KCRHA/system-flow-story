import { useEffect, useLayoutEffect, useRef, useState } from "react";

// A small "ⓘ" popover, used wherever a piece of UI needs an on-demand
// explanation without permanently occupying page space (see
// OutflowSection's section-header icon and its Category filter). Opens on
// hover for mouse users; also still opens on click/tap and keyboard focus,
// since hover alone doesn't exist on touch devices and isn't reachable by
// keyboard navigation.
//
// `align` controls which edge of the trigger the popover hangs from —
// "end" for a trigger near the right edge of its container (e.g. the
// rightmost filter-bar field), where a centered popover would overflow.
// `size` ("md", the filter-bar default, or "lg" for a standalone icon
// meant to read as its own element rather than an inline annotation — see
// OutflowSection's section-header icon).
// `variant` ("light", the default white popover used for the glossary/
// filter notes, or "dark" for the KPI cards' per-term definitions — a navy
// box with light text, matching the approved KPI card mockup).
export default function InfoIcon({ label, align = "center", size = "md", variant = "light", children }) {
  const [open, setOpen] = useState(false);
  // Whether the popover was opened by a click (vs. hover/focus) — a click
  // "pins" it open so a mouse user can move the pointer down into the
  // popover to interact with its content (e.g. the dark KPI-card popovers'
  // "See full definitions" link) without losing hover on the trigger
  // mid-move and closing it before they get there. A pinned popover only
  // closes on an explicit click elsewhere on the page or Escape, not on
  // mouseleave/blur.
  const [pinned, setPinned] = useState(false);
  const wrapperRef = useRef(null);
  const popoverRef = useRef(null);
  // Extra horizontal shift (px) applied on top of the CSS `align` position,
  // only when that position would otherwise run the popover off the left
  // or right edge of the viewport — e.g. a narrow window with a long
  // selected category pushes the Category filter (and its "end"-aligned
  // popover) far enough right that the popover's fixed max-width overflows
  // past the left edge. Reset to 0 on every close so each open re-measures
  // from the plain CSS position rather than compounding a stale shift.
  const [nudge, setNudge] = useState(0);

  const close = () => {
    setOpen(false);
    setPinned(false);
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) close();
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) {
      setNudge(0);
      return;
    }
    const rect = popoverRef.current?.getBoundingClientRect();
    if (!rect) return;
    const margin = 12;
    if (rect.left < margin) {
      setNudge(margin - rect.left);
    } else if (rect.right > window.innerWidth - margin) {
      setNudge(window.innerWidth - margin - rect.right);
    }
  }, [open]);

  return (
    <span
      className="info-icon"
      ref={wrapperRef}
      onMouseEnter={() => !pinned && setOpen(true)}
      onMouseLeave={() => !pinned && setOpen(false)}
    >
      <button
        type="button"
        className={`info-icon-trigger info-icon-trigger-${size}`}
        aria-label={label}
        aria-expanded={open}
        onClick={() => {
          // Toggles the pin: click once to pin it open, click again to close
          // it outright — same as clicking outside would (see `close`).
          if (pinned) {
            close();
          } else {
            setPinned(true);
            setOpen(true);
          }
        }}
        onFocus={() => !pinned && setOpen(true)}
        onBlur={(event) => {
          // A click on the popover's own content (e.g. the "See full
          // definitions" link) moves focus there, which blurs this button —
          // don't close on that, only on focus actually leaving the whole
          // widget. Pinned popovers ignore blur entirely, same as they
          // ignore mouseleave.
          if (pinned) return;
          if (wrapperRef.current && wrapperRef.current.contains(event.relatedTarget)) return;
          setOpen(false);
        }}
      >
        {/* A drawn icon, not the Unicode "ⓘ" glyph — renders identically
            across platforms/fonts instead of varying with whatever circled-i
            glyph the OS font happens to ship. */}
        <svg width={size === "lg" ? 30 : 15} height={size === "lg" ? 30 : 15} viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.3" />
          <circle cx="8" cy="5.1" r="0.9" fill="currentColor" />
          <path d="M8 7.3V11.3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div
          ref={popoverRef}
          className={`info-icon-popover align-${align}${variant === "dark" ? " info-icon-popover-dark" : ""}`}
          style={{ "--nudge": `${nudge}px` }}
          role="dialog"
          aria-label={label}
        >
          {children}
        </div>
      )}
    </span>
  );
}
