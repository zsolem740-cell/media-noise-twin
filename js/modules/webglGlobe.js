/* Média-Zaj Twin v38 – 3D glóbusz (Three.js, InstancedMesh).
   A hírek helyszíneit egyetlen InstancedMesh jeleníti meg (egy rajzolási hívás, GPU-n), ezért a telefonon is
   folyékony. Érintés: húzás = forgatás (tehetetlenséggel), csíptetés = nagyítás, koppintás = kijelölés.
   Ha a Three.js nem tölthető be vagy nincs WebGL, 2D-s tartalék glóbusz rajzol ugyanazzal a kezelőfelülettel. */

const D2R = Math.PI / 180;

/* lat/lon → egységgömb pont. lon = 0 a +z irányba néz (a kamera felé). */
export function latLonToVec3(lat, lon, r = 1) {
  const p = lat * D2R, l = lon * D2R;
  return [r * Math.cos(p) * Math.sin(l), r * Math.sin(p), r * Math.cos(p) * Math.cos(l)];
}

/* ATM → szín (zöld → borostyán → piros). th = {mid, high} a szerver küszöbei. */
export function atmColor(atm, th = { mid: 0.12, high: 0.25 }) {
  const lerp = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
  const G = [0.20, 0.83, 0.60], Y = [0.96, 0.62, 0.04], R = [0.94, 0.27, 0.27];
  const v = Math.max(0, atm || 0);
  if (v <= th.mid) return lerp(G, Y, v / th.mid);
  return lerp(Y, R, Math.min(1, (v - th.mid) / Math.max(1e-6, th.high - th.mid)));
}
export const rgbCss = (c) => `rgb(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)})`;

/* Azonos helyszínű cikkek: kis spirálba rendezve, hogy ne fedjék egymást. Visszatér: [{...pont, lat, lon}] */
export function spread(points) {
  const seen = new Map();
  return points.map((p) => {
    const key = p.lat.toFixed(2) + "," + p.lon.toFixed(2), k = seen.get(key) || 0;
    seen.set(key, k + 1);
    if (!k) return { ...p };
    const rad = 0.28 * Math.sqrt(k), ang = k * 2.39996;
    return { ...p, lat: p.lat + rad * Math.sin(ang), lon: p.lon + rad * Math.cos(ang) / Math.max(0.2, Math.cos(p.lat * D2R)) };
  });
}

/* Forgatás után a pont képernyő-koordinátája (ortografikus): visszaad [x, y, mélység(+ = előtte)] */
export function project(lat, lon, rotY, rotX) {
  const [x, y, z] = latLonToVec3(lat, lon);
  const cy = Math.cos(rotY), sy = Math.sin(rotY);
  const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
  const cx = Math.cos(rotX), sx = Math.sin(rotX);
  return [x1, y * cx - z1 * sx, y * sx + z1 * cx];
}

function webglOk() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch (e) { return false; }
}

export async function createGlobe(container, { onPick = () => {}, focus = [47, 16.6], thresholds, forceFallback = false } = {}) {
  let THREE = null;
  if (!forceFallback && webglOk()) {
    try { THREE = await import("three"); } catch (e) { THREE = null; }
  }
  return THREE ? createWebgl(THREE, container, { onPick, focus, thresholds }) : createFallback(container, { onPick, focus, thresholds });
}

