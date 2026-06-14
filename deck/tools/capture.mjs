// Capture real screenshots of the live Game Attribution Agent app for the deck.
// Requires Playwright (ESM resolves it from THIS file's location, so install it here):
//   cd deck && npm i -D @playwright/test && npx playwright install chromium
//   node tools/capture.mjs
// Writes deck/assets/screenshots/chat.png and (best-effort) dossier.png.
import { chromium } from '@playwright/test';

const URL = 'https://game-attribution-agent.vercel.app';
const OUT = new URL('../assets/screenshots/', import.meta.url).pathname;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });

await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: OUT + 'chat.png' });
console.log('captured chat.png');

// Best-effort dossier capture: ask a question and wait for the pipeline.
// The backend may be down — tolerate failure and keep the in-deck recreation.
try {
  const box = page.locator('textarea, [contenteditable="true"]').first();
  await box.click({ timeout: 5000 });
  await box.fill("What's going on with my Roblox game's DAU this week?");
  await page.keyboard.press('Enter');
  await page.waitForTimeout(45000);
  await page.screenshot({ path: OUT + 'dossier.png', fullPage: true });
  console.log('captured dossier.png');
} catch (e) {
  console.log('dossier capture skipped:', e.message);
}

await browser.close();
