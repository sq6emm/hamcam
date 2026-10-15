"""hamcam telemetry: polls rotctld (+ optional weather URL) and pushes JSON to browsers over WebSocket.

Env:
  ROTCTLD_HOST, ROTCTLD_PORT   rotctld address; empty host -> simulated azimuth (for testing)
  ROT_POLL_S                   rotator poll interval (default 0.1 s)
  ROT_DECIMAL                  1 = read K3NG \\?AZ (half degrees) via rotctld raw command (slow: ~0.9 s per query), 0 = standard 'p' (default)
  ROT_OVERLAP_DEG              which turn the rotator is on (SQ6EMM Easycomm III firmware, raw 'w AR'): asked only within this
                               many degrees of north, where the overlap can be (default 30 = range -30..390; 0 = off)
  ROT_RAW_S                    interval of that query near north (default 1 s)
  WEATHER_URL, WEATHER_POLL_S  optional JSON endpoint (URL incl. API keys stays server-side)
  WEATHER_FIELDS               name=dotted.path,... picked from the JSON; only these reach the page.
                               Ecowitt-style leaves ({"value": "12.2", "unit": "C"}) are unpacked.
  BEACON_URL, BEACON_BAND      IARU beacon list (default iaru.hamradio.pl raw API, 23cm), refreshed daily at BEACON_HOUR_UTC
  TLE_GROUPS, TLE_MAX_AGE_H    CelesTrak TLE groups (default visual,amateur) cached in TLE_DIR, served at /telemetry/tle/<group>
  OBJECTS_FILE                 objects.json with the station location (lat, lon, h ASL) - single source for the page too
  SOTA_ASSOCIATIONS, SUMMIT_MAX_KM  SOTA summits above the horizon from the station, served at /telemetry/summits
  CONTROL_ALLOW                rotator control (click-to-point, tracking) for these clients: CIDRs or single addresses
                               (IPv4/IPv6), separated by commas, spaces or semicolons; empty = disabled. Client IP = X-Real-IP set by the web nginx (trusted proxy aware).
  TRACK_STEP_DEG, TRACK_MIN_INTERVAL_S, TRACK_LEASE_S  tracking: move when the target is this far off, at most this
                               often; tracking ends when the page stops confirming it for TRACK_LEASE_S
  ROT_EL_MIN, ROT_EL_MAX       elevation range sent to rotctld (az-only rotators ignore it)
  QTHDB_URL                    callsign -> locator lookup for the "point to" field (default https://qthdb.hamradio.pl)
  RSANT_URL, RSANT_POLL_S      optional rsanttracker (rain/snow/air scatter + tropo) base URL, e.g. http://host:8073;
                               its /api/state is read (never its tracking endpoints) and served compact at /telemetry/scatter
  BEACON_MAX_KM, BEACON_KEEP_DAYS  radius from the station; the API only lists beacons reported recently, so the
                               list is kept in BEACON_FILE and a beacon is dropped only when QRT or unreported > KEEP_DAYS
"""
import asyncio
import datetime
import ipaddress
import json
import math
import os
import re
import time

import aiohttp
from aiohttp import web

ROT_HOST = os.environ.get("ROTCTLD_HOST", "")
ROT_PORT = int(os.environ.get("ROTCTLD_PORT", "4533"))
ROT_POLL = float(os.environ.get("ROT_POLL_S", "0.1"))
ROT_DECIMAL = os.environ.get("ROT_DECIMAL", "0") == "1"   # K3NG \\?AZ via rotctld raw command: half degrees instead of whole
ROT_OVERLAP_DEG = float(os.environ.get("ROT_OVERLAP_DEG", "30"))
ROT_RAW_S = float(os.environ.get("ROT_RAW_S", "1"))
WX_URL = os.environ.get("WEATHER_URL", "")
WX_POLL = float(os.environ.get("WEATHER_POLL_S", "60"))
WX_FIELDS = [f.split("=", 1) for f in os.environ.get("WEATHER_FIELDS", "").split(",") if "=" in f]
BEACON_URL = os.environ.get("BEACON_URL", "https://iaru.hamradio.pl/api/raw/beacons")
BEACON_BAND = os.environ.get("BEACON_BAND", "23cm")
BEACON_MAX_KM = float(os.environ.get("BEACON_MAX_KM", "900"))
BEACON_KEEP_DAYS = float(os.environ.get("BEACON_KEEP_DAYS", "90"))
BEACON_HOUR_UTC = int(os.environ.get("BEACON_HOUR_UTC", "3"))
BEACON_FILE = os.environ.get("BEACON_FILE", "/data/beacons.json")
TLE_GROUPS = [g for g in os.environ.get("TLE_GROUPS", "visual,amateur").split(",") if g]
TLE_URL = os.environ.get("TLE_URL", "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle")
TLE_MAX_AGE_H = float(os.environ.get("TLE_MAX_AGE_H", "12"))     # CelesTrak asks for at most a few downloads a day
TLE_DIR = os.environ.get("TLE_DIR", "/data")
TRUSTED_PROXY = os.environ.get("TRUSTED_PROXY", "").strip()   # same value as the web nginx: never a control client


