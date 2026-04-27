"""
Car Factory 3D Walkthrough Viewer

Reads all PLY mesh files from car_factory_scene/meshes/, merges them into
a single OBJ file, then serves an HTML page with Three.js first-person
navigation (WASD + mouse look). gNBs and UEs from config.json are rendered
as 3D markers inside the scene.

Usage:
    python factory_viewer.py          # serves on port 8889
    python factory_viewer.py --port 9000
"""

import os, struct, json, argparse
import http.server, socketserver, threading, webbrowser

SCENE_DIR = "car_factory_scene"
MESH_DIR  = os.path.join(SCENE_DIR, "meshes")
OBJ_FILE  = os.path.join(SCENE_DIR, "factory.obj")
HTML_FILE = os.path.join(SCENE_DIR, "index.html")

# ── PLY → OBJ exporter ────────────────────────────────────────────────────────

def _read_ply(path):
    """Read a binary little-endian PLY (x,y,z,u,v + face list) → verts, faces."""
    with open(path, "rb") as f:
        # parse header
        n_verts = n_faces = 0
        while True:
            line = b""
            while True:
                c = f.read(1)
                if c == b"\n": break
                line += c
            s = line.decode("ascii").strip()
            if s.startswith("element vertex"):
                n_verts = int(s.split()[-1])
            elif s.startswith("element face"):
                n_faces = int(s.split()[-1])
            elif s == "end_header":
                break
        verts, faces = [], []
        for _ in range(n_verts):
            x, y, z, u, v = struct.unpack("<fffff", f.read(20))
            verts.append((x, y, z))
        for _ in range(n_faces):
            n = struct.unpack("B", f.read(1))[0]
            idx = struct.unpack(f"<{n}i", f.read(4 * n))
            faces.append(idx)
    return verts, faces


def export_obj():
    """Merge all PLY files into one OBJ file."""
    all_verts, all_faces = [], []
    offset = 0
    for fname in sorted(os.listdir(MESH_DIR)):
        if not fname.endswith(".ply"):
            continue
        verts, faces = _read_ply(os.path.join(MESH_DIR, fname))
        all_verts.extend(verts)
        for f in faces:
            all_faces.append(tuple(i + offset + 1 for i in f))  # OBJ is 1-indexed
        offset += len(verts)

    with open(OBJ_FILE, "w") as f:
        f.write("# Car Factory — merged geometry\n")
        for x, y, z in all_verts:
            f.write(f"v {x:.4f} {z:.4f} {y:.4f}\n")  # swap y↔z for Three.js (y-up)
        for face in all_faces:
            f.write("f " + " ".join(str(i) for i in face) + "\n")

    print(f"Exported {len(all_verts):,} vertices, {len(all_faces):,} faces → {OBJ_FILE}")
    return OBJ_FILE


# ── HTML viewer ───────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Car Factory — 3D Walkthrough</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#111; overflow:hidden; font-family:monospace; color:#eee; }
  #info {
    position:absolute; top:12px; left:50%; transform:translateX(-50%);
    background:rgba(0,0,0,.6); padding:8px 18px; border-radius:6px;
    text-align:center; pointer-events:none; z-index:10;
  }
  #crosshair {
    position:absolute; top:50%; left:50%;
    transform:translate(-50%,-50%);
    width:16px; height:16px; pointer-events:none; opacity:.7;
  }
  #crosshair::before, #crosshair::after {
    content:''; position:absolute; background:#fff;
  }
  #crosshair::before { width:2px; height:100%; left:50%; transform:translateX(-50%); }
  #crosshair::after  { height:2px; width:100%; top:50%;  transform:translateY(-50%); }
  #overlay {
    position:absolute; inset:0; background:rgba(0,0,0,.75);
    display:flex; flex-direction:column;
    align-items:center; justify-content:center; z-index:20;
  }
  #overlay h2 { font-size:1.6rem; margin-bottom:12px; }
  #overlay p  { margin:4px 0; font-size:.95rem; color:#aaa; }
  #overlay button {
    margin-top:20px; padding:10px 28px; font-size:1rem;
    background:#2a7; border:none; border-radius:6px; cursor:pointer; color:#fff;
  }
  #loading { position:absolute; bottom:16px; left:50%;
             transform:translateX(-50%); font-size:.85rem; color:#888; }
</style>
</head>
<body>
<div id="overlay">
  <h2>🏭 Car Factory — 3D Walkthrough</h2>
  <p>WASD / Arrow keys — Move</p>
  <p>Mouse — Look around</p>
  <p>Shift — Run &nbsp;|&nbsp; Space / C — Up / Down</p>
  <p>Esc — Release cursor</p>
  <button onclick="startWalk()">Enter Factory</button>
