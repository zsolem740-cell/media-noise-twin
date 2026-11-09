// Solaris-stílusú glóbusz Canvas 2D-ben: nincs külső függőség, offline is megy, kíméli az akkut
// (csak látható lapnál rajzol, ~20 fps, a háttérben leáll).
import { LAND } from './land.js';

const D2R = Math.PI / 180;
const COLORS = { low: '#3ddc84', mid: '#ffb020', high: '#ff4d4d' };
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));


// A partvonalak sűrítése nagykör mentén (3°-os lépés), hogy a gömbön simán hajoljanak.
export function densify(ring, stepDeg = 3) {
  const vec = ([la, lo]) => { const p = la * D2R, l = lo * D2R; return [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)]; };
  const pts = ring.concat([ring[0]]);
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = vec(pts[i]), b = vec(pts[i + 1]);
    const dot = clamp(a[0] * b[0] + a[1] * b[1] + a[2] * b[2], -1, 1);
    const ang = Math.acos(dot);
    const n = Math.max(1, Math.ceil(ang / (stepDeg * D2R)));
    for (let k = 0; k < n; k++) {
      const t = k / n;
      let v = a;
      if (ang > 1e-6) {
        const s = Math.sin(ang), w1 = Math.sin(ang * (1 - t)) / s, w2 = Math.sin(ang * t) / s;
        v = [w1 * a[0] + w2 * b[0], w1 * a[1] + w2 * b[1], w1 * a[2] + w2 * b[2]];
      }
      out.push([Math.asin(clamp(v[2], -1, 1)) / D2R, Math.atan2(v[1], v[0]) / D2R]);
    }
  }
  out.push(out[0]);
  return out;
}

let _dense = null;
const landRings = () => (_dense = _dense || LAND.map(r => densify(r)));

export function project(lat, lng, rot, R) {
  const phi = lat * D2R, lam = (lng - rot.lng) * D2R, phi0 = rot.lat * D2R;
  const cosc = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(lam);
  return {
    x: R * Math.cos(phi) * Math.sin(lam),
    y: -R * (Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(lam)),
    z: cosc,
    vis: cosc > 0,
  };
}

