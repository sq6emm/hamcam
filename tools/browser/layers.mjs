// Screenshot, then toggle each layer button and count drawn elements per layer
import puppeteer from 'puppeteer-core';
const url = process.argv[2];
const b = await puppeteer.launch({ executablePath: process.env.CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-crash-reporter', '--disable-breakpad', '--user-data-dir=/tmp/prof', '--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage(); await p.setViewport({ width: 1400, height: 1100 });
const errs = []; p.on('pageerror', e => errs.push(e.message));
await p.goto(url, { waitUntil: 'load' }); await new Promise(r => setTimeout(r, 6000));
const count = () => p.evaluate(() => {
  const m = document.getElementById('marks'), col = c => [...m.querySelectorAll('text')].filter(t => t.style.fill === c).length;
  return { beaconLabels: col('rgb(196, 161, 255)'), summitLabels: col('rgb(126, 231, 135)'), poiLabels: col('rgb(255, 204, 51)'),
           planes: document.getElementById('planes').querySelectorAll('rect').length,
           sats: document.getElementById('sats').querySelectorAll('circle').length,
           bodies: document.getElementById('marks').querySelectorAll('circle').length,
           wxLines: document.querySelectorAll('#wx tspan').length, title: document.title };
});
await p.screenshot({ path: '/out/all.png' });
console.log('all on      ', JSON.stringify(await count()));
for (const id of ['lyWx', 'lyBeacons', 'lyPoi', 'lySummits', 'lyPlanes', 'lySky', 'lySats', 'lyHam']) {
  await p.click('#' + id); await new Promise(r => setTimeout(r, 400));
  console.log(`after ${id.padEnd(9)}`, JSON.stringify(await count()));
}
await p.reload({ waitUntil: 'load' }); await new Promise(r => setTimeout(r, 4000));
console.log('after reload', JSON.stringify(await count()), '(should stay all off)');
for (const id of ['lyWx', 'lyBeacons', 'lyPoi', 'lySummits', 'lyPlanes', 'lySky', 'lySats', 'lyHam']) await p.click('#' + id);
console.log('errors:', errs.length ? errs : 'none');
await b.close();
