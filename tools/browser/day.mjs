// Day view against tools/ctltest/stack.sh (panorama/web mounted): button, blend slider, D key, zoom, the picture
// follows the azimuth, button hidden without a panorama. FRAME_AZ=<az> + /in/live.jpg: also compares the day picture
// with a live frame taken at that rotator azimuth (edge correlation, best shift in px of the 1600 px view).
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
const U = process.env.U || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/pfx', '--use-angle=gl-egl', '--ignore-gpu-blocklist'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.evaluateOnNewDocument(() => { try { if (!sessionStorage.getItem('t')) { localStorage.clear(); sessionStorage.setItem('t', '1'); } } catch {} });
const errs = []; p.on('pageerror', e => errs.push(e.message));
const state = () => p.evaluate(() => {
  const c = document.getElementById('day'), btn = document.getElementById('dayBtn');
  let mean = null;
  if (!c.hidden) {                                   // average brightness of the canvas (0 = black / not drawn)
    const t = document.createElement('canvas'); t.width = 160; t.height = 120;
    const x = t.getContext('2d'); x.drawImage(c, 0, 0, 160, 120);
    const d = x.getImageData(0, 0, 160, 120).data; let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] + d[i + 1] + d[i + 2];
    mean = Math.round(s / (d.length / 4) / 3);
  }
  return { btn: btn.hidden ? 'hidden' : `${btn.textContent}${btn.classList.contains('on') ? ' (on)' : ''}`, canvas: c.hidden ? 'hidden' : `opacity ${c.style.opacity}`,
           mean, tag: document.getElementById('dayTag').hidden ? null : document.getElementById('dayTag').textContent };
});
let ok = true; const check = (c, m) => { console.log(`${c ? 'PASS' : 'FAIL'} ${m}`); ok &&= c; };

for (const az of [121.95, 280, 2]) {
  await p.goto(`${U}?simaz=${az}`, { waitUntil: 'load' }); await sleep(3000);
  const s0 = await state();
  await p.click('#dayBtn'); await sleep(4000);
  const s1 = await state();
  check(s1.btn === 'Day (on)' && s1.canvas === 'opacity 1' && s1.mean > 20, `az ${az}: Day shows the picture ${JSON.stringify(s1)} (before ${JSON.stringify(s0)})`);
  await p.screenshot({ path: `/out/day_${Math.round(az)}.png` });
}
// blend slider: vertical, bottom = live (0 %), top = day (100 %); dragging it is not a click / pan on the picture
const sl = await p.$eval('#dayOp', e => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, top: r.top, bottom: r.bottom, w: r.width, h: r.height }; });
check(sl.h > 3 * sl.w, `slider is vertical (${Math.round(sl.w)}x${Math.round(sl.h)} px)`);
const msgBefore = await p.$eval('#msg', e => e.hidden);
await p.mouse.move(sl.x, sl.top + 4); await p.mouse.down(); await p.mouse.move(sl.x, sl.bottom - sl.h * 0.25, { steps: 8 }); await p.mouse.up(); await sleep(300);
const op1 = await p.evaluate(() => [+document.getElementById('day').style.opacity, document.getElementById('dayOpTxt').textContent]);
check(op1[0] > 0.15 && op1[0] < 0.35, `drag top -> 1/4 from the bottom: opacity ${op1[0]} (${op1[1]})`);
await p.mouse.click(sl.x, sl.bottom - 3); await sleep(300);
const op0 = +(await p.$eval('#day', e => e.style.opacity));
check(op0 < 0.05, `bottom = live only: opacity ${op0}`);
await p.mouse.click(sl.x, sl.top + 3); await sleep(300);
const opT = +(await p.$eval('#day', e => e.style.opacity));
check(opT > 0.95, `top = day only: opacity ${opT}`);
check(await p.$eval('#msg', e => e.hidden) === msgBefore && !(await p.$eval('#frame', e => e.classList.contains('zoomed'))), 'slider use did not probe / pan the picture');
await p.mouse.click(sl.x, sl.top + sl.h * 0.4); await sleep(300);
const opM = +(await p.$eval('#day', e => e.style.opacity));
await p.reload({ waitUntil: 'load' }); await sleep(2500); await p.click('#dayBtn'); await sleep(2500);
const opR = +(await p.$eval('#day', e => e.style.opacity));
check(Math.abs(opR - opM) < 0.02, `slider position remembered after reload: ${opM} -> ${opR}`);
await p.screenshot({ path: '/out/day_blend.png' });
await p.keyboard.press('d'); await sleep(300);
const s3 = await state(); check(s3.btn === 'Day' && s3.canvas === 'hidden' && await p.$eval('#dayFade', e => e.hidden), `D key -> live, slider hidden: ${JSON.stringify(s3)}`);
await p.keyboard.press('d'); await sleep(500);
check((await state()).canvas.startsWith('opacity'), 'D key -> Day');
await p.click('#zoomIn'); await p.click('#zoomIn'); await sleep(500);
const z = await p.evaluate(() => [document.getElementById('day').style.transform, document.getElementById('hud').style.transform]);
check(z[0] && z[0] === z[1], `zoom moves day picture with the overlay: ${z[0]}`);
await p.screenshot({ path: '/out/day_zoom.png' });

