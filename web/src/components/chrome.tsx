import { RookMark } from "./mark";

export const REPO_URL = "https://github.com/cpantaleon06-coder/Rookwise";

const NAV_LEFT = [
  ["#poka-yoke", "Poka-yoke"],
  ["#how-it-works", "How it works"],
] as const;
const NAV_RIGHT = [
  ["#results", "Results"],
  [REPO_URL, "Source"],
] as const;

function NavLink({ href, children }: { href: string; children: string }) {
  const external = href.startsWith("http");
  return (
    <a
      href={href}
      rel={external ? "noreferrer" : undefined}
      className="label pill inline-flex min-h-11 items-center justify-center border border-line bg-surface px-21 text-muted hover:bg-raised hover:text-bone"
    >
      {children}
    </a>
  );
}

/**
 * The site header on its central axis: the rook mark in the middle, two links
 * on each side. On a phone the four links sit in a 2x2 grid under the mark.
 */
export function SiteHeader() {
  return (
    <header className="border-b border-line">
      <div className="mx-auto max-w-[1440px] px-21 py-13">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-21">
          <nav aria-label="Site, left" className="hidden justify-end gap-8 sm:flex">
            {NAV_LEFT.map(([href, word]) => (
              <NavLink key={href} href={href}>{word}</NavLink>
            ))}
          </nav>
          <a href="#/" className="col-start-2 flex flex-col items-center gap-8 rounded-sm px-8 text-bone">
            <RookMark className="h-[34px] w-[21px]" />
            <span className="label">Rookwise</span>
          </a>
          <nav aria-label="Site, right" className="hidden justify-start gap-8 sm:flex">
            {NAV_RIGHT.map(([href, word]) => (
              <NavLink key={href} href={href}>{word}</NavLink>
            ))}
          </nav>
        </div>
        <nav aria-label="Site" className="mt-8 grid grid-cols-2 gap-x-8 sm:hidden">
          {[...NAV_LEFT, ...NAV_RIGHT].map(([href, word]) => (
            <NavLink key={href} href={href}>{word}</NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}

export const LIVE_RUNS_NOTE = "Live runs are limited and not offered on this site. Recorded mode is the default.";

/** The live mode button alone: always disabled, described by the note with id live-runs-note. */
export function LiveRunsButton() {
  return (
    <button
      type="button"
      disabled
      aria-describedby="live-runs-note"
      className="inline-flex min-h-11 cursor-not-allowed items-center justify-center gap-8 rounded-full border border-line-strong px-21 font-medium text-muted"
    >
      <span aria-hidden="true" className="size-2 rounded-full border border-line-strong" />
      Live runs
    </button>
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
      className="sr-only rounded-full bg-berry px-21 py-8 text-ink focus:not-sr-only focus:fixed focus:left-13 focus:top-13 focus:z-50"
    >
      {children}
    </a>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-89 border-t border-line">
      <div className="mx-auto flex max-w-[89ch] flex-col items-center gap-13 px-21 py-89 text-center text-muted">
        <RookMark className="h-[34px] w-[21px] text-bone" />
        <p>
          <a className="underline underline-offset-4 hover:text-bone" href={REPO_URL} rel="noreferrer">
            Source on GitHub
          </a>
          . MIT license.
        </p>
        <p>
          Built for the Nebius x NVIDIA Global AI Hackathon 2026 on NVIDIA Nemotron models served by
          Nebius Token Factory.
        </p>
        <p>
          Fonts: Space Grotesk and JetBrains Mono, SIL Open Font License 1.1 (
          <a className="underline underline-offset-4 hover:text-bone" href="./licenses/space-grotesk-OFL.txt">
            license texts
          </a>
          ). This site replays recordings only and sets no cookies.
        </p>
      </div>
    </footer>
  );
}
