// Day view: a daylight panorama (true azimuth / elevation, tools/pano/build.py) projected through the page's camera
// model for the shown azimuth, so it covers the video exactly where the live picture would be and the overlay lands
// on the same objects. WebGL2: a mesh over the view, each vertex = camera.unproject() -> panorama texture coordinate.
import { Camera } from './sky.js';

const NX = 40, NY = 30;                         // mesh cells (the lens distortion is smooth: 40x40 px cells are plenty)

export class DayView {
  constructor(canvas, camOpts, W, H) {
    Object.assign(this, { canvas, W, H, meta: null, yaw: null, ready: false });
    this.cam = new Camera(camOpts);
    canvas.width = W; canvas.height = H;
    const gl = this.gl = canvas.getContext('webgl2', { preserveDrawingBuffer: true, alpha: false, antialias: false });
    if (!gl) return;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const p = this.prog = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, `#version 300 es
      in vec2 pos; in vec2 uv; out vec2 v;
      void main() { v = uv; gl_Position = vec4(pos, 0.0, 1.0); }`));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, `#version 300 es
      precision highp float; in vec2 v; uniform sampler2D tex; out vec4 o;
      void main() { o = (v.y < 0.0 || v.y > 1.0) ? vec4(0.0, 0.0, 0.0, 1.0) : texture(tex, v); }`));
    gl.linkProgram(p);
    // index buffer: two triangles per cell
    const idx = [];
    for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) {
      const a = j * (NX + 1) + i, b = a + 1, c = a + NX + 1, d = c + 1;
      idx.push(a, b, c, b, d, c);
    }
    this.nIdx = idx.length;
    this.vao = gl.createVertexArray(); gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW);
    this.buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    const lp = gl.getAttribLocation(p, 'pos'), lu = gl.getAttribLocation(p, 'uv');
    gl.enableVertexAttribArray(lp); gl.vertexAttribPointer(lp, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(lu); gl.vertexAttribPointer(lu, 2, gl.FLOAT, false, 16, 8);
    this.data = new Float32Array((NX + 1) * (NY + 1) * 4);
  }
  get supported() { return !!this.gl; }
  // meta: panorama.json; base: URL prefix of the images
  async load(meta, base) {
    const gl = this.gl;
    const big = gl.getParameter(gl.MAX_TEXTURE_SIZE) >= meta.width;
    const img = new Image();
    img.src = base + (big ? meta.image : meta.image_small);
    await img.decode();
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);       // azimuth wraps around
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.meta = meta; this.ready = true; this.yaw = null;
  }
  // yaw: true azimuth of the image centre (the same value the overlay uses)
  render(yaw) {
    if (!this.ready || yaw == null) return;
    const { gl, cam, meta, W, H, data } = this;
    this.yaw = yaw; cam.setYaw(yaw);
    const span = meta.az1 - meta.az0, eh = meta.el_max - meta.el_min;
    let k = 0;
    for (let j = 0; j <= NY; j++) for (let i = 0; i <= NX; i++) {
      const x = i * W / NX, y = j * H / NY;
      const { az, el } = cam.unproject(x, y);
      const a = yaw + ((az - yaw + 540) % 360) - 180;                    // continuous across 0/360 within the view
      data[k++] = x / W * 2 - 1; data[k++] = 1 - y / H * 2;
      data[k++] = (a - meta.az0) / span; data[k++] = (meta.el_max - el) / eh;
    }
    gl.viewport(0, 0, W, H);
    gl.useProgram(this.prog); gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf); gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
    gl.drawElements(gl.TRIANGLES, this.nIdx, gl.UNSIGNED_SHORT, 0);
  }
}
