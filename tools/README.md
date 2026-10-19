# tools

Generic helpers. `bin/` (git-ignored) holds local tool installs.

- `gltfview.py <model.gltf> <out.png> [--size 480]`: checks a glTF 2.0 file
  (buffer sizes, views, accessors, indices, min/max) and renders it from
  four angles into one PNG (numpy + pillow software rasteriser). Test:
  `python -m unittest discover -s tools/tests`.
