// Weather panel touches the DOM only when its text changes; weather layer toggle; fetches still work (timeouts).
import puppeteer from 'puppeteer-core';
const U = process.argv[2] || 'http://127.0.0.1:8098/', sleep = ms => new Promise(r => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new', args: ['--no-sandbox', '--user-data-dir=/tmp/pmin'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.goto(U, { waitUntil: 'load' }); await sleep(6000);
const wx = () => p.evaluate(() => [...document.querySelectorAll('#wx tspan')].map(t => t.textContent));
const muts = await p.evaluate(() => new Promise(res => {
  let n = 0; const o = new MutationObserver(m => n += m.length);
  o.observe(document.getElementById('wx'), { subtree: true, childList: true, characterData: true, attributes: true });
  setTimeout(() => { o.disconnect(); res(n); }, 10000);
}));
console.log('weather lines:', JSON.stringify(await wx()), '| DOM mutations in 10 s:', muts);
await p.click('#lyWx'); await sleep(300); const off = (await wx()).length;
await p.click('#lyWx'); await sleep(300); const on = (await wx()).length;
console.log('weather toggle: off ->', off, 'lines, on ->', on, 'lines');
console.log('beacons/summits/planes/sats:', JSON.stringify(await p.evaluate(() => ({
  objects: document.querySelectorAll('#marks text').length, planes: document.querySelectorAll('#planes rect').length,
  sats: document.querySelectorAll('#sats circle').length }))));
console.log('page errors:', errs.length ? errs : 'none');
await b.close();
