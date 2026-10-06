// A small, self-contained hover tooltip shared by every D3 chart in this
// app — inline styles (not CSS custom properties/classes) so it renders
// correctly whether the chart is mounted in the regular document or
// inside the embed's shadow root, where an external stylesheet wouldn't
// reliably apply.
const TOOLTIP_STYLE = {
  position: "fixed",
  pointerEvents: "none",
  background: "#ffffff",
  color: "#172b69",
  border: "1px solid #e5e5e5",
  borderRadius: "8px",
  boxShadow: "0 4px 16px rgba(23, 43, 105, 0.18)",
  padding: "8px 12px",
  fontSize: "12px",
  fontFamily: '"Arial Nova", Arial, sans-serif',
  lineHeight: "1.5",
  zIndex: "1000",
  opacity: "0",
  transition: "opacity 0.1s",
  maxWidth: "240px",
  whiteSpace: "normal",
};

// "dark" variant — a navy box with white text, used by the run chart
// (HomelessnessTrendChart) for its selected-period panel, per the approved
// mockup, instead of every other chart's white hover tooltip above.
const TOOLTIP_STYLE_DARK = {
  ...TOOLTIP_STYLE,
  background: "#172b69",
  color: "#ffffff",
  border: "none",
  borderRadius: "10px",
  padding: "14px 18px",
  fontSize: "13px",
  lineHeight: "1.7",
  maxWidth: "280px",
};

// Creates a fresh tooltip appended to `container` and returns handlers to
// wire up to D3 mouse events. Callers are expected to remove any tooltip
// left over from a prior render before calling this again — every chart
// in this app already fully clears and rebuilds its SVG each render, so
// this just follows that same pattern rather than needing its own
// persistent ref. `variant` ("light", the default, or "dark" — see above).
export function createTooltip(container, { variant = "light" } = {}) {
  const el = document.createElement("div");
  el.className = "chart-tooltip";
  Object.assign(el.style, variant === "dark" ? TOOLTIP_STYLE_DARK : TOOLTIP_STYLE);
  container.appendChild(el);

  const OFFSET = 14;

  function show(html, event) {
    el.innerHTML = html;
    el.style.opacity = "1";
    move(event);
  }
  function move(event) {
    el.style.left = `${event.clientX + OFFSET}px`;
    el.style.top = `${event.clientY + OFFSET}px`;
  }
  function hide() {
    el.style.opacity = "0";
  }
  // For a caller that creates one tooltip per persistent component instance
  // (e.g. KpiCard, one per card, appended to document.body) rather than per
  // chart render — clearTooltip's container-scoped removal assumes the
  // latter (a chart wiping and rebuilding its whole container each render),
  // which doesn't apply here since there's no shared container to clear.
  function destroy() {
    el.remove();
  }

  return { show, move, hide, destroy };
}

// Removes any tooltip left over from a previous render of this chart —
// call at the top of the chart's effect, before createTooltip().
export function clearTooltip(container) {
  container.querySelector(":scope > .chart-tooltip")?.remove();
}
