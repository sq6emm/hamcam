"""Live preset-encoder diagnostics: poll AN (raw ADC of encoder channels A6,A2) every 0.2 s, print changes (read-only).
The SQ6EMM rotor firmware decodes the encoder itself; this shows whether the contacts switch cleanly (low/high levels)."""
import sys, time
from rot import _val
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 240
t0 = time.time(); last = None
print(time.strftime("%H:%M:%S"), "encoder monitor start", flush=True)
while time.time() - t0 < dur:
    a, b = (int(x) for x in _val("AN").split(","))
    cur = (a > 512, b > 512)
    if cur != last:
        print(time.strftime("%H:%M:%S"), f"A6 {a:4d} ({'H' if cur[0] else 'L'})  A2 {b:4d} ({'H' if cur[1] else 'L'})", flush=True)
        last = cur
    time.sleep(0.2)
print(time.strftime("%H:%M:%S"), "encoder monitor end", flush=True)
