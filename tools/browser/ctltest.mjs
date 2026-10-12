// Rotator control test (click-to-point, marker, aircraft tracking, Esc=STOP, lease). Run ONLY against tools/ctltest/stack.sh (a
// fake rotctld) - it moves the rotator. Poses as a LAN visitor behind the front proxy (X-Forwarded-For).
import puppeteer from 'puppeteer-core';
const U = 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/pct'] });
const open = async () => {
  const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
  await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });     // LAN visitor behind the front proxy
  p.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await p.evaluateOnNewDocument(() => { window.__hook = true; });
  await p.goto(U, { waitUntil: 'load' }); await sleep(4000); return p;
};
const hud2px = async (p, x, y) => p.evaluate((x, y) => { const r = document.getElementById('hud').getBoundingClientRect();
  const vb = document.getElementById('hud').viewBox.baseVal; return [r.left + x / vb.width * r.width, r.top + y / vb.height * r.height]; }, x, y);
const azNow = p => p.$eval('#az', e => e.textContent);
let p = await open();
console.log('Control button visible:', await p.$eval('#ctl', e => !e.hidden), '| STOP visible before:', await p.$eval('#stopBtn', e => !e.hidden));
await p.click('#ctl'); console.log('STOP visible after Control on:', await p.$eval('#stopBtn', e => !e.hidden));
// 1) click a pixel left of centre, above the horizon
let [x, y] = await hud2px(p, 500, 400); await p.mouse.click(x, y); await sleep(1500);
console.log('1 pixel click -> msg:', await p.$eval('#msg', e => e.textContent));
await sleep(8000);
// 2) click a marker (first non-line mark in view)
const mk = await p.evaluate(() => window.__hits.marks.find(h => !h.line));
if (mk) { [x, y] = await hud2px(p, mk.x + 6, mk.y + 4); await p.mouse.click(x, y); await sleep(1500); console.log('2 marker click', mk.name, '-> msg:', await p.$eval('#msg', e => e.textContent)); }
else console.log('2 no marker in view');
await sleep(8000);
// 3) track the nearest aircraft that would be drawn (below the top edge of the picture, ~+22 deg): point there first, then click its box
const pl = (await p.evaluate(() => window.__planeList())).filter(q => q.el > 0.5 && q.el < 18 && q.dist < 60000).sort((a, b) => a.dist - b.dist)[0];
if (!pl) { console.log('3 no aircraft within 60 km right now'); } else {
  console.log(`3 aircraft ${pl.id} az ${pl.az.toFixed(1)} el ${pl.el.toFixed(1)} ${(pl.dist / 1000).toFixed(0)} km - pointing there first`);
  await p.evaluate(az => fetch('telemetry/control', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hamcam-Control': '1' },
    body: JSON.stringify({ cmd: 'goto', az, el: 0 }) }), pl.az);
  await sleep(22000);
  const h = await p.evaluate(hex => window.__hits.planes.find(q => q.track.key === hex), pl.hex);
  if (!h) console.log('   box not on screen (az now', await azNow(p), ')');
  else {
    [x, y] = await hud2px(p, h.x, h.y); await p.mouse.click(x, y); await sleep(1000);
    console.log('   click on box -> msg:', await p.$eval('#msg', e => e.textContent));
    await sleep(14000);
    console.log('   overlay text:', await p.evaluate(() => [...document.querySelectorAll('#ctlmarks text')].map(t => t.textContent).join(' | ')));
    // 4) Esc = STOP
    await p.keyboard.press('Escape'); await sleep(1000); console.log('4 Esc -> msg:', await p.$eval('#msg', e => e.textContent));
    // 5) track again, then close the page -> lease must expire
    const h2 = await p.evaluate(hex => window.__hits.planes.find(q => q.track.key === hex), pl.hex);
    if (h2) { [x, y] = await hud2px(p, h2.x, h2.y); await p.mouse.click(x, y); await sleep(3000); console.log('5 tracking again, closing the page'); await p.close(); await sleep(13000); }
  }
}
await b.close();
