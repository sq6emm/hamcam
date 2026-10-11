// hamcam page: go2rtc player (WebRTC, MSE fallback) + SVG HUD fed by the telemetry WebSocket.
// Camera model, station and objects come from objects.json; query params override camera values:
//   ?hfov= &pitch= &roll= &azoff= &azdelay= &bx= &by=
import { VideoRTC } from './video-rtc.js';
import { Camera, azElOf, bodies, locatorToLatLon } from './sky.js';
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

const q = new URLSearchParams(location.search);
const scene = await fetch('objects.json', { cache: 'no-cache' }).then(r => r.json());
const num = (k, d) => (q.has(k) ? parseFloat(q.get(k)) : d);
const cam0 = scene.camera;
const cfg = {
  src: 'main',                                   // always the full-resolution stream
  hfov: num('hfov', cam0.hfov),                  // horizontal field of view (deg), with the distortion model
  // lens model measured with the rotator as turntable (focal px at the camera's ref width, radial k1/k2)
  f: cam0.f_px ? cam0.f_px * 1600 / cam0.f_ref_w : null,         // HUD is 1600 wide
  k1: num('k1', cam0.k1 || 0), k2: num('k2', cam0.k2 || 0),
  pp: (cam0.pp_px || [0, 0]).map(v => v * 1600 / (cam0.f_ref_w || 1600)),
  pitch: num('pitch', cam0.pitch),               // camera tilt (deg, + up)
  roll: num('roll', cam0.roll),
  azOff: num('azoff', cam0.az_offset),           // true az of image centre = rotator az + azOff
  // video arrives ~1 s after rotctld reports the position (camera ~0.45 s + rotator/mast lag);
  // the overlay shows the azimuth from this long ago so it matches the picture while turning
  azDelay: num('azdelay', cam0.az_delay),
  bx: num('bx', cam0.boresight[0]),              // boresight (antenna direction) as fraction of the frame
  by: num('by', cam0.boresight[1]),
};
// HUD viewBox: 1600 wide, height from the camera's aspect ratio (camera.width/height in objects.json)
const W = 1600, H = Math.round(1600 * (cam0.height || 3) / (cam0.width || 4));
document.getElementById('hud').setAttribute('viewBox', `0 0 ${W} ${H}`);
const DISP = scene.display || {};
const SVG = 'http://www.w3.org/2000/svg';
const ST = scene.station;
const $ = id => document.getElementById(id);
const camera = new Camera({ W, H, hfov: cfg.hfov, f: q.has('hfov') ? null : cfg.f, k1: cfg.k1, k2: cfg.k2, pp: cfg.pp, pitch: cfg.pitch, roll: cfg.roll, tilt: q.has('notilt') ? null : cam0.tilt });

// objects: resolve locators, precompute az/el/distance from the station
const placeObject = o => {
  if (o.locator && o.lat == null) Object.assign(o, locatorToLatLon(o.locator));
  return Object.assign(o, azElOf(ST, o.lat, o.lon, o.h ?? ST.h));
};
scene.objects.forEach(placeObject);
// beacons (IARU list, merged daily) and SOTA summits visible from the station: computed by the telemetry service, re-fetched hourly
const fixedObjects = scene.objects.slice();
const beaconsNow = () => scene.objects.filter(o => o.kind === 'beacon'), summitsNow = () => scene.objects.filter(o => o.kind === 'summit');
// layers: objects.json display.layers.<name> = "on" (shown) | "off" (button, hidden at start) | "disabled" (no button, no data)
const LAYER_NAMES = ['weather', 'beacons', 'poi', 'summits', 'planes', 'sky', 'sats', 'hamsats'];
const layerMode = k => (DISP.layers || {})[k] ?? 'on';
const enabled = k => layerMode(k) !== 'disabled';
const layers = Object.fromEntries(LAYER_NAMES.map(k => [k, layerMode(k) === 'on']));
try {                                                    // the viewer's own choice (per browser) wins, except for disabled layers
  const saved = JSON.parse(localStorage.getItem('hamcam.layers') || '{}');
  for (const k of LAYER_NAMES) if (enabled(k) && k in saved) layers[k] = !!saved[k];
} catch { /* no storage */ }
document.title = `${ST.call} ${DISP.title || 'antenna cam'}`;
document.querySelector('#bar .title').textContent = `${ST.call} · ${DISP.title || 'antenna cam'}`;
async function loadBeacons() {
  try {
    const get = (on, u) => on ? fetch(u, { cache: 'no-store' }).then(r => r.json()).catch(() => null) : Promise.resolve({ beacons: [], summits: [] });
    const [d, sm] = await Promise.all([get(enabled('beacons'), 'telemetry/beacons'), get(enabled('summits'), 'telemetry/summits')]);
    scene.objects = [...fixedObjects,
      ...(d ? d.beacons.map(b => placeObject({ ...b, kind: 'beacon' })) : beaconsNow()),
      ...(sm ? sm.summits.map(s => placeObject({ ...s, kind: 'summit' })) : summitsNow())];
    if (shownAz != null) drawMarks(shownAz);
  } catch { /* keep what we have */ }
}


// ---------- video ----------
class HamVideo extends VideoRTC {
  oninit() {
    super.oninit();
    this.video.controls = false;
    this.video.muted = true;
  }
}
customElements.define('ham-video', HamVideo);

const player = $('video');
player.mode = 'webrtc,mse';
player.media = 'video';
player.background = true;          // keep streaming when tab is hidden (no reconnect delay)

player.src = new URL(`api/ws?src=${cfg.src}`, location.href).href;