/* ───────────────────────── WebGL ───────────────────────── */
function createWebgl(THREE, container, { onPick, focus, thresholds }) {
  const MAX = 2048;
  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.domElement.className = "globe-canvas";
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
  let zoom = 3.4;
  camera.position.set(0, 0, zoom);
  const globe = new THREE.Group();
  globe.rotation.order = "XYZ";
  scene.add(globe);

  globe.add(new THREE.Mesh(new THREE.SphereGeometry(1, 48, 32), new THREE.MeshBasicMaterial({ color: 0x050b1c })));
  globe.add(new THREE.Mesh(new THREE.SphereGeometry(1.035, 40, 28), new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.10, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false })));
  const g = [], e = [];
  for (let la = -80; la <= 80; la += 20) {
    for (let lo = 0; lo < 360; lo += 6) { const a = latLonToVec3(la, lo, 1.002), b = latLonToVec3(la, lo + 6, 1.002); (la === 0 ? e : g).push(...a, ...b); }
  }
  for (let lo = 0; lo < 360; lo += 20) {
    for (let la = -90; la < 90; la += 6) { g.push(...latLonToVec3(la, lo, 1.002), ...latLonToVec3(la + 6, lo, 1.002)); }
  }
  const lineGeo = (arr) => { const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(arr, 3)); return geo; };
  globe.add(new THREE.LineSegments(lineGeo(g), new THREE.LineBasicMaterial({ color: 0x2563eb, transparent: true, opacity: 0.28 })));
  globe.add(new THREE.LineSegments(lineGeo(e), new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.5 })));
  const ring = [];
  for (let a = 0; a < 360; a += 10) { const r = 3.2, p = [focus[0] + r * Math.sin(a * D2R), focus[1] + r * Math.cos(a * D2R) / Math.cos(focus[0] * D2R)], q = [focus[0] + r * Math.sin((a + 10) * D2R), focus[1] + r * Math.cos((a + 10) * D2R) / Math.cos(focus[0] * D2R)]; ring.push(...latLonToVec3(p[0], p[1], 1.004), ...latLonToVec3(q[0], q[1], 1.004)); }
  globe.add(new THREE.LineSegments(lineGeo(ring), new THREE.LineBasicMaterial({ color: 0x8b5cf6 })));

  const stars = [];
  for (let i = 0; i < 360; i++) { const u = Math.random() * 2 - 1, t = Math.random() * 6.2832, s = Math.sqrt(1 - u * u); stars.push(9 * s * Math.cos(t), 9 * u, 9 * s * Math.sin(t)); }
  scene.add(new THREE.Points(lineGeo(stars), new THREE.PointsMaterial({ color: 0x9fb4d8, size: 0.03, transparent: true, opacity: 0.7 })));

  const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 8, 6), new THREE.MeshBasicMaterial(), MAX);
  mesh.frustumCulled = false; mesh.count = 0;
  globe.add(mesh);
  const sel = new THREE.Mesh(new THREE.SphereGeometry(1, 14, 10), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35, depthWrite: false }));
  sel.visible = false; globe.add(sel);

  let pts = [], rotY = 0, rotX = 0, vY = 0, vX = 0, autoRotate = true, idleSince = performance.now(), dirty = true, alive = true, selected = null;
  const tmp = new THREE.Object3D(), col = new THREE.Color();
  const setView = (lat, lon) => { rotY = -lon * D2R; rotX = lat * D2R; dirty = true; };
  setView(focus[0], focus[1]);

  function setPoints(list, th = thresholds) {
    pts = spread(list).slice(0, MAX);
    pts.forEach((p, i) => {
      const [x, y, z] = latLonToVec3(p.lat, p.lon, 1.012);
      const s = 0.010 + 0.016 * Math.min(1, p.size || 0);
      tmp.position.set(x, y, z); tmp.scale.setScalar(s); tmp.updateMatrix();
      mesh.setMatrixAt(i, tmp.matrix);
      const c = atmColor(p.atm, th); col.setRGB(c[0], c[1], c[2]); mesh.setColorAt(i, col);
    });
    mesh.count = pts.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    if (selected) select(selected);
    dirty = true;
  }
  function select(id) {
    selected = id;
    const p = pts.find((q) => q.id === id);
    if (!p) { sel.visible = false; dirty = true; return; }
    const [x, y, z] = latLonToVec3(p.lat, p.lon, 1.012);
    sel.position.set(x, y, z); sel.scale.setScalar(0.028 + 0.016 * Math.min(1, p.size || 0)); sel.visible = true; dirty = true;
  }
  function focusOn(lat, lon) { setView(lat, lon); idleSince = performance.now(); }

  const v3 = new THREE.Vector3();
  function pickAt(clientX, clientY) {
    const r = renderer.domElement.getBoundingClientRect(), px = clientX - r.left, py = clientY - r.top;
    globe.updateMatrixWorld(); camera.updateMatrixWorld();
    let best = null, bd = 30 * 30;
    for (let i = 0; i < pts.length; i++) {
      const [x, y, z] = latLonToVec3(pts[i].lat, pts[i].lon, 1.012);
      v3.set(x, y, z).applyMatrix4(globe.matrixWorld);
      if (v3.z < 0.25) continue;               // a gömb hátoldalán: nem választható
      v3.project(camera);
      const sx = (v3.x + 1) / 2 * r.width, sy = (1 - v3.y) / 2 * r.height, d = (sx - px) ** 2 + (sy - py) ** 2;
      if (d < bd) { bd = d; best = pts[i]; }
    }
    return best;
  }

  const ptr = new Map(); let down = null, pinch = 0;
  const el = renderer.domElement;
  el.style.touchAction = "none";
  el.addEventListener("pointerdown", (ev) => {
    el.setPointerCapture(ev.pointerId); ptr.set(ev.pointerId, [ev.clientX, ev.clientY]);
    down = { x: ev.clientX, y: ev.clientY, t: performance.now(), moved: 0 }; vX = vY = 0; idleSince = performance.now();
    if (ptr.size === 2) { const [a, b] = [...ptr.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
  });
  el.addEventListener("pointermove", (ev) => {
    if (!ptr.has(ev.pointerId)) return;
    const prev = ptr.get(ev.pointerId); ptr.set(ev.pointerId, [ev.clientX, ev.clientY]); idleSince = performance.now();
    if (ptr.size === 2) {
      const [a, b] = [...ptr.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) { zoom = Math.max(1.9, Math.min(6, zoom * pinch / d)); camera.position.z = zoom; dirty = true; }
      pinch = d; if (down) down.moved = 99; return;
    }
    const dx = ev.clientX - prev[0], dy = ev.clientY - prev[1], k = 0.0052 * zoom / 3.4;
    if (down) down.moved += Math.abs(dx) + Math.abs(dy);
    rotY += dx * k; rotX = Math.max(-1.35, Math.min(1.35, rotX + dy * k)); vY = dx * k; vX = dy * k; dirty = true;
  });
  const up = (ev) => {
    ptr.delete(ev.pointerId); pinch = 0;
    if (down && down.moved < 7 && performance.now() - down.t < 450 && ptr.size === 0) { const p = pickAt(ev.clientX, ev.clientY); if (p) { select(p.id); onPick(p); } }
    if (!ptr.size) down = null;
  };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  el.addEventListener("wheel", (ev) => { ev.preventDefault(); zoom = Math.max(1.9, Math.min(6, zoom * (1 + Math.sign(ev.deltaY) * 0.08))); camera.position.z = zoom; dirty = true; }, { passive: false });

  const resize = () => {
    const w = Math.max(1, container.clientWidth), h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false); el.style.width = w + "px"; el.style.height = h + "px";
    camera.aspect = w / h; camera.updateProjectionMatrix(); dirty = true;
  };
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  if (ro) ro.observe(container); else addEventListener("resize", resize);
  resize();

  renderer.setAnimationLoop(() => {
    if (!alive || document.hidden) return;
    const idle = !ptr.size && performance.now() - idleSince > 4000;
    if (!ptr.size && (Math.abs(vY) > 1e-5 || Math.abs(vX) > 1e-5)) { rotY += vY; rotX = Math.max(-1.35, Math.min(1.35, rotX + vX)); vY *= 0.94; vX *= 0.94; dirty = true; }
    if (autoRotate && idle) { rotY += 0.0016; dirty = true; }
    if (!dirty) return;
    globe.rotation.set(rotX, rotY, 0);
    renderer.render(scene, camera);
    dirty = false;
  });

  return {
    kind: "webgl", setPoints, select, focus: focusOn, setAutoRotate: (b) => { autoRotate = !!b; },
    dispose() { alive = false; renderer.setAnimationLoop(null); if (ro) ro.disconnect(); renderer.dispose(); el.remove(); },
  };
}

