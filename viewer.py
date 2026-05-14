"""
Factory ISAC Viewer

Reads factory_layout.json, uegnb.json, isac_results.json (optional) and
serves a Three.js 3D viewer on http://localhost:8889

Toggles (buttons + keyboard shortcuts):
  F — Factory (walls, floor, objects)
  R — Roof
  I — ISAC sensing overlay

Usage:
    python viewer.py
    python viewer.py --port 9000
"""

import json, os, argparse, http.server, socketserver

PORT = 8889

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Factory ISAC Viewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #111; overflow: hidden; font-family: 'Courier New', monospace; }
canvas { display: block; }
#hud {
  position: absolute; top: 14px; left: 14px;
  color: #aabbcc; font-size: 12px; line-height: 1.7;
  pointer-events: none; text-shadow: 0 0 6px #000;
}
#hud b { color: #ddeeff; }
#toggles {
  position: absolute; bottom: 18px; right: 18px;
  display: flex; flex-direction: column; gap: 7px;
}
.btn {
  padding: 8px 20px; border: 1.5px solid transparent;
  border-radius: 5px; cursor: pointer;
  font-family: 'Courier New', monospace; font-size: 12px; font-weight: bold;
  letter-spacing: 0.05em; transition: all 0.12s;
  min-width: 120px; text-align: center;
}
.btn.on  { background: #1a4a3a; border-color: #4aaa88; color: #88ffcc; }
.btn.off { background: #1e1e28; border-color: #445; color: #668; }
.btn:hover { filter: brightness(1.2); }
#status { position: absolute; top: 14px; right: 18px; color: #556; font-size: 11px; }
</style>
</head>
<body>
<div id="hud">
  <b>Factory ISAC Viewer</b><br>
  Drag: orbit &nbsp;·&nbsp; Scroll: zoom &nbsp;·&nbsp; Right-drag: pan<br>
  Shortcuts: <b>F</b> factory &nbsp;<b>R</b> roof &nbsp;<b>I</b> ISAC<br>
  <br>
  <span id="info">Loading…</span>
</div>
<div id="status" id="status"></div>
<div id="toggles">
  <button class="btn on"  id="btnFactory" onclick="toggle('factory')">&#x25FC; Factory [F]</button>
  <button class="btn off" id="btnRoof"    onclick="toggle('roof')">&#x25B2; Roof [R]</button>
  <button class="btn off" id="btnISAC"    onclick="toggle('isac')">&#x25CB; ISAC [I]</button>
</div>

<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── Data injected by server ────────────────────────────────────────────────────
const LAYOUT = __LAYOUT__;
const UEGNB  = __UEGNB__;
const ISAC   = __ISAC__;

// ── Renderer ───────────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x141820);

const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 2000);
camera.position.set(30, 52, -28);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(30, 2, 20);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.update();

// ── Lights ─────────────────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const sun = new THREE.DirectionalLight(0xffeedd, 0.9);
sun.position.set(40, 60, -10);
scene.add(sun);
const fill = new THREE.DirectionalLight(0xccddff, 0.3);
fill.position.set(-20, 20, 40);
scene.add(fill);

// ── Coordinate transform ───────────────────────────────────────────────────────
// Factory: x=east(0..60), y=north(0..40), z=up(0..7)
// Three.js y-up: T.x = F.x, T.y = F.z (height), T.z = F.y (depth)
function f2t(fx, fy, fz) { return new THREE.Vector3(fx, fz, fy); }

// ── Scene groups ───────────────────────────────────────────────────────────────
const gFactory = new THREE.Group();  // walls, floor, objects
const gRoof    = new THREE.Group();  // roof panel
const gMarkers = new THREE.Group();  // gNBs + UEs (always visible)
const gISAC    = new THREE.Group();  // estimated positions + error lines
[gFactory, gRoof, gMarkers, gISAC].forEach(g => scene.add(g));
gRoof.visible = false;
gISAC.visible = false;

// ── Materials ──────────────────────────────────────────────────────────────────
const matConcrete = new THREE.MeshLambertMaterial({ color: 0x7a8fa0, side: THREE.DoubleSide });
const matFloor    = new THREE.MeshLambertMaterial({ color: 0x2d3d4d });
const matMetal    = new THREE.MeshLambertMaterial({ color: 0x8fa8a0, side: THREE.DoubleSide });
const matRoof     = new THREE.MeshLambertMaterial({ color: 0x3a4f60, side: THREE.DoubleSide, transparent: true, opacity: 0.55 });
const matGNB      = new THREE.MeshLambertMaterial({ color: 0xffdd33 });
const matUE       = new THREE.MeshLambertMaterial({ color: 0x44ff99 });
const matEst      = new THREE.MeshLambertMaterial({ color: 0x00ddff });
const matLine     = new THREE.LineBasicMaterial({ color: 0xff4422 });
const matGrid     = new THREE.LineBasicMaterial({ color: 0x1e2d3d, transparent: true, opacity: 0.7 });

// ── Geometry helpers ───────────────────────────────────────────────────────────
function quad(a, b, c, d, mat, grp) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
    a.x,a.y,a.z,  b.x,b.y,b.z,  c.x,c.y,c.z,
    a.x,a.y,a.z,  c.x,c.y,c.z,  d.x,d.y,d.z,
  ]), 3));
  geo.computeVertexNormals();
  grp.add(new THREE.Mesh(geo, mat));
}

