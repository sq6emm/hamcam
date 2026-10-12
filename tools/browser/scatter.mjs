// R/S, A/S, Tropo layers (rsanttracker via telemetry) against tools/ctltest/stack.sh: buttons appear, markers drawn where
// the data says, layer toggles, Control click on a cell -> goto (fake rotator). Saves /out/scatter_<az>.png.
import puppeteer from 'puppeteer-core';
const U = process.argv[2] || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/psc2'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
const errs = []; p.on('pageerror', e => errs.push(e.message));
const d = await (await fetch(U + 'telemetry/scatter')).json();
console.log('telemetry/scatter:', d.enabled, d.error, `${d.cells?.length} cells, ${d.aircraft?.length} A/S aircraft, tropo ${d.tropo?.state}, DX ${d.dx?.callsign}`);
const pick = [...(d.cells || [])].sort((a, b) => b.score - a.score)[0];
const az = Math.round(pick ? pick.az : 60);
await p.goto(`${U}?simaz=${az}`, { waitUntil: 'load' }); await sleep(7000);
const count = () => p.evaluate(() => {
  const g = document.getElementById('scatter'), t = [...g.querySelectorAll('text')].map(e => e.textContent);
  return { rs: t.filter(x => /^(R\/S|S\/S|hail) /.test(x)).length, as: t.filter(x => x.startsWith('A/S ')).length,
           tropo: t.filter(x => x.startsWith('Tropo ')), dx: t.filter(x => x.startsWith('DX ')).length,
           buttons: ['lyRs', 'lyAs', 'lyTropo'].map(id => { const e = document.getElementById(id); return `${e.textContent}:${e.hidden ? 'hidden' : e.classList.contains('on') ? 'on' : 'off'}`; }) };
});
const c0 = await count(); console.log(`view az ${az}:`, JSON.stringify(c0));
await p.screenshot({ path: `/out/scatter_${az}.png` });
for (const id of ['lyRs', 'lyAs', 'lyTropo']) { await p.click('#' + id); await sleep(300); }
console.log('all three off:', JSON.stringify(await count()));
for (const id of ['lyRs', 'lyAs', 'lyTropo']) { await p.click('#' + id); await sleep(300); }
if (pick) {                                     // Control click on the best cell's marker -> goto its aim point
  const pt = await p.evaluate(() => { const c = document.querySelector('#scatter circle'); const r = document.getElementById('hud').getBoundingClientRect();
    return c ? { x: r.left + c.cx.baseVal.value / 1600 * r.width, y: r.top + c.cy.baseVal.value / 1200 * r.height } : null; });
  if (pt) { await p.click('#ctl'); await sleep(200); await p.mouse.click(pt.x, pt.y); await sleep(1500);
    console.log('control click on a cell ->', await p.$eval('#msg', e => e.textContent)); await p.keyboard.press('Escape'); }
}
console.log('page errors:', errs.length ? errs : 'none');
await b.close();
