"""Fake rotctld for tests: p / P az el / S / w AR / anything else -> RPRT 0; simulated movement 10 deg/s; logs every command.
Keeps a raw position in -30..390 like the SQ6EMM firmware (a heading goes to the closest turn) and answers 'w AR' with
rotctld's framing ("AR-10.0\\r\\n\\n\\n"). Env: PDELAY = seconds before answering P (provokes races), ELMAX = refuse P with
el above it (RPRT -8, like an az-only model), RAW0 = start position (raw, default 122), NOAR=1 = controller without AR
(rotctld then sends nothing)."""
import asyncio, os, time
PDELAY = float(os.environ.get("PDELAY", "0")); ELMAX = float(os.environ.get("ELMAX", "999"))
NOAR = os.environ.get("NOAR") == "1"; LO, HI = -30.0, 390.0
state = {"raw": float(os.environ.get("RAW0", "122")), "el": 0.0, "target": None}
def log(*a): print(f"{time.strftime('%H:%M:%S')}", *a, flush=True)
def closest(h, raw):
    cands = [c for c in (h - 360, h, h + 360) if LO <= c <= HI]
    return min(cands, key=lambda c: abs(c - raw))
async def mover():
    while True:
        await asyncio.sleep(0.25)
        t = state["target"]
        if t is None: continue
        d = t - state["raw"]
        if abs(d) <= 2.5: state["raw"] = t; state["target"] = None; log(f"reached raw {t:.1f}")
        else: state["raw"] += 2.5 if d > 0 else -2.5
async def handle(r, w):
    while True:
        line = await r.readline()
        if not line: break
        c = line.decode().strip()
        if c == "p": w.write(f"{round(state['raw'] % 360)}.00\n{state['el']:.2f}\n".encode())
        elif c == "w AR":
            if not NOAR: w.write(f"AR{state['raw']:.1f}\r\n\n\n".encode())
        elif c.startswith("P "):
            _, az, el = c.split()
            if float(el) > ELMAX: log(f"CMD P az={az} el={el} REFUSED (el > {ELMAX})"); w.write(b"RPRT -8\n")
            else:
                log(f"CMD P az={az} el={el} received"); await asyncio.sleep(PDELAY)
                state["target"] = closest(float(az) % 360, state["raw"]); state["el"] = float(el)
                log(f"CMD P az={az} el={el} executed -> raw {state['target']:.1f}"); w.write(b"RPRT 0\n")
        elif c == "S": state["target"] = None; log("CMD S (stop)"); w.write(b"RPRT 0\n")
        else: w.write(b"RPRT 0\n")
        await w.drain()
    w.close()
async def main():
    asyncio.create_task(mover())
    async with await asyncio.start_server(handle, "0.0.0.0", 4533): await asyncio.Event().wait()
asyncio.run(main())
