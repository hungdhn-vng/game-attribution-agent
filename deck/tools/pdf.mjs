// Export the deck to a clean one-page-per-slide PDF.
// Requires Playwright (ESM resolves it from THIS file's location, so install it here):
//   cd deck && npm i -D @playwright/test && npx playwright install chromium
//   node tools/pdf.mjs            # writes deck/gaa-deck.pdf (14 pages)
import { chromium } from '@playwright/test';

const deckUrl = new URL('../index.html?print-pdf', import.meta.url).href;
const out = new URL('../gaa-deck.pdf', import.meta.url).pathname;

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(deckUrl, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500); // let reveal build the print-pdf layout
await page.pdf({ path: out, preferCSSPageSize: true, printBackground: true });
await browser.close();
console.log('wrote', out);
