import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import tokensCss from "./styles/tokens.css?inline";
import layoutCss from "./styles/layout.css?inline";

const MOUNT_SELECTOR = "[data-kcrha-system-flow-dashboard]";

function mount(host) {
  if (host.shadowRoot) return; // already mounted

  // Shadow root gives the same style isolation an iframe would (host CSS
  // can't leak in, ours can't leak out) without creating a separate
  // browsing context — so, unlike an iframe, native scroll/sticky/
  // IntersectionObserver-driven interactivity still works against the
  // real page scroll.
  const shadowRoot = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `${tokensCss}\n${layoutCss}`;
  shadowRoot.appendChild(style);

  const appRoot = document.createElement("div");
  shadowRoot.appendChild(appRoot);

  ReactDOM.createRoot(appRoot).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

function mountAll() {
  document.querySelectorAll(MOUNT_SELECTOR).forEach(mount);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAll);
} else {
  mountAll();
}

// Exposed for host pages that add a mount point after initial page load
// (e.g. dynamically inserted content) and want to trigger mounting manually.
window.KCRHASystemFlowDashboard = { mount, mountAll };
