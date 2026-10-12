FROM node:20-alpine
# mesa: software OpenGL, so WebGL works headless (Chromium flag --use-angle=gl-egl; used by day.mjs)
RUN apk add --no-cache chromium font-dejavu mesa-gl mesa-egl mesa-gles mesa-dri-gallium
WORKDIR /app
RUN npm init -y >/dev/null && npm install puppeteer-core@23.6.0 >/dev/null
ENV CHROME=/usr/bin/chromium-browser