// watchdog: camera/go2rtc hiccups can leave a connected but frozen stream -> reconnect after 5 s without frames
let lastFrameT = Date.now(), lastVT = -1;
setInterval(() => {
  const v = player.video;
  if (!v) return;
  if (v.currentTime !== lastVT) { lastVT = v.currentTime; lastFrameT = Date.now(); return; }
  if (Date.now() - lastFrameT > 5000) {
    console.warn('no video frames for 5 s, reconnecting');
    lastFrameT = Date.now();
    player.ondisconnect();
    player.src = new URL(`api/ws?src=${cfg.src}`, location.href).href;
  }
}, 1000);

// MSE fallback: stay at the live edge (WebRTC manages its own jitter buffer)
setInterval(() => {
  const v = player.video;
  if (!v || v.srcObject || !v.buffered.length) return;
  const lag = v.buffered.end(v.buffered.length - 1) - v.currentTime;
  if (lag > 1.0) v.currentTime = v.buffered.end(v.buffered.length - 1) - 0.1;
  else v.playbackRate = lag > 0.3 ? 1.1 : 1.0;
}, 500);

// MSE delay compensation: with MSE the visible frame is older than with WebRTC by the video waiting in the buffer,
// so that much is added to every "as in the frame" time (azimuth, aircraft, satellites). WebRTC: 0.
// Smoothed (time constant ~1 s), limited to 0..3 s. ?msecomp=0 switches it off (for comparison tests).
const MSE_COMP = q.get('msecomp') !== '0';
let mseExtra = 0;
setInterval(() => {
  const v = player.video;
  if (!MSE_COMP || !v || v.srcObject || !v.buffered.length) { mseExtra = 0; if (window.__hook) window.__mseExtra = 0; return; }
  const lag = Math.min(Math.max(v.buffered.end(v.buffered.length - 1) - v.currentTime, 0), 3);
  mseExtra += (lag - mseExtra) * 0.1;
  if (window.__hook) window.__mseExtra = mseExtra;      // test hook (set only by the browser tests)
}, 100);

// ---------- HUD ----------
const focal = camera.f;
const bx = cfg.bx * W, by = cfg.by * H;
const azToX = d => camera.xOf(d) + bx - W / 2;                      // d = bearing minus antenna az (tape)

