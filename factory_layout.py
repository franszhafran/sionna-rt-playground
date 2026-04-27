"""
Car Factory Layout Generator for Sionna RT

Total area: 250 m (x, width) × 160 m (y, length)

Buildings (all unique size, with doors):
  Stamping Plant     x:  5– 80  y:  5– 85  h=12 m  (75×80 m)
  Body Shop          x: 95–200  y:  5– 90  h=10 m (105×85 m)
  Paint Shop         x:210–245  y:  5– 75  h= 9 m  (35×70 m)
  General Assembly   x:  5–245  y:100–155  h=10 m (240×55 m)

Generates:
  car_factory_scene/car_factory.xml
  car_factory_scene/meshes/*.ply   (one file per building surface)
  config.json                      (updated with new positions)
"""

import os, json, struct, random

# ── Output paths ───────────────────────────────────────────────────────────────

SCENE_DIR = "car_factory_scene"
MESH_DIR  = os.path.join(SCENE_DIR, "meshes")
SCENE_XML = os.path.join(SCENE_DIR, "car_factory.xml")

# ── Building definitions ───────────────────────────────────────────────────────
# doors per wall key: "south"/"north" → c = center along x-axis
#                     "east"/"west"   → c = center along y-axis
# door format: {"c": float, "w": float (width), "h": float (opening height)}

BUILDINGS = [
    {
        "id": "stamping", "name": "Stamping Plant",
        "x0":   5.0, "x1":  80.0,
        "y0":   5.0, "y1":  85.0, "height": 12.0,
        "doors": {
            "south": [{"c": 42.0, "w": 6.0, "h": 4.0}],
            "north": [{"c": 60.0, "w": 6.0, "h": 4.0}],
            "east":  [{"c": 45.0, "w": 6.0, "h": 4.0}],
        },
    },
    {
        "id": "body_shop", "name": "Body Shop",
        "x0":  95.0, "x1": 200.0,
        "y0":   5.0, "y1":  90.0, "height": 10.0,
        "doors": {
            "south": [{"c": 140.0, "w": 6.0, "h": 4.0}],
            "west":  [{"c":  45.0, "w": 6.0, "h": 4.0}],
            "east":  [{"c":  35.0, "w": 5.0, "h": 4.0}],
            "north": [{"c": 150.0, "w": 6.0, "h": 4.0}],
        },
    },
    {
        "id": "paint_shop", "name": "Paint Shop",
        "x0": 210.0, "x1": 245.0,
        "y0":   5.0, "y1":  75.0, "height":  9.0,
        "doors": {
            "west":  [{"c": 35.0, "w": 5.0, "h": 4.0}],
            "east":  [{"c": 35.0, "w": 5.0, "h": 4.0}],
            "south": [{"c": 227.0, "w": 5.0, "h": 4.0}],
        },
    },
    {
        "id": "assembly", "name": "General Assembly",
        "x0":   5.0, "x1": 245.0,
        "y0": 100.0, "y1": 155.0, "height": 10.0,
        "doors": {
            "south": [
                {"c":  60.0, "w": 8.0, "h": 4.5},
                {"c": 150.0, "w": 8.0, "h": 4.5},
                {"c": 215.0, "w": 8.0, "h": 4.5},
            ],
            "north": [{"c": 125.0, "w": 6.0, "h": 4.0}],
        },
    },
]

# ── gNBs (ceiling-mounted) ─────────────────────────────────────────────────────

GNBS = [
    # Stamping Plant (2)
    [27.0,  30.0, 11.5],
    [57.0,  60.0, 11.5],
    # Body Shop (3)
    [120.0, 35.0,  9.5],
    [147.0, 55.0,  9.5],
    [175.0, 75.0,  9.5],
    # Paint Shop (2)
    [227.0, 25.0,  8.5],
    [227.0, 58.0,  8.5],
    # General Assembly (3)
    [ 65.0, 127.0,  9.5],
    [125.0, 127.0,  9.5],
    [195.0, 127.0,  9.5],
]

# ── Static UEs (floor-level workstations / robots) ────────────────────────────
# Randomly distributed inside each building with a 4 m wall clearance.
# Seed is fixed so the layout is reproducible across re-runs.

