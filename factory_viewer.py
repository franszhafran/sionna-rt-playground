"""
Car Factory 3D Walkthrough Viewer

Reads all PLY mesh files from car_factory_scene/meshes/, exports:
  factory.obj      — walls, floors, partitions (no roofs)
  factory_roof.obj — roof panels only (separately toggleable)

Then serves an HTML page with Three.js first-person navigation (WASD + mouse look).
gNBs and UEs from config.json are rendered as 3D markers. If sim_results.json
exists, UE→best-gNB connection lines are rendered (toggleable). Roof is also
independently toggleable.

Usage:
    python factory_viewer.py          # serves on port 8889
    python factory_viewer.py --port 9000
"""

import os, struct, json, argparse, time
import http.server, socketserver, threading, webbrowser

SCENE_DIR      = "car_factory_scene"
MESH_DIR       = os.path.join(SCENE_DIR, "meshes")
OBJ_FILE       = os.path.join(SCENE_DIR, "factory.obj")
OBJ_ROOF_FILE       = os.path.join(SCENE_DIR, "factory_roof.obj")
OBJ_PARTITION_FILE  = os.path.join(SCENE_DIR, "factory_partitions.obj")
HTML_FILE           = os.path.join(SCENE_DIR, "index.html")

# ── PLY → OBJ exporter ────────────────────────────────────────────────────────

def _read_ply(path):
    """Read a binary little-endian PLY (x,y,z,u,v + face list) → verts, faces."""
    with open(path, "rb") as f:
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


def _is_roof(fname):
    return fname.endswith("_roof.ply")


_BLDG_SUFFIXES = (
    '_floor.ply', '_roof.ply',
    '_wall_south.ply', '_wall_north.ply', '_wall_west.ply', '_wall_east.ply',
)

def _is_partition(fname):
    """True for internal partition-wall PLY files (not ground, not building surfaces)."""
    if fname == 'ground.ply':
        return False
    return not any(fname.endswith(s) for s in _BLDG_SUFFIXES)


def export_obj():
    """Merge PLY files into three OBJ files: main geometry, roofs, and partition walls."""
    main_verts, main_faces  = [], []
    roof_verts, roof_faces  = [], []
    part_verts, part_faces  = [], []
    main_off = roof_off = part_off = 0

    for fname in sorted(os.listdir(MESH_DIR)):
        if not fname.endswith(".ply"):
            continue
        verts, faces = _read_ply(os.path.join(MESH_DIR, fname))
        if _is_roof(fname):
            roof_verts.extend(verts)
            for f in faces:
                roof_faces.append(tuple(i + roof_off + 1 for i in f))
            roof_off += len(verts)
        elif _is_partition(fname):
            # Partition walls have both east & west faces in the PLY (needed by Sionna).
            # Export them to a separate OBJ so the viewer can use FrontSide rendering,
            # which lets each winding be visible only from its own side — no z-fighting.
            part_verts.extend(verts)
            for f in faces:
                part_faces.append(tuple(i + part_off + 1 for i in f))
            part_off += len(verts)
        else:
            main_verts.extend(verts)
            for f in faces:
                main_faces.append(tuple(i + main_off + 1 for i in f))
            main_off += len(verts)

    def _write(path, verts, faces, label):
        with open(path, "w") as f:
            f.write(f"# Car Factory — {label}\n")
            for x, y, z in verts:
                f.write(f"v {x:.4f} {z:.4f} {y:.4f}\n")  # swap y↔z for Three.js y-up
            for face in faces:
                f.write("f " + " ".join(str(i) for i in face) + "\n")
        print(f"Exported {len(verts):,} vertices, {len(faces):,} faces → {path}")

    _write(OBJ_FILE,           main_verts, main_faces, "main geometry")
    _write(OBJ_ROOF_FILE,      roof_verts, roof_faces, "roofs")
    _write(OBJ_PARTITION_FILE, part_verts, part_faces, "partition walls")


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
  #toggles {
    position:absolute; bottom:16px; right:16px;
    display:flex; gap:8px; z-index:25;
  }
  #toggles button {
    padding:6px 14px; font-size:.8rem; font-family:monospace;
    background:rgba(0,0,0,.65); border:1px solid #555;
    border-radius:5px; cursor:pointer; color:#ccc;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  #toggles button.active {
    background:rgba(40,160,100,.85); border-color:#2a7; color:#fff;
  }
