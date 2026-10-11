FROM node:20-alpine
RUN apk add --no-cache chromium font-dejavu
WORKDIR /app
RUN npm init -y >/dev/null && npm install puppeteer-core@23.6.0 >/dev/null
ENV CHROME=/usr/bin/chromium-browser