function el(tag, attrs, parent) {
  const e = document.createElementNS(SVG, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  // the SVG <style> beats presentation attributes, so colours go in as inline style
  for (const k of ['stroke', 'fill']) if (k in attrs) e.style[k] = attrs[k];
  parent && parent.appendChild(e);
  return e;
}

// boresight reticle (fixed: azimuth-only rotator, camera moves with the antenna)
(() => {
  const g = $('boresight');
  // dashed vertical line through the image centre, from the tape down to the bottom of the frame
  el('line', { x1: bx, y1: 84, x2: bx, y2: H }, g).style.strokeDasharray = '6 10';
  // elevation scale (true elevation, from the camera model: pitch, roll, lens distortion)
  camera.setYaw(0);
  for (const e of [-15, -10, -5, 0, 5, 10, 15]) {
    const y = camera.project(0, e).y;
    if (y < 100 || y > H - 20) continue;
    const len = e === 0 ? 30 : 16;
    el('line', { x1: bx - len, y1: y, x2: bx + len, y2: y }, g);
    el('rect', { x: bx + len + 3, y: y - 15, width: e ? 62 : 36, height: 30, rx: 5, class: 'panel' }, g);   // readable over bearing labels
    const t = el('text', { x: bx + len + 8, y: y + 8, class: 'elv' }, g);
    t.textContent = `${e > 0 ? '+' : e < 0 ? '\u2212' : ''}${Math.abs(e)}°`;
  }
})();

const CARD = { 0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW' };
function drawTape(az) {
  const g = $('tape');
  g.replaceChildren();
  el('path', { d: `M0 80 H${W}`, 'stroke-width': 2 }, g);
  el('path', { d: `M${bx - 12} 92 L${bx} 80 L${bx + 12} 92`, 'stroke-width': 3, fill: 'none' }, g);
  const half = cfg.hfov / 2 + 5;
  for (let b = Math.ceil((az - half) / 5) * 5; b <= az + half; b += 5) {
    const x = azToX(b - az);
    if (x < 0 || x > W) continue;
    const brg = ((b % 360) + 360) % 360;
    const major = brg % 10 === 0;
    el('line', { x1: x, y1: 80, x2: x, y2: major ? 52 : 66, 'stroke-width': major ? 3 : 2 }, g);
    if (CARD[brg] !== undefined) {
      const t = el('text', { x, y: 40, 'text-anchor': 'middle', class: 'card' }, g); t.textContent = CARD[brg];
    } else if (major) {
      const t = el('text', { x, y: 40, 'text-anchor': 'middle' }, g); t.textContent = String(brg).padStart(3, '0');
    }
  }
}

// ---------- objects, Sun, Moon ----------
let sky = [];                                     // Sun, Moon, planets; refreshed every 5 s
const refreshSky = () => { sky = bodies(ST, new Date(Date.now() + clockOffset)); };
const fmtKm = d => (d < 10000 ? (d / 1000).toFixed(1) : Math.round(d / 1000)) + ' km';
const COL = { landmark: '#ffcc33', radio: '#5ad1ff', beacon: '#c4a1ff', summit: '#7ee787', Sun: '#ffb020', Moon: '#e6e9ef',
  Mercury: '#c9c3b8', Venus: '#fff1b8', Mars: '#ff8a65', Jupiter: '#ffd6a0', Saturn: '#ead28c', Uranus: '#a5f3fc', Neptune: '#93b4ff' };

function label(g, x, y, text, color, anchor = 'start', cls = 'sm') {
  const t = el('text', { x, y, 'text-anchor': anchor, class: cls }, g);
  t.style.fill = color; t.textContent = text; return t;
}

// hanging labels start under the tape, or under the az box near the centre
const topY = x => (x > 640 && x < 960 ? 196 : 124);

// vertical label reading bottom-to-top, centred on x. 'start': text rises from y; 'end': text hangs down to y
function vlabel(g, x, y, text, color, anchor = 'start') {
  const t = el('text', { x, y, 'text-anchor': anchor, 'dominant-baseline': 'central', class: 'sm', transform: `rotate(-90 ${x} ${y})` }, g);
  t.style.fill = color; t.textContent = text; return t;
}

// marks on the tape (always, also for things above/below the frame) and in the picture
// clickable things drawn this frame (rotator control): {x, y, r?, line?, az, el, name} or {..., track: {type, key, name}}
const hits = { marks: [], planes: [], sats: [] };

function drawMarks(az) {
  const g = $('marks');
  g.replaceChildren();
  hits.marks = [];
  camera.setYaw(az + cfg.azOff);
  const items = [
    ...scene.objects.filter(o => layers[LAYER_OF[o.kind] || 'poi']).map(o => ({ ...o, color: COL[o.kind] || COL.landmark })),
    ...(layers.sky ? sky.map(b => ({ ...b, kind: 'body', color: COL[b.name] })) : []),
  ];
  const summits = [];
  for (const it of items) {
    const d = ((it.az - (az + cfg.azOff) + 540) % 360) - 180;       // bearing relative to image centre
    if (Math.abs(d) > cfg.hfov / 2 + 2) continue;
    const tx = azToX(d);
    // tape marker
    if (it.kind === 'radio' || it.kind === 'beacon') {
      el('path', { d: `M${tx - 9} 84 L${tx + 9} 84 L${tx} 98 Z`, fill: 'none', stroke: it.color, 'stroke-width': 3 }, g);
    } else if (it.kind === 'summit') {
      el('path', { d: `M${tx - 6} 96 L${tx + 6} 96 L${tx} 86 Z`, fill: it.color, stroke: '#000', 'stroke-width': 1 }, g);
    } else if (it.kind === 'body') {
      el('circle', { cx: tx, cy: 92, r: 8, fill: it.color, stroke: '#000', 'stroke-width': 1.5 }, g);
    } else {
      el('path', { d: `M${tx} 84 L${tx + 8} 92 L${tx} 100 L${tx - 8} 92 Z`, fill: it.color, stroke: '#000', 'stroke-width': 1.5 }, g);
    }
    const p = camera.project(it.az, it.el);
    if (!p.front) continue;
    if (it.kind === 'radio' || it.kind === 'beacon') {
      // never visible: dashed bearing line through the picture + label, no point
      const ln = el('line', { x1: p.x, y1: 110, x2: p.x, y2: H - 60, stroke: it.color, 'stroke-width': 2 }, g);
      ln.style.strokeDasharray = '4 14'; ln.style.stroke = it.color;
      vlabel(g, p.x + 16, topY(p.x + 16), `${it.name}${it.freq ? ' ' + it.freq.toFixed(3) : ''} ${it.az.toFixed(1)}° ${fmtKm(it.dist)}`, it.color, 'end');
      hits.marks.push({ x: p.x, line: true, az: it.az, el: 0, name: it.name });   // bearing only -> horizon
      continue;
    }
    if (p.y > 110 && p.y < H - 10) hits.marks.push({ x: p.x, y: p.y, az: it.az, el: it.el, name: it.name });
    if (it.kind === 'summit') { summits.push({ it, p }); continue; }
    const inY = p.y > 110 && p.y < H - 10;
    const y = Math.min(Math.max(p.y, 118), H - 20);
    if (it.kind === 'body') {
      const r = Math.max(camera.degToPx(it.diam / 2), 6);
      const below = it.el < -0.5;                      // behind the Earth: shown dimmed, label says so
      const bg = below ? el('g', { opacity: 0.4 }, g) : g;
      const c = el('circle', { cx: p.x, cy: y, r: inY ? r : 6, fill: 'none', 'stroke-width': 3 }, bg);
      c.style.stroke = it.color;
      if (inY) el('circle', { cx: p.x, cy: y, r: r + 14, fill: 'none', 'stroke-width': 1.5 }, bg).style.stroke = it.color;
      const extra = it.name === 'Moon' ? ` ${Math.round(it.illum * 100)}%` : it.mag != null ? ` ${it.mag.toFixed(1)}m` : '';
      const txt = `${it.name}${extra} ${it.az.toFixed(1)}° el ${it.el.toFixed(1)}°${below ? ' (below horizon)' : ''}`;
      if (inY) vlabel(bg, p.x, y - r - 22, txt, it.color);
      else {
        // below the frame: label rises from just above the camera OSD line
        vlabel(g, p.x + 16, p.y <= 110 ? topY(p.x + 16) : H - 110, `${txt} ${p.y <= 110 ? '↑' : '↓'}`, it.color, p.y <= 110 ? 'end' : 'start');
      }
    } else {
      const m = el('path', { d: `M${p.x} ${y - 10} L${p.x + 10} ${y} L${p.x} ${y + 10} L${p.x - 10} ${y} Z`, fill: 'none', 'stroke-width': 3 }, g);
      m.style.stroke = it.color;
      if (inY) el('line', { x1: p.x, y1: y - 14, x2: p.x, y2: y - 46, 'stroke-width': 2 }, g).style.stroke = it.color;
      const lx = Math.abs(p.x - bx) < 36 ? bx - 36 : p.x;              // keep clear of the elevation scale
      vlabel(g, lx, y - 54, `${it.name} ${it.az.toFixed(1)}° ${fmtKm(it.dist)}${inY ? '' : (p.y <= 110 ? ' ↑' : ' ↓')}`, it.color);
    }
  }
  // summits: marker for each, labels for the highest first where they do not overlap (vertical text ~26 px wide)
  const used = [];
  for (const { it, p } of summits.sort((x, y) => y.it.h - x.it.h)) {
    if (p.y < 110 || p.y > H - 10) continue;
    const m = el('path', { d: `M${p.x - 7} ${p.y + 5} L${p.x + 7} ${p.y + 5} L${p.x} ${p.y - 7} Z`, fill: 'none', 'stroke-width': 2.5 }, g);
    m.style.stroke = it.color;
    if (used.some(x => Math.abs(x - p.x) < 28)) continue;
    used.push(p.x);
    el('line', { x1: p.x, y1: p.y - 10, x2: p.x, y2: p.y - 30, 'stroke-width': 1.5 }, g).style.stroke = it.color;
    vlabel(g, p.x, p.y - 36, `${it.name} ${Math.round(it.h)} m ${fmtKm(it.dist)}`, it.color);
  }
}

// ---------- aircraft: ADS-B from the local receiver (same as https://sq6emm.hamradio.pl/adsb/) ----------
const PLANE_COL = '#5eead4';
const GEOID_N = DISP.geoid_n_m ?? 0;                // geoid height above WGS84 at the station (m): alt_geom is ellipsoidal, h is ASL
const VIDEO_LAG = DISP.video_lag_s ?? 0.45;         // camera -> browser (s): show aircraft/satellites where they were when the frame was taken
const ADSB_KM = num('adsbkm', DISP.adsb_max_km ?? 60);   // farther aircraft are not visible in the picture anyway
let planes = [];
async function pollAdsb() {
  if (!enabled('planes')) return;
  try {
    const d = await fetch('adsb/aircraft.json', { cache: 'no-store' }).then(r => r.json());
    planes = d.aircraft.filter(p => p.lat != null && p.seen_pos < 20 && p.alt_baro !== 'ground'
                                    && (typeof p.alt_geom === 'number' || typeof p.alt_baro === 'number'))
      .map(p => ({
        hex: p.hex, id: (p.flight || '').trim() || p.r || p.hex.toUpperCase(),
        type: p.t || '', lat: p.lat, lon: p.lon,
        h: typeof p.alt_geom === 'number' ? p.alt_geom * 0.3048 - GEOID_N : p.alt_baro * 0.3048,
        fl: typeof p.alt_baro === 'number' ? Math.round(p.alt_baro / 100) : null,
        v: (p.gs || 0) * 0.514444, trk: (p.track || 0) * D2R, vz: ((p.geom_rate ?? p.baro_rate) || 0) * 0.00508,
        t: d.now - p.seen_pos,
      }));
  } catch { planes = []; }
}
pollAdsb(); setInterval(pollAdsb, 1000);

// position (az, el, distance) of an aircraft at time t (s): dead-reckoned from its last ADS-B report
function planeLook(p, t) {
  const dt = Math.min(Math.max(t - p.t, 0), 20), s = p.v * dt;
  const lat = p.lat + s * Math.cos(p.trk) / 111132;
  const lon = p.lon + s * Math.sin(p.trk) / (111320 * Math.cos(lat * D2R));
  return azElOf(ST, lat, lon, p.h + p.vz * dt);
}

function drawPlanes(az) {
  const g = $('planes');
  g.replaceChildren();
  hits.planes = [];
  if (az == null || !layers.planes) return;
  const yaw = az + cfg.azOff;
  camera.setYaw(yaw);
  const tNow = (Date.now() + clockOffset) / 1000 - VIDEO_LAG - mseExtra;
  const shown = [], boxes = [];
  hits.planes = [];
  for (const p of planes) {
    const { az: paz, el: pel, dist } = planeLook(p, tNow);       // where it was when the frame was taken
    if (pel < -0.3 || dist > ADSB_KM * 1000) continue;            // below the horizon / too far to see
    if (Math.abs(((paz - yaw + 540) % 360) - 180) > cfg.hfov / 2 + 2) continue;
    const q = camera.project(paz, pel);
    if (!q.front || q.x < 0 || q.x > W || q.y < 110 || q.y > H - 10) continue;
    shown.push({ p, q, dist });
  }
  // nearest first; labels step down until they no longer overlap an earlier one
  shown.sort((a, b) => a.dist - b.dist);
  const taken = [];
  const hit = (x0, y0, x1, y1) => taken.some(b => x0 < b[2] && x1 > b[0] && y0 < b[3] && y1 > b[1]);
  for (const { p, q, dist } of shown) {
    const r = Math.max(camera.degToPx(Math.atan(25 / dist) * R2D), 18);   // box ~ aircraft size, at least 36 px
    const op = dist > ADSB_KM * 500 ? 0.55 : 1;
    const tracked = track && track.type === 'plane' && track.key === p.hex;
    hits.planes.push({ x: q.x, y: q.y, r, track: { type: 'plane', key: p.hex, name: p.id } });
    const box = el('rect', { x: q.x - r, y: q.y - r, width: 2 * r, height: 2 * r, rx: 4, fill: 'none', 'stroke-width': tracked ? 6 : 2.5 }, g);
    box.style.stroke = PLANE_COL; box.style.opacity = op;
    const l2 = `${p.type ? p.type + ' ' : ''}${p.fl != null ? 'FL' + String(p.fl).padStart(3, '0') + ' ' : ''}${fmtKm(dist)}`;
    const wTxt = Math.max(p.id.length * 16, l2.length * 13.5) + 4;
    const end = q.x + r + 8 + wTxt > W;
    const x = end ? q.x - r - 8 : q.x + r + 8, x0 = end ? x - wTxt : x, x1 = end ? x : x + wTxt;
    let y = q.y - 4;
    for (let i = 0; i < 6 && hit(x0, y - 24, x1, y + 30); i++) y += 56;
    taken.push([x0, y - 24, x1, y + 30]);
    if (Math.abs(y - (q.y - 4)) > 1)                                   // leader line to a shifted label
      el('line', { x1: end ? q.x - r : q.x + r, y1: q.y, x2: x, y2: y + 6, 'stroke-width': 1.5 }, g).style.stroke = PLANE_COL;
    label(g, x, y, p.id, PLANE_COL, end ? 'end' : 'start', 'pl').style.opacity = op;
    label(g, x, y + 26, l2, PLANE_COL, end ? 'end' : 'start').style.opacity = op;
  }
}
setInterval(() => drawPlanes(shownAz), 100);

// ---------- satellites: TLEs from the telemetry service (CelesTrak, cached), propagated here with satellite.js ----------
const SAT = { sats: { url: 'telemetry/tle/visual', col: '#f0abfc', recs: [] },
              hamsats: { url: 'telemetry/tle/amateur', col: '#fdba74', recs: [] } };
const OBS_GD = { latitude: ST.lat * D2R, longitude: ST.lon * D2R, height: ST.h / 1000 };
async function loadTle() {
  for (const [key, g] of Object.entries(SAT)) {
    if (!enabled(key)) continue;
    try {
      const L = (await fetch(g.url, { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })).split(/\r?\n/);
      const recs = [];
      for (let i = 1; i + 1 < L.length; i++)
        if (L[i].startsWith('1 ') && L[i + 1].startsWith('2 ')) recs.push({ name: L[i - 1].trim(), rec: satellite.twoline2satrec(L[i], L[i + 1]) });
      g.recs = recs;
    } catch { /* keep the previous set */ }
  }
}
loadTle(); setInterval(loadTle, 6 * 3600 * 1000);

function satLook(rec, date) {
  const pv = satellite.propagate(rec, date);
  if (!pv || !pv.position) return null;
  const la = satellite.ecfToLookAngles(OBS_GD, satellite.eciToEcf(pv.position, satellite.gstime(date)));
  return { az: (la.azimuth * R2D + 360) % 360, el: la.elevation * R2D, range: la.rangeSat, eci: pv.position };
}
// in Earth's shadow (cylinder model): seen only when sunlit
function inShadow(eci, sunDir) {
  const p = eci.x * sunDir[0] + eci.y * sunDir[1] + eci.z * sunDir[2];
  if (p > 0) return false;
  return Math.hypot(eci.x - p * sunDir[0], eci.y - p * sunDir[1], eci.z - p * sunDir[2]) < 6371;
}

function drawSats(az) {
  const g = $('sats');
  g.replaceChildren();
  hits.sats = [];
  if (az == null || !(layers.sats || layers.hamsats) || !window.satellite) return;
  const yaw = az + cfg.azOff;
  camera.setYaw(yaw);
  const date = new Date(Date.now() + clockOffset - (VIDEO_LAG + mseExtra) * 1000), later = new Date(date.getTime() + 20000);
  const sv = window.Astronomy.GeoVector('Sun', date, true), sn = Math.hypot(sv.x, sv.y, sv.z);
  const sunDir = [sv.x / sn, sv.y / sn, sv.z / sn];
  const taken = [], seen = new Set();
  for (const key of ['hamsats', 'sats']) {                 // ham first: a satellite in both lists gets the ham colour
    if (!layers[key]) continue;
    for (const s of SAT[key].recs) {
      if (seen.has(s.rec.satnum)) continue;
      const l = satLook(s.rec, date);
      if (!l || l.el < 0) continue;
      if (Math.abs(((l.az - yaw + 540) % 360) - 180) > cfg.hfov / 2 + 2) continue;
      const q = camera.project(l.az, l.el);
      if (!q.front || q.x < 0 || q.x > W || q.y < 110 || q.y > H - 10) continue;
      seen.add(s.rec.satnum);
      const dark = inShadow(l.eci, sunDir), col = SAT[key].col, op = dark ? 0.45 : 1;
      const l2 = satLook(s.rec, later);                    // where it will be in 20 s: direction of motion
      if (l2) {
        const q2 = camera.project(l2.az, l2.el);
        if (q2.front) {
          const ln = el('line', { x1: q.x, y1: q.y, x2: q2.x, y2: q2.y, 'stroke-width': 2 }, g);
          ln.style.stroke = col; ln.style.opacity = op; ln.style.strokeDasharray = '3 5';
        }
      }
      const tracked = track && track.type === 'sat' && track.key === s.rec.satnum;
      hits.sats.push({ x: q.x, y: q.y, track: { type: 'sat', key: s.rec.satnum, name: s.name.replace(/\s+/g, ' ').slice(0, 22) } });
      const c = el('circle', { cx: q.x, cy: q.y, r: tracked ? 12 : 7, fill: 'none', 'stroke-width': tracked ? 4 : 2.5 }, g);
      c.style.stroke = col; c.style.opacity = op;
      const name = s.name.replace(/\s+/g, ' ').slice(0, 22);
      const l2txt = `el ${l.el.toFixed(0)}° ${Math.round(l.range)} km${dark ? ' · shadow' : ''}`;
      const wTxt = Math.max(name.length * 13.5, l2txt.length * 12.5);
      const end = q.x + 14 + wTxt > W, x = end ? q.x - 14 : q.x + 14, x0 = end ? x - wTxt : x, x1 = end ? x : x + wTxt;
      let y = q.y - 2;
      for (let i = 0; i < 5 && taken.some(b => x0 < b[2] && x1 > b[0] && y - 22 < b[3] && y + 26 > b[1]); i++) y += 50;
      taken.push([x0, y - 22, x1, y + 26]);
      label(g, x, y, name, col, end ? 'end' : 'start').style.opacity = op;
      label(g, x, y + 24, l2txt, col, end ? 'end' : 'start').style.opacity = op;
    }
  }
}
setInterval(() => drawSats(shownAz), 200);

// click on the picture: az/el of that point + offset to the nearest object (for calibration)
let probe = null;
function drawProbe() {
  const g = $('probe');
  g.replaceChildren();
  if (!probe || Date.now() - probe.t > 15000) return;
  const { x, y, az, el: e, near } = probe;
  for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]])
    el('line', { x1: x + dx * 6, y1: y + dy * 6, x2: x + dx * 22, y2: y + dy * 22, 'stroke-width': 2.5 }, g).style.stroke = '#ff5ad1';
  const lines = [`click: az ${az.toFixed(2)}° el ${e.toFixed(2)}°`];
  if (near) lines.push(`${near.name}: Δaz ${(near.daz >= 0 ? '+' : '') + near.daz.toFixed(2)}°  Δel ${(near.del >= 0 ? '+' : '') + near.del.toFixed(2)}°`);
  lines.forEach((l, i) => label(g, x + 28, y + 8 + i * 30, l, '#ff9ae6'));
}
$('frame').addEventListener('click', ev => {
  const r = $('hud').getBoundingClientRect();
  const x = (ev.clientX - r.left) / r.width * W, y = (ev.clientY - r.top) / r.height * H;
  if (x < 0 || x > W || y < 0 || y > H || shownAz == null) return;
  if (ctlOn) { controlClick(x, y); return; }
  const { az, el: e } = camera.unproject(x, y);
  let near = null;
  for (const o of [...scene.objects.filter(o => o.kind !== 'radio' && o.kind !== 'beacon'), ...sky]) {
    const daz = ((az - o.az + 540) % 360) - 180, del = e - o.el;
    if (Math.abs(daz) < 6 && (!near || Math.abs(daz) < Math.abs(near.daz))) near = { name: o.name, daz, del };
  }
  probe = { t: Date.now(), x, y, az, el: e, near };
  drawProbe();
});


