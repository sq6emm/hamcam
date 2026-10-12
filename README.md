# hamcam – antenna camera with a calibrated overlay

Live, low-latency view from a camera mounted on a rotating antenna (SQ6EMM, JO81LC), with a browser-side overlay that
knows where the antenna points: compass tape and elevation scale, local landmarks, 23 cm beacons, SOTA summits,
aircraft (ADS-B), Sun, Moon and planets, bright and amateur radio satellites, and – with rsanttracker – rain/snow
scatter cells, aircraft scatter candidates and the tropo state. Every layer can be switched on/off. The view zooms up to
6× with all overlays (wheel, pinch, − / + buttons or keys, `0` resets; drag to pan).
From allowed networks the page can also steer the rotator: with **Control** on, a click turns the antenna to that
point or object (az and el are sent), a click on an aircraft or satellite tracks it; the point-to field takes an azimuth (`213`, `213/10` = az/el),
a locator (`JO80HK`) or a callsign (`SP6GWB`, looked up at qthdb.hamradio.pl); **STOP** / Esc stops at once.

```
camera --RTSP--> go2rtc --WebRTC--> browser  (overlay drawn in the browser: web/www)
rotctld, weather, IARU beacons, CelesTrak TLEs, SOTA, rsanttracker --> telemetry service --WebSocket/JSON--> browser
ADS-B receiver aircraft.json --> nginx --> browser
```

| Part | Directory | Container |
|---|---|---|
| Page and overlay (camera model, projection, layers) | `web/www` | `hamcam-web` (nginx, port 8097) |
| Telemetry: rotator 10 Hz, weather, beacons, TLEs, summits | `telemetry/` | `hamcam-telemetry` |
| Video passthrough (no transcoding) | – | `hamcam-go2rtc` (WebRTC on 8556) |
| Deployment: compose files, go2rtc config, example `objects.json`, `.env.example` | `deploy/` | – |
| Calibration and test tools | `tools/` | run ad hoc in containers |

## Deploy

Images are built by GitHub Actions and published to GitHub Container Registry (linux/amd64 and linux/arm64):
`ghcr.io/sq6emm/hamcam-telemetry` and `ghcr.io/sq6emm/hamcam-web` (tags: `latest`, `sha-…`, release versions).

```
mkdir -p /etc/docker-compose/hamcam/config && cd /etc/docker-compose/hamcam
base=https://raw.githubusercontent.com/sq6emm/hamcam/main/deploy
curl -O $base/compose.yaml -O $base/go2rtc.yaml -o .env $base/.env.example
curl -o config/objects.json $base/objects.json
chmod 600 .env        # fill in .env, then set your station, camera model and POIs in config/objects.json
mkdir -p data         # persistent data (HAMCAM_DATA); must be writable by HAMCAM_UID:HAMCAM_GID
docker compose up -d  # page on http://<host>:8097/
```

To build from source instead: clone the repository and run
`docker compose -f deploy/compose.yaml -f deploy/compose.build.yaml up -d --build` (or set `HAMCAM_SRC` when the
compose files live elsewhere).

