// Screenshots of the landing page and a recorded run, for the README and the Devpost page.
//
// Usage:
//   node release/shots/capture.mjs http://localhost:5173
//
// Needs Playwright installed globally, not in any package.json:
//   npm install -g playwright
//   npx playwright install chromium
//
// For each viewport (1280x800 and 390x844) it saves PNGs in release/shots/out/:
//   landing-top, poka-yoke (section whose heading contains "poka-yoke"),
//   test-split (section whose heading contains "test split"), run (#/run/inc-03-run2 after
//   clicking the "Instant" speed control), evidence (heading containing "evidence") and
//   approval (heading containing "Approve"). Elements are found by visible text; one that is
//   not found is logged as SKIPPED and the script goes on. It also prints
//   document.documentElement.scrollWidth per viewport (wider than the viewport means a
//   horizontal scroll).

import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "out");
const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile", width: 390, height: 844 },
];
const RUN_ROUTE = "#/run/inc-03-run2";
const SETTLE_MS = 600;

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch {
    // Not resolvable from this folder: use the global install.
    const root = execSync("npm root -g", { encoding: "utf8" }).trim();
    return await import(pathToFileURL(join(root, "playwright", "index.mjs")).href);
  }
}

// Marks the first element matching the text and returns true, or false when none matches.
// kind "section": a <section> whose headings (h1-h6) or first child (where the tag pill sits)
// contain the text. kind "heading": the panel or section around a heading with the text.
// kind "control": a button or radio whose visible text is exactly the text.
async function mark(page, kind, text) {
  return page.evaluate(
    ({ kind, text }) => {
      const needle = text.toLowerCase();
      const visible = (el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      };
      const has = (el) => (el?.textContent || "").toLowerCase().includes(needle);
      let found = null;
      if (kind === "section") {
        found = [...document.querySelectorAll("section")].find(
          (s) => visible(s) && ([...s.querySelectorAll("h1,h2,h3,h4,h5,h6")].some(has) || has(s.firstElementChild)),
        );
      } else if (kind === "heading") {
        const heading = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].find((h) => visible(h) && has(h));
        // From the parent up, so a heading with its own id is not picked as the area.
        found = heading ? heading.parentElement.closest("section, article") || heading.parentElement : null;
      } else if (kind === "control") {
        found = [...document.querySelectorAll("button, [role=radio]")].find(
          (b) => visible(b) && (b.textContent || "").trim().toLowerCase() === needle,
        );
      }
      document.querySelectorAll("[data-shot]").forEach((el) => el.removeAttribute("data-shot"));
      if (!found) return false;
      found.setAttribute("data-shot", "1");
      return true;
    },
    { kind, text },
  );
}

async function shootMarked(page, kind, text, file) {
  if (!(await mark(page, kind, text))) {
    console.log(`SKIPPED ${file}: no ${kind} with "${text}"`);
    return;
  }
  const target = page.locator("[data-shot]").first();
  await target.scrollIntoViewIfNeeded();
  await page.waitForTimeout(SETTLE_MS);
  await target.screenshot({ path: join(OUT_DIR, file) });
  console.log(`saved ${file}`);
}

async function main() {
  const base = process.argv[2];
  if (!base) {
    console.error("usage: node release/shots/capture.mjs <base URL>");
    process.exit(2);
  }
  const root = base.replace(/#.*$/, "").replace(/\/+$/, "") + "/";
  mkdirSync(OUT_DIR, { recursive: true });
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch();
  try {
    for (const vp of VIEWPORTS) {
      const size = `${vp.width}x${vp.height}`;
      const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });

      await page.goto(root, { waitUntil: "networkidle" });
      await page.waitForTimeout(SETTLE_MS);
      await page.screenshot({ path: join(OUT_DIR, `landing-top-${size}.png`) });
      console.log(`saved landing-top-${size}.png`);
      const landingWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      console.log(`${size} landing scrollWidth ${landingWidth}`);
      await shootMarked(page, "section", "poka-yoke", `poka-yoke-${size}.png`);
      await shootMarked(page, "section", "test split", `test-split-${size}.png`);

      await page.goto(root + RUN_ROUTE, { waitUntil: "networkidle" });
      await page.waitForTimeout(SETTLE_MS);
      if (await mark(page, "control", "Instant")) {
        await page.locator("[data-shot]").first().click();
        await page.waitForTimeout(SETTLE_MS * 3);
      } else {
        console.log(`SKIPPED instant control at ${size}: no button with "Instant"`);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: join(OUT_DIR, `run-${size}.png`) });
      console.log(`saved run-${size}.png`);
      await shootMarked(page, "heading", "evidence", `evidence-${size}.png`);
      await shootMarked(page, "heading", "Approve", `approval-${size}.png`);
      const runWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      console.log(`${size} run scrollWidth ${runWidth}`);

      await page.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
