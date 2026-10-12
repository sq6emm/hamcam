// Off-screen tropo + R/S indicators against tools/ctltest/stack.sh: /telemetry/scatter is replaced by a synthetic answer with
// enhanced/ducting directions and rain/snow cells; checks in-view reach marks, edge arrows (nearest per side, +N), Control click -> goto.
import puppeteer from 'puppeteer-core';
const U = process.argv[2] || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/ptr'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
const errs = []; p.on('pageerror', e => errs.push(e.message));
// 16 directions: NE(2)=enhanced 450, E(4)=ducting 900 (in view at az 90), SSW(10)=super 600, W(12)=enhanced 300, N(0)=enhanced 350
const reach = Array(16).fill(0), level = Array(16).fill(null);
for (const [i, km, l] of [[0, 350, 'enhanced'], [2, 450, 'enhanced'], [4, 900, 'ducting'], [10, 600, 'super-refraction'], [12, 300, 'enhanced']]) { reach[i] = km; level[i] = l; }
const cell = (id, az, dbz, km, score, kind = 'rain', snow = false) => ({ id, az, el: 1, max_dbz: dbz, range_km: km, score, kind, snow, alt_m: 3000, area_km2: 50, reachable: true });
// at az 200: left (turn < 0) = C1 (az 100, best) and C2; right = C3 snow (az 300); in view = C4 (az 205)
const cells = [cell('C1', 100, 48, 120, 9), cell('C2', 140, 35, 60, 3), cell('C3', 300, 30, 80, 5, 'rain', true), cell('C4', 205, 40, 50, 4)];
await p.setRequestInterception(true);
p.on('request', r => {
  if (!r.url().includes('telemetry/scatter')) return r.continue();
  r.respond({ contentType: 'application/json', body: JSON.stringify({ enabled: true, updated: Date.now() / 1000, cells, aircraft: [], radio: { freq_mhz: 1296 },
    tropo: { state: 'enhanced', k: 1.6, dndh: -60, ducts: [], window: null, map_best: null, reach_km: reach, level, n_az: 16 } }) });
});
const texts = () => p.evaluate(() => [...document.querySelectorAll('#scatter text')].map(e => `${e.textContent}@${Math.round(e.getAttribute('y'))}`).filter(t => /km|Tropo/.test(t)));
for (const az of [90, 200]) {
  await p.goto(`${U}?simaz=${az}`, { waitUntil: 'load' }); await sleep(6000);
  console.log(`az ${az}:`, JSON.stringify(await texts()));
  await p.screenshot({ path: `/out/tropoff_${az}.png` });
}
// Control click on the right-hand arrow (at az 200: nearest right = W 270) -> goto
const pt = await p.evaluate(() => { const t = [...document.querySelectorAll('#scatter text')].find(e => e.textContent.startsWith('W ') && e.textContent.endsWith('▶'));
  const bb = t.getBoundingClientRect(); return { x: bb.left + bb.width / 2, y: bb.top + bb.height / 2 }; });
await p.click('#ctl'); await sleep(300); await p.mouse.click(pt.x, pt.y); await sleep(1500);
console.log('control click on right tropo arrow ->', await p.$eval('#msg', e => e.textContent));
const pt2 = await p.evaluate(() => { const t = [...document.querySelectorAll('#scatter text')].find(e => e.textContent.startsWith('◀ R/S'));
  const bb = t.getBoundingClientRect(); return { x: bb.left + 30, y: bb.top + bb.height / 2 }; });
await sleep(3500); await p.mouse.click(pt2.x, pt2.y); await sleep(1500);
console.log('control click on left R/S arrow ->', await p.$eval('#msg', e => e.textContent)); await p.keyboard.press('Escape');
console.log('page errors:', errs.length ? errs : 'none');
await b.close();
