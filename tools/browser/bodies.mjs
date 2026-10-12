// Out-of-frame Sun/Moon/planet labels must move with the compass tape: sweeps ?simaz= around the given azimuths.
// Usage: node bodies.mjs <page url> <az> [az ...]
import puppeteer from 'puppeteer-core';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/pb'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
const read = () => p.evaluate(() => {
  const out = {};
  for (const t of document.querySelectorAll('#marks text')) {
    const m = t.textContent.match(/^(Sun|Moon|Mercury|Venus|Mars|Jupiter|Saturn|Uranus|Neptune)\b.*?el (-?[\d.]+)°.*?([↑↓])?$/);
    if (!m || !m[3]) continue;                                  // only out-of-frame labels (arrow)
    out[m[1]] = { el: +m[2], labelX: +t.getAttribute('x') };
  }
  return out;
});
const URL = process.argv[2];
for (const base of process.argv.slice(3).map(Number)) {
  const rows = {};
  for (let az = base - 16; az <= base + 16; az += 2) {
    await p.goto(`${URL}?simaz=${az}`, { waitUntil: 'load' }); await sleep(700);
    for (const [n, v] of Object.entries(await read())) (rows[n] ||= []).push([az, v.labelX, v.el]);
  }
  for (const [n, r] of Object.entries(rows)) {
    const steps = r.slice(1).map((x, i) => +(x[1] - r[i][1]).toFixed(1));
    console.log(`view ${base}: ${n} el ${r[0][2]}° label x per 2° turn: min ${Math.min(...steps)} max ${Math.max(...steps)} px (${r.length} positions)`);
  }
}
await b.close();