// ---------- rotator control: click-to-point and tracking (only for allowed networks; the server enforces it) ----------
let ctlOn = false, track = null;                       // track: {type: 'plane'|'sat', key, name, since}
const wrap360 = a => ((a % 360) + 360) % 360;
async function ctl(body) {
  try {
    const r = await fetch('telemetry/control', { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Hamcam-Control': '1' }, body: JSON.stringify(body) });
    if (!r.ok) { flash(`Rotator: ${(await r.text()).slice(0, 80)}`); return null; }
    return await r.json();
  } catch { flash('Rotator: no connection'); return null; }
}
fetch('telemetry/control', { cache: 'no-store' }).then(r => r.json())
  .then(d => { if (d.allowed) $('ctl').hidden = false; }).catch(() => { /* control not available */ });
$('ctl').onclick = () => {
  ctlOn = !ctlOn;
  $('ctl').classList.toggle('on', ctlOn); $('stopBtn').hidden = !ctlOn; $('frame').classList.toggle('ctl', ctlOn);
};
function stopNow() { track = null; ctl({ cmd: 'stop' }); flash('Rotator: STOP'); }
$('stopBtn').onclick = stopNow;
document.addEventListener('keydown', e => { if (e.key === 'Escape' && ctlOn) stopNow(); });

// click: nearest drawn object (planes/satellites -> track, others -> their exact az/el), else the clicked pixel
function controlClick(x, y) {
  let best = null;
  if (!$('hud').classList.contains('off')) {
    for (const h of [...hits.planes, ...hits.sats, ...hits.marks]) {
      const d = h.line ? (y > 100 ? Math.abs(h.x - x) : Infinity) : Math.hypot(h.x - x, h.y - y);
      if (d < (h.line ? 14 : Math.max(28, h.r || 0)) && (!best || d < best.d)) best = { ...h, d };
    }
  }
  if (best && best.track) { startTrack(best.track); return; }
  track = null;                                          // a new target ends tracking (the server cancels it on goto)
  const t = best || { ...camera.unproject(x, y), name: null };
  ctl({ cmd: 'goto', az: wrap360(t.az - cfg.azOff), el: t.el })
    .then(r => r && flash(`Rotator → ${t.name ? t.name + ' ' : ''}${wrap360(t.az).toFixed(1)}° / ${t.el.toFixed(1)}°`));
}

// tracking: current (real-time, not video-delayed) az/el of the target, sent every 2 s; the server moves the
// rotator when the target is far enough off and ends tracking if these confirmations stop
function trackLook(t, date) {
  if (t.type === 'plane') { const p = planes.find(q => q.hex === t.key); return p ? planeLook(p, date / 1000) : null; }
  for (const g of Object.values(SAT)) { const s = g.recs.find(r => r.rec.satnum === t.key); if (s) return satLook(s.rec, date); }
  return null;
}
function startTrack(t) { track = { ...t, since: Date.now() }; flash(`Rotator: tracking ${t.name}`); trackTick(); }
async function trackTick() {
  if (!track) return;
  const l = trackLook(track, new Date(Date.now() + clockOffset));
  if (!l || l.el < 0) {                                  // out of ADS-B range / below the horizon / satellite set
    const n = track.name; track = null; ctl({ cmd: 'untrack' }); flash(`Rotator: ${n} left view – tracking ended`); return;
  }
  const t = track;
  const r = await ctl({ cmd: 'track', az: wrap360(l.az - cfg.azOff), el: l.el, id: String(t.key), name: t.name });
  if (!r && track === t) track = null;
}
setInterval(trackTick, 2000);
if (window.__hook) Object.assign(window, { __hits: hits,      // test hooks (set only by the browser tests)
  __planeList: () => planes.map(p => ({ hex: p.hex, id: p.id, ...planeLook(p, (Date.now() + clockOffset) / 1000) })) });

// commanded position (from the telemetry broadcast, so every viewer sees it): tape marker, elevation marker, text
function drawCtl(az) {
  const g = $('ctlmarks');
  g.replaceChildren();
  if (az == null || !tele || tele.target_az == null) return;
  const yaw = az + cfg.azOff, tAz = tele.target_az + cfg.azOff;
  const away = Math.abs(((tAz - yaw + 540) % 360) - 180);
  if (!tele.tracking && away < 1) return;                // reached: nothing to show
  const col = '#ffffff';
  const d = ((tAz - yaw + 540) % 360) - 180;
  if (Math.abs(d) < cfg.hfov / 2) {
    const tx = azToX(d);
    el('path', { d: `M${tx - 11} 100 L${tx + 11} 100 L${tx} 84 Z`, fill: 'none', 'stroke-width': 3 }, g).style.stroke = col;
  }
  camera.setYaw(yaw);
  const ey = camera.project(yaw, tele.target_el ?? 0).y;
  if (ey > 110 && ey < H - 10) el('path', { d: `M${bx - 52} ${ey - 9} L${bx - 52} ${ey + 9} L${bx - 36} ${ey} Z`, fill: col }, g);
  const txt = tele.tracking ? `tracking ${tele.tracking}` : `→ ${wrap360(tAz).toFixed(0)}° / ${(tele.target_el ?? 0).toFixed(0)}°`;
  el('rect', { x: bx - txt.length * 7.5 - 10, y: 192, width: txt.length * 15 + 20, height: 34, rx: 6, class: 'panel' }, g);
  label(g, bx, 218, txt, col, 'middle');
}
setInterval(() => drawCtl(shownAz), 200);

$('hudToggle').onclick = e => { $('hud').classList.toggle('off'); e.target.classList.toggle('on'); };
// layer switches (remembered per browser)
const LAYER_OF = { beacon: 'beacons', radio: 'beacons', landmark: 'poi', summit: 'summits' };
for (const [k, btn] of Object.entries({ weather: 'lyWx', beacons: 'lyBeacons', poi: 'lyPoi', summits: 'lySummits', planes: 'lyPlanes',
                                         sky: 'lySky', sats: 'lySats', hamsats: 'lyHam' })) {
  if (!enabled(k)) { $(btn).hidden = true; continue; }
  $(btn).classList.toggle('on', layers[k]);
  $(btn).onclick = () => {
    layers[k] = !layers[k]; $(btn).classList.toggle('on', layers[k]);
    try { localStorage.setItem('hamcam.layers', JSON.stringify(layers)); } catch { /* private mode */ }
    if (shownAz != null) { drawMarks(shownAz); drawPlanes(shownAz); drawSats(shownAz); }
    showWeather(lastWx);
  };
}
$('hudToggle').classList.add('on');
$('fs').onclick = () => document.fullscreenElement ? document.exitFullscreen() : $('stage').requestFullscreen();

// ---------- telemetry ----------
let tele = null, clockOffset = 0, teleOk = false, shownAz = null;
loadBeacons(); setInterval(loadBeacons, 3600 * 1000);
const azHist = [];                 // [server ms, az]

// azimuth as it was cfg.azDelay seconds ago (0.48 s: measured in the browser, video motion vs overlay). The rotator reports whole degrees ~10x/s; instead of jumping from sample
// to sample, fit a straight line through the samples around that time (wrap-aware) -> smooth motion, no lag at constant speed
function delayedAz() {
  if (!azHist.length) return null;
  const tt = Date.now() + clockOffset - (cfg.azDelay + mseExtra) * 1000;
  const ref = azHist[azHist.length - 1][1];
  const pts = [];
  for (const [t, a] of azHist) if (t >= tt - 1200 && t <= tt + 500) pts.push([(t - tt) / 1000, ((a - ref + 540) % 360) - 180]);
  if (pts.length < 2) {                       // standing still (only heartbeats) or too few samples: last value before tt
    let i = azHist.length - 1;
    while (i > 0 && azHist[i][0] > tt) i--;
    return azHist[i][1];
  }
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const [x, y] of pts) { sx += x; sy += y; sxx += x * x; sxy += x * y; }
  const n = pts.length, den = n * sxx - sx * sx;
  let v = den > 1e-9 ? (sy - ((n * sxy - sx * sy) / den) * sx) / n : sy / n;   // intercept at x = 0 (= time tt)
  const lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1]));
  v = Math.min(hi, Math.max(lo, v));          // never beyond the reported values (no overshoot when stopping)
  return ((ref + v) % 360 + 360) % 360;
}

