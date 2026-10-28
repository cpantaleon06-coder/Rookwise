import { useEffect, useId, useRef, useState } from "react";
import { HOLD_MS } from "../lib/scale";
import { ProgressRing } from "./figures";
import { useReducedMotion } from "./motion";
import { buttonClass } from "./ui";

type Step = "idle" | "holding" | "released" | "confirm";

/**
 * Approve by holding for 1.618 s (pointer, or Space or Enter held down), with a
 * progress ring, or in two steps: Approve, then Confirm. With reduced motion
 * only the two steps are offered. Reject is a plain button.
 */
export function ApproveControls({ onApprove, onReject }: { onApprove: () => void; onReject: () => void }) {
  const reduced = useReducedMotion();
  const hintId = useId();
  const [step, setStep] = useState<Step>("idle");
  const [progress, setProgress] = useState(0);
  const frame = useRef<number | null>(null);
  const started = useRef<number | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (step === "confirm") confirmRef.current?.focus();
  }, [step]);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    [],
  );

  const begin = () => {
    if (started.current !== null) return;
    started.current = performance.now();
    setStep("holding");
    const tick = (now: number) => {
      const p = Math.min(1, (now - (started.current ?? now)) / HOLD_MS);
      setProgress(p);
      if (p >= 1) {
        frame.current = null;
        started.current = null;
        onApprove();
        return;
      }
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  };

  const cancel = () => {
    if (started.current === null) return;
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    started.current = null;
    setProgress(0);
    setStep("released");
  };

  const isHoldKey = (key: string) => key === " " || key === "Enter";

  const announcement =
    step === "holding"
      ? "Keep holding to approve."
      : step === "released"
        ? "Released before 1.6 seconds. Nothing was recorded."
        : step === "confirm"
          ? "Step 2 of 2: press Confirm approval to record it, or Cancel."
          : "";

  return (
    <div className="flex flex-col items-center gap-13 text-center">
      {step === "confirm" ? (
        <div className="flex flex-col items-center gap-8 sm:flex-row">
          <button ref={confirmRef} type="button" className={buttonClass("primary")} onClick={onApprove}>
            Confirm approval
          </button>
          <button type="button" className={buttonClass("secondary")} onClick={() => setStep("idle")}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-8 sm:flex-row">
          {reduced ? (
            <button type="button" className={buttonClass("primary")} onClick={() => setStep("confirm")}>
              Approve
            </button>
          ) : (
            <button
              type="button"
              aria-describedby={hintId}
              className={`${buttonClass("primary")} min-h-[55px] touch-none select-none gap-13 pl-8 pr-21`}
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                e.currentTarget.setPointerCapture(e.pointerId);
                begin();
              }}
              onPointerUp={cancel}
              onPointerCancel={cancel}
              onLostPointerCapture={cancel}
              onKeyDown={(e) => {
                if (!isHoldKey(e.key)) return;
                e.preventDefault();
                if (!e.repeat) begin();
              }}
              onKeyUp={(e) => {
                if (isHoldKey(e.key)) cancel();
              }}
              onBlur={cancel}
              onContextMenu={(e) => e.preventDefault()}
            >
              <ProgressRing value={progress} size={39} stroke={4} tone="bg" />
              Hold to approve
            </button>
          )}
          <button type="button" className={buttonClass("secondary")} onClick={onReject}>
            Reject
          </button>
        </div>
      )}
      {!reduced && step !== "confirm" && (
        <>
          <p id={hintId} className="max-w-[55ch] text-muted">
            Press and hold for 1.6 seconds, with the pointer or with Space or Enter held down.
          </p>
          <button
            type="button"
            className="ui min-h-11 rounded-sm px-13 text-fg underline hover:decoration-2"
            onClick={() => setStep("confirm")}
          >
            Approve in two steps instead
          </button>
        </>
      )}
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}