def parse_networks(spec: str) -> list:
    """CIDRs or single addresses separated by commas, spaces or semicolons; invalid entries are skipped (logged)."""
    nets, bad = [], []
    for n in re.split(r"[\s,;]+", spec.strip()):
        if not n:
            continue
        try:
            nets.append(ipaddress.ip_network(n, strict=False))
        except ValueError:
            bad.append(n)
    if bad:
        print(f"CONTROL_ALLOW: ignoring invalid entries {bad}", flush=True)
    return nets


CONTROL_ALLOW = parse_networks(os.environ.get("CONTROL_ALLOW", ""))
TRACK_STEP_DEG = float(os.environ.get("TRACK_STEP_DEG", "2"))
TRACK_MIN_INTERVAL_S = float(os.environ.get("TRACK_MIN_INTERVAL_S", "3"))
TRACK_LEASE_S = float(os.environ.get("TRACK_LEASE_S", "10"))
ROT_EL_MIN = float(os.environ.get("ROT_EL_MIN", "0"))
ROT_EL_MAX = float(os.environ.get("ROT_EL_MAX", "90"))
RSANT_URL = os.environ.get("RSANT_URL", "").rstrip("/")
RSANT_POLL = float(os.environ.get("RSANT_POLL_S", "5"))
QTHDB_URL = os.environ.get("QTHDB_URL", "https://qthdb.hamradio.pl").rstrip("/")
OBJECTS_FILE = os.environ.get("OBJECTS_FILE", "/config/objects.json")
SOTA_ASSOCIATIONS = [a for a in os.environ.get("SOTA_ASSOCIATIONS", "SP,OK").split(",") if a]
SUMMIT_MAX_KM = float(os.environ.get("SUMMIT_MAX_KM", "250"))
SUMMIT_FILE = os.environ.get("SUMMIT_FILE", "/data/summits.json")


def station() -> dict:
    """Antenna location: the "station" block of objects.json (same file the page uses), read fresh each time."""
    with open(OBJECTS_FILE) as fp:
        st = json.load(fp)["station"]
    return {"lat": float(st["lat"]), "lon": float(st["lon"]), "h": float(st.get("h", 0))}

state = {"az": None, "el": None, "rot_ok": False, "rot_src": "rotctld" if ROT_HOST else "simulated",
         "wx": None, "wx_ts": None, "target_az": None, "target_el": None, "tracking": None,
         "az_raw": None, "overlap": None}       # overlap: None (normal turn or unknown), "ccw" (raw < 0), "cw" (raw > 360)
clients: set[web.WebSocketResponse] = set()


async def broadcast(msg: dict) -> None:
    data = json.dumps(msg)

    async def send(ws):
        try:
            await asyncio.wait_for(ws.send_str(data), 2)
        except Exception:                                # closed or not reading: drop it, never stall the others
            clients.discard(ws)
            await ws.close()
    await asyncio.gather(*(send(ws) for ws in list(clients)))


def snapshot() -> dict:
    return {"type": "state", "t": time.time(), **state}


