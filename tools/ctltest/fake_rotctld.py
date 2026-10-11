"""Fake rotctld for tests: p / P az el / S / anything else -> RPRT 0; simulated movement 10 deg/s; logs every command."""
import asyncio, time
state = {"az": 122.0, "el": 0.0, "target": None}
def log(*a): print(f"{time.strftime('%H:%M:%S')}", *a, flush=True)
async def mover():
    while True:
        await asyncio.sleep(0.25)
        t = state["target"]
        if t is None: continue
        d = ((t - state["az"] + 540) % 360) - 180
        if abs(d) <= 2.5: state["az"] = t; state["target"] = None; log(f"reached {t:.1f}")
        else: state["az"] = (state["az"] + (2.5 if d > 0 else -2.5)) % 360
async def handle(r, w):
    while True:
        line = await r.readline()
        if not line: break
        c = line.decode().strip()
        if c == "p": w.write(f"{round(state['az'])}.00\n{state['el']:.2f}\n".encode())
        elif c.startswith("P "):
            _, az, el = c.split(); state["target"] = float(az) % 360; state["el"] = float(el); log(f"CMD P az={az} el={el}"); w.write(b"RPRT 0\n")
        elif c == "S": state["target"] = None; log("CMD S (stop)"); w.write(b"RPRT 0\n")
        else: w.write(b"RPRT 0\n")
        await w.drain()
    w.close()
async def main():
    asyncio.create_task(mover())
    async with await asyncio.start_server(handle, "0.0.0.0", 4533): await asyncio.Event().wait()
asyncio.run(main())