def _random_ues(b, n, margin=4.0, z_min=0.25, z_max=3.0, rng=None):
    """Place n UEs uniformly at random inside building b, margin m from walls."""
    x0, x1 = b["x0"] + margin, b["x1"] - margin
    y0, y1 = b["y0"] + margin, b["y1"] - margin
    return [[round(rng.uniform(x0, x1), 2),
             round(rng.uniform(y0, y1), 2),
             round(rng.uniform(z_min, z_max), 2)] for _ in range(n)]

_rng = random.Random(42)

# UE type mix per building: (type_name, count)
# Types: agv, robotic_arm, vision_camera, safety_sensor, worker_tablet
_TYPE_MIX = {
    # Stamping Plant (78): heavy press + transfer robots
    "stamping":  [("robotic_arm", 31), ("agv", 16), ("safety_sensor", 20), ("worker_tablet", 11)],
    # Body Shop (117): welding robots + inspection cameras
    "body_shop": [("robotic_arm", 41), ("vision_camera", 23), ("agv", 23), ("safety_sensor", 18), ("worker_tablet", 12)],
    # Paint Shop (32): spray robots + vision QC
    "paint_shop":[("robotic_arm", 11), ("vision_camera", 10), ("safety_sensor", 6), ("worker_tablet", 5)],
    # General Assembly (173): mixed workforce + AGVs
    "assembly":  [("worker_tablet", 52), ("vision_camera", 43), ("robotic_arm", 35), ("agv", 26), ("safety_sensor", 17)],
}

def _typed_ues(b, type_mix, margin=4.0, rng=None):
    """Place UEs of each type randomly inside building b."""
    positions, types = [], []
    for ue_type, n in type_mix:
        for pos in _random_ues(b, n, margin=margin, rng=rng):
            positions.append(pos)
            types.append(ue_type)
    return positions, types

_ue_pos_stamping,  _ue_typ_stamping  = _typed_ues(BUILDINGS[0], _TYPE_MIX["stamping"],  rng=_rng)
_ue_pos_bodyshop,  _ue_typ_bodyshop  = _typed_ues(BUILDINGS[1], _TYPE_MIX["body_shop"],  rng=_rng)
_ue_pos_paint,     _ue_typ_paint     = _typed_ues(BUILDINGS[2], _TYPE_MIX["paint_shop"], rng=_rng)
_ue_pos_assembly,  _ue_typ_assembly  = _typed_ues(BUILDINGS[3], _TYPE_MIX["assembly"],   rng=_rng)

UES      = _ue_pos_stamping + _ue_pos_bodyshop + _ue_pos_paint + _ue_pos_assembly
UE_TYPES = _ue_typ_stamping + _ue_typ_bodyshop + _ue_typ_paint + _ue_typ_assembly

# ── PLY helpers ────────────────────────────────────────────────────────────────
# Vertex conventions verified against Sionna's own wall.ply / floor.ply:
#   wall.ply  → (x, y_a, z_top), (x, y_a, z_bot), (x, y_b, z_bot), (x, y_b, z_top)
#               normal +x (east wall)
#   floor.ply → (x_a, y_a, 0), (x_b, y_a, 0), (x_b, y_b, 0), (x_a, y_b, 0)
#               normal +z (upward)

_UV = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]


def _write_ply(path, panels):
    """Write N quad panels to a binary little-endian PLY file."""
    nv, nf = 4 * len(panels), 2 * len(panels)
    hdr = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {nv}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float u\nproperty float v\n"
        f"element face {nf}\n"
        "property list uchar int vertex_indices\nend_header\n"
    )
    with open(path, "wb") as f:
        f.write(hdr.encode("ascii"))
        for v0, v1, v2, v3 in panels:
            for i, (x, y, z) in enumerate([v0, v1, v2, v3]):
                u, v = _UV[i]
                f.write(struct.pack("<fffff", x, y, z, u, v))
        for i in range(len(panels)):
            b = i * 4
            f.write(struct.pack("<Biii", 3, b, b+1, b+2))
            f.write(struct.pack("<Biii", 3, b, b+2, b+3))


