import { useEffect, useRef, useState } from "react";
import scrollama from "scrollama";

/**
 * A narrative scroll section: text steps down the left/top, a sticky graphic
 * on the right/bottom. `onStepEnter(index)` fires as each step crosses the
 * trigger offset; the graphic render-prop receives the current step index.
 */
export default function Scrolly({ steps, renderGraphic, threshold = 0.6 }) {
  const containerRef = useRef(null);
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const scroller = scrollama();
    scroller
      .setup({
        step: ".scrolly-step",
        // Scoped to this instance's own container rather than a global
        // document-wide selector — avoids collisions with other Scrolly
        // instances on the page, AND (unlike a plain document query) still
        // resolves correctly when this component is mounted inside a
        // shadow root, since a parent element's querySelectorAll doesn't
        // need to cross that boundary.
        parent: containerRef.current,
        offset: threshold,
        progress: false,
      })
      .onStepEnter(({ index }) => setActiveStep(index));

    const onResize = () => scroller.resize();
    window.addEventListener("resize", onResize);
    return () => {
      scroller.destroy();
      window.removeEventListener("resize", onResize);
    };
  }, [threshold]);

  return (
    <div className="scrolly" ref={containerRef}>
      <div className="scrolly-steps">
        {steps.map((step, i) => {
          // A step can be a plain string, or { text, extra } to attach
          // static content (e.g. a legend) right after that step's text —
          // `extra` isn't part of the fade-in/out narrative styling, it's
          // always fully visible.
          const text = typeof step === "string" ? step : step.text;
          const extra = typeof step === "string" ? null : step.extra;
          return (
            <div key={i}>
              <div className={`scrolly-step ${i === activeStep ? "is-active" : ""}`}>
                <p>{text}</p>
              </div>
              {extra}
            </div>
          );
        })}
      </div>
      <div className="scrolly-sticky">
        <div className="scrolly-graphic">{renderGraphic(activeStep)}</div>
      </div>
    </div>
  );
}