export class Globe {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = (opts.webgl || !canvas.getContext) ? null : canvas.getContext('2d');
    this.rot = { lat: 38, lng: 16.6 };
    this.target = null;
    this.points = [];
    this.scr = [];
    this.th = opts.th || { low: 0.1, high: 0.25 };
    this.onPick = opts.onPick || (() => {});
    this.drag = null;
    this.last = 0;
    this.running = false;
    this.inView = true;
    this.dpr = 1;
    this.pulse = 0;
    this.zoom = 1;
    this.full = false;
    this.pointers = new Map();
    this.pinch = 0;
    this.lastTap = 0;
    this._bind();
  }

  setThresholds(th) { this.th = th; }
  setPoints(p) { this.points = p; this.draw(); }
  focus(lat, lng) { this.target = { lat: clamp(lat, -60, 70), lng }; }

  // Nagyítás: 1× (egész glóbusz) … 4×; nagyítva az érintés a forgatást kapja, nem az oldalgörgetést.
  setZoom(z) { this.zoom = clamp(z, 1, 4); this._touchAction(); this.draw(); }
  zoomBy(f) { this.setZoom(this.zoom * f); }
  setFull(on) { this.full = !!on; this._touchAction(); this.draw(); }
  _touchAction() { if (this.c.style) this.c.style.touchAction = (this.zoom > 1.02 || this.full) ? 'none' : 'pan-y'; }
  _dist() {
    const v = [...this.pointers.values()];
    return v.length < 2 ? 0 : Math.hypot(v[0].x - v[1].x, v[0].y - v[1].y);
  }
  _tap(e) {
    const now = Date.now();
    if (now - this.lastTap < 320) { this.lastTap = 0; this.setZoom(this.zoom > 1.5 ? 1 : 2.2); return; } // dupla koppintás
    this.lastTap = now;
    this._pick(e);
  }

  resize() {
    this.dpr = Math.min((typeof devicePixelRatio !== 'undefined' && devicePixelRatio) || 1, 2);
    const w = Math.max(160, this.c.clientWidth || 320), h = Math.max(160, this.c.clientHeight || 320);
    if (this.c.width !== Math.round(w * this.dpr) || this.c.height !== Math.round(h * this.dpr)) { this.c.width = Math.round(w * this.dpr); this.c.height = Math.round(h * this.dpr); }
  }

  _bind() {
    const c = this.c;
    if (!c.addEventListener) return;
    const pts = this.pointers;
    c.addEventListener('pointerdown', e => {
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 1) this.drag = { x: e.clientX, y: e.clientY, moved: 0 };
      else if (pts.size === 2) { this.drag = null; this.pinch = this._dist(); }
      this.target = null;
    });
    c.addEventListener('pointermove', e => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size >= 2) {                       // két ujjas csípés = nagyítás
        const d = this._dist();
        if (this.pinch && d) this.setZoom(this.zoom * d / this.pinch);
        this.pinch = d;
        return;
      }
      if (!this.drag) return;
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
      this.drag.x = e.clientX; this.drag.y = e.clientY; this.drag.moved += Math.abs(dx) + Math.abs(dy);
      this.rot.lng -= (dx * 0.35) / this.zoom;   // nagyítva finomabb forgatás
      this.rot.lat = clamp(this.rot.lat + (dy * 0.25) / this.zoom, -70, 75);
      this.draw();
    });
    const end = e => {
      const d = this.drag;
      pts.delete(e.pointerId);
      if (pts.size < 2) this.pinch = 0;
      if (d && d.moved < 8 && e.type === 'pointerup') this._tap(e);
      if (pts.size === 0) this.drag = null;
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    c.addEventListener('wheel', e => { e.preventDefault(); this.zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
    if (typeof IntersectionObserver !== 'undefined') {
      new IntersectionObserver(es => { this.inView = es[0].isIntersecting; }).observe(c);
    }
  }

  _pick(e) {
    const r = this.c.getBoundingClientRect();
    const x = (e.clientX - r.left) * this.dpr, y = (e.clientY - r.top) * this.dpr;
    let best = null, bd = (18 * this.dpr) ** 2;
    for (const s of this.scr) {
      const d = (s.x - x) ** 2 + (s.y - y) ** 2;
      if (d < bd) { bd = d; best = s.p; }
    }
    this.onPick(best);
  }

  _line(pts, R, cx, cy) {
    const ctx = this.ctx;
    let pen = false;
    for (const [lat, lng] of pts) {
      const p = project(lat, lng, this.rot, R);
      if (!p.vis) { pen = false; continue; }
      if (pen) ctx.lineTo(cx + p.x, cy + p.y); else { ctx.moveTo(cx + p.x, cy + p.y); pen = true; }
    }
  }

  draw() {
    this.resize();
    const ctx = this.ctx, W = this.c.width, H = this.c.height;
    const R = Math.min(W, H) * 0.46 * this.zoom, cx = W / 2, cy = H / 2, dpr = this.dpr;
    ctx.clearRect(0, 0, W, H);

    const g = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, R * 0.1, cx, cy, R);
    g.addColorStop(0, '#0e1c2e'); g.addColorStop(1, '#02060b');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    ctx.lineWidth = dpr; ctx.strokeStyle = 'rgba(0,255,136,0.35)'; ctx.stroke();

    ctx.strokeStyle = 'rgba(0,229,255,0.14)'; ctx.lineWidth = dpr * 0.8;
    ctx.beginPath();
    for (let lat = -60; lat <= 60; lat += 30) {
      const pts = []; for (let lng = -180; lng <= 180; lng += 6) pts.push([lat, lng]);
      this._line(pts, R, cx, cy);
    }
    for (let lng = -180; lng < 180; lng += 30) {
      const pts = []; for (let lat = -90; lat <= 90; lat += 6) pts.push([lat, lng]);
      this._line(pts, R, cx, cy);
    }
    ctx.stroke();

    ctx.strokeStyle = 'rgba(0,229,255,0.42)'; ctx.lineWidth = dpr;
    ctx.beginPath();
    for (const ring of landRings()) this._line(ring, R, cx, cy);
    ctx.stroke();

    this.scr = [];
    for (const p of this.points) {
      const pr = project(p.lat, p.lng, this.rot, R);
      if (!pr.vis) continue;
      const x = cx + pr.x, y = cy + pr.y;
      const lvl = p.atm >= this.th.high ? 'high' : p.atm >= this.th.low ? 'mid' : 'low';
      const r = (1.5 + Math.min(p.size !== undefined ? p.size : p.atm, 0.5) * 8) * dpr * (1 + 0.25 * (this.zoom - 1));
      ctx.globalAlpha = 0.45 + 0.55 * pr.z;
      ctx.fillStyle = COLORS[lvl];
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      if (lvl === 'high') {
        ctx.globalAlpha = (0.35 - 0.3 * (this.pulse / 2)) * pr.z;
        ctx.strokeStyle = COLORS.high; ctx.lineWidth = dpr;
        ctx.beginPath(); ctx.arc(x, y, r * (1.6 + this.pulse), 0, Math.PI * 2); ctx.stroke();
      }
      this.scr.push({ x, y, p });
    }
    ctx.globalAlpha = 1;
  }

  start() {
    if (this.running) return;
    this.running = true;
    const step = t => {
      if (!this.running) return;
      requestAnimationFrame(step);
      if ((typeof document !== 'undefined' && document.hidden) || !this.inView || t - this.last < 50) return;
      const dt = Math.min((t - this.last) / 1000, 0.2);
      this.last = t;
      this.pulse = (t / 1000) % 2;
      if (this.target) {
        let dl = ((this.target.lng - this.rot.lng + 540) % 360) - 180;
        this.rot.lng += dl * 0.15; this.rot.lat += (this.target.lat - this.rot.lat) * 0.15;
        if (Math.abs(dl) < 0.3 && Math.abs(this.target.lat - this.rot.lat) < 0.3) this.target = null;
      } else if (!this.drag) {
        this.rot.lng += 4 * dt;
      }
      this.draw();
    };
    requestAnimationFrame(step);
  }

  stop() { this.running = false; }
}