</style>
</head>
<body>
<div id="overlay">
  <h2>&#127981; Car Factory &#8212; 3D Walkthrough</h2>
  <p>WASD / Arrow keys &#8212; Move</p>
  <p>Mouse &#8212; Look around</p>
  <p>Shift &#8212; Run &nbsp;|&nbsp; Space / C &#8212; Up / Down</p>
  <p>Esc &#8212; Release cursor</p>
  <p style="margin-top:8px;color:#888;">L &#8212; Toggle lines &nbsp;|&nbsp; R &#8212; Toggle roof</p>
  <button onclick="startWalk()">Enter Factory</button>
</div>
<div id="crosshair"></div>
<div id="info">Car Factory &nbsp;|&nbsp; 250 m &times; 160 m &nbsp;|&nbsp; 4 buildings &nbsp;|&nbsp;
  <span style="color:#d0b060">&#9644; Section Wall</span> &nbsp;
  <span style="color:#ff6633">&#9632; gNB</span> &nbsp;
  <span style="color:#ff4444">&#9679; AGV</span> &nbsp;
  <span style="color:#ffaa00">&#9679; Robotic Arm</span> &nbsp;
  <span style="color:#aa44ff">&#9679; Vision Camera</span> &nbsp;
  <span style="color:#ff44aa">&#9679; Safety Sensor</span> &nbsp;
  <span style="color:#44ffaa">&#9679; Worker Tablet</span>
</div>
<div id="toggles">
  <button id="btn-lines" onclick="toggleLines()">Lines: OFF</button>
  <button id="btn-roof"  onclick="toggleRoof()"  class="active">Roof: ON</button>
</div>
<div id="loading">Loading geometry&#8230;</div>

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
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';

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
camera.position.set(35, 3, 127);   // inside Chassis section of General Assembly

// ── Lighting ─────────────────────────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.7));

const sun = new THREE.DirectionalLight(0xfff5e0, 1.2);
sun.position.set(100, 200, 50);
sun.castShadow = true;
scene.add(sun);

[
  [42, 6, 45], [147, 5, 47], [227, 4.5, 40], [125, 5, 127]
].forEach(([x, y, z]) => {
  const l = new THREE.PointLight(0xffe8c0, 1.5, 80);
  l.position.set(x, y, z);
  scene.add(l);
});

// ── gNB / UE data (injected from Python) ─────────────────────────────────────
const GNB_POSITIONS = __GNB_POSITIONS__;
const UE_POSITIONS  = __UE_POSITIONS__;
const UE_TYPES      = __UE_TYPES__;
const BEST_GNB      = __BEST_GNB__;
const SLA_PASS      = __SLA_PASS__;
const BUILDINGS     = __BUILDINGS__;
const V             = '__CACHE_BUST__';   // cache-bust version injected by Python

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

// ── gNB markers ──────────────────────────────────────────────────────────────
const gnbPole = new THREE.CylinderGeometry(0.15, 0.15, 3.0, 8);
const gnbHead = new THREE.BoxGeometry(0.6, 0.4, 0.25);
const gnbMatPole = new THREE.MeshLambertMaterial({ color: 0x888888 });
const gnbMatHead = new THREE.MeshLambertMaterial({ color: 0xff6633, emissive: 0x441100 });

GNB_POSITIONS.forEach(([x, y, z], i) => {
  const pole = new THREE.Mesh(gnbPole, gnbMatPole);
  pole.position.set(x, y - 1.5, z);
  scene.add(pole);
  const head = new THREE.Mesh(gnbHead, gnbMatHead);
  head.position.set(x, y, z);
  scene.add(head);

  const canvas = document.createElement('canvas');
  canvas.width = 128; canvas.height = 40;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.roundRect(2, 2, 124, 36, 6); ctx.fill();
  ctx.fillStyle = '#ff9966';
  ctx.font = 'bold 20px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(`gNB-${i}`, 64, 26);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }));
  sprite.scale.set(3, 1, 1);
  sprite.position.set(x, y + 0.8, z);
  scene.add(sprite);

  const light = new THREE.PointLight(0xff6633, 0.8, 20);
  light.position.set(x, y, z);
  scene.add(light);
});

// ── UE markers ───────────────────────────────────────────────────────────────
const ueGeo = new THREE.SphereGeometry(0.3, 10, 8);

