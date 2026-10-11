#!/bin/sh
# Noon capture for tilt calibration: full circle in 30-deg steps (all approached CW), then back to the start position.
# Usage: capture.sh <out frames dir>
set -e
OUT=$1; mkdir -p "$OUT"; P=/data/claude/hamcam
# rotctld address from the stack's .env (/etc/docker-compose/hamcam)
ROTCTLD_HOST=$(sed -n "s/^ROTCTLD_HOST=//p" /etc/docker-compose/hamcam/.env); ROTCTLD_PORT=$(sed -n "s/^ROTCTLD_PORT=//p" /etc/docker-compose/hamcam/.env); ROTCTLD_PORT=${ROTCTLD_PORT:-4533}
START=$(python3 -c "import socket; s=socket.create_connection(('$ROTCTLD_HOST',$ROTCTLD_PORT),timeout=5); f=s.makefile('rwb'); f.write(b'p\n'); f.flush(); print(round(float(f.readline())))")
echo "start position $START"
for A in 2 30 60 90 120 150 180 210 240 270 300 330 358; do
  timeout 300 docker run --rm --name hamcam-grab --label owner=claude --network host --user $(id -u):$(id -g) -e ROTCTLD_HOST=$ROTCTLD_HOST -e ROTCTLD_PORT=$ROTCTLD_PORT \
    -v $P/tools/calib:/t:ro -v "$OUT":/o hamcam-calib:dev python -I -u /t/point_and_grab.py $A /o/g$A | grep -E "settled|final"
  cp "$OUT/g${A}_1.jpg" "$OUT/rot$(printf %03d $A).jpg"
done
timeout 300 docker run --rm --name hamcam-grab --label owner=claude --network host --user $(id -u):$(id -g) -e ROTCTLD_HOST=$ROTCTLD_HOST -e ROTCTLD_PORT=$ROTCTLD_PORT \
  -v $P/tools/calib:/t:ro -v "$OUT":/o hamcam-calib:dev python -I -u /t/point_and_grab.py $START /o/back | grep -E "settled|final"