# ── Panel constructors (verified winding → correct outward normals) ────────────

def _panel_south(xa, xb, y, za, zb):
    """South wall segment at y=y, x:xa..xb, z:za..zb. Normal −y."""
    return (xa,y,zb), (xa,y,za), (xb,y,za), (xb,y,zb)

def _panel_north(xa, xb, y, za, zb):
    """North wall segment at y=y, x:xa..xb, z:za..zb. Normal +y."""
    return (xb,y,zb), (xb,y,za), (xa,y,za), (xa,y,zb)

def _panel_west(x, ya, yb, za, zb):
    """West wall segment at x=x, y:ya..yb, z:za..zb. Normal −x."""
    return (x,yb,zb), (x,yb,za), (x,ya,za), (x,ya,zb)

def _panel_east(x, ya, yb, za, zb):
    """East wall segment at x=x, y:ya..yb, z:za..zb. Normal +x."""
    return (x,ya,zb), (x,ya,za), (x,yb,za), (x,yb,zb)

def _panel_floor(x0, x1, y0, y1):
    """Floor at z=0. Normal −z (outward below slab)."""
    return (x0,y0,0), (x0,y1,0), (x1,y1,0), (x1,y0,0)

def _panel_roof(x0, x1, y0, y1, h):
    """Roof at z=h. Normal +z (outward above roof)."""
    return (x0,y0,h), (x1,y0,h), (x1,y1,h), (x0,y1,h)


# ── Wall-with-doors splitter ───────────────────────────────────────────────────

def _split(start, end, doors):
    """Yield (is_gap, a, b, gap_h) segments along [start, end]."""
    gaps = sorted(
        [(d["c"] - d["w"]/2, d["c"] + d["w"]/2, d["h"]) for d in doors],
        key=lambda t: t[0]
    )
    prev = start
    for da, db, dh in gaps:
        if prev < da - 1e-6:
            yield False, prev, da, 0.0
        yield True, da, db, dh
        prev = db
    if prev < end - 1e-6:
        yield False, prev, end, 0.0


def _wall_panels(kind, b, doors):
    """Return list of quad panels for one wall face of building b."""
    x0, x1 = b["x0"], b["x1"]
    y0, y1 = b["y0"], b["y1"]
    h = b["height"]
    panels = []

    if kind == "south":
        for gap, xa, xb, dh in _split(x0, x1, doors):
            if gap:
                if dh < h:
                    panels.append(_panel_south(xa, xb, y0, dh, h))
            else:
                panels.append(_panel_south(xa, xb, y0, 0, h))

    elif kind == "north":
        for gap, xa, xb, dh in _split(x0, x1, doors):
            if gap:
                if dh < h:
                    panels.append(_panel_north(xa, xb, y1, dh, h))
            else:
                panels.append(_panel_north(xa, xb, y1, 0, h))

    elif kind == "west":
        for gap, ya, yb, dh in _split(y0, y1, doors):
            if gap:
                if dh < h:
                    panels.append(_panel_west(x0, ya, yb, dh, h))
            else:
                panels.append(_panel_west(x0, ya, yb, 0, h))

    elif kind == "east":
        for gap, ya, yb, dh in _split(y0, y1, doors):
            if gap:
                if dh < h:
                    panels.append(_panel_east(x1, ya, yb, dh, h))
            else:
                panels.append(_panel_east(x1, ya, yb, 0, h))

    return panels


# ── Scene XML ─────────────────────────────────────────────────────────────────

def _build_xml(surfaces):
    lines = [
        '<scene version="2.1.0">',
        "",
        "    <!-- ITU Radio Materials -->",
        "",
        '    <bsdf type="itu-radio-material" id="concrete">',
        '        <string name="type" value="concrete"/>',
        '        <float name="thickness" value="0.3"/>',
        '    </bsdf>',
        "",
        '    <bsdf type="itu-radio-material" id="metal">',
        '        <string name="type" value="metal"/>',
        '        <float name="thickness" value="0.01"/>',
        '    </bsdf>',
        "",
        "    <!-- Building Surfaces -->",
        "",
    ]
    for mesh_id, ply_file, mat in surfaces:
        lines += [
            f'    <shape type="ply" id="{mesh_id}">',
            f'        <string name="filename" value="meshes/{ply_file}"/>',
            f'        <boolean name="face_normals" value="true"/>',
            f'        <ref id="{mat}" name="bsdf"/>',
            f'    </shape>',
            "",
        ]
    lines.append("</scene>")
    return "\n".join(lines)


