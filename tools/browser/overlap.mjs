// Overlap tag check (run ONLY against tools/ctltest/stack.sh - it moves the fake rotator): the "↻/↺ overlap" tag next to
// the azimuth follows the controller's raw position. Start the stack with RAW0=370 (clockwise overlap).
import puppeteer from 'puppeteer-core';
const U = 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/povl'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
p.on('pageerror', e => console.log('PAGE ERROR', e.message));
await p.goto(U, { waitUntil: 'load' }); await sleep(4000);
const goto = az => fetch(U + 'telemetry/control', { method: 'POST', body: JSON.stringify({ cmd: 'goto', az, el: 0 }),
  headers: { 'X-Forwarded-For': '192.168.12.38', 'X-Hamcam-Control': '1', 'Content-Type': 'application/json' } }).then(r => r.json());
const tag = () => p.evaluate(() => ({ az: document.getElementById('az').textContent, ovl: document.getElementById('ovl').textContent,
  title: document.querySelector('#ovl title')?.textContent ?? null }));
let fails = 0;
const check = (ok, ...m) => { console.log(ok ? 'PASS' : 'FAIL', ...m); if (!ok) fails++; };
let t = await tag(); check(t.ovl.startsWith('↻') && /clockwise overlap turn \(raw 370/.test(t.title), 'raw 370: clockwise tag', JSON.stringify(t));
await p.screenshot({ path: '/out/overlap-cw.png', clip: { x: 300, y: 0, width: 800, height: 220 } });
await goto(90); await sleep(32000);
t = await tag(); check(t.ovl === '' && t.title === null, 'raw 90: no tag', JSON.stringify(t));
await goto(350); await sleep(14000);
t = await tag(); check(t.ovl.startsWith('↺') && /counter-clockwise overlap turn \(raw -10/.test(t.title), 'raw -10: counter-clockwise tag', JSON.stringify(t));
await p.screenshot({ path: '/out/overlap-ccw.png', clip: { x: 300, y: 0, width: 800, height: 220 } });
await b.close();
console.log(fails ? `${fails} FAILED` : 'ALL PASS'); process.exit(fails ? 1 : 0);
