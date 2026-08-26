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
  whiteSpace: "nowrap",
};

// Creates a fresh tooltip appended to `container` and returns handlers to
// wire up to D3 mouse events. Callers are expected to remove any tooltip
// left over from a prior render before calling this again — every chart
// in this app already fully clears and rebuilds its SVG each render, so
// this just follows that same pattern rather than needing its own
// persistent ref.
export function createTooltip(container) {
  const el = document.createElement("div");
  el.className = "chart-tooltip";
  Object.assign(el.style, TOOLTIP_STYLE);
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

  return { show, move, hide };
}

// Removes any tooltip left over from a previous render of this chart —
// call at the top of the chart's effect, before createTooltip().
export function clearTooltip(container) {
  container.querySelector(":scope > .chart-tooltip")?.remove();
}