async def rotator_loop() -> None:
    last = None
    while True:
        if not ROT_HOST:
            # slow sweep, ~1 deg/s, so the overlay can be tested without the rotator
            state["az"] = round((time.time() * 1.0) % 360, 1)
            state["el"] = 0.0
            state["rot_ok"] = True
            await broadcast(snapshot())
            await asyncio.sleep(ROT_POLL)
            continue
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ROT_HOST, ROT_PORT), 5)
            print(f"rotctld connected {ROT_HOST}:{ROT_PORT}")
            while True:
                if ROT_DECIMAL:
                    # rotctld raw passthrough: reply lines are the echo and "\\!OKAZ123.500000"
                    writer.write(b"w \\?AZ\n")
                    await writer.drain()
                    az = None
                    for _ in range(12):   # reply: echo, blank lines, \\!OKAZ..., trailing blank lines
                        line = (await asyncio.wait_for(reader.readline(), 3)).decode(errors="replace")
                        if "OKAZ" in line:
                            az = float(line.split("OKAZ")[1].strip()); break
                    if az is None:
                        raise ValueError("no \\?AZ reply")
                    el = 0.0
                else:
                    writer.write(b"p\n")
                    await writer.drain()
                    az = float((await asyncio.wait_for(reader.readline(), 3)).strip())
                    el = float((await asyncio.wait_for(reader.readline(), 3)).strip())
                state.update(az=round(az % 360, 1), el=round(el, 1), rot_ok=True)
                cur = (state["az"], state["el"])
                if cur != last:
                    last = cur
                    await broadcast(snapshot())
                await asyncio.sleep(ROT_POLL)
        except Exception as e:
            print(f"rotctld error: {e!r}")
            state["rot_ok"] = False
            await broadcast(snapshot())
            await asyncio.sleep(3)
        finally:
            if writer:
                writer.close()


async def set_overlap(overlap, raw) -> None:
    changed = state["overlap"] != overlap
    state["overlap"], state["az_raw"] = overlap, raw
    if changed:
        await broadcast(snapshot())


async def overlap_loop() -> None:
    """Which turn the rotator is on: position from 'p' as usual (standard Hamlib), the raw position from the SQ6EMM
    firmware's 'w AR' on a separate rotctld connection. Asked only near north, because only there can the rotator be
    in the overlap (raw -30..0 or 360..390); elsewhere it is on the normal turn. A controller without AR (no reply,
    or an error) just leaves the overlap unknown; it is tried again after a minute."""
    if not ROT_HOST or ROT_DECIMAL or ROT_OVERLAP_DEG <= 0:
        return
    reader = writer = None
    while True:
        az = state["az"]
        try:
            if not state["rot_ok"] or az is None:
                await set_overlap(None, None)
            elif min(az, 360 - az) > ROT_OVERLAP_DEG:
                await set_overlap(None, az)
            else:
                if writer is None:
                    reader, writer = await asyncio.wait_for(asyncio.open_connection(ROT_HOST, ROT_PORT), 5)
                writer.write(b"w AR\n")
                await writer.drain()
                raw, deadline = None, time.monotonic() + 2
                while raw is None:   # rotctld frames the reply as "AR-10.0\r\n\n\n": blank lines are skipped
                    line = (await asyncio.wait_for(reader.readline(), max(0.05, deadline - time.monotonic()))).decode(errors="replace").strip()
                    if line.startswith("AR"):
                        raw = float(line[2:])
                    elif line.startswith("RPRT -"):
                        raise ValueError(line)
                turn = round((raw - state["az"]) / 360)   # tolerates 'p' and AR read a moment apart
                await set_overlap({-1: "ccw", 1: "cw"}.get(turn), raw)
                await asyncio.sleep(ROT_RAW_S)
                continue
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"overlap query (w AR) failed: {e!r}; controller without AR? next try in 60 s")
            await set_overlap(None, None)
            if writer:
                writer.close()
            reader = writer = None
            await asyncio.sleep(60)


def pick_fields(doc: dict) -> dict:
    out = {}
    for name, path in WX_FIELDS:
        v = doc
        for k in path.strip().split("."):
            v = v.get(k) if isinstance(v, dict) else None
        unit = ""
        if isinstance(v, dict):
            v, unit = v.get("value"), v.get("unit", "")
        try:
            out[name.strip()] = {"value": float(v), "unit": unit}
        except (TypeError, ValueError):
            pass
    return out


async def weather_loop() -> None:
    if not WX_URL:
        return
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        while True:
            try:
                async with s.get(WX_URL) as r:
                    state["wx"] = pick_fields(await r.json(content_type=None))
                    state["wx_ts"] = time.time()
                    await broadcast(snapshot())
            except Exception as e:
                print(f"weather error: {e!r}")
            await asyncio.sleep(WX_POLL)


async def heartbeat_loop() -> None:
    # keeps clocks/state fresh even when the rotator is idle
    while True:
        await asyncio.sleep(1)
        await broadcast(snapshot())


