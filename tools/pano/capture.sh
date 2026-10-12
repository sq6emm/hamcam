#!/bin/sh
# Daylight reference frames for the night view panorama: full circle in 20-deg steps (all approached CW, soft
# start/stop by the firmware on each move), 3 frames per stop, then back to the start position.
# Usage: capture.sh <out frames dir>        log: <out>/capture.log (settled/final rotator az per stop)
set -e
OUT=$1; mkdir -p "$OUT"; P=/data/claude/hamcam
ROTCTLD_HOST=$(sed -n "s/^ROTCTLD_HOST=//p" /etc/docker-compose/hamcam/.env); ROTCTLD_PORT=$(sed -n "s/^ROTCTLD_PORT=//p" /etc/docker-compose/hamcam/.env); ROTCTLD_PORT=${ROTCTLD_PORT:-4533}
START=$(python3 -c "import socket; s=socket.create_connection(('$ROTCTLD_HOST',$ROTCTLD_PORT),timeout=5); f=s.makefile('rwb'); f.write(b'p\n'); f.flush(); print(round(float(f.readline())))")
echo "start position $START" | tee -a "$OUT/capture.log"
grab() {  # <az> <prefix>; rotctld sometimes answers RPRT -8 -> retry the stop
  for try in 1 2 3; do
    if timeout 300 docker run --rm --name hamcam-grab --label owner=claude --network host --user $(id -u):$(id -g) -e ROTCTLD_HOST=$ROTCTLD_HOST -e ROTCTLD_PORT=$ROTCTLD_PORT \
        -v $P/tools/calib:/t:ro -v "$OUT":/o hamcam-calib:dev python -I -u /t/point_and_grab.py $1 /o/$2 > "$OUT/$2.txt" 2>&1; then
      grep -E "settled|final" "$OUT/$2.txt" | sed "s/^/$2: /" | tee -a "$OUT/capture.log"; return 0
    fi
    echo "$2: try $try failed: $(tail -1 "$OUT/$2.txt")" | tee -a "$OUT/capture.log"; sleep 3
  done
  return 1
}
for A in 2 20 40 60 80 100 120 140 160 180 200 220 240 260 280 300 320 340 358; do
  grab $A g$(printf %03d $A)
done
grab $START back
echo done | tee -a "$OUT/capture.log"
