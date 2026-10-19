import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gltfview  # noqa: E402

POSITIONS = [(-1, -1, 0), (1, -1, 0), (0, 1, 0)]


def write_triangle(folder, byte_length=None):
    """One untextured triangle facing +Z: positions, normals, uvs, indices."""
    data = b"".join(struct.pack("<3f", *p) for p in POSITIONS)
    data += struct.pack("<3f", 0, 0, 1) * 3 + struct.pack("<2f", 0, 0) * 3 + struct.pack("<3H", 0, 1, 2) + b"\0\0"
    (folder / "tri.bin").write_bytes(data)
    views = [(0, 36), (36, 36), (72, 24), (96, 6)]
    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "tri.bin", "byteLength": byte_length or len(data)}],
        "bufferViews": [{"buffer": 0, "byteOffset": o, "byteLength": n} for o, n in views],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [-1, -1, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "materials": [{"pbrMetallicRoughness": {}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }
    path = folder / "tri.gltf"
    path.write_text(json.dumps(doc))
    return path


class GltfViewTest(unittest.TestCase):
    def test_triangle_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, groups = gltfview.world_triangles(write_triangle(Path(tmp)))
            self.assertEqual(len(groups), 1)
            np.testing.assert_allclose(groups[0][0][0], POSITIONS)
            image = gltfview.render(groups, (0, 0, 4), (0, 0, 0), 64)
            self.assertLess(image[32, 32].mean(), 0.85 * 255 - 10)  # the triangle covers the centre, shaded
            self.assertEqual(image[2, 2].tolist(), [216, 216, 216])  # background in the corner

    def test_wrong_buffer_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                gltfview.load(write_triangle(Path(tmp), byte_length=200))


if __name__ == "__main__":
    unittest.main()