# ---------- scatter + tropo from rsanttracker (read-only) ----------
scatter = {"updated": None, "error": None}


def _pick(d: dict, keys: tuple) -> dict:
    return {k: d.get(k) for k in keys}


def compact_scatter(d: dict) -> dict:
    """Only what the overlay needs: scatter cells above the horizon, aircraft usable for the DX path, fixed reflectors
    (terrain slopes, named targets) above the horizon, tropo state."""
    t = d.get("time") or time.time()
    cells = [_pick(c, ("id", "kind", "snow", "lat", "lon", "alt_m", "top_m", "max_dbz", "area_km2", "score", "az", "el",
                       "range_km", "dist_km", "reachable", "atten_db", "scatter_angle", "beam_dbz", "outline", "speed_ms",
                       "heading", "aim_src", "dx_el"))
             for c in d.get("cells", []) if c.get("visible") and not c.get("stale")]
    fixed = [_pick(f, ("id", "kind", "name", "lat", "lon", "alt_m", "rcs_dbsm", "score", "az", "el", "range_km", "dist_km",
                       "grazing_deg", "area_km2", "scatter_angle", "atten_db", "dx_el"))
             for f in d.get("fixed") or [] if f.get("visible") and not f.get("blocked")]
    planes = [{**_pick(a, ("id", "flight", "reg", "type", "lat", "lon", "alt_m", "gs_kmh", "track", "score", "doppler_hz",
                           "scatter_angle", "dx_el", "length_m")), "t": t - (a.get("age_s") or 0)}
              for a in d.get("aircraft", []) if a.get("usable")]
    prop = d.get("propagation") or {}
    model, fc, mp = prop.get("model") or {}, prop.get("forecast") or {}, prop.get("map") or {}
    now_h = min(mp.get("hours") or [{}], key=lambda h: abs((h.get("t") or 0) - t))
    tropo = {"state": model.get("state"), "k": prop.get("k"), "dndh": model.get("dndh"), "ducts": model.get("ducts") or [],
             "freezing_level_m": prop.get("freezing_level_m"), "model_time": model.get("model_time"),
             "window": fc.get("window"), "best": fc.get("best"), "map_best": mp.get("best"),
             "reach_km": now_h.get("reach_km"), "level": now_h.get("level"), "n_az": mp.get("n_az")}
    dx = d.get("dx") or {}
    return {"updated": t, "error": None, "radio": d.get("radio"), "radar": (d.get("radar") or {}).get("status"),
            "dx": _pick(dx, ("callsign", "locator", "lat", "lon", "alt_m", "dist_km")) if dx.get("lat") is not None else None,
            "cells": cells, "aircraft": planes, "fixed": fixed, "tropo": tropo}


async def scatter_loop() -> None:
    if not RSANT_URL:
        return
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
        while True:
            try:
                async with s.get(RSANT_URL + "/api/state") as r:
                    r.raise_for_status()
                    scatter.clear(); scatter.update(compact_scatter(await r.json(content_type=None)))
            except Exception as e:
                if scatter.get("error") is None:
                    print(f"rsanttracker error: {e!r}")
                scatter["error"] = repr(e)[:200]
            await asyncio.sleep(RSANT_POLL)


def scatter_response(request: web.Request) -> web.Response:
    if not RSANT_URL:
        return web.json_response({"enabled": False})
    return web.json_response({"enabled": True, **scatter})


# ---------- beacons ----------
def locator_center(loc: str) -> tuple[float, float]:
    loc = loc.strip().upper()
    lon, lat, dlon, dlat = (ord(loc[0]) - 65) * 20 - 180, (ord(loc[1]) - 65) * 10 - 90, 20.0, 10.0
    for i, (n, base) in enumerate([(10, "0"), (24, "A"), (10, "0"), (24, "A")]):
        if len(loc) < 4 + 2 * i:
            break
        dlon, dlat = dlon / n, dlat / n
        lon += (ord(loc[2 + 2 * i]) - ord(base)) * dlon
        lat += (ord(loc[3 + 2 * i]) - ord(base)) * dlat
    return lat + dlat / 2, lon + dlon / 2


def distance_km(lat: float, lon: float, st: dict | None = None) -> float:
    st = st or station()
    p1, p2, dl = math.radians(st["lat"]), math.radians(lat), math.radians(lon - st["lon"])
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371.0 * math.acos(max(-1.0, min(1.0, c)))


