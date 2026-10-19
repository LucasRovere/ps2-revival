"""Check a glTF 2.0 file (JSON + .bin) and render it to a PNG from several angles.

A visual check for mesh exports; nothing engine- or game-specific. Software rasteriser
(numpy + pillow): textured, Lambert light, alpha MASK/BLEND, node matrices.

Usage:
  python tools/gltfview.py model.gltf out.png [--size 480]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

COMPONENTS = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
VIEWS = (("front 3/4", (-0.8, 0.45, 1.0)), ("rear 3/4", (0.8, 0.45, -1.0)),
         ("side", (-1.0, 0.15, 0.0)), ("top", (0.0, 1.0, 0.01)))


def load(path):
    """JSON + buffers, with the structure checks a loader would trip over. Returns (doc, read)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["asset"]["version"] == "2.0"
    buffers = []
    for b in doc["buffers"]:
        data = (path.parent / b["uri"]).read_bytes()
        assert len(data) == b["byteLength"], f"buffer {b['uri']}: {len(data)} != {b['byteLength']}"
        buffers.append(data)
    for v in doc["bufferViews"]:
        assert v["byteOffset"] + v["byteLength"] <= len(buffers[v["buffer"]]), "bufferView past buffer end"

    def read(index):
        acc = doc["accessors"][index]
        view = doc["bufferViews"][acc["bufferView"]]
        dtype, width = COMPONENTS[acc["componentType"]], WIDTH[acc["type"]]
        size = acc["count"] * width * np.dtype(dtype).itemsize
        assert acc.get("byteOffset", 0) + size <= view["byteLength"], f"accessor {index} past its bufferView"
        a = np.frombuffer(buffers[view["buffer"]], dtype, acc["count"] * width,
                          view["byteOffset"] + acc.get("byteOffset", 0)).reshape(acc["count"], width)
        if "min" in acc:
            assert np.allclose(a.min(0), acc["min"]) and np.allclose(a.max(0), acc["max"]), f"accessor {index} min/max"
        return a

    return doc, read


def world_triangles(path):
    """Every triangle in world space with uv, normals and its material."""
    doc, read = load(path)
    textures = []
    for t in doc.get("textures", []):
        img = Image.open(path.parent / doc["images"][t["source"]]["uri"]).convert("RGBA")
        textures.append(np.asarray(img, np.float32) / 255)
    out = []

    def walk(index, parent):
        node = doc["nodes"][index]
        m = parent @ np.array(node.get("matrix", np.eye(4).reshape(-1)), np.float64).reshape(4, 4).T
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                pos = read(prim["attributes"]["POSITION"]).astype(np.float64)
                nrm = read(prim["attributes"]["NORMAL"]).astype(np.float64)
                uv = read(prim["attributes"]["TEXCOORD_0"])
                idx = read(prim["indices"]).reshape(-1, 3)
                assert idx.max() < len(pos), "index past vertex count"
                mat = doc["materials"][prim["material"]]
                tex = mat["pbrMetallicRoughness"].get("baseColorTexture", {}).get("index")
                wpos = pos @ m[:3, :3].T + m[:3, 3]
                wnrm = nrm @ np.linalg.inv(m[:3, :3])
                out.append((wpos[idx], wnrm[idx], uv[idx], None if tex is None else textures[tex],
                            mat.get("alphaMode", "OPAQUE")))
        for child in node.get("children", []):
            walk(child, m)

    for root in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        walk(root, np.eye(4))
    return doc, out


def look_at(eye, target):
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return np.array([r, u, -f]), eye


def render(groups, eye, target, size):
    rot, origin = look_at(np.array(eye, float), np.array(target, float))
    h = w = size
    focal = size * 1.4
    color = np.full((h, w, 3), 0.85)
    depth = np.full((h, w), np.inf)
    light = np.array([0.3, 0.8, 0.5]) / np.linalg.norm([0.3, 0.8, 0.5])
    for alpha_pass in (False, True):
        for tri_pos, tri_nrm, tri_uv, tex, mode in groups:
            if (mode == "BLEND") != alpha_pass:
                continue
            cam = (tri_pos - origin) @ rot.T
            for k in range(len(cam)):
                z = -cam[k, :, 2]
                if (z <= 0.05).any():
                    continue
                sx = w / 2 + focal * cam[k, :, 0] / z
                sy = h / 2 - focal * cam[k, :, 1] / z
                x0, x1 = max(int(sx.min()), 0), min(int(sx.max()) + 1, w)
                y0, y1 = max(int(sy.min()), 0), min(int(sy.max()) + 1, h)
                if x0 >= x1 or y0 >= y1:
                    continue
                area = (sx[1] - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (sy[1] - sy[0])
                if abs(area) < 1e-9:
                    continue
                py, px = np.mgrid[y0:y1, x0:x1] + 0.5
                b1 = ((px - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (py - sy[0])) / area
                b2 = ((sx[1] - sx[0]) * (py - sy[0]) - (px - sx[0]) * (sy[1] - sy[0])) / area
                b0 = 1 - b1 - b2
                inside = (b0 >= 0) & (b1 >= 0) & (b2 >= 0)
                if not inside.any():
                    continue
                iz = b0 / z[0] + b1 / z[1] + b2 / z[2]
                zz = 1 / np.where(inside, iz, 1)
                win = depth[y0:y1, x0:x1]
                inside &= zz < win
                weights = np.stack([b0 / z[0], b1 / z[1], b2 / z[2]], -1) * zz[..., None]
                n = weights @ tri_nrm[k]
                n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
                view = origin - (weights @ tri_pos[k])
                n *= np.sign((n * view).sum(-1, keepdims=True) + 1e-12)
                shade = 0.35 + 0.65 * np.clip(n @ light, 0, 1)
                if tex is not None:
                    uv = weights @ tri_uv[k]
                    th, tw = tex.shape[:2]
                    tx = (np.floor(uv[..., 0] * tw).astype(int)) % tw
                    ty = (np.floor(uv[..., 1] * th).astype(int)) % th
                    texel = tex[ty, tx]
                else:
                    texel = np.ones(inside.shape + (4,))
                if mode == "MASK":
                    inside &= texel[..., 3] >= 0.5
                rgb = texel[..., :3] * shade[..., None]
                a = texel[..., 3:4] if mode == "BLEND" else 1.0
                region = color[y0:y1, x0:x1]
                region[inside] = (rgb * a + region * (1 - a))[inside]
                if mode != "BLEND":
                    win[inside] = zz[inside]
    return (np.clip(color, 0, 1) * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gltf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--size", type=int, default=480)
    args = ap.parse_args()
    doc, groups = world_triangles(args.gltf)
    pts = np.concatenate([g[0].reshape(-1, 3) for g in groups])
    centre, radius = (pts.min(0) + pts.max(0)) / 2, np.linalg.norm(pts.max(0) - pts.min(0)) / 2
    print(f"{args.gltf.name}: structure OK; {sum(len(g[0]) for g in groups)} triangles, "
          f"bounds {np.round(pts.min(0), 3).tolist()} .. {np.round(pts.max(0), 3).tolist()}")
    tiles = []
    for _, d in VIEWS:
        d = np.array(d) / np.linalg.norm(d)
        tiles.append(render(groups, centre + d * radius * 3.0, centre, args.size))
    sheet = np.concatenate([np.concatenate(tiles[:2], 1), np.concatenate(tiles[2:], 1)], 0)
    Image.fromarray(sheet).save(args.out)
    print(f"views {', '.join(v for v, _ in VIEWS)} -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
