"""Measure rotation speed (deg/s) at a given SPEED level over a short move, then restore the level."""
import socket, sys, time
lvl, a0, a1, restore = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
s = socket.create_connection(("192.168.14.199", 4533), timeout=10); f = s.makefile("rwb")
def cmd(c): f.write((c + "\n").encode()); f.flush()
def pos():
    for _ in range(20):
        cmd("p"); l = f.readline()
        try: a = float(l); f.readline(); return a
        except ValueError: time.sleep(0.3)
cmd(f"w X{lvl}"); print("set X", lvl, "->", f.readline().decode().strip())
log = []; cmd(f"P {a1:.0f} 0"); f.readline(); t0 = time.time(); still = time.time(); last = None
while time.time() - t0 < 120:
    a = pos(); log.append((time.time() - t0, a))
    if a != last: last, still = a, time.time()
    if time.time() - still > 3 and abs(a - a1) <= 2: break
    time.sleep(0.2)
lo, hi = min(a0, a1), max(a0, a1)
mv = [(t, a) for t, a in log if lo + 1 < a < hi - 1]
if len(mv) > 2: print(f"SPEED {lvl}: {abs(mv[-1][1]-mv[0][1])/(mv[-1][0]-mv[0][0]):.2f} deg/s over {abs(mv[-1][1]-mv[0][1]):.0f} deg")
print("final", last)
cmd(f"w X{restore}"); print("restored X", restore, "->", f.readline().decode().strip())