def bearing_deg(lat: float, lon: float, st: dict) -> float:
    p1, p2, dl = math.radians(st["lat"]), math.radians(lat), math.radians(lon - st["lon"])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                   math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def load_beacons() -> dict:
    try:
        with open(BEACON_FILE) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {"updated": None, "beacons": {}}


beacons = load_beacons()


def utc_iso(v) -> str | None:
    """Any ISO 8601 date/time (Z, offset, space separator, date only) or epoch number -> 'YYYY-MM-DDTHH:MM:SS' UTC."""
    try:
        if isinstance(v, (int, float)):
            t = datetime.datetime.fromtimestamp(v, datetime.timezone.utc)
        else:
            t = datetime.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
            t = t.replace(tzinfo=datetime.timezone.utc) if t.tzinfo is None else t.astimezone(datetime.timezone.utc)
        return t.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OverflowError, OSError):
        return None


def merge_beacons(rows: list) -> tuple[int, int, int]:
    known = beacons["beacons"]
    st = station()
    added = updated = dropped = 0
    for r in rows:
        if r.get("band") != BEACON_BAND:
            continue
        call, loc = r.get("spotted_beacon"), r.get("static_locator") or r.get("spotted_locator")
        if not call or not loc:
            continue
        if r.get("static_status") == "QRT":
            dropped += known.pop(call, None) is not None
            continue
        try:
            lat, lon = locator_center(loc)
        except (IndexError, ValueError):
            continue
        dist = distance_km(lat, lon, st)
        if dist > BEACON_MAX_KM:
            continue
        old = known.get(call)
        # the API lists only recently reported beacons: an unreadable date counts as "reported now"
        last = utc_iso(r.get("last_reported")) or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        if old and (utc_iso(old.get("last_reported")) or "") > last and old.get("confidence") == "perfect":
            continue            # keep the newer / better entry when the API lists a beacon twice
        freq = (r.get("static_freq") or r.get("spotted_freq") or 0) / 1e6
        known[call] = {"name": call, "locator": loc, "freq": round(freq, 3), "dist_km": round(dist),
                       "status": r.get("static_status"), "confidence": r.get("confidence_score"), "last_reported": last,
                       "first_seen": old["first_seen"] if old else time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
        added += old is None
        updated += old is not None
    limit = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - BEACON_KEEP_DAYS * 86400))
    for call in [c for c, b in known.items() if (utc_iso(b.get("last_reported")) or limit) < limit]:
        del known[call]
        dropped += 1
    beacons["updated"] = time.time()
    tmp = BEACON_FILE + ".tmp"
    with open(tmp, "w") as fp:
        json.dump(beacons, fp, indent=1)
    os.replace(tmp, BEACON_FILE)
    return added, updated, dropped


async def beacon_loop() -> None:
    # at start (if the saved list is older than 20 h), then daily at BEACON_HOUR_UTC; after an error retry hourly
    due = not beacons["updated"] or time.time() - beacons["updated"] > 20 * 3600
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        while True:
            ok = True
            if due:
                try:
                    async with s.get(BEACON_URL) as r:
                        rows = await r.json(content_type=None)
                    a, u, d = merge_beacons(rows)
                    print(f"beacons: {len(rows)} rows, {BEACON_BAND} within {BEACON_MAX_KM:.0f} km: "
                          f"+{a} new, {u} updated, -{d} dropped, {len(beacons['beacons'])} kept")
                except Exception as e:
                    ok = False
                    print(f"beacon refresh error: {e!r}")      # keep the old list
            now = time.time()
            nxt = (now // 86400) * 86400 + BEACON_HOUR_UTC * 3600
            if nxt <= now:
                nxt += 86400
            await asyncio.sleep(nxt - now if ok else 3600)
            due = True


def beacons_response(request: web.Request) -> web.Response:
    lst = sorted(beacons["beacons"].values(), key=lambda b: b["dist_km"])
    return web.json_response({"updated": beacons["updated"], "band": BEACON_BAND, "max_km": BEACON_MAX_KM, "beacons": lst})


# ---------- satellite TLEs ----------
def tle_path(group: str) -> str:
    return os.path.join(TLE_DIR, f"tle_{group}.txt")


async def tle_loop() -> None:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),
                                     headers={"User-Agent": "hamcam-telemetry (SQ6EMM)"}) as s:
        while True:
            for g in TLE_GROUPS:
                try:
                    age_h = (time.time() - os.path.getmtime(tle_path(g))) / 3600
                except OSError:
                    age_h = 1e9
                if age_h < TLE_MAX_AGE_H:
                    continue
                try:
                    async with s.get(TLE_URL.format(group=g)) as r:
                        txt = await r.text()
                    if r.status != 200 or "\n1 " not in txt:
                        raise ValueError(f"HTTP {r.status}: {txt[:80]!r}")
                    with open(tle_path(g) + ".tmp", "w") as fp:
                        fp.write(txt)
                    os.replace(tle_path(g) + ".tmp", tle_path(g))
                    print(f"tle {g}: {txt.count(chr(10)) // 3} satellites")
                except Exception as e:
                    print(f"tle {g} refresh error: {e!r}")          # keep the old file
            await asyncio.sleep(3600)


