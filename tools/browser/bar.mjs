// Bar fit: with Control on (LAN visitor in the ctltest stack), does every bar item fit at each width? Saves bar_<w>.png to /out.
import puppeteer from 'puppeteer-core';
const U = process.argv[2] || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/pbar'] });
const p = await b.newPage();
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.setViewport({ width: 1400, height: 900 });
await p.goto(U, { waitUntil: 'load' }); await sleep(4000);
await p.click('#ctl'); await sleep(300);
for (const w of [1920, 1411, 1410, 1400, 1300, 1290, 1280, 1100, 1024, 900, 800, 640, 390]) {
  await p.setViewport({ width: w, height: 900 }); await sleep(400);
  const r = await p.evaluate(() => {
    const bar = document.getElementById('bar'), vw = innerWidth;
    const cut = [...bar.querySelectorAll('a, button, input, #clock')].filter(e => !e.hidden && getComputedStyle(e).display !== 'none')
      .filter(e => { const q = e.getBoundingClientRect(); return q.right > vw + 0.5 || q.left < -0.5; }).map(e => e.id || e.className);
    const offRow = [...bar.querySelectorAll('button, input')].filter(e => !e.hidden).some(e => e.getBoundingClientRect().bottom > bar.getBoundingClientRect().bottom + 0.5);
    if (offRow) cut.push('below bar');
    return { overflow: bar.scrollWidth - bar.clientWidth, cut, h: bar.getBoundingClientRect().height,
             clock: document.getElementById('clock').textContent };
  });
  console.log(String(w).padStart(5), `overflow ${r.overflow}px`, `height ${r.h}`, r.cut.length ? `CUT: ${r.cut.join(',')}` : 'all visible', '|', r.clock);
  const bar = await p.$('#bar'); await bar.screenshot({ path: `/out/bar_${w}.png` });
}
console.log('page errors:', errs.length ? errs : 'none');
await b.close();