// Horizontal panel at factory height fz
function hPanel(x0, x1, y0, y1, fz, mat, grp) {
  quad(f2t(x0,y0,fz), f2t(x1,y0,fz), f2t(x1,y1,fz), f2t(x0,y1,fz), mat, grp);
}

// Vertical wall panel along X (south/north face)
function xWallSeg(xa, xb, fy, za, zb, north, mat, grp) {
  if (north) {
    quad(f2t(xb,fy,zb), f2t(xb,fy,za), f2t(xa,fy,za), f2t(xa,fy,zb), mat, grp);
  } else {
    quad(f2t(xa,fy,zb), f2t(xa,fy,za), f2t(xb,fy,za), f2t(xb,fy,zb), mat, grp);
  }
}

// Vertical wall panel along Y (west/east face)
function yWallSeg(fx, ya, yb, za, zb, east, mat, grp) {
  if (east) {
    quad(f2t(fx,ya,zb), f2t(fx,ya,za), f2t(fx,yb,za), f2t(fx,yb,zb), mat, grp);
  } else {
    quad(f2t(fx,yb,zb), f2t(fx,yb,za), f2t(fx,ya,za), f2t(fx,ya,zb), mat, grp);
  }
}

// Split range [s,e] at door openings
function splitDoors(s, e, doors) {
  const gaps = (doors || []).map(d => [d.c - d.w/2, d.c + d.w/2, d.h])
    .sort((a, b) => a[0] - b[0]);
  const segs = [];
  let prev = s;
  for (const [da, db, dh] of gaps) {
    if (prev < da - 1e-6) segs.push([false, prev, da, 0]);
    segs.push([true, da, db, dh]);
    prev = db;
  }
  if (prev < e - 1e-6) segs.push([false, prev, e, 0]);
  return segs;
}

// ── Build factory ──────────────────────────────────────────────────────────────
const bld = LAYOUT.building;
const { x0, x1, y0, y1 } = bld;
const H = bld.height;
const doors = bld.doors || {};

// Floor
hPanel(x0, x1, y0, y1, 0, matFloor, gFactory);