</div>
<div id="crosshair"></div>
<div id="info">Car Factory &nbsp;|&nbsp; 250 m × 160 m &nbsp;|&nbsp; 4 buildings &nbsp;|&nbsp;
  <span style="color:#ff6633">&#9632; gNB</span> &nbsp;
  <span style="color:#ff4444">&#9679; AGV</span> &nbsp;
  <span style="color:#ffaa00">&#9679; Robotic Arm</span> &nbsp;
  <span style="color:#aa44ff">&#9679; Vision Camera</span> &nbsp;
  <span style="color:#ff44aa">&#9679; Safety Sensor</span> &nbsp;
  <span style="color:#44ffaa">&#9679; Worker Tablet</span>
</div>
<div id="loading">Loading geometry…</div>

<script type="importmap">
{
  "imports": {
    "three":              "https://cdn.jsdelivr.net/npm/three@0.163/build/three.module.js",
    "three/addons/":      "https://cdn.jsdelivr.net/npm/three@0.163/examples/jsm/"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';

// ── Scene setup ──────────────────────────────────────────────────────────────
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87ceeb);
scene.fog = new THREE.FogExp2(0xd0e8f0, 0.003);

const camera = new THREE.PerspectiveCamera(75, innerWidth / innerHeight, 0.1, 2000);
camera.position.set(125, 1.7, -80);   // start outside, looking at factory

// ── Lighting ─────────────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.7));

const sun = new THREE.DirectionalLight(0xfff5e0, 1.2);
sun.position.set(100, 200, 50);
sun.castShadow = true;
scene.add(sun);

// Interior point lights (one per building area)
[
  [42, 6, 45], [147, 5, 47], [227, 4.5, 40], [125, 5, 127]
].forEach(([x, y, z]) => {
  const l = new THREE.PointLight(0xffe8c0, 1.5, 80);
  l.position.set(x, y, z);
  scene.add(l);
});

// ── gNB / UE markers (injected from config.json) ─────────────────────────────
const GNB_POSITIONS = __GNB_POSITIONS__;
const UE_POSITIONS  = __UE_POSITIONS__;
const UE_TYPES      = __UE_TYPES__;

const UE_TYPE_COLOR = {
  agv:           0xff4444,
  robotic_arm:   0xffaa00,
  vision_camera: 0xaa44ff,
  safety_sensor: 0xff44aa,
  worker_tablet: 0x44ffaa,
  unknown:       0x888888,
};
const UE_TYPE_LABEL = {
  agv:           'AGV',
  robotic_arm:   'Arm',
  vision_camera: 'Cam',
  safety_sensor: 'Safe',
  worker_tablet: 'Tab',
  unknown:       'UE',
};

// gNB: orange pole (cylinder) + antenna box on top
const gnbPole = new THREE.CylinderGeometry(0.15, 0.15, 3.0, 8);
const gnbHead = new THREE.BoxGeometry(0.6, 0.4, 0.25);
const gnbMatPole = new THREE.MeshLambertMaterial({ color: 0x888888 });
const gnbMatHead = new THREE.MeshLambertMaterial({ color: 0xff6633, emissive: 0x441100 });

GNB_POSITIONS.forEach(([x, y, z], i) => {
  const pole = new THREE.Mesh(gnbPole, gnbMatPole);
  pole.position.set(x, y - 1.5, z);   // pole hangs down 3m from mount
  scene.add(pole);
  const head = new THREE.Mesh(gnbHead, gnbMatHead);
  head.position.set(x, y, z);
  scene.add(head);

  // label
  const canvas = document.createElement('canvas');
  canvas.width = 128; canvas.height = 40;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.roundRect(2, 2, 124, 36, 6);
  ctx.fill();
  ctx.fillStyle = '#ff9966';
  ctx.font = 'bold 20px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(`gNB-${i}`, 64, 26);
  const tex = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sprite.scale.set(3, 1, 1);
  sprite.position.set(x, y + 0.8, z);
  scene.add(sprite);

  // beacon glow
  const light = new THREE.PointLight(0xff6633, 0.8, 20);
  light.position.set(x, y, z);
  scene.add(light);
});

// UE: sphere colored by type, label only shown when close
const ueGeo = new THREE.SphereGeometry(0.3, 10, 8);
const ueMeshes = [];

UE_POSITIONS.forEach(([x, y, z], i) => {
  const ueType  = UE_TYPES[i] || 'unknown';
  const color   = UE_TYPE_COLOR[ueType] ?? 0x888888;
  const label   = UE_TYPE_LABEL[ueType] ?? 'UE';
  const mat     = new THREE.MeshLambertMaterial({ color });
  const sphere  = new THREE.Mesh(ueGeo, mat);
  sphere.position.set(x, y, z);
  scene.add(sphere);
  ueMeshes.push(sphere);

  const canvas = document.createElement('canvas');
  canvas.width = 112; canvas.height = 36;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.roundRect(2, 2, 108, 32, 5);
  ctx.fill();
  const hex = '#' + color.toString(16).padStart(6, '0');
  ctx.fillStyle = hex;
  ctx.font = 'bold 15px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(`${label}-${i}`, 56, 23);
  const tex = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sprite.scale.set(2.5, 0.8, 1);
  sprite.position.set(x, y + 0.7, z);
  scene.add(sprite);
});

// ── Load OBJ ─────────────────────────────────────────────────────────────────
const mat = new THREE.MeshLambertMaterial({
  color: 0xc8c0b0,
  side: THREE.DoubleSide,
  wireframe: false,
});

new OBJLoader().load(
  'factory.obj',
  (obj) => {
    obj.traverse(child => {
      if (child.isMesh) {
        child.material = mat;
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });
    scene.add(obj);
    document.getElementById('loading').textContent = 'Geometry loaded. Click "Enter Factory" to start.';
  },
  xhr => {
    const pct = xhr.total ? Math.round(xhr.loaded / xhr.total * 100) : '…';
    document.getElementById('loading').textContent = `Loading… ${pct}%`;
  },
  err => console.error(err)
);

// ── First-person controls ─────────────────────────────────────────────────────
const controls = new PointerLockControls(camera, renderer.domElement);
scene.add(controls.getObject());

window.startWalk = () => controls.lock();

controls.addEventListener('lock',   () => document.getElementById('overlay').style.display = 'none');
controls.addEventListener('unlock', () => document.getElementById('overlay').style.display = 'flex');

// ── Movement ──────────────────────────────────────────────────────────────────
const keys = {};
addEventListener('keydown', e => keys[e.code] = true);
addEventListener('keyup',   e => keys[e.code] = false);

const velocity = new THREE.Vector3();
const dir      = new THREE.Vector3();
let prev = performance.now();

function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt  = Math.min((now - prev) / 1000, 0.05);
  prev = now;

  const speed = keys['ShiftLeft'] || keys['ShiftRight'] ? 20 : 7;

  if (controls.isLocked) {
    velocity.x -= velocity.x * 10 * dt;
    velocity.z -= velocity.z * 10 * dt;
    velocity.y -= velocity.y * 10 * dt;

    const fwd  = (keys['KeyW'] || keys['ArrowUp'])    ? 1 : 0;
    const back = (keys['KeyS'] || keys['ArrowDown'])  ? 1 : 0;
    const left = (keys['KeyA'] || keys['ArrowLeft'])  ? 1 : 0;
    const rgt  = (keys['KeyD'] || keys['ArrowRight']) ? 1 : 0;
    const up   = keys['Space']  ? 1 : 0;
    const dn   = keys['KeyC']   ? 1 : 0;

    dir.z = fwd - back;
    dir.x = rgt - left;
    dir.y = up  - dn;
    dir.normalize();

    velocity.z -= dir.z * speed * 20 * dt;
    velocity.x -= dir.x * speed * 20 * dt;
    velocity.y += dir.y * speed * 20 * dt;

    controls.moveRight(-velocity.x * dt);
    controls.moveForward(-velocity.z * dt);
    controls.getObject().position.y += velocity.y * dt;

    // Floor clamp
    if (controls.getObject().position.y < 1.7)
      controls.getObject().position.y = 1.7;
  }

  renderer.render(scene, camera);
}
animate();

// ── Resize ────────────────────────────────────────────────────────────────────
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
</script>
</body>
</html>
"""

# ── HTTP server ───────────────────────────────────────────────────────────────

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SCENE_DIR, **kw)
    def log_message(self, *_):
        pass  # suppress request logs


def _load_markers():
    """Load gNB/UE positions and UE types from config.json, swapping y↔z for Three.js y-up."""
    cfg_path = "config.json"
    if not os.path.exists(cfg_path):
        return [], [], []
    with open(cfg_path) as f:
        cfg = json.load(f)
    def swap(pos):
        x, y, z = pos[0], pos[1], pos[2]
        return [x, z, y]   # Three.js: x=x, y=z(height), z=y
    gnbs     = [swap(p) for p in cfg.get("transmitters", [])]
    ues      = [swap(p) for p in cfg.get("static_receivers", [])]
    ue_types = cfg.get("ue_types", ["unknown"] * len(ues))
    return gnbs, ues, ue_types


def serve(port=8889):
    export_obj()
    gnbs, ues, ue_types = _load_markers()
    html = HTML_TEMPLATE \
        .replace("__GNB_POSITIONS__", json.dumps(gnbs)) \
        .replace("__UE_POSITIONS__",  json.dumps(ues)) \
        .replace("__UE_TYPES__",      json.dumps(ue_types))
    with open(HTML_FILE, "w") as f:
        f.write(html)
    print(f"\nFactory viewer ready!")
    print(f"  Serving from : {os.path.abspath(SCENE_DIR)}/")
    print(f"  Open in browser : http://localhost:{port}/")
    print(f"  gNBs visualized : {len(gnbs)}  |  UEs visualized : {len(ues)}")
    print(f"\n  Controls:")
    print(f"    WASD / Arrows — move    Shift — run")
    print(f"    Mouse — look around     Space/C — up/down")
    print(f"    Esc — release cursor")
    print(f"\nPress Ctrl+C to stop.\n")
    with socketserver.TCPServer(("", port), _Handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8889)
    serve(ap.parse_args().port)