// draw in step with the display (max ~30 fps), only when something changed
let lastDraw = 0;
function frame(ts) {
  requestAnimationFrame(frame);
  if (ts - lastDraw < 33) return;
  lastDraw = ts;
  const ok = tele && tele.rot_ok;
  const az = q.has('simaz') ? parseFloat(q.get('simaz')) : ok ? delayedAz() : null;   // ?simaz= for testing only
  if (az === shownAz || (az != null && shownAz != null && Math.abs(((az - shownAz + 540) % 360) - 180) < 0.01)) {
    if (probe) drawProbe();
    return;
  }
  shownAz = az;
  // shown azimuth = rotator + calibration offset (true bearing of the image centre / boresight)
  const tAz = az == null ? null : (az + cfg.azOff + 360) % 360;
  $('az').textContent = tAz == null ? '---.-°' : `${tAz.toFixed(1).padStart(5, '0')}°`;
  if (az != null) { drawTape(tAz); drawMarks(az); }
  drawProbe();
}
requestAnimationFrame(frame);
refreshSky();
setInterval(() => { refreshSky(); if (shownAz != null) drawMarks(shownAz); }, 5000);

// multi-line SVG text: one <tspan> per line
function setLines(gid, lines, dy = 34) {
  const t = $(gid).querySelector('text');
  const x = t.getAttribute('x');
  t.replaceChildren(...lines.map((l, i) => {
    const ts = document.createElementNS(SVG, 'tspan');
    ts.setAttribute('x', x); if (i) ts.setAttribute('dy', dy);
    ts.textContent = l; return ts;
  }));
}