async def tle_response(request: web.Request) -> web.Response:
    g = request.match_info["group"]
    if g not in TLE_GROUPS:
        raise web.HTTPNotFound()
    try:
        with open(tle_path(g)) as fp:
            return web.Response(text=fp.read(), content_type="text/plain")
    except OSError:
        raise web.HTTPServiceUnavailable()


# ---------- SOTA summits visible from the station ----------
def load_summits() -> dict:
    try:
        with open(SUMMIT_FILE) as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {"updated": None, "station": None, "summits": []}


summits = load_summits()


def visible_summits(all_summits: list, st: dict) -> list:
    """Above the horizon (earth curvature, refraction k=0.13), within SUMMIT_MAX_KM, and not behind a nearer summit
    that appears higher at nearly the same bearing (+-0.7 deg). Intermediate terrain is not checked."""
    R, K = 6371000.0, 0.13
    pts = []
    for s in all_summits:
        d = distance_km(s["lat"], s["lon"], st) * 1000
        if d < 500 or d > SUMMIT_MAX_KM * 1000:
            continue
        el = math.degrees(math.atan2(s["h"] - st["h"], d)) - math.degrees(d / (2 * R) * (1 - K))
        pts.append({**s, "dist": d, "el": el, "az": bearing_deg(s["lat"], s["lon"], st)})
    vis = sorted((p for p in pts if p["el"] > 0), key=lambda p: p["dist"])
    return [p for p in vis if not any(n["dist"] < p["dist"] and abs((n["az"] - p["az"] + 540) % 360 - 180) < 0.7
                                      and n["el"] > p["el"] + 0.02 for n in pts)]


async def summit_loop() -> None:
    api = "https://api2.sota.org.uk/api"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        while True:
            try:
                st = station()
            except (OSError, ValueError, KeyError) as e:     # e.g. objects.json being saved right now
                print(f"summits: cannot read station ({e!r}), retry in 1 h")
                await asyncio.sleep(3600)
                continue
            stale = not summits["updated"] or time.time() - summits["updated"] > 7 * 86400
            if stale or summits.get("station") != st:      # weekly, or right away when the station was changed
                try:
                    found = []
                    for a in SOTA_ASSOCIATIONS:
                        async with s.get(f"{api}/associations/{a}") as r:
                            regions = [x["regionCode"] for x in (await r.json(content_type=None)).get("regions", [])]
                        for reg in regions:
                            async with s.get(f"{api}/regions/{a}/{reg}") as r:
                                d = await r.json(content_type=None)
                            today = time.strftime("%Y-%m-%d")
                            found += [{"ref": x["summitCode"], "name": x["name"], "lat": x["latitude"], "lon": x["longitude"],
                                       "h": x["altM"]} for x in d.get("summits") or []
                                      if (x.get("validTo") or "9999")[:10] >= today and x.get("latitude") is not None]
                    vis = visible_summits(found, st)
                    summits.update({"updated": time.time(), "station": st, "summits": vis})
                    with open(SUMMIT_FILE + ".tmp", "w") as fp:
                        json.dump(summits, fp, ensure_ascii=False, indent=1)
                    os.replace(SUMMIT_FILE + ".tmp", SUMMIT_FILE)
                    print(f"summits: {len(found)} in {','.join(SOTA_ASSOCIATIONS)}, {len(vis)} visible within {SUMMIT_MAX_KM:.0f} km")
                except Exception as e:
                    print(f"summit refresh error: {e!r}")
            await asyncio.sleep(3600)


# ---------- rotator control: click-to-point and tracking (allowed client networks only) ----------
control = {"last_cmd": None, "last_t": 0.0, "lease": 0.0, "stop_seq": 0}   # last commanded (az, el), when, lease end