UE_POSITIONS.forEach(([x, y, z], i) => {
  const ueType = UE_TYPES[i] || 'unknown';
  const color  = UE_TYPE_COLOR[ueType] ?? 0x888888;
  const label  = UE_TYPE_LABEL[ueType] ?? 'UE';
  const sphere = new THREE.Mesh(ueGeo, new THREE.MeshLambertMaterial({ color }));
  sphere.position.set(x, y, z);
  scene.add(sphere);

  const canvas = document.createElement('canvas');
  canvas.width = 112; canvas.height = 36;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.roundRect(2, 2, 108, 32, 5); ctx.fill();
  ctx.fillStyle = '#' + color.toString(16).padStart(6, '0');
  ctx.font = 'bold 15px monospace';
  ctx.textAlign = 'center';
  ctx.fillText(`${label}-${i}`, 56, 23);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }));
  sprite.scale.set(2.5, 0.8, 1);
  sprite.position.set(x, y + 0.7, z);
  scene.add(sprite);
});

// ── UE→gNB connection lines (Line2 for thick rendering) ──────────────────────
// Green = SLA pass, Red = SLA fail (or yellow when no sim_results.json)
const lineGroup = new THREE.Group();
lineGroup.visible = false;   // hidden by default; toggle with L key or button

const _lineRes = new THREE.Vector2(innerWidth, innerHeight);
const matPass = new LineMaterial({ color: 0x00ee88, linewidth: 2.5, transparent: true, opacity: 0.75, resolution: _lineRes });
const matFail = new LineMaterial({ color: 0xff3333, linewidth: 2.5, transparent: true, opacity: 0.75, resolution: _lineRes });
const matUnkn = new LineMaterial({ color: 0xffff00, linewidth: 2.5, transparent: true, opacity: 0.65, resolution: _lineRes });

UE_POSITIONS.forEach(([ux, uy, uz], i) => {
  const gnbIdx = (BEST_GNB && BEST_GNB[i] !== undefined) ? BEST_GNB[i] : null;
  if (gnbIdx === null) return;
  const [gx, gy, gz] = GNB_POSITIONS[gnbIdx];
  let mat = matUnkn;
  if (SLA_PASS && SLA_PASS[i] !== undefined) mat = SLA_PASS[i] ? matPass : matFail;
  const geo = new LineGeometry();
  geo.setPositions([ux, uy, uz, gx, gy, gz]);
  const line = new Line2(geo, mat);
  line.computeLineDistances();
  lineGroup.add(line);
});
scene.add(lineGroup);

window.toggleLines = () => {
  lineGroup.visible = !lineGroup.visible;
  const btn = document.getElementById('btn-lines');
  btn.textContent = `Lines: ${lineGroup.visible ? 'ON' : 'OFF'}`;
  btn.className   = lineGroup.visible ? 'active' : '';
};

// ── Load main OBJ geometry ────────────────────────────────────────────────────
const wallMat = new THREE.MeshLambertMaterial({ color: 0xc8c0b0, side: THREE.DoubleSide });

