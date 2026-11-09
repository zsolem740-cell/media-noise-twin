// WebGL-glóbusz Three.js-szel (Solaris 3D / HUD stílus).
// A Three.js-t futásidőben tölti be (CDN, a service worker gyorsítótárazza); ha nem érhető el, nincs WebGL, vagy a
// renderelés hibázik, az alkalmazás a Canvas-glóbuszra (globe.js) esik vissza. A vetítés és a kiválasztás saját
// matematika (Three nélkül tesztelhető), a Three csak a rajzolást végzi.
import { Globe, densify } from './globe.js';
import { LAND } from './land.js';

export const THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
const D2R = Math.PI / 180;
const HALF_FOV = 20 * D2R;
const COLORS = { low: 0x3ddc84, mid: 0xffb020, high: 0xff4d4d };

// Egység-vektor a gömbön: lng 0, lat 0 = +z (a kamera felé néz).
export const unit = (lat, lng) => {
  const p = lat * D2R, l = lng * D2R;
  return [Math.cos(p) * Math.sin(l), Math.sin(p), Math.cos(p) * Math.cos(l)];
};

// A nézet forgatása: Ry(−lng0), majd Rx(lat0) – ugyanez a két egymásba ágyazott Three.js csoport (spin, tilt).
export function rotateView(v, lat0, lng0) {
  const b = -lng0 * D2R, a = lat0 * D2R;
  const x = v[0] * Math.cos(b) + v[2] * Math.sin(b);
  const z = -v[0] * Math.sin(b) + v[2] * Math.cos(b);
  return [x, v[1] * Math.cos(a) - z * Math.sin(a), v[1] * Math.sin(a) + z * Math.cos(a)];
}

// A kamera távolsága úgy, hogy a teljes gömb elférjen a vásznon (álló képernyőn is).
export function baseDistance(aspect) {
  const m = Math.min(HALF_FOV, Math.atan(Math.tan(HALF_FOV) * aspect));
  return (1 / Math.sin(m)) * 1.06;
}

// Perspektív vetítés a +z tengelyen álló kamerával; x, y: −1…1; vis: a gömb kamera felé néző felén van-e.
export function projectPoint(u, rot, dist, tanHalf, aspect) {
  const p = rotateView(u, rot.lat, rot.lng);
  const depth = dist - p[2];
  return { x: p[0] / depth / (tanHalf * aspect), y: p[1] / depth / tanHalf, vis: p[2] > 1 / dist };
}

function webglSupported() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch (_) { return false; }
}