`deploy/` mirrors a live configuration (SQ6EMM's, without `.env`): `objects.json` is a working example to adapt.

## Calibration tools (`tools/`)

- `calib/distortion.py` – lens model (f, k1, k2, optical centre, roll) from frames taken with the rotator as a turntable
- `tilt/` – mast / rotation-axis tilt from roof edges (LiDAR surface model + OSM buildings)
- `calib/blink_measure.py` – az/el of (blinking) lights from a short video
- `browser/` – headless Chromium tests: screenshots, overlay timing vs video, layer switches

All configuration is in **/etc/docker-compose/hamcam/**:

| File | Content |
|---|---|
| `compose.yaml` | the stack (go2rtc, telemetry, web) |
| `.env` | network, equipment, credentials (chmod 600; not visible inside the containers) |
| `go2rtc.yaml` | stream settings; camera URLs and WebRTC addresses come from `.env` |
| `compose.build.yaml` | optional: build the images from source |
| `config/objects.json` | station location, camera/lens model, display values, POIs (served at `/objects.json`) |

Code (`web/`, `telemetry/`, `tools/`) is in the repository and in the images; persistent data in `HAMCAM_DATA` (beacon/TLE/summit
lists, `tools/`). Apply a change: `cd /etc/docker-compose/hamcam && docker compose up -d` (after editing `.env`,
`compose.yaml` or `go2rtc.yaml`); `objects.json` only needs a page reload (the telemetry service
re-reads it on its next refresh).

## `.env` – network, equipment, credentials (chmod 600, never published)

| Variable | Used by | Meaning |
|---|---|---|
| `HAMCAM_VERSION` | compose | image tag: `latest`, a release version without "v" (`0.0.9`), or `0.0` for the newest 0.0.x |
| `HAMCAM_DATA`, `HAMCAM_UID`, `HAMCAM_GID` | telemetry | persistent data directory and the uid:gid that writes it |
| `HAMCAM_WEB_PORT` | web | host port of the page (8097) |
| `HAMCAM_ANALYSIS` | web | optional directory with a calibration report, served read-only at `/analysis/` (default `./analysis`) |
| `CAMERA_MAIN_URL` | go2rtc | RTSP URL of the camera main stream, incl. user/password (required) |
| `CAMERA_SUB_URL` | go2rtc | RTSP URL of the sub stream (optional) |
| `WEBRTC_CANDIDATE_LAN` | go2rtc | `host:port` LAN viewers connect to for WebRTC media (e.g. `192.168.12.12:8556`) |
| `WEBRTC_CANDIDATE_WAN` | go2rtc | public address for remote viewers: `stun:8556` (public IP found via STUN, also with a dynamic IP) or `IP:8556`. Forward 8556 UDP **and** TCP on the firewall to this host; if remote viewers fall back to MSE, check the forward first. |
| `ROTCTLD_HOST`, `ROTCTLD_PORT` | telemetry, tools | Hamlib rotctld; empty host = simulated azimuth sweep |
| `WEATHER_URL`, `WEATHER_FIELDS` | telemetry | weather JSON endpoint (API keys stay server-side) and `name=dotted.path,...` fields shown |
| `ADSB_URL` | nginx | `aircraft.json` of the ADS-B receiver (readsb / tar1090 / ultrafeeder) |
| `BEACON_BAND`, `BEACON_MAX_KM`, `BEACON_KEEP_DAYS` | telemetry | IARU beacon list: band (`23cm`), radius from the station (900), drop after N days unreported (90) |
| `TLE_GROUPS` | telemetry | CelesTrak groups for the satellite layers (`visual,amateur`) |
| `CONTROL_ALLOW` | telemetry | clients allowed to steer the rotator from the page: CIDRs or single addresses (IPv4/IPv6), comma-separated, e.g. `192.168.0.0/16,10.8.0.0/24,203.0.113.7`; invalid entries are skipped and logged, the list in effect is logged at start; **empty = disabled** |
| `TRUSTED_PROXY` | web | public front proxy; only its `X-Forwarded-For` is trusted (its last entry), so visitors coming through it are judged by their real address |
| `QTHDB_URL` | telemetry | callsign → locator lookup for the point-to field (`https://qthdb.hamradio.pl`) |
| `RSANT_URL` | telemetry | [rsanttracker](#scatter-and-tropo) base URL (e.g. `http://192.168.12.12:8073`); empty = R/S, A/S, Tropo hidden |
| `TRACK_STEP_DEG`, `TRACK_MIN_INTERVAL_S`, `TRACK_LEASE_S`, `ROT_EL_MIN`, `ROT_EL_MAX` | telemetry | tracking: move when ≥ 2° off, at most every 3 s, ends 10 s after the page stops confirming; elevation range sent to rotctld |
| `SOTA_ASSOCIATIONS`, `SUMMIT_MAX_KM` | telemetry | SOTA associations searched for visible summits (`SP,OK`) and radius (250 km) |

## `config/objects.json` – station, camera model, POIs

- `station`: `lat`, `lon`, `h` (antenna height **above sea level**, m), `call`, `locator`.
  **Single source of the location**: page, telemetry (beacon distances, summit visibility) and the calibration tools use it.
- `camera`:
  - `width`, `height`: image size (sets the overlay aspect ratio)
  - lens: `f_px` (focal length in px at `f_ref_w` width), `k1`, `k2` (radial distortion), `pp_px` (optical centre offset),
    `hfov` – measured with `tools/calib/distortion.py`
  - orientation: `pitch`, `roll` (at the image centre), `az_offset` (true azimuth of the image centre − rotator azimuth),
    `tilt` (`A`, `B`, `ref_az`: mast tilt, from `tools/tilt/tilt_calib.py`)
  - `az_delay`: how much the video lags the rotator readout (s); `boresight`: antenna direction in the frame (fractions)
- `display`: `title` (browser tab title, after the call sign), `layers` – per layer `weather`, `beacons`, `poi`, `summits`,
  `planes`, `sky`, `sats`, `hamsats`, `rs`, `as`, `tropo`: `"on"` (shown), `"off"` (button, hidden at start) or `"disabled"` (no button,
  no data loaded); `video_lag_s` (camera→browser latency for aircraft/satellite positions), `geoid_n_m` (geoid height at the
  station, for ADS-B GPS altitudes), `adsb_max_km`.
- `objects`: your own points – `landmark` (with `lat`, `lon`, `h` = top height ASL) or `radio` (`locator`); add/remove freely.

Query parameters override camera values for testing: `?hfov= &pitch= &roll= &azoff= &azdelay= &k1= &k2= &adsbkm= &notilt`.

## Scatter and tropo

With `RSANT_URL` set, the telemetry service reads [rsanttracker](../rsanttracker)'s `/api/state` every
`RSANT_POLL_S` (5 s) – read only, it never uses its tracking endpoints – and serves a compact copy at
`/telemetry/scatter`. Three layers use it:

- **R/S**: rain (blue), snow (cyan, dashed) and hail (magenta) scatter cells above the horizon, drawn at rsanttracker's
  aim point with a ring sized by the cell area; label: reflectivity, range, aim height. Dimmed when the DX station can't
  see the cell.
  Cells outside the view: an arrow at each end of the tape shows the best-scoring one on that side
  (`◀ R/S 48 dBZ 100° 120 km +1`).
- **A/S**: aircraft rsanttracker rates usable for scatter towards its DX station (diamonds; relative score, scattering
  angle, range), dead-reckoned to the video time like the Planes layer, plus the DX direction on the tape.
- **Tropo**: state (normal / enhanced / super-refraction / ducting), k, dN/dh and the ducts that trap the band, the next
  opening or the best forecast direction; directions where enhanced conditions reach out now are marked on the tape,
  and arrows at the tape ends point to the nearest such direction outside the view on each side (`◀ NE 450 km +2`).

With Control on, a click on a cell points the rotator at it, a click on an off-screen arrow turns it to that
direction or cell; a click on an A/S aircraft tracks it.

## Derived automatically from the station location

Azimuth/elevation/distance of all objects · 23 cm beacons (IARU API, merged daily) · SOTA summits above the horizon (weekly,
and immediately after the station changes) · Sun, Moon, planets · satellite passes (TLEs every 12 h) · aircraft positions.

## Measured per installation (re-measure when the camera or mast changes)

Lens model and roll (`tools/calib/distortion.py`), pitch / `az_offset` (a known landmark, here Sky Tower),
`az_delay` and `video_lag_s` (browser timing test), mast tilt (`tools/tilt/`). The older one-off scripts in
`tools/calib/` (drift/speed tests, encoder monitor) still contain this site's addresses. Tools that read the
camera model mount `/etc/docker-compose/hamcam/config` as `/www`.

## License

hamcam is licensed under the **PolyForm Noncommercial License 1.0.0** (`LICENSE.md`): free to use, modify and share for
any noncommercial purpose (amateur radio, personal, research, education, clubs and other noncommercial organisations).
Commercial use is not permitted. Bundled third-party libraries keep their own (MIT) licenses, see `THIRD-PARTY.md`.
