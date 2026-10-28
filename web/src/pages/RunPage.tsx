import { useCallback, useEffect, useState } from "react";
import { SiteFooter, SiteHeader, SkipLink } from "../components/chrome";
import { buttonClass, Skeleton } from "../components/ui";
import { loadRecording, RecordingError, type LoadedRecording } from "../lib/recording";
import { RecordedBanner } from "../run/RunHeader";
import { RunView } from "../run/RunView";

const BASE = `${import.meta.env.BASE_URL}recordings/`;

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: RecordingError }
  | { kind: "ready"; recording: LoadedRecording };

export function RunPage({ folder }: { folder: string }) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    loadRecording(folder, BASE, (url) => fetch(url))
      .then((recording) => !cancelled && setState({ kind: "ready", recording }))
      .catch((error: unknown) => {
        if (cancelled) return;
        const typed =
          error instanceof RecordingError
            ? error
            : new RecordingError("invalid", "The recording could not be read.");
        setState({ kind: "error", error: typed });
      });
    return () => {
      cancelled = true;
    };
  }, [folder, attempt]);

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  if (state.kind === "ready") return <RunView recording={state.recording} />;

  return (
    <>
      <SkipLink target="run">Skip to the run</SkipLink>
      <SiteHeader />
      <RecordedBanner provenance={null} summary={null} notice={null} />
      <main id="run" className="mx-auto max-w-[1440px] px-21 py-34 lg:px-55">
        {state.kind === "loading" ? (
          <div role="status" className="flex flex-col gap-13">
            <p className="text-muted">Loading the recording “{folder}”.</p>
            <Skeleton className="h-24 w-full rounded-sm" />
            <div className="grid gap-21 lg:grid-cols-[1.618fr_1fr]">
              <Skeleton className="h-96 rounded-lg" />
              <Skeleton className="h-96 rounded-lg" />
            </div>
          </div>
        ) : (
          <div role="alert" className="max-w-[60ch] rounded-lg border border-rule bg-withdrawn-tint p-21">
            <h1 className="text-title font-semibold">This recording could not be loaded.</h1>
            <p className="mt-13 wrap-anywhere">{state.error.message}</p>
            <p className="mt-8 text-muted">
              {state.error.kind === "invalid_name"
                ? "Recording names use letters, digits, dots, dashes and underscores."
                : state.error.kind === "not_found"
                  ? `A recording folder needs recorded_run.json and recorded_run.events.json under recordings/${folder}/.`
                  : state.error.kind === "invalid"
                    ? "The recording files are not in the expected shape."
                    : "Check the connection and try again."}
            </p>
            <div className="mt-21 flex flex-wrap gap-13">
              {state.error.kind === "network" && (
                <button type="button" className={buttonClass("primary")} onClick={retry}>
                  Try again
                </button>
              )}
              <a className={buttonClass("secondary")} href="#/">
                Back to the recordings
              </a>
            </div>
          </div>
        )}
      </main>
      <SiteFooter />
    </>
  );
}
