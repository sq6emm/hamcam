// Fixed layer + R/S bands against tools/ctltest/stack.sh: markers, arrows, Control click on a terrain marker -> goto, bar stays one row.
import puppeteer from 'puppeteer-core';
const U = 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/pfx'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
const errs = []; p.on('pageerror', e => errs.push(e.message));
const d = await (await fetch(U + 'telemetry/scatter')).json();
const best = [...d.fixed].sort((a, b) => b.score - a.score)[0], cell = [...d.cells].sort((a, b) => b.score - a.score)[0];
for (const [az, what] of [[Math.round(best.az), 'fixed'], [Math.round(cell.az), 'cell']]) {
  await p.goto(`${U}?simaz=${az}`, { waitUntil: 'load' }); await sleep(7000);
  const r = await p.evaluate(() => {
    const t = [...document.querySelectorAll('#scatter text')].map(e => e.textContent);
    return { scale0: (() => { const t = [...document.querySelectorAll('#elscale text')].find(x => x.textContent === '0°'); return t ? Math.round(+t.getAttribute('y')) : null; })(), markers: document.querySelectorAll('#scatter path.fix').length, fixed: t.filter(x => /^terrain |observatory|Śnieżka/.test(x)), rs: t.filter(x => /^(R\/S|S\/S|hail) /.test(x)), arrows: t.filter(x => /[◀▶]/.test(x)),
      bands: document.querySelectorAll('#scatter rect[rx="5"]').length, btn: document.getElementById('lyFixed').hidden ? 'hidden' : document.getElementById('lyFixed').className,
      barRows: (() => { const ys = new Set([...document.querySelectorAll('#bar button:not([hidden])')].map(x => Math.round(x.getBoundingClientRect().top))); return ys.size; })() };
  });
  console.log(`${what} az ${az}:`, JSON.stringify(r));
  await p.screenshot({ path: `/out/fixed_${what}.png` });
}
// Control click on the best fixed marker -> goto (fake rotator)
await p.goto(`${U}?simaz=${Math.round(best.az)}`, { waitUntil: 'load' }); await sleep(7000);
await p.click('#ctl'); await sleep(300);
const rows = await p.evaluate(() => { const ys = new Set([...document.querySelectorAll('#bar button:not([hidden])')].map(x => Math.round(x.getBoundingClientRect().top))); return ys.size; });
const pt = await p.evaluate(() => { const e = document.querySelector('#scatter path.fix'); if (!e) return null; const bb = e.getBoundingClientRect(); return { x: bb.left + bb.width / 2, y: bb.top + bb.height / 2 }; });
if (pt) { await p.mouse.click(pt.x, pt.y); await sleep(1500); console.log('control click on fixed marker ->', await p.$eval('#msg', e => e.textContent)); }
console.log('bar rows with Control on:', rows); await p.keyboard.press('Escape');
console.log('page errors:', errs.length ? errs : 'none'); await b.close();