let lastWx = null;
function showWeather(wx) {
  lastWx = wx;
  if (!layers.weather || !wx || typeof wx !== 'object') { setLines('wx', []); return; }
  // fields are picked server-side (WEATHER_FIELDS): {name: {value, unit}}
  const v = k => wx[k] && wx[k].value;
  const lines = [];
  if (v('temp') != null) lines.push(`${v('temp').toFixed(1)} °C`);
  if (v('pressure') != null) lines.push(`${v('pressure').toFixed(1)} hPa`);
  if (v('wind') != null) {
    const dir = v('wind_dir') != null ? ` ${String(Math.round(v('wind_dir'))).padStart(3, '0')}°` : '';
    lines.push(`wind ${v('wind').toFixed(1)} m/s${dir}`);
    if (v('gust') != null) lines.push(`gust ${v('gust').toFixed(1)} m/s`);
  }
  setLines('wx', lines);
  const t = $('wx').querySelector('text');             // bottom-right corner, grows upwards
  t.setAttribute('x', W - 14); t.setAttribute('y', H - 14 - (lines.length - 1) * 34);
}

function connectTelemetry() {
  const ws = new WebSocket(new URL('telemetry', location.href).href.replace(/^http/, 'ws'));
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === 'pong') {
      const now = Date.now();
      clockOffset = m.t * 1000 + (now - m.c) / 2 - now;
    } else if (m.type === 'state') {
      tele = m;
      if (track && !m.tracking && Date.now() - track.since > 3000) track = null;
      if (m.az != null && m.rot_ok) {
        azHist.push([m.t * 1000, m.az]);
        while (azHist.length > 2 && azHist[1][0] < m.t * 1000 - 10000) azHist.shift();
      }
      showWeather(m.wx);
    }
  };
  ws.onopen = () => { teleOk = true; ws.send(JSON.stringify({ type: 'ping', c: Date.now() })); };
  ws.onclose = () => { teleOk = false; setTimeout(connectTelemetry, 2000); };
  setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: 'ping', c: Date.now() })), 30000);
}
connectTelemetry();
drawTape(0);

