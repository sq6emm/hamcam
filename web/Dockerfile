# hamcam web: nginx serving the page; build context = repository root
FROM nginxinc/nginx-unprivileged:1.29-alpine
LABEL org.opencontainers.image.source="https://github.com/sq6emm/hamcam" \
      org.opencontainers.image.description="hamcam page and overlay (nginx); mount your config dir at /config" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"
COPY web/www /usr/share/nginx/html
# ${ADSB_URL} is filled in from the environment when nginx starts
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
# example configuration; mount your own directory over /config
COPY deploy/objects.json /config/objects.json
