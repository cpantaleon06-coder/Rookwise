// Browser checks on the built site (run `npm run build` first). It serves dist/
// with `vite preview` on port 4175 and drives Chromium through Playwright,
// which is not a dependency of this package: point PLAYWRIGHT_DIR at a folder
// where `npm i playwright` and `npx playwright install chromium` were run.
//
//   npm run check:overflow   fails when the page is wider than the viewport at 360 or 390 px
//   npm run screenshots      saves screenshots to screenshots-local/ (gitignored)

import { spawn, spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const PORT = 4175;
const BASE = `http://localhost:${PORT}/`;
const RUN = "#/run/inc-03-run2";

function loadPlaywright() {
  const dir = process.env.PLAYWRIGHT_DIR;
  const require = createRequire(dir ? join(resolve(dir), "noop.js") : import.meta.url);
  try {
    return require("playwright");
  } catch {
    console.error("visual-check: Playwright not found. Set PLAYWRIGHT_DIR to a folder with `npm i playwright`.");
    process.exit(2);
  }
}

function serve() {
  const child = spawn(`npx vite preview --port ${PORT} --strictPort`, { cwd: ROOT, shell: true, stdio: "pipe" });
  return new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error("vite preview did not start")), 30000);
    child.stdout.on("data", (chunk) => {
      if (String(chunk).includes(String(PORT))) {
        clearTimeout(timer);
        ok(child);
      }
    });
    child.on("exit", (code) => fail(new Error(`vite preview exited with ${code}`)));
  });
}

async function finishReplay(page) {
  const instant = page.getByRole("radio", { name: "Instant" });
  await instant.click();
  const play = page.getByRole("button", { name: "Play" });
  if (await play.count()) await play.click();
  await page.getByRole("heading", { name: "Approve the recommendation?" }).waitFor({ timeout: 20000 });
}

async function overflow(browser) {
  let failed = false;
  for (const width of [360, 390]) {
    for (const route of ["#/", RUN]) {
      const page = await browser.newPage({ viewport: { width, height: 844 } });
      await page.goto(BASE + route);
      await page.waitForLoadState("networkidle");
      // The landing is complete once Table 1 (built from the loaded recording) exists.
      if (route === "#/") await page.locator("#method table").first().waitFor({ timeout: 20000 });
      if (route === RUN) await finishReplay(page);
      await page.waitForTimeout(500);
      const { scroll, inner } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        inner: window.innerWidth,
      }));
      const ok = scroll <= inner;
      if (!ok) failed = true;
      console.log(`${ok ? "ok  " : "FAIL"} ${width}px ${route.padEnd(18)} scrollWidth ${scroll}, viewport ${inner}`);
      await page.close();
    }
  }
  return failed;
}

async function shots(browser) {
  const out = join(ROOT, "screenshots-local");
  mkdirSync(out, { recursive: true });
  const reduced = process.argv.includes("--reduced");
  for (const width of [1280, 390]) {
    const page = await browser.newPage({
      viewport: { width, height: width === 1280 ? 900 : 844 },
      reducedMotion: reduced ? "reduce" : "no-preference",
    });
    await page.goto(BASE + "#/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    await page.screenshot({ path: join(out, `${width}-landing-hero.png`) });
    await page.locator("#abstract").screenshot({ path: join(out, `${width}-landing-abstract-figure.png`) });
    await page.locator("#method table").first().waitFor({ timeout: 20000 });
    for (const id of ["abstract", "method", "results", "limitations", "reproduce"]) {
      await page.locator(`#${id}`).scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await page.locator(`#${id}`).screenshot({ path: join(out, `${width}-landing-${id}.png`) });
    }
    await page.screenshot({ path: join(out, `${width}-landing-full.png`), fullPage: true });
    await page.goto(BASE + RUN);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: join(out, `${width}-run-top.png`) });
    await finishReplay(page);
    await page.waitForTimeout(500);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: join(out, `${width}-run-top-finished.png`) });
    await page.locator("#evidence").screenshot({ path: join(out, `${width}-run-evidence.png`) });
    await page.locator("#safeguards").screenshot({ path: join(out, `${width}-run-safeguards.png`) });
    await page.locator("#decision").screenshot({ path: join(out, `${width}-run-approval.png`) });
    await page.locator("#budget").screenshot({ path: join(out, `${width}-run-budget.png`) });
    await page.close();
  }
  console.log(`screenshots saved to ${out}`);
}

const { chromium } = loadPlaywright();
const server = await serve();
const browser = await chromium.launch();
let code = 0;
try {
  if (process.argv.includes("--overflow")) code = (await overflow(browser)) ? 1 : 0;
  if (process.argv.includes("--shots")) await shots(browser);
} finally {
  await browser.close();
  // The preview runs under a shell; stop the whole tree before exiting.
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(server.pid), "/t", "/f"], { stdio: "ignore" });
  else server.kill();
}
process.exit(code);