// Grid lines on floor
{
  const pts = [];
  for (let xi = x0; xi <= x1 + 0.1; xi += 5) {
    pts.push(f2t(xi, y0, 0.015), f2t(xi, y1, 0.015));
  }
  for (let yi = y0; yi <= y1 + 0.1; yi += 5) {
    pts.push(f2t(x0, yi, 0.015), f2t(x1, yi, 0.015));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  gFactory.add(new THREE.LineSegments(geo, matGrid));
}

// South wall (y=y0, splits along x)
for (const [gap, a, b, dh] of splitDoors(x0, x1, doors.south)) {
  if (gap) { if (dh < H) xWallSeg(a, b, y0, dh, H, false, matConcrete, gFactory); }
  else xWallSeg(a, b, y0, 0, H, false, matConcrete, gFactory);
}
// North wall (y=y1)
for (const [gap, a, b, dh] of splitDoors(x0, x1, doors.north)) {
  if (gap) { if (dh < H) xWallSeg(a, b, y1, dh, H, true, matConcrete, gFactory); }
  else xWallSeg(a, b, y1, 0, H, true, matConcrete, gFactory);
}
// West wall (x=x0, splits along y)
for (const [gap, a, b, dh] of splitDoors(y0, y1, doors.west)) {
  if (gap) { if (dh < H) yWallSeg(x0, a, b, dh, H, false, matConcrete, gFactory); }
  else yWallSeg(x0, a, b, 0, H, false, matConcrete, gFactory);
}
// East wall (x=x1)
for (const [gap, a, b, dh] of splitDoors(y0, y1, doors.east)) {
  if (gap) { if (dh < H) yWallSeg(x1, a, b, dh, H, true, matConcrete, gFactory); }
  else yWallSeg(x1, a, b, 0, H, true, matConcrete, gFactory);
}

// Roof
hPanel(x0, x1, y0, y1, H, matRoof, gRoof);

// Objects
for (const obj of (LAYOUT.objects || [])) {
  const m = obj.material === 'metal' ? matMetal : matConcrete;
  const oh = obj.height;
  hPanel(obj.x0, obj.x1, obj.y0, obj.y1, 0,  m, gFactory);
  hPanel(obj.x0, obj.x1, obj.y0, obj.y1, oh, m, gFactory);
  xWallSeg(obj.x0, obj.x1, obj.y0, 0, oh, false, m, gFactory);
  xWallSeg(obj.x0, obj.x1, obj.y1, 0, oh, true,  m, gFactory);
  yWallSeg(obj.x0, obj.y0, obj.y1, 0, oh, false, m, gFactory);
  yWallSeg(obj.x1, obj.y0, obj.y1, 0, oh, true,  m, gFactory);
}

// ── gNBs ──────────────────────────────────────────────────────────────────────
{
  const geo = new THREE.OctahedronGeometry(0.55);
  for (const g of UEGNB.gnbs) {
    const mesh = new THREE.Mesh(geo, matGNB);
    mesh.position.copy(f2t(...g.pos));
    gMarkers.add(mesh);
  }
}

// ── UEs ───────────────────────────────────────────────────────────────────────
{
  const geo = new THREE.SphereGeometry(0.45, 10, 7);
  for (const u of UEGNB.ues) {
    const mesh = new THREE.Mesh(geo, matUE);
    mesh.position.copy(f2t(...u.pos));
    gMarkers.add(mesh);
  }
}

// ── ISAC overlay ──────────────────────────────────────────────────────────────
function textSprite(text) {
  const cvs = document.createElement('canvas');
  cvs.width = 140; cvs.height = 50;
  const ctx = cvs.getContext('2d');
  ctx.fillStyle = 'rgba(0,16,24,0.75)';
  ctx.roundRect(2, 2, 136, 46, 6);
  ctx.fill();
  ctx.fillStyle = '#00ddff';
  ctx.font = 'bold 22px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 70, 26);
  const tex = new THREE.CanvasTexture(cvs);
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  spr.scale.set(3.5, 1.3, 1);
  return spr;
}

if (ISAC && ISAC.ue_localization) {
  const estGeo = new THREE.OctahedronGeometry(0.6);
  const LIFT = 2.5;  // raise ISAC markers above UEs so they're visible even at 0 error
  for (const loc of ISAC.ue_localization) {
    if (!loc.est_pos) continue;
    const [ex, ey, ez] = loc.est_pos;
    const [tx, ty, tz] = loc.true_pos;

    // Cyan octahedron raised above estimated position
    const estMesh = new THREE.Mesh(estGeo, matEst);
    estMesh.position.copy(f2t(ex, ey, ez + LIFT));
    gISAC.add(estMesh);

    // Drop line from raised marker down to true position
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
      f2t(tx, ty, tz), f2t(ex, ey, ez + LIFT)
    ]);
    gISAC.add(new THREE.Line(lineGeo, matLine));

    // Label above marker
    const errText = loc.error_m != null ? `${loc.error_m.toFixed(2)}m` : '?';
    const spr = textSprite(`UE-${loc.ue_idx} ${errText}`);
    spr.position.copy(f2t(ex, ey, ez + LIFT + 1.4));
    gISAC.add(spr);
  }
}

