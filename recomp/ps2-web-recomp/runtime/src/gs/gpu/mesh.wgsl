// GPU mesh path (T48): the primitive records of mesh strips, as gpu.cpp draw() makes them from the GS vertices
// the strip's path 1 packet would give (see ps2/chain.hpp MeshDraw). One invocation per strip triangle.
struct Params {
    v: array<vec4<u32>, 16>,
}

@group(0) @binding(0) var<storage, read_write> data: array<u32>;
@group(0) @binding(1) var<uniform> params: Params;
@group(0) @binding(2) var<storage, read> mesh: array<u32>;

override SCALE: u32 = 1u;

const PRIM_WORDS: u32 = 28u;
const ITEM_WORDS: u32 = 32u;
const VERTEX_WORDS: u32 = 9u;

fn prm(i: u32) -> u32 {
    return params.v[i / 4u][i % 4u];
}

fn fat(i: u32) -> f32 {
    return bitcast<f32>(data[i]);
}

fn row(i: u32) -> vec4<f32> {
    return vec4<f32>(fat(i), fat(i + 1u), fat(i + 2u), fat(i + 3u));
}

// Exactness: VU1 (vu_ops) and draw() round every product and use the exact reciprocal truncated (VU1) or
// rounded (1 / area). A product is kept from fusing with an add by an xor with params word 3 (always 0);
// reciprocals are corrected with fma residuals.
fn mul4(a: vec4<f32>, b: f32) -> vec4<f32> {
    return bitcast<vec4<f32>>(bitcast<vec4<u32>>(a * b) ^ vec4<u32>(prm(3u)));
}

fn mul(a: f32, b: f32) -> f32 {
    return bitcast<f32>(bitcast<u32>(a * b) ^ prm(3u));
}

fn up(r: f32) -> f32 {
    return bitcast<f32>(bitcast<u32>(r) + 1u);
}

fn down(r: f32) -> f32 {
    return bitcast<f32>(bitcast<u32>(r) - 1u);
}

fn recip_trunc(w: f32) -> f32 {
    let a = abs(w);
    var r = 1.0 / a;
    for (var i = 0; i < 3; i = i + 1) {
        if (fma(-a, r, 1.0) < 0.0) {
            r = down(r);
        } else if (fma(-a, up(r), 1.0) >= 0.0) {
            r = up(r);
        }
    }
    return select(r, -r, w < 0.0);
}

fn recip_round(w: f32) -> f32 {
    let a = abs(w);
    var r = 1.0 / a;
    for (var i = 0; i < 3; i = i + 1) {
        let e = abs(fma(-a, r, 1.0));
        if (abs(fma(-a, up(r), 1.0)) < e) {
            r = up(r);
        } else if (abs(fma(-a, down(r), 1.0)) < e) {
            r = down(r);
        }
    }
    return select(r, -r, w < 0.0);
}

struct V {
    x: f32,
    y: f32,
    z: u32,
    rgba: u32,
    s: f32,
    t: f32,
    q: f32,
    adc: bool,
}

// Item words: 0 first record, 2 first vertex (word offset in mesh), 4 flags (1 second st set, 2 flat, 4 IIP),
// 5 flat RGBA, 6/7 XYOFFSET, 8/9 scissor, 11-14 ADC bits, 16-31 matrix rows.
fn vertex(item: u32, k: u32) -> V {
    let at = data[item + 2u] + k * VERTEX_WORDS;
    let flags = data[item + 4u];
    let c = row(item + 28u) + mul4(row(item + 16u), bitcast<f32>(mesh[at])) + mul4(row(item + 20u), bitcast<f32>(mesh[at + 1u])) +
            mul4(row(item + 24u), bitcast<f32>(mesh[at + 2u]));
    let q = recip_trunc(c.w);
    let st_at = at + 4u + (flags & 1u) * 2u;
    var v: V;
    v.x = (f32(u32(i32(c.x * q * 16.0)) & 0xFFFFu) - f32(data[item + 6u])) / 16.0;
    v.y = (f32(u32(i32(c.y * q * 16.0)) & 0xFFFFu) - f32(data[item + 7u])) / 16.0;
    v.z = (u32(i32(c.z * q * 16.0)) >> 4u) & 0xFFFFFFu;
    v.rgba = select(mesh[at + 3u], data[item + 5u], (flags & 2u) != 0u);
    v.s = bitcast<f32>(mesh[st_at]) * q;
    v.t = bitcast<f32>(mesh[st_at + 1u]) * q;
    v.q = q;
    v.adc = mesh[at + 8u] != 0u || ((data[item + 11u + k / 32u] >> (k % 32u)) & 1u) != 0u;
    return v;
}

