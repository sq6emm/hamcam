// Geometry for the HUD: geodetic -> az/el from the station, Sun/Moon via astronomy-engine,
// and az/el -> pixel through a pinhole camera model (yaw from rotator, fixed pitch/roll).

const D2R = Math.PI / 180, R2D = 180 / Math.PI;
const WGS_A = 6378137, WGS_E2 = 6.69437999014e-3;
const K_REFR = 0.13;                    // standard terrestrial refraction coefficient

// Maidenhead locator (2..10 chars) -> centre of the square
export function locatorToLatLon(loc) {
  loc = loc.trim().toUpperCase();
  let lon = -180, lat = -90, lonStep = 20, latStep = 10;
  lon += (loc.charCodeAt(0) - 65) * lonStep; lat += (loc.charCodeAt(1) - 65) * latStep;
  const steps = [[10, 10, '0'], [24, 24, 'A'], [10, 10, '0'], [24, 24, 'A']];
  for (let i = 2, s = 0; i + 1 < loc.length && s < steps.length; i += 2, s++) {
    const [nLon, nLat, base] = steps[s];
    lonStep /= nLon; latStep /= nLat;
    lon += (loc.charCodeAt(i) - base.charCodeAt(0)) * lonStep;
    lat += (loc.charCodeAt(i + 1) - base.charCodeAt(0)) * latStep;
  }
  return { lat: lat + latStep / 2, lon: lon + lonStep / 2, precisionKm: latStep * 111 };
}

function ecef(lat, lon, h) {
  const sl = Math.sin(lat * D2R), cl = Math.cos(lat * D2R);
  const N = WGS_A / Math.sqrt(1 - WGS_E2 * sl * sl);
  return [(N + h) * cl * Math.cos(lon * D2R), (N + h) * cl * Math.sin(lon * D2R), (N * (1 - WGS_E2) + h) * sl];
}

// az/el/distance of a point as seen from the station (ellipsoid, curvature + standard refraction)
export function azElOf(st, lat, lon, h) {
  const [x0, y0, z0] = ecef(st.lat, st.lon, st.h), [x1, y1, z1] = ecef(lat, lon, h ?? 0);
  const dx = x1 - x0, dy = y1 - y0, dz = z1 - z0;
  const sl = Math.sin(st.lat * D2R), cl = Math.cos(st.lat * D2R), so = Math.sin(st.lon * D2R), co = Math.cos(st.lon * D2R);
  const e = -so * dx + co * dy;
  const n = -sl * co * dx - sl * so * dy + cl * dz;
  const u = cl * co * dx + cl * so * dy + sl * dz;
  const dist = Math.hypot(e, n, u);
  const az = (Math.atan2(e, n) * R2D + 360) % 360;
  const el = Math.atan2(u, Math.hypot(e, n)) * R2D + (K_REFR * dist / (2 * WGS_A)) * R2D;
  return { az, el, dist };
}

// Sun / Moon topocentric az/el with refraction; Moon also gets illuminated fraction
export function bodies(st, date) {
  const A = window.Astronomy;
  if (!A) return [];
  const obs = new A.Observer(st.lat, st.lon, st.h);
  const PLANET_KM = { Mercury: 2440, Venus: 6052, Mars: 3390, Jupiter: 69911, Saturn: 58232, Uranus: 25362, Neptune: 24622 };
  return ['Sun', 'Moon', ...Object.keys(PLANET_KM)].map(name => {
    const eq = A.Equator(name, date, obs, true, true);
    const hor = A.Horizon(date, obs, eq.ra, eq.dec, 'normal');
    const out = { name, az: hor.azimuth, el: hor.altitude, diam: name === 'Sun' ? 0.533 : 0.52 };
    if (PLANET_KM[name]) {
      out.diam = 2 * Math.atan(PLANET_KM[name] / (eq.dist * 149597870.7)) * R2D;
      out.mag = A.Illumination(name, date).mag;
    }
    if (name === 'Moon') {
      out.illum = A.Illumination('Moon', date).phase_fraction;
      out.diam = 2 * Math.atan(1737.4 / (eq.dist * 149597870.7)) * R2D;
    }
    return out;
  });
}

