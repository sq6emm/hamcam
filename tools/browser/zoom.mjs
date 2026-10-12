// Zoom test against tools/ctltest/stack.sh (fake rotctld): wheel zoom keeps the point under the cursor, video and HUD stay
// aligned, drag pans without clicking, buttons/keys, click-to-point while zoomed hits the same az/el as unzoomed.
import puppeteer from 'puppeteer-core';
const U = process.argv[2] || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/pzm'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
await p.setExtraHTTPHeaders({ 'X-Forwarded-For': '192.168.12.38' });
const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.goto(U, { waitUntil: 'load' }); await sleep(4000);
const probe = () => p.evaluate(() => (document.querySelector('#probe text')?.textContent || '').match(/az ([\d.]+)° el (-?[\d.]+)°/)?.slice(1).map(Number));
const rects = () => p.evaluate(() => ['ham-video', '#hud'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(v => Math.round(v)); }));
const lvl = () => p.$eval('#zoomRst', e => e.textContent);
const ok = (c, m) => console.log(c ? 'PASS' : 'FAIL', m);
const X = 900, Y = 400, r0 = await rects();
await p.mouse.click(X, Y); await sleep(300); const a0 = await probe();
for (let i = 0; i < 5; i++) { await p.mouse.move(X, Y); await p.mouse.wheel({ deltaY: -150 }); await sleep(80); }
await sleep(300); const r1 = await rects();
ok(JSON.stringify(r1[0]) === JSON.stringify(r1[1]), `video and HUD share one box when zoomed ${JSON.stringify(r1)} (level ${await lvl()})`);
await p.mouse.click(X, Y); await sleep(300); const a1 = await probe();
ok(a0 && a1 && Math.abs(a0[0] - a1[0]) < 0.05 && Math.abs(a0[1] - a1[1]) < 0.05, `wheel keeps the point under the cursor: ${a0} -> ${a1}`);
await p.mouse.click(X + 100, Y); await sleep(300); const a2 = await probe();
ok(a2 && Math.abs(a2[0] - a1[0]) < 1.2, `100 px to the right is a smaller angle when zoomed: Δaz ${(a2[0] - a1[0]).toFixed(2)}° (unzoomed ~2.7°)`);
// drag pans and is not a click
const before = await probe(), rb = await rects();
await p.mouse.move(700, 500); await p.mouse.down(); for (let i = 1; i <= 10; i++) await p.mouse.move(700 + i * 20, 500 + i * 5); await p.mouse.up(); await sleep(300);
const ra = await rects(), after = await probe();
ok(ra[0][0] - rb[0][0] === 200 && ra[0][1] - rb[0][1] === 50, `drag pans by the mouse movement: ${ra[0][0] - rb[0][0]}, ${ra[0][1] - rb[0][1]}`);
ok(JSON.stringify(before) === JSON.stringify(after), 'drag did not register as a click');
// clamped: the picture always covers its box
await p.mouse.move(700, 500); await p.mouse.down(); for (let i = 1; i <= 10; i++) await p.mouse.move(700 + i * 300, 500 + i * 300); await p.mouse.up(); await sleep(200);
const rc = await rects(), fr = await p.evaluate(() => { const r = document.querySelector('#frame').getBoundingClientRect(); return [r.left, r.top]; });
ok(rc[0][0] === r0[0][0] && rc[0][1] === r0[0][1], `pan is clamped at the picture edge ${JSON.stringify(rc[0])}`);
// buttons and keys
await p.click('#zoomRst'); await sleep(200); const l0 = await lvl();
await p.click('#zoomIn'); await sleep(100); await p.click('#zoomIn'); await sleep(100); const l2 = await lvl();
await p.click('#zoomOut'); await sleep(100); const l1 = await lvl();
await p.keyboard.press('+'); await sleep(100); const lk = await lvl();
await p.keyboard.press('0'); await sleep(100); const lr = await lvl();
for (let i = 0; i < 12; i++) await p.click('#zoomIn'); const lmax = await lvl();
ok(l0 === '1×' && l2 === '2.3×' && l1 === '1.5×' && lk === '2.3×' && lr === '1×' && lmax === '6×', `buttons/keys: ${[l0, l2, l1, lk, lr, lmax].join(' ')}`);
await p.keyboard.press('0'); await sleep(200);
// click-to-point while zoomed hits the same direction as unzoomed (Control on, fake rotator)
await p.click('#ctl'); await sleep(200); await p.click('#ctl'); await sleep(200);   // Control off again: probe click
await p.evaluate(() => { document.getElementById('ctl').click(); document.getElementById('ctl').click(); });
const ctlLayout = async on => { await p.evaluate(v => { const c = document.getElementById('ctl'); if (c.classList.contains('on') !== v) c.click(); }, on); await sleep(200); };
await ctlLayout(true); await p.evaluate(() => { document.getElementById('frame').classList.remove('ctl'); });
await p.evaluate(() => document.getElementById('ctl').click()); await sleep(100);   // off (layout with Control on is what matters)
await p.mouse.click(1000, 450); await sleep(300); const u = await probe();
await ctlLayout(true);
for (let i = 0; i < 4; i++) { await p.mouse.move(1000, 450); await p.mouse.wheel({ deltaY: -150 }); await sleep(80); }
await sleep(200); await p.mouse.click(1000, 450); await sleep(1500);
const msg = await p.$eval('#msg', e => e.textContent), m = msg.match(/→ ([\d.]+)° \/ (-?[\d.]+)°/);
ok(m && Math.abs(m[1] - u[0]) < 0.05 && Math.abs(m[2] - u[1]) < 0.05, `zoomed control click -> "${msg}" (unzoomed probe ${u})`);
await p.keyboard.press('Escape'); await sleep(500);
console.log('page errors:', errs.length ? errs : 'none');
await b.close();