// ── Info panel ─────────────────────────────────────────────────────────────────
{
  const el = document.getElementById('info');
  let s = `${UEGNB.gnbs.length} gNBs &nbsp;·&nbsp; ${UEGNB.ues.length} UEs`
        + ` &nbsp;·&nbsp; <b>${UEGNB.frequency_ghz} GHz</b> / ${UEGNB.bandwidth_mhz} MHz`;
  if (ISAC) {
    const n = ISAC.ue_localization.filter(r => r.est_pos).length;
    const e = ISAC.mean_error_m != null ? ` &nbsp;·&nbsp; mean err <b>${ISAC.mean_error_m} m</b>` : '';
    s += `<br>ISAC: <b>${n}/${ISAC.n_ues}</b> localized${e}`;
  } else {
    s += `<br>ISAC: no results yet — run sionna.py first`;
  }
  el.innerHTML = s;
}

// ── Toggles ────────────────────────────────────────────────────────────────────
const state = { factory: true, roof: false, isac: false };

function toggle(which) {
  state[which] = !state[which];
  const id = 'btn' + which[0].toUpperCase() + which.slice(1);
  document.getElementById(id).className = 'btn ' + (state[which] ? 'on' : 'off');
  if (which === 'factory') gFactory.visible = state.factory;
  if (which === 'roof')    gRoof.visible    = state.roof;
  if (which === 'isac')    gISAC.visible    = state.isac;
}
window.toggle = toggle;  // expose for onclick= attributes in HTML

document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase();
  if (k === 'f') toggle('factory');
  if (k === 'r') toggle('roof');
  if (k === 'i') toggle('isac');
});

// ── Resize ─────────────────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ── Render loop ────────────────────────────────────────────────────────────────
(function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
})();
</script>
</body>
</html>
"""


def serve(port=PORT):
    with open("factory_layout.json") as f:
        layout = json.load(f)
    with open("uegnb.json") as f:
        uegnb = json.load(f)

    isac = None
    if os.path.exists("isac_results.json"):
        with open("isac_results.json") as f:
            isac = json.load(f)
        n = isac.get("n_localized", "?")
        total = isac.get("n_ues", "?")
        err = isac.get("mean_error_m", "?")
        print(f"ISAC results: {n}/{total} localized, mean err {err} m")
    else:
        print("No isac_results.json — ISAC overlay disabled (run sionna.py first)")

    html = (_HTML
            .replace("__LAYOUT__", json.dumps(layout))
            .replace("__UEGNB__",  json.dumps(uegnb))
            .replace("__ISAC__",   json.dumps(isac) if isac else "null"))
    html_bytes = html.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html_bytes)

        def log_message(self, *_):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"Viewer → http://localhost:{port}   (Ctrl-C to stop)")
        httpd.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    serve(parser.parse_args().port)
