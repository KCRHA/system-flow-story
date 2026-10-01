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
export default function InfoIcon({ label, align = "center", size = "md", children }) {
  const [open, setOpen] = useState(false);
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

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false);
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
    <span className="info-icon" ref={wrapperRef} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className={`info-icon-trigger info-icon-trigger-${size}`}
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
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
          className={`info-icon-popover align-${align}`}
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
