import { RookMark } from "./mark";

export const REPO_URL = "https://github.com/cpantaleon06-coder/Rookwise";

const NAV_LEFT = [
  ["#abstract", "Abstract"],
  ["#method", "Method"],
  ["#results", "Results"],
] as const;
const NAV_RIGHT = [
  ["#limitations", "Limitations"],
  ["#reproduce", "Reproduce"],
  [REPO_URL, "Source"],
] as const;

function NavLink({ href, children }: { href: string; children: string }) {
  const external = href.startsWith("http");
  return (
    <a
      href={href}
      rel={external ? "noreferrer" : undefined}
      className="label inline-flex min-h-11 items-center justify-center rounded-sm px-8 text-muted no-underline hover:text-fg hover:underline"
    >
      {children}
    </a>
  );
}

/**
 * The site header on its central axis: the rook mark in the middle, three
 * links on each side. On a phone the six links sit in a 3x2 grid under it.
 */
export function SiteHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto max-w-[1100px] px-21 py-13">
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-21">
          <nav aria-label="Site, left" className="hidden justify-end gap-8 md:flex">
            {NAV_LEFT.map(([href, word]) => (
              <NavLink key={href} href={href}>{word}</NavLink>
            ))}
          </nav>
          <a href="#/" className="col-start-2 flex flex-col items-center gap-8 rounded-sm px-8 text-fg no-underline">
            <RookMark className="h-[34px] w-[21px]" />
            <span className="label">Rookwise</span>
          </a>
          <nav aria-label="Site, right" className="hidden justify-start gap-8 md:flex">
            {NAV_RIGHT.map(([href, word]) => (
              <NavLink key={href} href={href}>{word}</NavLink>
            ))}
          </nav>
        </div>
        <nav aria-label="Site" className="mt-8 grid grid-cols-3 gap-x-8 md:hidden">
          {[...NAV_LEFT, ...NAV_RIGHT].map(([href, word]) => (
            <NavLink key={href} href={href}>{word}</NavLink>
          ))}
        </nav>
      </div>
    </header>
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
      className="ui sr-only rounded-sm bg-fg px-21 py-8 text-bg focus:not-sr-only focus:fixed focus:left-13 focus:top-13 focus:z-50"
    >
      {children}
    </a>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-89 border-t border-rule">
      <div className="ui mx-auto flex max-w-[68ch] flex-col items-center gap-13 px-21 py-55 text-center text-muted">
        <RookMark className="h-[34px] w-[21px] text-fg" />
        <p>
          <a className="text-fg underline" href={REPO_URL} rel="noreferrer">
            Source on GitHub
          </a>
          . MIT license.
        </p>
        <p>
          Built for the Nebius x NVIDIA Global AI Hackathon 2026 on NVIDIA Nemotron models served by
          Nebius Token Factory.
        </p>
        <p>
          Fonts: Source Serif 4, IBM Plex Sans and IBM Plex Mono, SIL Open Font License 1.1 (
          <a className="text-fg underline" href="./licenses/source-serif-4-OFL.txt">
            license texts
          </a>
          ). This site replays recordings only and sets no cookies.
        </p>
      </div>
    </footer>
  );
}
