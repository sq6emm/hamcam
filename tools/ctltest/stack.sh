#!/bin/sh
# Isolated test stack for rotator control: fake rotctld + telemetry built from source + page on 127.0.0.1:8098.
# The real rotator and the live installation are not touched. The test network gateway plays the front proxy, so a
# browser/curl sending "X-Forwarded-For: 192.168.12.38" is treated as a LAN visitor.
#   [PDELAY=s] [ELMAX=deg] stack.sh up | down   (fake rotctld options; config: /etc/docker-compose/hamcam/config, ADSB_URL and WEATHER_* from its .env)
set -e
R=$(cd "$(dirname "$0")/../.." && pwd); W=$R/analysis-ctltest; E=/etc/docker-compose/hamcam
case "$1" in
up)
  mkdir -p $W/data $W/static && cp $R/telemetry/data/* $W/data/ 2>/dev/null || true
  for f in video-rtc.js video-stream.js; do curl -s -o $W/static/$f http://127.0.0.1:8097/$f; done
  docker build -q --label owner=claude -f $R/telemetry/Dockerfile -t hamcam-telemetry:ctltest $R >/dev/null
  docker network create --label owner=claude hamcam-ctltest >/dev/null
  GW=$(docker network inspect hamcam-ctltest -f '{{(index .IPAM.Config 0).Gateway}}')
  docker run -d --rm --name hamcam-fakerot --label owner=claude --network hamcam-ctltest -e PDELAY=${PDELAY:-0} -e ELMAX=${ELMAX:-999} -v $R/tools/ctltest/fake_rotctld.py:/f.py:ro python:3.12-slim python -u /f.py >/dev/null
  docker run -d --rm --name hamcam-ctl-go2rtc --label owner=claude --network hamcam-ctltest --network-alias go2rtc -v $W/static:/s:ro -w /s python:3.12-slim python -m http.server 1985 >/dev/null
  docker run -d --rm --name hamcam-ctl-telemetry --label owner=claude --network hamcam-ctltest --network-alias telemetry --user $(id -u):$(id -g) \
    -e ROTCTLD_HOST=hamcam-fakerot -e WEATHER_URL="$(sed -n 's/^WEATHER_URL=//p' $E/.env)" -e WEATHER_FIELDS="$(sed -n 's/^WEATHER_FIELDS=//p' $E/.env)" -e CONTROL_ALLOW=192.168.0.0/16 -e TRUSTED_PROXY=$GW -e OBJECTS_FILE=/config/objects.json -e BEACON_FILE=/data/beacons.json \
    -v $W/data:/data -v $E/config:/config:ro hamcam-telemetry:ctltest >/dev/null
  docker run -d --rm --name hamcam-ctl-web --label owner=claude --network hamcam-ctltest -p 127.0.0.1:8098:8080 -e TRUSTED_PROXY=$GW \
    -e ADSB_URL=$(sed -n 's/^ADSB_URL=//p' $E/.env) -v $R/web/www:/usr/share/nginx/html:ro \
    -v $R/web/nginx.conf.template:/etc/nginx/templates/default.conf.template:ro -v $E/config:/config:ro nginxinc/nginx-unprivileged:1.29-alpine >/dev/null
  echo "test stack up: http://127.0.0.1:8098/  (proxy = $GW; logs: docker logs hamcam-fakerot / hamcam-ctl-telemetry)" ;;
down)
  docker rm -f hamcam-ctl-web hamcam-ctl-telemetry hamcam-ctl-go2rtc hamcam-fakerot >/dev/null 2>&1 || true
  docker network rm hamcam-ctltest >/dev/null 2>&1 || true
  docker rmi hamcam-telemetry:ctltest >/dev/null 2>&1 || true
  rm -rf $W; echo "test stack removed" ;;
*) echo "usage: $0 up|down"; exit 1 ;;
esac
