import { useEffect, useState } from "react";
import { Landing } from "./pages/Landing";
import { RunPage } from "./pages/RunPage";

// Hash routes, so the app works on any static host without rewrites:
// "#/" is the landing, "#/run/<folder>" replays public/recordings/<folder>/.
export type Route = { page: "landing"; anchor: string | null } | { page: "run"; folder: string };

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, "");
  const match = /^\/run\/([^/?#]+)\/?$/.exec(path);
  if (match) {
    let folder = match[1];
    try {
      folder = decodeURIComponent(folder);
    } catch {
      // Keep the raw segment; the loader rejects names that are not plain.
    }
    return { page: "run", folder };
  }
  const anchor = /^\/?([A-Za-z][\w-]*)$/.exec(path);
  return { page: "landing", anchor: anchor ? anchor[1] : null };
}

export function runHref(folder: string): string {
  return `#/run/${encodeURIComponent(folder)}`;
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (route.page === "run") {
      window.scrollTo(0, 0);
    } else if (route.anchor) {
      document.getElementById(route.anchor)?.scrollIntoView();
    } else {
      window.scrollTo(0, 0);
    }
  }, [route]);

  return route.page === "run" ? <RunPage key={route.folder} folder={route.folder} /> : <Landing />;
}
