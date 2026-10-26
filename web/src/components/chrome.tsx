import { useEffect, useState } from "react";

export const REPO_URL = "https://github.com/cpantaleon06-coder/Rookwise";

type Theme = "system" | "dark" | "light";

const THEME_KEY = "rookwise-theme";

function readTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "dark" || value === "light" ? value : "system";
  } catch {
    return "system";
  }
}

/** Follows the system setting; the button cycles system, dark, light (open question 1). */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Storage can be blocked; the theme still applies for this visit.
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "dark", dark: "light", light: "system" };
  const words: Record<Theme, string> = { system: "System", dark: "Dark", light: "Light" };
  return (
    <button
      type="button"
      onClick={() => setTheme(next[theme])}
      className="label inline-flex min-h-11 items-center rounded-full px-3 text-muted hover:bg-raised hover:text-ink"
      aria-label={`Theme: ${words[theme]}. Change theme`}
    >
      Theme: {words[theme]}
    </button>
  );
}

/** The live mode control: always disabled here, with the reason as visible text. */
export function LiveRunsControl({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "flex flex-wrap items-center gap-x-3 gap-y-1" : "flex flex-col gap-2"}>
      <button
        type="button"
        disabled
        aria-describedby="live-runs-note"
        className="inline-flex min-h-11 cursor-not-allowed items-center justify-center gap-2 rounded-full border border-line px-5 text-sm font-medium text-muted"
      >
        <span aria-hidden="true" className="size-2 rounded-full border border-line-strong" />
        Live runs
      </button>
      <p id="live-runs-note" className="text-sm text-muted">
        Live runs are limited and not offered on this site. Recorded mode is the default.
      </p>
    </div>
  );
}

export function SkipLink({ target, children }: { target: string; children: string }) {
  return (
    <a
      href={`#${target}`}
      onClick={(e) => {
        // Hash routing owns location.hash, so move focus without changing it.
        e.preventDefault();
        const el = document.getElementById(target);
        if (el) {
          el.setAttribute("tabindex", "-1");
          el.focus();
        }
      }}
      className="sr-only rounded-full bg-primary px-4 py-2 text-on-primary focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50"
    >
      {children}
    </a>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto flex max-w-[1440px] flex-col gap-3 px-4 py-10 text-sm text-muted sm:px-6 lg:px-8">
        <p>
          MIT license.{" "}
          <a className="underline underline-offset-4 hover:text-ink" href={REPO_URL} rel="noreferrer">
            Source on GitHub
          </a>
          . Built for the Nebius x NVIDIA Global AI Hackathon 2026.
        </p>
        <p>
          Models: NVIDIA Nemotron, served by Nebius Token Factory. Web search: Tavily. Fonts: Inter,
          JetBrains Mono and Source Serif 4 (SIL Open Font License 1.1,{" "}
          <a className="underline underline-offset-4 hover:text-ink" href="./licenses/inter-OFL.txt">
            license texts
          </a>
          ).
        </p>
        <p>This site replays recordings only. It sets no cookies and makes no request except for its own files.</p>
      </div>
    </footer>
  );
}