// draw()'s floor(ceil(lo * samples) / samples): the float quotient of an integer by 1-3 floors as the integer one.
fn first_pixel(lo: f32) -> i32 {
    let m = i32(ceil(lo * f32(SCALE)));
    let s = i32(SCALE);
    return select(m / s, (m - s + 1) / s, m < 0);
}

fn inclusive(ax: f32, ay: f32, bx: f32, by: f32, sg: f32) -> bool {
    let gx = (ay - by) * sg;
    let gy = (bx - ax) * sg;
    return gx > 0.0 || (gx == 0.0 && gy > 0.0);
}

fn put_vertex(out: u32, n: u32, v: V, colour: u32) {
    data[out + 12u + n] = colour;
    data[out + 15u + n * 3u] = bitcast<u32>(v.s);
    data[out + 16u + n * 3u] = bitcast<u32>(v.t);
    data[out + 17u + n * 3u] = bitcast<u32>(v.q);
}

// Record i of the dispatch (box lo = 0xFFFFFFFF, hi = 0 when it draws nothing).
fn build(i: u32) {
    let items = prm(0u);
    var lo = 0u;
    var hi = prm(1u);
    while (hi - lo > 1u) {
        let mid = (lo + hi) / 2u;
        if (data[items + mid * ITEM_WORDS + 10u] <= i) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let item = items + lo * ITEM_WORDS;
    let j = i - data[item + 10u];
    let out = (data[item] + j) * PRIM_WORDS;
    data[out] = data[item + 3u];
    data[out + 1u] = 0u;
    data[out + 2u] = 0xFFFFFFFFu;
    data[out + 3u] = 0u;
    let v0 = vertex(item, j);
    let v1 = vertex(item, j + 1u);
    let v2 = vertex(item, j + 2u);
    if (v2.adc) {
        return;
    }
    let area = mul(v1.x - v0.x, v2.y - v0.y) - mul(v2.x - v0.x, v1.y - v0.y);
    if (area == 0.0) {
        return;
    }
    let sx = data[item + 8u];
    let sy = data[item + 9u];
    let minx = max(max(i32(sx & 0xFFFFu), first_pixel(min(v0.x, min(v1.x, v2.x)))), 0);
    let maxx = min(min(i32(sx >> 16u), i32(ceil(max(v0.x, max(v1.x, v2.x)))) - 1), 2047);
    let miny = max(max(i32(sy & 0xFFFFu), first_pixel(min(v0.y, min(v1.y, v2.y)))), 0);
    let maxy = min(min(i32(sy >> 16u), i32(ceil(max(v0.y, max(v1.y, v2.y)))) - 1), 2047);
    if (minx > maxx || miny > maxy) {
        return;
    }
    data[out + 4u] = bitcast<u32>(v0.x);
    data[out + 5u] = bitcast<u32>(v0.y);
    data[out + 6u] = bitcast<u32>(v1.x);
    data[out + 7u] = bitcast<u32>(v1.y);
    data[out + 8u] = bitcast<u32>(v2.x);
    data[out + 9u] = bitcast<u32>(v2.y);
    data[out + 10u] = bitcast<u32>(recip_round(area));
    data[out + 11u] = 0u;
    let sg = select(-1.0, 1.0, area > 0.0);
    data[out + 27u] = select(0u, 1u, inclusive(v1.x, v1.y, v2.x, v2.y, sg)) | select(0u, 2u, inclusive(v2.x, v2.y, v0.x, v0.y, sg)) |
                      select(0u, 4u, inclusive(v0.x, v0.y, v1.x, v1.y, sg));
    let iip = (data[item + 4u] & 4u) != 0u;
    put_vertex(out, 0u, v0, select(v2.rgba, v0.rgba, iip));
    put_vertex(out, 1u, v1, select(v2.rgba, v1.rgba, iip));
    put_vertex(out, 2u, v2, v2.rgba);
    data[out + 24u] = v0.z;
    data[out + 25u] = bitcast<u32>(f32(i32(v1.z) - i32(v0.z)));
    data[out + 26u] = bitcast<u32>(f32(i32(v2.z) - i32(v0.z)));
    data[out + 2u] = u32(minx) | (u32(miny) << 16u);
    data[out + 3u] = u32(maxx) | (u32(maxy) << 16u);
}

@compute @workgroup_size(64)
fn mesh_build(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x + gid.y * 64u * 1024u;
    if (i < prm(2u)) {
        build(i);
    }
}
// Per tile of a mesh batch (one workgroup per tile): the records of the tile's chunks (64 records each, listed by
// flush_meshes) that touch it, in order, into the tile's list for raster_mesh. Params: 0 tiles, 1 first record,
// 2 records, 3 tiles (origin, first chunk entry, list; a closing entry), 4 chunk entries.
var<workgroup> wg_bits: array<atomic<u32>, 8>;
var<workgroup> wg_count: u32;

// The invocation's slot among the set flags, in invocation order, and their number.
fn ordered_slot(lid: u32, flag: bool) -> vec2<u32> {
    if (lid < 8u) {
        atomicStore(&wg_bits[lid], 0u);
    }
    workgroupBarrier();
    if (flag) {
        atomicOr(&wg_bits[lid / 32u], 1u << (lid % 32u));
    }
    workgroupBarrier();
    var slot = 0u;
    var total = 0u;
    for (var w = 0u; w < 8u; w = w + 1u) {
        let bits = atomicLoad(&wg_bits[w]);
        total = total + countOneBits(bits);
        if (w < lid / 32u) {
            slot = slot + countOneBits(bits);
        } else if (w == lid / 32u) {
            slot = slot + countOneBits(bits & ((1u << (lid % 32u)) - 1u));
        }
    }
    return vec2<u32>(slot, total);
}

// False when the tile's sample rectangle lies outside one edge of the record's triangle (all four corners, with a
// margin for rounding against the per-sample test).
fn triangle_touches(p: u32, cx0: f32, cy0: f32, cx1: f32, cy1: f32) -> bool {
    let xs = vec3<f32>(fat(p + 4u), fat(p + 6u), fat(p + 8u));
    let ys = vec3<f32>(fat(p + 5u), fat(p + 7u), fat(p + 9u));
    let inv = fat(p + 10u);
    for (var e = 0u; e < 3u; e = e + 1u) {
        let a = (e + 1u) % 3u;
        let b = (e + 2u) % 3u;
        var outside = true;
        for (var q = 0u; q < 4u; q = q + 1u) {
            let qx = select(cx0, cx1, (q & 1u) != 0u);
            let qy = select(cy0, cy1, (q & 2u) != 0u);
            let w = ((xs[a] - qx) * (ys[b] - qy) - (xs[b] - qx) * (ys[a] - qy)) * inv;
            outside = outside && w < -1e-3;
        }
        if (outside) {
            return false;
        }
    }
    return true;
}

@compute @workgroup_size(256)
fn mesh_bin(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) lid: u32) {
    let index = wid.x + wid.y * 1024u;
    if (index >= prm(0u)) {
        return;
    }
    let tile = prm(3u) + index * 3u;
    let tx = data[tile] & 0xFFFFu;
    let ty = data[tile] >> 16u;
    let x0 = i32(tx * 16u / SCALE);
    let y0 = i32(ty * 16u / SCALE);
    let x1 = i32((tx * 16u + 15u) / SCALE);
    let y1 = i32((ty * 16u + 15u) / SCALE);
    let cx0 = f32(tx * 16u) / f32(SCALE);
    let cy0 = f32(ty * 16u) / f32(SCALE);
    let cx1 = f32(tx * 16u + 15u) / f32(SCALE);
    let cy1 = f32(ty * 16u + 15u) / f32(SCALE);
    let first = prm(1u);
    let records = prm(2u);
    let entries = prm(4u) + data[tile + 1u];
    let list = data[tile + 2u];
    if (lid == 0u) {
        wg_count = data[tile + 4u] - data[tile + 1u];
    }
    let chunks = workgroupUniformLoad(&wg_count);
    var held = 0u;
    for (var g = 0u; g < chunks; g = g + 4u) {
        let slot = g + lid / 64u;
        var r = 0u;
        var hit = false;
        if (slot < chunks) {
            r = data[entries + slot] * 64u + lid % 64u;
            let p = (first + r) * PRIM_WORDS;
            let lo = data[p + 2u];
            let hi = data[p + 3u];
            hit = r < records && i32(lo & 0xFFFFu) <= x1 && i32(lo >> 16u) <= y1 && i32(hi & 0xFFFFu) >= x0 && i32(hi >> 16u) >= y0 &&
                  triangle_touches(p, cx0, cy0, cx1, cy1);
        }
        let rs = ordered_slot(lid, hit);
        if (hit) {
            data[list + 1u + held + rs.x] = r;
        }
        if (lid == 0u) {
            wg_count = rs.y;
        }
        held = held + workgroupUniformLoad(&wg_count);
    }
    if (lid == 0u) {
        data[list] = held;
    }
}