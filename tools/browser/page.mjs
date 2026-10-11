// Screenshot any page (full page) after it settles: node page.mjs <url> <out.png> [width]
import puppeteer from 'puppeteer-core';
const [url, out, width] = [process.argv[2], process.argv[3], parseInt(process.argv[4] || '1400')];
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/prof'] });
const p = await b.newPage(); await p.setViewport({ width, height: 900 });
p.on('console', m => console.log('console:', m.type(), m.text())); p.on('pageerror', e => console.log('pageerror:', e.message));
await p.goto(url, { waitUntil: 'networkidle0' }); await new Promise(r => setTimeout(r, 1500));
await p.screenshot({ path: out, fullPage: true }); await b.close();
