// Track a satellite (via its circle), then: Control off must end tracking; another viewer taking over must stop this page.
import puppeteer from 'puppeteer-core';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/pst'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
await p.evaluateOnNewDocument(() => { window.__hook = true; });
await p.goto('http://127.0.0.1:8098/', { waitUntil: 'load' }); await sleep(5000);
const post = body => p.evaluate(b => fetch('telemetry/control', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hamcam-Control': '1' }, body: JSON.stringify(b) }).then(r => r.status), body);
const hud2px = (x, y) => p.evaluate((x, y) => { const s = document.getElementById('hud'), r = s.getBoundingClientRect(), vb = s.viewBox.baseVal; return [r.left + x / vb.width * r.width, r.top + y / vb.height * r.height]; }, x, y);
const msg = () => p.$eval('#msg', e => e.textContent);
await p.click('#ctl');
let sat = null;
for (const az of [0, 60, 120, 180, 240, 300]) {           // look around for a satellite in the picture
  await post({ cmd: "goto", az, el: 0 }); await sleep(az === 0 ? 20000 : 11000);
  sat = await p.evaluate(() => window.__hits.sats[0]); if (sat) break;
}
if (!sat) { console.log('no satellite in view anywhere'); await b.close(); process.exit(0); }
let [x, y] = await hud2px(sat.x, sat.y); await p.mouse.click(x, y); await sleep(1500);
console.log('click on satellite ->', await msg());
await sleep(5000);
console.log('tracking shown:', await p.evaluate(() => [...document.querySelectorAll('#ctlmarks text')].map(t => t.textContent).join('')));
await p.click('#ctl'); await sleep(1500);                   // #6: Control off
console.log('Control off ->', await msg(), '| STOP hidden:', await p.$eval('#stopBtn', e => e.hidden));
await sleep(4000);
// #7: track again, then another viewer tracks something else
await p.click('#ctl'); const s2 = await p.evaluate(() => window.__hits.sats[0]);
if (s2) { [x, y] = await hud2px(s2.x, s2.y); await p.mouse.click(x, y); await sleep(4000);
  const c = await (await fetch('http://127.0.0.1:8098/telemetry/control', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Hamcam-Control': '1', 'X-Forwarded-For': '192.168.12.50' }, body: JSON.stringify({ cmd: 'track', az: 10, el: 5, name: 'OTHER-VIEWER' }) })).status;
  await sleep(5000); console.log(`other viewer tracks (HTTP ${c}) ->`, await msg()); }
await sleep(6000);
await b.close();