// Pinhole camera. W,H: image size in HUD units; f from hfov; yaw = image-centre azimuth.
export class Camera {
  // f: focal length in px of this W (else from hfov, rectilinear); k1, k2: radial lens distortion
  // (normalized tan-plane coords: r_d = r_u (1 + k1 r_u^2 + k2 r_u^4); barrel lens -> k1 < 0)
  // pp: optical centre offset from the image centre (px, + = right/down). yaw and pitch stay the direction of the
  // IMAGE CENTRE (what the rotator / Sky Tower calibration refers to); the optical axis is derived from them.
  // tilt: mast / rotation-axis tilt as elevation error of the world direction, delta(az) = A sin az + B cos az,
  // taken relative to refAz (where pitch was calibrated); objects appear delta higher than an ideal camera shows them
  constructor({ W, H, hfov, f = null, k1 = 0, k2 = 0, pp = [0, 0], pitch = 0, roll = 0, tilt = null }) {
    Object.assign(this, { W, H, pitch, roll, k1, k2 });
    this.tilt = tilt && (tilt.A || tilt.B) ? tilt : null;
    this.f = f || (W / 2) / Math.tan(hfov / 2 * D2R);
    this.cx = W / 2 + pp[0]; this.cy = H / 2 + pp[1];
    this.a0 = Math.atan(-pp[0] / this.f) * R2D;    // image centre is a0 deg right of the optical axis
    this.e0 = Math.atan(pp[1] / this.f) * R2D;     // ... and e0 deg above it
  }
  setYaw(yaw) { this.yaw = yaw; this._axes(); }
  _axes() {
    const p = (this.yaw - this.a0) * D2R, t = (this.pitch - this.e0) * D2R, r = this.roll * D2R;
    const fwd = [Math.sin(p) * Math.cos(t), Math.cos(p) * Math.cos(t), Math.sin(t)];
    const right0 = [Math.cos(p), -Math.sin(p), 0];
    const up0 = [right0[1] * fwd[2] - right0[2] * fwd[1], right0[2] * fwd[0] - right0[0] * fwd[2], right0[0] * fwd[1] - right0[1] * fwd[0]];
    this.fwd = fwd;
    this.right = right0.map((v, i) => v * Math.cos(r) + up0[i] * Math.sin(r));
    this.up = up0.map((v, i) => v * Math.cos(r) - right0[i] * Math.sin(r));
  }
  // az/el (deg) -> {x, y, front}; x/y may be outside the frame
  project(az, el) {
    const a = az * D2R, e = (el + this.tiltDelta(az)) * D2R;
    const d = [Math.sin(a) * Math.cos(e), Math.cos(a) * Math.cos(e), Math.sin(e)];
    const dot = v => v[0] * d[0] + v[1] * d[1] + v[2] * d[2];
    const Z = dot(this.fwd);
    const X = dot(this.right) / Z, Y = dot(this.up) / Z, s = this.distort(X * X + Y * Y);
    return { x: this.cx + this.f * X * s, y: this.cy - this.f * Y * s, front: Z > 0.05 };
  }
  // pixel -> az/el (inverse of project)
  unproject(x, y) {
    const xd = (x - this.cx) / this.f, yd = -(y - this.cy) / this.f, rd = Math.hypot(xd, yd);
    let ru = rd;                                   // invert the distortion (Newton)
    for (let i = 0; i < 8; i++) ru -= (ru * this.distort(ru * ru) - rd) / (1 + 3 * this.k1 * ru * ru + 5 * this.k2 * ru ** 4);
    const sc = rd > 1e-9 ? ru / rd : 1, X = xd * sc, Y = yd * sc;
    const d = [0, 1, 2].map(i => this.fwd[i] + X * this.right[i] + Y * this.up[i]);
    const n = Math.hypot(...d);
    const az = (Math.atan2(d[0], d[1]) * R2D + 360) % 360;
    return { az, el: Math.asin(d[2] / n) * R2D - this.tiltDelta(az) };
  }
  tiltDelta(az) {
    const t = this.tilt; if (!t) return 0;
    const d = a => t.A * Math.sin(a * D2R) + t.B * Math.cos(a * D2R);
    return d(az) - d(t.ref_az ?? 121.95);
  }
  distort(r2) { return 1 + this.k1 * r2 + this.k2 * r2 * r2; }
  // x (px) of a direction d deg right of the image centre, near the horizon
  xOf(d) { const t = Math.tan((d + this.a0) * D2R); return this.cx + this.f * t * this.distort(t * t); }
  degToPx(deg) { return this.f * deg * D2R; }
}