# ── ASCII floor plan ──────────────────────────────────────────────────────────

def _floorplan():
    # 50-char wide (1 char ≈ 5 m), 32-row tall (1 row ≈ 5 m)
    W, H = 50, 32
    grid = [list("·" * W) for _ in range(H)]

    def rc(x, y):
        return int(round(x / 5)), int(round(y / 5))

    # Draw building outlines
    for b in BUILDINGS:
        cx0, cy0 = rc(b["x0"], b["y0"])
        cx1, cy1 = rc(b["x1"], b["y1"])
        for c in range(max(0,cx0), min(W,cx1+1)):
            if cy0 < H: grid[cy0][c] = "─"
            if cy1 < H: grid[cy1][c] = "─"
        for r in range(max(0,cy0), min(H,cy1+1)):
            if cx0 < W: grid[r][cx0] = "│"
            if cx1 < W: grid[r][cx1] = "│"
        # corners
        for cy in (cy0, cy1):
            for cx in (cx0, cx1):
                if 0 <= cy < H and 0 <= cx < W:
                    grid[cy][cx] = "+"
        # fill
        for r in range(cy0+1, min(H,cy1)):
            for c in range(cx0+1, min(W,cx1)):
                grid[r][c] = " "
        # label
        label = b["name"][:max(0, cx1-cx0-2)]
        mr = (cy0 + cy1) // 2
        mc = (cx0 + cx1) // 2 - len(label) // 2
        for i, ch in enumerate(label):
            if 0 <= mr < H and 0 <= mc+i < W:
                grid[mr][mc+i] = ch
        # doors: mark "D" on the wall
        for wall, doors in b.get("doors", {}).items():
            for d in doors:
                if wall in ("south", "north"):
                    dc, dy = rc(d["c"], b["y0"] if wall=="south" else b["y1"])
                    if 0<=dy<H and 0<=dc<W: grid[dy][dc] = "D"
                else:
                    dx, dc = rc(b["x0"] if wall=="west" else b["x1"], d["c"])
                    if 0<=dc<H and 0<=dx<W: grid[dc][dx] = "D"

    # gNBs
    for pos in GNBS:
        c, r = rc(pos[0], pos[1])
        if 0<=r<H and 0<=c<W: grid[r][c] = "G"

    # UEs
    for pos in UES:
        c, r = rc(pos[0], pos[1])
        if 0<=r<H and 0<=c<W and grid[r][c] == " ":
            grid[r][c] = "u"

    lines = ["  Factory Floor Plan  250m×160m  (each cell ≈ 5m)",
             "  G=gNB  u=UE  D=door",
             "  y(m)"]
    for r in range(H-1, -1, -1):
        lines.append(f"  {r*5:3d} │{''.join(grid[r])}│")
    lines.append("       └" + "─"*W + "┘")
    lines.append("        " + "".join(str((c*5//10)%10) if c%2==0 else " " for c in range(W)))
    lines.append("        x-axis  0 ─────────────────────────────── 250 m")
    return "\n".join(lines)


# ── Global options ────────────────────────────────────────────────────────────
# Set to False to omit roofs from the scene (useful for top-down visualization
# in scene.preview() or when roof reflections are not needed).
# Can also be overridden per building by adding "enable_roof": False in BUILDINGS.
ENABLE_ROOFS = False

# ── Main ───────────────────────────────────────────────────────────────────────

def generate():
    os.makedirs(MESH_DIR, exist_ok=True)

    # Remove stale PLY files so disabled surfaces (e.g. roofs) don't linger
    for f in os.listdir(MESH_DIR):
        if f.endswith(".ply"):
            os.remove(os.path.join(MESH_DIR, f))

    xml_surface_list = []   # (mesh_id, ply_file, material)

    # Ground plane covering full factory area (250 m × 160 m)
    _write_ply(
        os.path.join(MESH_DIR, "ground.ply"),
        [_panel_floor(0.0, 250.0, 0.0, 160.0)]
    )
    xml_surface_list.append(("ground", "ground.ply", "concrete"))

    for b in BUILDINGS:
        bid, h = b["id"], b["height"]
        x0, x1, y0, y1 = b["x0"], b["x1"], b["y0"], b["y1"]
        doors = b.get("doors", {})

        enable_roofs = b.get("enable_roof", ENABLE_ROOFS)
        surfaces = {
            "floor":      ("concrete", [_panel_floor(x0, x1, y0, y1)]),
            "roof":       ("metal",    [_panel_roof(x0, x1, y0, y1, h)] if enable_roofs else []),
            "wall_south": ("concrete", _wall_panels("south", b, doors.get("south", []))),
            "wall_north": ("concrete", _wall_panels("north", b, doors.get("north", []))),
            "wall_west":  ("concrete", _wall_panels("west",  b, doors.get("west",  []))),
            "wall_east":  ("concrete", _wall_panels("east",  b, doors.get("east",  []))),
        }

        for surf, (mat, panels) in surfaces.items():
            if not panels:
                continue
            mesh_id  = f"{bid}_{surf}"
            ply_file = f"{mesh_id}.ply"
            _write_ply(os.path.join(MESH_DIR, ply_file), panels)
            xml_surface_list.append((mesh_id, ply_file, mat))

    # Write scene XML
    with open(SCENE_XML, "w") as f:
        f.write(_build_xml(xml_surface_list))

    # Write config.json
    config = {
        "scene": SCENE_XML,
        "frequency": 3.8e9,
        "max_depth": 3,
        "beamforming_method": "MMSE",
        "use_statistical_channel": False,
        "enable_roofs": ENABLE_ROOFS,
        "noise_variance": 1e-8,
        "tx_array":  {"rows": 4, "cols": 4, "spacing": 0.5},
        "rx_array":  {"rows": 1, "cols": 1, "spacing": 0.5},
        "transmitters":      GNBS,
        "static_receivers":  UES,
        "ue_types":          UE_TYPES,
        "moving_receivers":  [],
    }
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)

    # ── Summary ────────────────────────────────────────────────────────────────
    print("=" * 65)
    print("  CAR FACTORY — SCENE GENERATED")
    print("=" * 65)
    print(f"\n  Scene XML : {SCENE_XML}")
    print(f"  PLY files : {len(xml_surface_list)} in {MESH_DIR}/")
    print(f"  Config    : config.json updated\n")

    print(f"  {'Building':<22} {'W':>5} {'L':>5} {'H':>5}  "
          f"{'x-range':>12}  {'y-range':>12}  Doors")
    print("  " + "─" * 72)
    for b in BUILDINGS:
        w  = b["x1"] - b["x0"]
        l  = b["y1"] - b["y0"]
        nd = sum(len(v) for v in b.get("doors", {}).values())
        print(f"  {b['name']:<22} {w:>4.0f}m {l:>4.0f}m {b['height']:>4.0f}m"
              f"  {b['x0']:>4.0f}–{b['x1']:<5.0f}  {b['y0']:>4.0f}–{b['y1']:<5.0f}  {nd}")

    print(f"\n  gNBs ({len(GNBS)} total)")
    for i, pos in enumerate(GNBS):
        print(f"    gNB-{i}  ({pos[0]:>5.1f}, {pos[1]:>5.1f}, {pos[2]:>4.1f})")

    by_type = {}
    for t in UE_TYPES:
        by_type[t] = by_type.get(t, 0) + 1
    print(f"\n  UEs ({len(UES)} total)  — "
          f"78 Stamping + 117 Body Shop + 32 Paint Shop + 173 Assembly")
    for t, n in sorted(by_type.items()):
        print(f"    {t:<18} {n:>4}")

    print()
    print(_floorplan())
    print()
    print("  ⚠  Ray tracing on a 250×160 m scene can be slow.")
    print("     Set  use_statistical_channel: true  for fast iteration.")


if __name__ == "__main__":
    generate()