/* ───────────────────────── 2D tartalék ───────────────────────── */
function createFallback(container, { onPick, focus, thresholds }) {
  const cv = document.createElement("canvas");
  cv.className = "globe-canvas"; container.appendChild(cv);
  const ctx = cv.getContext("2d");
  let pts = [], rotY = -focus[1] * D2R, rotX = focus[0] * D2R, selected = null, w = 1, h = 1, R = 100, cx = 50, cy = 50, down = null, autoRotate = true, idleSince = performance.now(), alive = true;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = Math.max(1, container.clientWidth); h = Math.max(1, container.clientHeight);
    cv.width = w * dpr; cv.height = h * dpr; cv.style.width = w + "px"; cv.style.height = h + "px"; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    R = Math.min(w, h) * 0.38; cx = w / 2; cy = h / 2; draw();
  };
  const scr = (lat, lon) => { const [x, y, z] = project(lat, lon, rotY, rotX); return [cx + x * R, cy - y * R, z]; };
  function draw() {
    ctx.clearRect(0, 0, w, h);
    const g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.05); g.addColorStop(0, "#0b1530"); g.addColorStop(1, "#050b1c");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.2832); ctx.fill();
    ctx.strokeStyle = "rgba(59,130,246,.3)"; ctx.lineWidth = 1;
    for (let la = -80; la <= 80; la += 20) { ctx.beginPath(); let on = false; for (let lo = 0; lo <= 360; lo += 6) { const [x, y, z] = scr(la, lo); if (z > 0) { on ? ctx.lineTo(x, y) : ctx.moveTo(x, y); on = true; } else on = false; } ctx.stroke(); }
    for (let lo = 0; lo < 360; lo += 20) { ctx.beginPath(); let on = false; for (let la = -90; la <= 90; la += 6) { const [x, y, z] = scr(la, lo); if (z > 0) { on ? ctx.lineTo(x, y) : ctx.moveTo(x, y); on = true; } else on = false; } ctx.stroke(); }
    pts.forEach((p) => {
      const [x, y, z] = scr(p.lat, p.lon); if (z <= 0.05) return;
      const c = atmColor(p.atm, thresholds), r = 2.2 + 3.5 * Math.min(1, p.size || 0);
      ctx.fillStyle = rgbCss(c); ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill();
      if (p.id === selected) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r + 4, 0, 6.2832); ctx.stroke(); }
    });
  }
  cv.style.touchAction = "none";
  cv.addEventListener("pointerdown", (ev) => { cv.setPointerCapture(ev.pointerId); down = { x: ev.clientX, y: ev.clientY, px: ev.clientX, py: ev.clientY, t: performance.now(), moved: 0 }; idleSince = performance.now(); });
  cv.addEventListener("pointermove", (ev) => { if (!down) return; const dx = ev.clientX - down.px, dy = ev.clientY - down.py; down.px = ev.clientX; down.py = ev.clientY; down.moved += Math.abs(dx) + Math.abs(dy); rotY += dx * 0.006; rotX = Math.max(-1.35, Math.min(1.35, rotX + dy * 0.006)); idleSince = performance.now(); draw(); });
  cv.addEventListener("pointerup", (ev) => {
    if (down && down.moved < 7 && performance.now() - down.t < 450) {
      const r = cv.getBoundingClientRect(), px = ev.clientX - r.left, py = ev.clientY - r.top; let best = null, bd = 900;
      pts.forEach((p) => { const [x, y, z] = scr(p.lat, p.lon); if (z > 0.1) { const d = (x - px) ** 2 + (y - py) ** 2; if (d < bd) { bd = d; best = p; } } });
      if (best) { selected = best.id; draw(); onPick(best); }
    }
    down = null;
  });
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
  if (ro) ro.observe(container); else addEventListener("resize", resize);
  resize();
  const timer = setInterval(() => { if (alive && !document.hidden && autoRotate && !down && performance.now() - idleSince > 4000) { rotY += 0.004; draw(); } }, 50);
  return {
    kind: "2d", setPoints(list) { pts = spread(list).slice(0, 2048); draw(); }, select(id) { selected = id; draw(); },
    focus(lat, lon) { rotY = -lon * D2R; rotX = lat * D2R; idleSince = performance.now(); draw(); }, setAutoRotate: (b) => { autoRotate = !!b; },
    dispose() { alive = false; clearInterval(timer); if (ro) ro.disconnect(); cv.remove(); },
  };
}