new OBJLoader().load(
  `factory.obj?v=${V}`,
  (obj) => {
    obj.traverse(child => {
      if (child.isMesh) { child.material = wallMat; child.castShadow = true; child.receiveShadow = true; }
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

// ── Load partition walls (internal section dividers with door openings) ────────
// Rendered with FrontSide so east & west panels don't z-fight each other.
const partMat = new THREE.MeshLambertMaterial({ color: 0xd0b060, side: THREE.FrontSide });

new OBJLoader().load(
  `factory_partitions.obj?v=${V}`,
  (obj) => {
    obj.traverse(child => {
      if (child.isMesh) { child.material = partMat; child.castShadow = true; child.receiveShadow = true; }
    });
    scene.add(obj);
  },
  null,
  err => console.warn('No partition geometry:', err)
);

// ── Viewer-only roof planes (one PlaneGeometry per building; not in Sionna scene)
const roofMat = new THREE.MeshLambertMaterial({ color: 0x8899aa, side: THREE.DoubleSide, transparent: true, opacity: 0.82 });
const roofMeshes = [];
BUILDINGS.forEach(({x0, x1, y0, y1, height}) => {
  const geo  = new THREE.PlaneGeometry(x1 - x0, y1 - y0);
  const mesh = new THREE.Mesh(geo, roofMat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set((x0 + x1) / 2, height, (y0 + y1) / 2);
  roofMeshes.push(mesh);
  scene.add(mesh);
});

// Also load PLY-based roofs if factory_layout was run with ENABLE_ROOFS=True
let roofGroup = null;
new OBJLoader().load(
  `factory_roof.obj?v=${V}`,
  (obj) => {
    let hasMesh = false;
    obj.traverse(child => { if (child.isMesh) { child.material = roofMat; hasMesh = true; } });
    if (hasMesh) { roofGroup = obj; scene.add(roofGroup); }
  },
  null,
  () => {}
);

window.toggleRoof = () => {
  const newVis = roofMeshes.length ? !roofMeshes[0].visible : false;
  roofMeshes.forEach(m => m.visible = newVis);
  if (roofGroup) roofGroup.visible = newVis;
  const btn = document.getElementById('btn-roof');
  btn.textContent = `Roof: ${newVis ? 'ON' : 'OFF'}`;
  btn.className   = newVis ? 'active' : '';
};

// ── First-person controls ─────────────────────────────────────────────────────
const controls = new PointerLockControls(camera, renderer.domElement);
scene.add(controls.getObject());

controls.getObject().rotation.y = -Math.PI / 2;   // face east toward partition walls
window.startWalk = () => controls.lock();
controls.addEventListener('lock',   () => document.getElementById('overlay').style.display = 'none');
controls.addEventListener('unlock', () => document.getElementById('overlay').style.display = 'flex');

// ── Movement ──────────────────────────────────────────────────────────────────
const keys = {};
addEventListener('keydown', e => {
  keys[e.code] = true;
  if (e.code === 'KeyL') toggleLines();
  if (e.code === 'KeyR') toggleRoof();
});
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

    dir.z = fwd - back; dir.x = rgt - left; dir.y = up - dn;
    dir.normalize();

    velocity.z -= dir.z * speed * 20 * dt;
    velocity.x -= dir.x * speed * 20 * dt;
    velocity.y += dir.y * speed * 20 * dt;

    controls.moveRight(-velocity.x * dt);
    controls.moveForward(-velocity.z * dt);
    controls.getObject().position.y += velocity.y * dt;

    if (controls.getObject().position.y < 1.7)
      controls.getObject().position.y = 1.7;
  }

  renderer.render(scene, camera);
}
animate();

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  [matPass, matFail, matUnkn].forEach(m => m.resolution.set(innerWidth, innerHeight));
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
        pass


def _load_markers():
    """Load positions from config.json and best_gnb/sla_pass from sim_results.json."""
    cfg_path = "config.json"
    if not os.path.exists(cfg_path):
        return [], [], [], None, None

    with open(cfg_path) as f:
        cfg = json.load(f)

    def swap(pos):
        x, y, z = pos[0], pos[1], pos[2]
        return [x, z, y]   # Three.js y-up: x=x, y=z(height), z=y

    gnbs     = [swap(p) for p in cfg.get("transmitters", [])]
    ues      = [swap(p) for p in cfg.get("static_receivers", [])]
    ue_types = cfg.get("ue_types", ["unknown"] * len(ues))
    buildings = cfg.get("buildings", [])

    best_gnb = sla_pass = None
    sim_path = "sim_results.json"
    if os.path.exists(sim_path):
        with open(sim_path) as f:
            res = json.load(f)
        best_gnb = res.get("best_gnb")
        sla_pass = res.get("sla_pass")

    return gnbs, ues, ue_types, best_gnb, sla_pass, buildings


def serve(port=8889):
    export_obj()
    gnbs, ues, ue_types, best_gnb, sla_pass, buildings = _load_markers()
    has_sim = best_gnb is not None

    html = HTML_TEMPLATE \
        .replace("__GNB_POSITIONS__", json.dumps(gnbs)) \
        .replace("__UE_POSITIONS__",  json.dumps(ues)) \
        .replace("__UE_TYPES__",      json.dumps(ue_types)) \
        .replace("__BEST_GNB__",      json.dumps(best_gnb)) \
        .replace("__SLA_PASS__",      json.dumps(sla_pass)) \
        .replace("__BUILDINGS__",     json.dumps(buildings)) \
        .replace("__CACHE_BUST__",    str(int(time.time())))

    with open(HTML_FILE, "w") as f:
        f.write(html)

    print(f"\nFactory viewer ready!")
    print(f"  Serving from    : {os.path.abspath(SCENE_DIR)}/")
    print(f"  Open in browser : http://localhost:{port}/")
    print(f"  gNBs            : {len(gnbs)}  |  UEs : {len(ues)}")
    print(f"  Sim results     : {'loaded (lines available)' if has_sim else 'not found — run factory_sim.py first'}")
    print(f"\n  Controls:")
    print(f"    WASD / Arrows — move    Shift — run")
    print(f"    Mouse — look            Space/C — up/down")
    print(f"    Esc — release cursor")
    print(f"\n  Toggles (buttons bottom-right):")
    print(f"    Lines — UE→best-gNB connections (green=pass, red=fail)")
    print(f"    Roof  — show/hide building roofs")
    print(f"\nPress Ctrl+C to stop.\n")

    with socketserver.TCPServer(("", port), _Handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8889)
    serve(ap.parse_args().port)