def client_ip(request: web.Request) -> str:
    # set by the web nginx from the real client address (X-Forwarded-For only trusted from TRUSTED_PROXY);
    # telemetry is not published, so only that nginx can reach it
    return request.headers.get("X-Real-IP", "") or (request.remote or "")


def control_allowed(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:                  # ::ffff:192.168.1.5 -> 192.168.1.5
        a = a.ipv4_mapped
    # if the front proxy did not pass a usable X-Forwarded-For, nginx reports the proxy itself - refuse that
    if TRUSTED_PROXY and ip == TRUSTED_PROXY:
        return False
    return any(a in n for n in CONTROL_ALLOW)


rot_lock = asyncio.Lock()                               # one control command at a time


async def rotctl(cmd: str) -> str:
    """One command on a short separate rotctld connection (the poll loop keeps its own)."""
    if not ROT_HOST:
        return "RPRT 0"
    reader, writer = await asyncio.wait_for(asyncio.open_connection(ROT_HOST, ROT_PORT), 5)
    try:
        writer.write((cmd + "\n").encode())
        await writer.drain()
        return (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace").strip()
    finally:
        writer.close()


async def point(az: float, el: float) -> str:
    """Send P az el. A STOP requested meanwhile cancels it; anything but RPRT 0 is an error (state unchanged)."""
    az = round(az % 360.0, 2) % 360.0
    el = round(min(max(el, ROT_EL_MIN), ROT_EL_MAX), 2)
    seq = control["stop_seq"]
    control["last_t"] = time.time()                      # rate limits count from the request, not the reply
    async with rot_lock:
        if control["stop_seq"] != seq:                   # STOP came in while we waited: do not move
            return "cancelled by STOP"
        reply = await rotctl(f"P {az:.2f} {el:.2f}")     # 0.01 deg; GS-232 controllers use whole degrees
    if reply != "RPRT 0":
        raise web.HTTPBadGateway(text=f"rotctld refused P {az:.2f} {el:.2f}: {reply or 'no reply'}")
    control["last_cmd"] = (az, el)
    state.update(target_az=round(az, 2), target_el=round(el, 2))
    return reply


async def stop() -> str:
    control["stop_seq"] += 1                             # cancels P commands still waiting for the lock
    async with rot_lock:
        return await rotctl("S")


def off_by(a: tuple, b: tuple) -> float:
    """angular distance (deg) between two az/el directions"""
    daz = (a[0] - b[0] + 540) % 360 - 180
    return math.hypot(daz * math.cos(math.radians((a[1] + b[1]) / 2)), a[1] - b[1])


async def control_get(request: web.Request) -> web.Response:
    return web.json_response({"allowed": control_allowed(client_ip(request))})


async def control_post(request: web.Request) -> web.Response:
    ip = client_ip(request)
    # the custom header makes browsers send a CORS preflight, which is never approved: other sites cannot do this
    if request.headers.get("X-Hamcam-Control") != "1":
        raise web.HTTPBadRequest(text="missing X-Hamcam-Control header")
    if not control_allowed(ip):
        print(f"control DENIED for {ip}")
        raise web.HTTPForbidden(text="rotator control is not allowed from this network")
    try:
        m = await request.json()
        cmd = m["cmd"]
        az, el = (float(m.get("az", 0)), float(m.get("el", 0))) if cmd in ("goto", "track") else (None, None)
    except (ValueError, KeyError, TypeError):
        raise web.HTTPBadRequest(text="bad request")
    # JSON allows NaN/Infinity; never pass those (or out-of-range values) towards the rotator
    if az is not None and not (math.isfinite(az) and math.isfinite(el) and 0 <= az <= 360 and -90 <= el <= 90):
        raise web.HTTPBadRequest(text="az must be 0..360 and el -90..90")
    now = time.time()
    reply = None
    if cmd == "stop":
        state["tracking"] = None
        control["lease"] = 0
        reply = await stop()
    elif cmd == "untrack":
        state["tracking"] = None
        control["lease"] = 0
    elif cmd == "goto":
        if now - control["last_t"] < 1.0:
            raise web.HTTPTooManyRequests(text="one command per second")
        state["tracking"] = None
        control["lease"] = 0
        reply = await point(az, el)
    elif cmd == "track":
        name = str(m.get("name") or m.get("id") or "?")[:40]
        new = state["tracking"] != name
        since = now - control["last_t"]
        if since >= 1.0 and (new or control["last_cmd"] is None or
                             (off_by((az, el), control["last_cmd"]) >= TRACK_STEP_DEG and since >= TRACK_MIN_INTERVAL_S)):
            reply = await point(az, el)                  # raises on rotctld errors: tracking is then not (re)started
        state["tracking"] = name
        control["lease"] = now + TRACK_LEASE_S
    else:
        raise web.HTTPBadRequest(text="unknown cmd")
    if reply is not None or cmd != "track":
        print(f"control {cmd} az={az} el={el} tracking={state['tracking']} from {ip}: {reply}")
    await broadcast(snapshot())
    return web.json_response({"ok": True, "reply": reply, "target_az": state["target_az"], "target_el": state["target_el"],
                              "tracking": state["tracking"]})


locate_cache: dict = {}                                  # call -> (time, response dict)


async def locate(request: web.Request) -> web.Response:
    """Callsign -> locator via qthdb, for the page's "point to" field (control users only: not an open proxy)."""
    if not control_allowed(client_ip(request)):
        raise web.HTTPForbidden(text="not allowed from this network")
    call = request.match_info["call"].upper()
    if not (3 <= len(call) <= 15) or not all(c.isalnum() or c == "/" for c in call):
        raise web.HTTPBadRequest(text="bad callsign")
    hit = locate_cache.get(call)
    if hit and time.time() - hit[0] < 600:
        return web.json_response(hit[1])
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(f"{QTHDB_URL}/v1/locator/{call}") as r:
                if r.status == 404:
                    raise web.HTTPNotFound(text=f"{call}: unknown callsign")
                d = await r.json(content_type=None)
    except web.HTTPException:
        raise
    except Exception as e:
        raise web.HTTPBadGateway(text=f"qthdb lookup failed: {e!r}"[:120])
    out = {k: d.get(k) for k in ("call", "locator", "confidence", "level", "last_seen", "mobile")}
    if not out["locator"]:
        raise web.HTTPNotFound(text=f"{call}: no locator")
    if len(locate_cache) > 500:
        locate_cache.clear()
    locate_cache[call] = (time.time(), out)
    return web.json_response(out)


async def control_watchdog() -> None:
    # tracking needs the page to keep confirming it; when it stops (page closed, connection lost) tracking ends
    while True:
        await asyncio.sleep(1)
        if state["tracking"] and time.time() > control["lease"]:
            print(f"control: tracking {state['tracking']} ended (no confirmation for {TRACK_LEASE_S:.0f} s)")
            state["tracking"] = None
            await broadcast(snapshot())


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    clients.add(ws)
    await ws.send_str(json.dumps(snapshot()))
    try:
        async for msg in ws:
            # ping for clock-offset estimation: {"type":"ping","c":<client ms>}
            if msg.type == aiohttp.WSMsgType.TEXT:
                m = json.loads(msg.data)
                if m.get("type") == "ping":
                    await ws.send_str(json.dumps({"type": "pong", "c": m.get("c"), "t": time.time()}))
    finally:
        clients.discard(ws)
    return ws


async def on_startup(app: web.Application) -> None:
    print("rotator control allowed for: " + (", ".join(map(str, CONTROL_ALLOW)) or "nobody (CONTROL_ALLOW empty)"), flush=True)
    for coro in (rotator_loop(), overlap_loop(), weather_loop(), heartbeat_loop(), beacon_loop(), tle_loop(), summit_loop(), control_watchdog(), scatter_loop()):
        asyncio.create_task(coro)


app = web.Application()
app.router.add_get("/telemetry", ws_handler)
app.router.add_get("/telemetry/state", lambda r: web.json_response(snapshot()))
app.router.add_get("/telemetry/beacons", beacons_response)
app.router.add_get("/telemetry/control", control_get)
app.router.add_post("/telemetry/control", control_post)
app.router.add_get("/telemetry/locate/{call}", locate)
app.router.add_get("/telemetry/tle/{group}", tle_response)
app.router.add_get("/telemetry/scatter", scatter_response)
app.router.add_get("/telemetry/summits", lambda r: web.json_response({"updated": summits["updated"], "summits": [
    {k: x[k] for k in ("ref", "name", "lat", "lon", "h")} for x in summits["summits"]]}))
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=8000, access_log=None)
