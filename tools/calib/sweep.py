"""Drive the rotator through a list of targets (rotctld P), waiting until each is reached and still."""
import socket, sys, time
s = socket.create_connection(("192.168.14.199", 4533), timeout=10); f = s.makefile("rwb")
def cmd(c):
    f.write((c + "\n").encode()); f.flush()
def pos():
    # rotctld sometimes answers RPRT -8 while the controller is busy: retry
    for _ in range(20):
        cmd("p"); l1 = f.readline()
        try:
            a = float(l1); f.readline(); return a
        except ValueError:
            time.sleep(0.3)
    raise RuntimeError("rotctld keeps failing")
for tgt in [float(x) for x in sys.argv[1:]]:
    t0 = time.time(); cmd(f"P {tgt:.0f} 0"); rep = f.readline().decode().strip()
    last, still = None, time.time()
    while time.time() - t0 < 200:
        a = pos()
        if a != last: last, still = a, time.time()
        if time.time() - still > 4 and abs(a - tgt) <= 2: break
        time.sleep(0.25)
    print(f"{time.strftime('%H:%M:%S')} P {tgt:.0f}: {rep}, reached {last:.1f} in {time.time()-t0:.0f}s", flush=True)
    time.sleep(10)