// the picture follows the azimuth: canvas differs between two headings
const sig = async az => { await p.goto(`${U}?simaz=${az}`, { waitUntil: 'load' }); await sleep(2500); await p.click('#dayBtn'); await sleep(2500);
  return p.evaluate(() => document.getElementById('day').toDataURL('image/jpeg', 0.3).length); };
const a1 = await sig(100), a2 = await sig(200);
check(a1 !== a2, `different picture at az 100 and 200 (${a1} vs ${a2} bytes)`);

// live frame comparison
if (process.env.FRAME_AZ && fs.existsSync('/in/live.jpg')) {
  await p.goto(`${U}?simaz=${process.env.FRAME_AZ}`, { waitUntil: 'load' }); await sleep(2500); await p.click('#dayBtn'); await sleep(3000);
  const live = 'data:image/jpeg;base64,' + fs.readFileSync('/in/live.jpg').toString('base64');
  const r = await p.evaluate(async live => {
    const W = 400, H = 300, get = async src => {
      const t = document.createElement('canvas'); t.width = W; t.height = H; const x = t.getContext('2d');
      if (typeof src === 'string') { const i = new Image(); i.src = src; await i.decode(); x.drawImage(i, 0, 0, W, H); } else x.drawImage(src, 0, 0, W, H);
      const d = x.getImageData(0, 0, W, H).data, g = new Float32Array(W * H);
      for (let i = 0; i < W * H; i++) g[i] = d[4 * i] + d[4 * i + 1] + d[4 * i + 2];
      const e = new Float32Array(W * H);                            // gradient magnitude
      for (let y = 1; y < H - 1; y++) for (let xx = 1; xx < W - 1; xx++) { const k = y * W + xx; e[k] = Math.hypot(g[k + 1] - g[k - 1], g[k + W] - g[k - W]); }
      return e;
    };
    const a = await get(document.getElementById('day')), bb = await get(live);
    let best = null;
    for (let dy = -8; dy <= 8; dy++) for (let dx = -12; dx <= 12; dx++) {
      let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0, n = 0;
      for (let y = 30; y < H - 30; y += 2) for (let x = 30; x < W - 30; x += 2) {
        const u = a[y * W + x], v = bb[(y + dy) * W + x + dx]; sa += u; sb += v; saa += u * u; sbb += v * v; sab += u * v; n++;
      }
      const c = (sab - sa * sb / n) / Math.sqrt((saa - sa * sa / n) * (sbb - sb * sb / n));
      if (!best || c > best.c) best = { c, dx, dy };
    }
    return { corr: +best.c.toFixed(2), dx_px1600: best.dx * 4, dy_px1600: best.dy * 4 };
  }, live);
  check(r.corr > 0.2 && Math.abs(r.dx_px1600) <= 24 && Math.abs(r.dy_px1600) <= 24, `day picture vs live frame at az ${process.env.FRAME_AZ}: ${JSON.stringify(r)} (23 px = 1 deg)`);
}

// no panorama -> no button
await p.setRequestInterception(true);
p.on('request', r => r.url().includes('panorama/') ? r.respond({ status: 404, body: '' }) : r.continue());
await p.goto(U, { waitUntil: 'load' }); await sleep(2500);
check((await state()).btn === 'hidden', 'no panorama -> Day button hidden');

console.log('page errors:', errs.length ? errs : 'none'); ok &&= !errs.length;
console.log(ok ? 'ALL PASS' : 'SOME FAILED'); await b.close();