export class Globe3D extends Globe {
  constructor(THREE, canvas, opts = {}) {
    super(canvas, Object.assign({}, opts, { webgl: true }));
    this.T = THREE;
    this.is3d = true;
    this.onError = opts.onError || null;
    this.size = { w: 0, h: 0 };
    this._dpr = 0;
    this.dist = 3;
    this.dotMesh = null;
    this.ringMesh = null;
    this.pts3 = [];
    this.failed = false;

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
    this.renderer.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50);
    this.tilt = new THREE.Group();
    this.spin = new THREE.Group();
    this.tilt.add(this.spin);
    this.scene.add(this.tilt);
    this._build();
    if (canvas.addEventListener) canvas.addEventListener('webglcontextlost', e => { if (e.preventDefault) e.preventDefault(); this._fail(new Error('WebGL-kontextus elveszett')); });
    this.resize();
  }

  _lines(positions, color, opacity) {
    const T = this.T;
    const g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(positions, 3));
    return new T.LineSegments(g, new T.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
  }

  _segments(rings, radius) {
    const out = [];
    for (const pts of rings) {
      for (let i = 0; i < pts.length - 1; i++) {
        const a = unit(pts[i][0], pts[i][1]), b = unit(pts[i + 1][0], pts[i + 1][1]);
        out.push(a[0] * radius, a[1] * radius, a[2] * radius, b[0] * radius, b[1] * radius, b[2] * radius);
      }
    }
    return new Float32Array(out);
  }

  _build() {
    const T = this.T;
    this.spin.add(new T.Mesh(new T.SphereGeometry(0.997, 48, 32), new T.MeshBasicMaterial({ color: 0x050d17 })));
    this.scene.add(new T.Mesh(
      new T.SphereGeometry(1.035, 48, 32),
      new T.MeshBasicMaterial({ color: 0x00ff88, transparent: true, opacity: 0.07, side: T.BackSide, depthWrite: false })));
    const grid = [];
    for (let lat = -60; lat <= 60; lat += 30) {
      const r = []; for (let lng = -180; lng <= 180; lng += 6) r.push([lat, lng]); grid.push(r);
    }
    for (let lng = -180; lng < 180; lng += 30) {
      const r = []; for (let lat = -90; lat <= 90; lat += 6) r.push([lat, lng]); grid.push(r);
    }
    this.spin.add(this._lines(this._segments(grid, 1.001), 0x00e5ff, 0.16));
    this.spin.add(this._lines(this._segments(LAND.map(r => densify(r)), 1.002), 0x00e5ff, 0.6));
  }

  _disposeDots() {
    for (const m of [this.dotMesh, this.ringMesh]) {
      if (!m) continue;
      this.spin.remove(m);
      m.geometry.dispose();
      m.material.dispose();
      if (m.dispose) m.dispose();
    }
    this.dotMesh = this.ringMesh = null;
    this.pts3 = [];
  }

  setPoints(points) {
    this.points = points;
    const T = this.T;
    this._disposeDots();
    const n = points.length;
    if (n) {
      const mesh = new T.InstancedMesh(new T.SphereGeometry(1, 8, 6), new T.MeshBasicMaterial({ color: 0xffffff }), n);
      mesh.frustumCulled = false;
      const dummy = new T.Object3D(), col = new T.Color();
      const highs = [];
      points.forEach((p, i) => {
        const u = unit(p.lat, p.lng);
        const lvl = p.atm >= this.th.high ? 'high' : p.atm >= this.th.low ? 'mid' : 'low';
        const s = 0.012 + Math.min(p.size !== undefined ? p.size : p.atm, 0.5) * 0.045;
        dummy.position.set(u[0] * 1.012, u[1] * 1.012, u[2] * 1.012);
        dummy.scale.setScalar(s);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
        mesh.setColorAt(i, col.setHex(COLORS[lvl]));
        this.pts3.push({ u, p });
        if (lvl === 'high') highs.push({ u, s });
      });
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      this.spin.add(mesh);
      this.dotMesh = mesh;
      if (highs.length) {
        const ring = new T.InstancedMesh(
          new T.SphereGeometry(1, 10, 8),
          new T.MeshBasicMaterial({ color: COLORS.high, transparent: true, opacity: 0.2, depthWrite: false }), highs.length);
        ring.frustumCulled = false;
        highs.forEach((h, i) => {
          dummy.position.set(h.u[0] * 1.012, h.u[1] * 1.012, h.u[2] * 1.012);
          dummy.scale.setScalar(h.s * 2.6);
          dummy.updateMatrix();
          ring.setMatrixAt(i, dummy.matrix);
        });
        ring.instanceMatrix.needsUpdate = true;
        this.spin.add(ring);
        this.ringMesh = ring;
      }
    }
    this.draw();
  }

  resize() {
    this.dpr = Math.min((typeof devicePixelRatio !== 'undefined' && devicePixelRatio) || 1, 2);
    const w = Math.max(160, this.c.clientWidth || 320), h = Math.max(160, this.c.clientHeight || 320);
    if (this.size.w !== w || this.size.h !== h || this._dpr !== this.dpr) {
      this.size = { w, h };
      this._dpr = this.dpr;
      this.renderer.setPixelRatio(this.dpr);
      this.renderer.setSize(w, h, false);
    }
  }

  _fail(err) {
    if (this.failed) return;
    this.failed = true;
    this.stop();
    if (this.onError) this.onError(err);
  }

  draw() {
    if (this.failed || !this.renderer) return;
    try {
      this.resize();
      const { w, h } = this.size, aspect = w / h;
      this.dist = baseDistance(aspect);
      const tanHalf = Math.tan(HALF_FOV) / this.zoom; // nagyítás = szűkebb látószög, a kamera nem megy a gömbbe
      this.camera.aspect = aspect;
      this.camera.fov = (2 * Math.atan(tanHalf)) / D2R;
      this.camera.position.set(0, 0, this.dist);
      this.camera.updateProjectionMatrix();
      this.tilt.rotation.x = this.rot.lat * D2R;
      this.spin.rotation.y = -this.rot.lng * D2R;
      if (this.ringMesh) this.ringMesh.material.opacity = 0.1 + 0.14 * Math.abs(Math.sin(this.pulse * Math.PI / 2));
      this.renderer.render(this.scene, this.camera);
      this._screen(aspect, tanHalf);
    } catch (e) {
      this._fail(e);
    }
  }

  _screen(aspect, tanHalf) {
    const W = this.size.w * this.dpr, H = this.size.h * this.dpr;
    this.scr = [];
    for (const q of this.pts3) {
      const r = projectPoint(q.u, this.rot, this.dist, tanHalf, aspect);
      if (r.vis) this.scr.push({ x: ((r.x + 1) / 2) * W, y: ((1 - r.y) / 2) * H, p: q.p });
    }
  }

  dispose() {
    this.stop();
    this._disposeDots();
    try { this.renderer.dispose(); } catch (_) {}
    if (this.c && this.c.remove) this.c.remove();
  }
}

export async function createGlobe3D(canvas, opts = {}, loader = () => import(THREE_URL)) {
  if (typeof document !== 'undefined' && !webglSupported()) throw new Error('A böngésző nem támogatja a WebGL-t');
  const THREE = await loader();
  return new Globe3D(THREE, canvas, opts);
}