// ---------- clock ----------
setInterval(() => {
  // server-synced UTC date and time, whole seconds (e.g. 2026-10-11 23:08:15 UTC)
  const d = new Date(Date.now() + clockOffset);
  $('clock').textContent = d.toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
}, 200);

// ---------- screenshot: current video frame + full HUD, at native resolution ----------
function flash(text, ms = 2500) {
  const m = $('msg'); m.textContent = text; m.hidden = false;
  clearTimeout(flash.t); flash.t = setTimeout(() => { m.hidden = true; }, ms);
}

async function screenshot() {
  const v = player.video;
  if (!v || !v.videoWidth) { flash('No video yet'); return; }
  const when = new Date(Date.now() + clockOffset);
  const w = Math.max(v.videoWidth, 1600), h = Math.round(w * H / W);   // keep HUD legible on the sub stream
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(v, 0, 0, w, h);

  // HUD as it is right now, always included even if hidden on screen (call, locator and time are in the camera OSD)
  const svg = $('hud').cloneNode(true);
  svg.classList.remove('off');
  svg.setAttribute('width', w); svg.setAttribute('height', h);
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    ctx.drawImage(img, 0, 0, w, h);
  } finally {
    URL.revokeObjectURL(url);
  }

  const az = shownAz != null ? ((shownAz + cfg.azOff + 360) % 360).toFixed(1) : 'na';   // true bearing
  const name = `SQ6EMM_${when.toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_')}Z_az${az}.jpg`;
  const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.95));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  flash(`Saved ${name}`);
}
$('shot').onclick = () => screenshot().catch(e => { console.error(e); flash('Screenshot failed: ' + e.message); });
