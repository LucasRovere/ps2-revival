enable dual_source_blending;

// Native renderer (T57): GS primitives as hardware-rasterised triangles. Colours are in the GS's
// 0-255 range; render targets are rgba16float with RGB = value / 255 and alpha = value / 128, so the
// blend factors As, Ad and FIX (128 = 1.0) are plain WebGPU factors.

override SCALE: f32 = 1.0;

struct Draw {
    frame: vec2<f32>,
    scale: f32,
    flags: u32,
    tex_size: vec2<f32>,
    store_size: vec2<f32>,
    aref: f32,
    lod_l: f32,
    lod_k: f32,
    mxl: f32,
    ta0: f32,
    ta1: f32,
    fbmsk: u32,
    blend: u32,
    tex: u32,
    pad: u32,
}

const F_TME: u32 = 1u;
const F_TCC: u32 = 2u;
const F_ATE: u32 = 16u;
const F_FBA: u32 = 256u;
const F_MAG_LINEAR: u32 = 512u;
const F_LCM: u32 = 8192u;
const F_REPEAT_U: u32 = 16384u;
const F_REPEAT_V: u32 = 32768u;
const F_SOURCE16: u32 = 65536u;
const F_SRC_ONE: u32 = 131072u;
const F_AEM: u32 = 262144u;
const F_SOURCE_TARGET: u32 = 524288u;
const F_MASKED: u32 = 1048576u;
const F_TARGET16: u32 = 2097152u;
const F_FACTORS: u32 = 16777216u;

@group(0) @binding(0) var<storage, read> draws: array<Draw>;
// The draw's texture is textures[d.tex]; samplers by wrap mode (bit 0: clamp U, bit 1: clamp V).
@group(1) @binding(0) var textures: binding_array<texture_2d<f32>, 1024>;
@group(1) @binding(1) var near0: sampler;
@group(1) @binding(2) var near1: sampler;
@group(1) @binding(3) var near2: sampler;
@group(1) @binding(4) var near3: sampler;
@group(1) @binding(5) var lin0: sampler;
@group(1) @binding(6) var lin1: sampler;
@group(1) @binding(7) var lin2: sampler;
@group(1) @binding(8) var lin3: sampler;
// Masked draws: a copy of the target being drawn.
@group(2) @binding(0) var dest: texture_2d<f32>;

// A target texel as the GS pixel (RGBA8, alpha up to 255) and back; 16-bit pixels from and to it.
fn pack32(c: vec4<f32>) -> u32 {
    let rgb = vec3<u32>(clamp(round(c.rgb * 255.0), vec3<f32>(0.0), vec3<f32>(255.0)));
    let a = u32(clamp(round(c.a * 128.0), 0.0, 255.0));
    return rgb.r | (rgb.g << 8u) | (rgb.b << 16u) | (a << 24u);
}

fn unpack32(v: u32) -> vec4<f32> {
    return vec4<f32>(vec3<f32>(f32(v & 0xFFu), f32((v >> 8u) & 0xFFu), f32((v >> 16u) & 0xFFu)) / 255.0, f32(v >> 24u) / 128.0);
}

fn to16(v: u32) -> u32 {
    return ((v >> 3u) & 0x1Fu) | (((v >> 11u) & 0x1Fu) << 5u) | (((v >> 19u) & 0x1Fu) << 10u) | ((v >> 16u) & 0x8000u);
}

fn from16(h: u32) -> u32 {
    return ((h & 0x1Fu) << 3u) | (((h >> 5u) & 0x1Fu) << 11u) | (((h >> 10u) & 0x1Fu) << 19u) | ((h & 0x8000u) << 16u);
}

fn blend_input(sel: u32, cs: vec3<i32>, cd: vec3<i32>) -> vec3<i32> {
    if (sel == 0u) {
        return cs;
    }
    if (sel == 1u) {
        return cd;
    }
    return vec3<i32>(0);
}

// FBMSK bits inside a channel: the GS blend and the bit merge done here against the destination copy.
fn masked(d: Draw, c: vec4<f32>, pos: vec2<f32>) -> vec4<f32> {
    let target16 = has(d, F_TARGET16);
    let dv = pack32(textureLoad(dest, vec2<i32>(pos), 0));
    var dst = dv;
    if (target16) {
        dst = from16(to16(dv));
    }
    var rgb = vec3<i32>(c.rgb);
    if ((d.blend & 0x10000u) != 0u) {
        let cd = vec3<i32>(i32(dst & 0xFFu), i32((dst >> 8u) & 0xFFu), i32((dst >> 16u) & 0xFFu));
        let csel = (d.blend >> 4u) & 3u;
        var cc = i32((d.blend >> 8u) & 0xFFu);
        if (csel == 0u) {
            cc = i32(c.a);
        } else if (csel == 1u) {
            cc = i32(dst >> 24u);
        }
        let a = blend_input(d.blend & 3u, rgb, cd);
        let b = blend_input((d.blend >> 2u) & 3u, rgb, cd);
        let e = blend_input((d.blend >> 6u) & 3u, rgb, cd);
        rgb = clamp((((a - b) * cc) >> vec3<u32>(7u)) + e, vec3<i32>(0), vec3<i32>(255));
    }
    var alpha = u32(c.a);
    if (has(d, F_FBA)) {
        alpha = alpha | 0x80u;
    }
    let src = u32(rgb.r) | (u32(rgb.g) << 8u) | (u32(rgb.b) << 16u) | (alpha << 24u);
    if (target16) {
        let m = to16(d.fbmsk);
        return unpack32(from16((to16(src) & ~m) | (to16(dv) & m)));
    }
    return unpack32((src & ~d.fbmsk) | (dv & d.fbmsk));
}

struct VertexIn {
    @location(0) pos: vec3<f32>,
    @location(1) color: vec4<f32>,
    @location(2) stq: vec3<f32>,
    @location(3) draw: u32,
}

struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) @interpolate(linear) color: vec4<f32>,
    @location(1) @interpolate(linear) stq: vec3<f32>,
    @location(2) @interpolate(flat) draw: u32,
}

// GS pixel x is covered when the point (x, y) is inside; hardware tests pixel centres: shift by half a pixel.
@vertex
fn vs(in: VertexIn) -> VertexOut {
    let d = draws[in.draw];
    let p = (in.pos.xy * d.scale + 0.5) / d.frame;
    var o: VertexOut;
    o.position = vec4<f32>(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0, in.pos.z, 1.0);
    o.color = in.color * 255.0;
    o.stq = in.stq;
    o.draw = in.draw;
    return o;
}

fn has(d: Draw, f: u32) -> bool {
    return (d.flags & f) != 0u;
}

fn field(d: Draw, shift: u32, bits: u32) -> u32 {
    return (d.flags >> shift) & ((1u << bits) - 1u);
}

fn texel(d: Draw, stq: vec3<f32>, pos: vec2<f32>, dx: vec2<f32>, dy: vec2<f32>) -> vec4<f32> {
    let st = stq.xy / stq.z;
    var t = st * d.tex_size;
    if (has(d, F_REPEAT_U)) {
        t.x = t.x - floor(t.x / d.tex_size.x) * d.tex_size.x;
    }
    if (has(d, F_REPEAT_V)) {
        t.y = t.y - floor(t.y / d.tex_size.y) * d.tex_size.y;
    }
    var uv = t / d.store_size;
    var lod = d.lod_k;
    if (!has(d, F_LCM)) {
        lod = log2(1.0 / abs(stq.z)) * d.lod_l + d.lod_k;
    }
    var linear = has(d, F_MAG_LINEAR);
    var level = 0.0;
    if (lod > 0.0) {
        let mmin = field(d, 10u, 3u);
        linear = mmin == 1u || mmin >= 4u;
        if (mmin >= 2u) {
            level = clamp(lod, 0.0, d.mxl);
            if (mmin == 2u || mmin == 4u) {
                level = floor(level + 0.5);
            }
        }
    }
    if (has(d, F_SOURCE_TARGET) && !linear) {
        // Nearest from a scaled target, as the GS does it: the texel is picked at the GS pixel this sub-pixel
        // belongs to and the sub-pixel keeps its place in it (1:1 copies through a reinterpreted target stay exact).
        let p = pos - 0.5;
        let sub = p - floor(p / SCALE) * SCALE;
        var g = (stq.xy / stq.z - dx * sub.x - dy * sub.y) * d.tex_size;
        if (has(d, F_REPEAT_U)) {
            g.x = g.x - floor(g.x / d.tex_size.x) * d.tex_size.x;
        }
        if (has(d, F_REPEAT_V)) {
            g.y = g.y - floor(g.y / d.tex_size.y) * d.tex_size.y;
        }
        uv = (floor(g) * SCALE + sub + 0.5) / (d.store_size * SCALE);
    }
    var c: vec4<f32>;
    switch field(d, 22u, 2u) + select(0u, 4u, linear) {
        case 0u { c = textureSampleLevel(textures[d.tex], near0, uv, level); }
        case 1u { c = textureSampleLevel(textures[d.tex], near1, uv, level); }
        case 2u { c = textureSampleLevel(textures[d.tex], near2, uv, level); }
        case 3u { c = textureSampleLevel(textures[d.tex], near3, uv, level); }
        case 4u { c = textureSampleLevel(textures[d.tex], lin0, uv, level); }
        case 5u { c = textureSampleLevel(textures[d.tex], lin1, uv, level); }
        case 6u { c = textureSampleLevel(textures[d.tex], lin2, uv, level); }
        default { c = textureSampleLevel(textures[d.tex], lin3, uv, level); }
    }
    if (!has(d, F_SOURCE_TARGET)) {
        return c * 255.0;
    }
    var rgb = clamp(round(c.rgb * 255.0), vec3<f32>(0.0), vec3<f32>(255.0));
    var a = min(round(c.a * 128.0), 255.0);
    if (has(d, F_SOURCE16)) {
        rgb = floor(rgb / 8.0) * 8.0;
        if (a >= 128.0) {
            a = d.ta1;
        } else if (has(d, F_AEM) && all(rgb == vec3<f32>(0.0))) {
            a = 0.0;
        } else {
            a = d.ta0;
        }
    }
    return vec4<f32>(rgb, a);
}

struct FragmentOut {
    @location(0) @blend_src(0) color: vec4<f32>,
    @location(0) @blend_src(1) blend: vec4<f32>,
}

@fragment
fn fs(in: VertexOut) -> FragmentOut {
    let d = draws[in.draw];
    let st = in.stq.xy / in.stq.z;
    let st_dx = dpdx(st);
    let st_dy = dpdy(st);
    var c = floor(in.color);
    if (has(d, F_TME)) {
        let t = floor(texel(d, in.stq, in.position.xy, st_dx, st_dy));
        let tcc = has(d, F_TCC);
        switch field(d, 2u, 2u) {
            case 0u {
                c = vec4<f32>(min(floor(t.rgb * c.rgb / 128.0), vec3<f32>(255.0)), select(c.a, min(floor(t.a * c.a / 128.0), 255.0), tcc));
            }
            case 1u {
                c = vec4<f32>(t.rgb, select(c.a, t.a, tcc));
            }
            case 2u {
                c = vec4<f32>(min(floor(t.rgb * c.rgb / 128.0) + c.a, vec3<f32>(255.0)), select(c.a, min(t.a + c.a, 255.0), tcc));
            }
            default {
                c = vec4<f32>(min(floor(t.rgb * c.rgb / 128.0) + c.a, vec3<f32>(255.0)), select(c.a, t.a, tcc));
            }
        }
    }
    if (has(d, F_ATE)) {
        var ok = true;
        switch field(d, 5u, 3u) {
            case 0u { ok = false; }
            case 2u { ok = c.a < d.aref; }
            case 3u { ok = c.a <= d.aref; }
            case 4u { ok = c.a == d.aref; }
            case 5u { ok = c.a >= d.aref; }
            case 6u { ok = c.a > d.aref; }
            case 7u { ok = c.a != d.aref; }
            default {}
        }
        if (!ok) {
            discard;
        }
    }
    var o: FragmentOut;
    if (has(d, F_MASKED)) {
        o.color = masked(d, c, in.position.xy);
        o.blend = vec4<f32>(0.0);
        return o;
    }
    var written = c.a;
    if (has(d, F_FBA) && written < 128.0) {
        written = written + 128.0;
    }
    o.color = vec4<f32>(select(c.rgb / 255.0, vec3<f32>(1.0), has(d, F_SRC_ONE)), written / 128.0);
    o.blend = vec4<f32>(0.0, 0.0, 0.0, c.a / 128.0);
    if (has(d, F_FACTORS)) {
        // The pipeline blends Cs * blend.rgb + Cd * blend.a: the factors 0, 1, C or 1 - C (C = As or FIX).
        let cv = select(c.a, f32((d.blend >> 8u) & 0xFFu), (d.blend & 16u) != 0u) / 128.0;
        o.blend = vec4<f32>(vec3<f32>(factor(d.blend & 3u, cv)), factor((d.blend >> 2u) & 3u, cv));
    }
    return o;
}

fn factor(kind: u32, cv: f32) -> f32 {
    switch kind {
        case 0u { return 0.0; }
        case 1u { return 1.0; }
        case 2u { return cv; }
        default { return 1.0 - cv; }
    }
}

struct FullOut {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
}

@vertex
fn vs_full(@builtin(vertex_index) i: u32) -> FullOut {
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    var o: FullOut;
    o.position = vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
    o.uv = vec2<f32>(p.x, 1.0 - p.y);
    return o;
}

// ---- GS memory on the GPU (T59b): uploads, CLUT loads and texture decodes as gs.cpp does them on the CPU.
// Address math after the vendored gs.wgsl (MIT): swizzle tables from gs::swizzle_tables, GS memory 1x.

struct Job {
    a: vec4<u32>,
    b: vec4<u32>,
    c: vec4<u32>,
}

@group(0) @binding(5) var<uniform> job: Job;
@group(0) @binding(6) var<storage, read> job_data: array<u32>;
@group(0) @binding(7) var<storage, read_write> cluts: array<u32, 512>;
@group(1) @binding(8) var<storage, read_write> vram: array<atomic<u32>>;
@group(1) @binding(9) var<storage, read> swizzle: array<u32>;
@group(2) @binding(10) var decode_out: texture_storage_2d<rgba8unorm, write>;

struct Loc {
    word: u32,
    shift: u32,
    mask: u32,
}

fn page_addr(bp: u32, bw: u32, x: u32, y: u32, pw: u32, ph: u32) -> u32 {
    let per_row = max(1u, bw * 64u / pw);
    return bp * 256u + ((x / pw) + (y / ph) * per_row) * 8192u;
}

fn locate(psm: u32, bp: u32, bw: u32, x: u32, y: u32) -> Loc {
    var a = 0u;
    var shift = 0u;
    var mask = 0xFFFFFFFFu;
    switch psm {
        case 0x30u {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[2048u + (y & 31u) * 64u + (x & 63u)];
        }
        case 0x31u {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[2048u + (y & 31u) * 64u + (x & 63u)];
            mask = 0xFFFFFFu;
        }
        case 0x01u {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[(y & 31u) * 64u + (x & 63u)];
            mask = 0xFFFFFFu;
        }
        case 0x02u {
            a = page_addr(bp, bw, x, y, 64u, 64u) + swizzle[4096u + (y & 63u) * 64u + (x & 63u)];
            shift = (a & 2u) * 8u;
            mask = 0xFFFFu;
        }
        case 0x0Au {
            a = page_addr(bp, bw, x, y, 64u, 64u) + swizzle[8192u + (y & 63u) * 64u + (x & 63u)];
            shift = (a & 2u) * 8u;
            mask = 0xFFFFu;
        }
        case 0x32u {
            a = page_addr(bp, bw, x, y, 64u, 64u) + swizzle[12288u + (y & 63u) * 64u + (x & 63u)];
            shift = (a & 2u) * 8u;
            mask = 0xFFFFu;
        }
        case 0x3Au {
            a = page_addr(bp, bw, x, y, 64u, 64u) + swizzle[16384u + (y & 63u) * 64u + (x & 63u)];
            shift = (a & 2u) * 8u;
            mask = 0xFFFFu;
        }
        case 0x13u {
            a = page_addr(bp, bw, x, y, 128u, 64u) + swizzle[20480u + (y & 63u) * 128u + (x & 127u)];
            shift = (a & 3u) * 8u;
            mask = 0xFFu;
        }
        case 0x14u {
            let n = swizzle[28672u + (y & 127u) * 128u + (x & 127u)];
            a = page_addr(bp, bw, x, y, 128u, 128u) + n / 2u;
            shift = (a & 3u) * 8u + (n & 1u) * 4u;
            mask = 0xFu;
        }
        case 0x1Bu {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[(y & 31u) * 64u + (x & 63u)];
            shift = 24u;
            mask = 0xFFu;
        }
        case 0x24u {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[(y & 31u) * 64u + (x & 63u)];
            shift = 24u;
            mask = 0xFu;
        }
        case 0x2Cu {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[(y & 31u) * 64u + (x & 63u)];
            shift = 28u;
            mask = 0xFu;
        }
        default {
            a = page_addr(bp, bw, x, y, 64u, 32u) + swizzle[(y & 31u) * 64u + (x & 63u)];
        }
    }
    return Loc((a & 0x3FFFFFu) >> 2u, shift, mask);
}

fn gs_read(psm: u32, bp: u32, bw: u32, x: u32, y: u32) -> u32 {
    let l = locate(psm, bp, bw, x, y);
    return (atomicLoad(&vram[l.word]) >> l.shift) & l.mask;
}

// Pixels narrower than a word share it with other threads: and/or keeps their bits.
fn gs_write(psm: u32, bp: u32, bw: u32, x: u32, y: u32, value: u32) {
    let l = locate(psm, bp, bw, x, y);
    if (l.mask == 0xFFFFFFFFu) {
        atomicStore(&vram[l.word], value);
        return;
    }
    atomicAnd(&vram[l.word], ~(l.mask << l.shift));
    atomicOr(&vram[l.word], (value & l.mask) << l.shift);
}

fn expand16(c: u32, ta0: u32, ta1: u32, aem: bool) -> u32 {
    var a = ta0;
    if ((c & 0x8000u) != 0u) {
        a = ta1;
    } else if (aem && (c & 0x7FFFu) == 0u) {
        a = 0u;
    }
    return ((c & 0x1Fu) << 3u) | (((c >> 5u) & 0x1Fu) << 11u) | (((c >> 10u) & 0x1Fu) << 19u) | (a << 24u);
}

fn job_bits(word: u32, bit: u32, count: u32) -> u32 {
    let w = word + bit / 32u;
    let s = bit % 32u;
    var v = job_data[w] >> s;
    if (s + count > 32u) {
        v = v | (job_data[w + 1u] << (32u - s));
    }
    if (count == 32u) {
        return v;
    }
    return v & ((1u << count) - 1u);
}

fn thread(gid: vec3<u32>) -> u32 {
    return gid.x + gid.y * 65536u;
}

// Image transfers: records of 9 words (bp, bw, psm, x, y, width, data word, bits per pixel, first thread),
// job.a = (first record word, records, threads). Bits per pixel 0: PSMT4 in whole 32 x 4 cells, a thread per word.
@compute @workgroup_size(64)
fn upload(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = thread(gid);
    if (i >= job.a.z) {
        return;
    }
    var lo = 0u;
    var hi = job.a.y;
    while (hi - lo > 1u) {
        let mid = (lo + hi) / 2u;
        if (job_data[job.a.x + mid * 9u + 8u] <= i) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let r = job.a.x + lo * 9u;
    let k = i - job_data[r + 8u];
    let w = job_data[r + 5u];
    let bpp = job_data[r + 7u];
    if (bpp == 0u) {
        upload_t4_word(r, k, w);
        return;
    }
    let x = (job_data[r + 3u] + k % w) & 0x7FFu;
    let y = (job_data[r + 4u] + k / w) & 0x7FFu;
    gs_write(job_data[r + 2u], job_data[r], job_data[r + 1u], x, y, job_bits(job_data[r + 6u], k * bpp, bpp));
}

// A PSMT4 cell (32 x 4 pixels) is 16 words: the word holding (x, y) with x % 32 < 8 and y % 4 < 2 holds x, x + 8,
// x + 16, x + 24 in its bytes, each byte (x, y) in its low nibble and (x ^ 4, y + 2) in its high nibble.
fn upload_t4_word(r: u32, k: u32, w: u32) {
    let cell = k / 16u;
    let x0 = (cell % (w / 32u)) * 32u + k % 8u;
    let y0 = (cell / (w / 32u)) * 4u + (k / 8u) % 2u;
    let data = job_data[r + 6u];
    var v = 0u;
    for (var i = 0u; i < 4u; i = i + 1u) {
        let lo = job_bits(data, (y0 * w + x0 + i * 8u) * 4u, 4u);
        let hi = job_bits(data, ((y0 + 2u) * w + ((x0 + i * 8u) ^ 4u)) * 4u, 4u);
        v = v | ((lo | (hi << 4u)) << (i * 8u));
    }
    let l = locate(0x14u, job_data[r], job_data[r + 1u], (job_data[r + 3u] + x0) & 0x7FFu, (job_data[r + 4u] + y0) & 0x7FFu);
    atomicStore(&vram[l.word], v);
}

// CLUT loads (no decode between them): records of 8 words (cbp, cpsm, csm, csa, 8-bit, cbw, cou, cov), then per
// 16-entry group the last load that writes it (~0u: none); job.a = (first record word, records). Each thread owns two
// CLUT entries and takes them from their group's last load.
@compute @workgroup_size(256)
fn load_clut(@builtin(local_invocation_index) t: u32) {
    for (var slot = t; slot < 512u; slot = slot + 256u) {
        let n = job_data[job.a.x + job.a.y * 8u + slot / 16u];
        if (n == 0xFFFFFFFFu) {
            continue;
        }
        let r = job.a.x + n * 8u;
        let cbp = job_data[r];
        let cpsm = job_data[r + 1u];
        let csa = job_data[r + 3u];
        let eight = job_data[r + 4u] != 0u;
        let entries = select(16u, 256u, eight);
        if (job_data[r + 2u] != 0u) {
            let k = (slot - csa * 16u) & 511u;
            if (k < entries) {
                cluts[slot] = gs_read(cpsm, cbp, job_data[r + 5u], job_data[r + 6u] * 16u + k, job_data[r + 7u]);
            }
        } else if (slot < 256u) {
            if (eight) {
                let j = (slot & ~0x18u) | ((slot & 0x08u) << 1u) | ((slot & 0x10u) >> 1u);
                cluts[slot] = gs_read(cpsm, cbp, 1u, j & 15u, j >> 4u);
            } else {
                let k = (slot - (csa & 15u) * 16u) & 255u;
                if (k < 16u) {
                    cluts[slot] = gs_read(cpsm, cbp, 1u, k & 7u, k >> 3u);
                }
            }
        }
    }
}

// One texture level into decode_out: job.a = (psm, bp, bw, log2 width), job.b = (texels, cpsm, csa),
// job.c = (ta0, ta1, aem). Reads the CLUT as the loads before it left it (they run before, the next after).
@compute @workgroup_size(64)
fn decode(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = thread(gid);
    if (i >= job.b.x) {
        return;
    }
    let psm = job.a.x;
    let x = i & ((1u << job.a.w) - 1u);
    let y = i >> job.a.w;
    let raw = gs_read(psm, job.a.y, job.a.z, x, y);
    let ta0 = job.c.x;
    let ta1 = job.c.y;
    let aem = job.c.z != 0u;
    var c = 0u;
    var paletted = false;
    switch psm {
        case 0x00u {
            c = raw;
        }
        case 0x01u {
            c = raw | (select(ta0, 0u, aem && raw == 0u) << 24u);
        }
        case 0x02u, 0x0Au {
            c = expand16(raw, ta0, ta1, aem);
        }
        case 0x13u, 0x1Bu {
            c = cluts[raw & 255u];
            paletted = true;
        }
        default {
            c = cluts[((job.b.z & 15u) * 16u + (raw & 15u)) & 511u];
            paletted = psm == 0x14u || psm == 0x24u || psm == 0x2Cu;
        }
    }
    if (paletted && job.b.y != 0u && job.b.y != 1u) {
        c = expand16(c, ta0, ta1, aem);
    }
    textureStore(decode_out, vec2<u32>(x, y), vec4<f32>(f32(c & 0xFFu), f32((c >> 8u) & 0xFFu), f32((c >> 16u) & 0xFFu), f32(c >> 24u)) / 255.0);
}

// A new target starts with what GS memory holds there (1x, PS2 alpha): draws[i].flags = psm, fbmsk = block
// pointer, blend = width in 64-pixel units.
@fragment
fn fs_fill(in: ConvertOut) -> @location(0) vec4<f32> {
    let d = draws[in.draw];
    let g = vec2<u32>(in.position.xy) / u32(SCALE);
    var c = gs_read(d.flags, d.fbmsk, d.blend, g.x, g.y);
    if ((d.flags & 0xFu) == 2u || (d.flags & 0xFu) == 0xAu) {
        c = expand16(c, 0u, 0x80u, false);
    } else if (d.flags == 0x01u || d.flags == 0x31u) {
        c = c | 0x80000000u;
    }
    return vec4<f32>(f32(c & 0xFFu) / 255.0, f32((c >> 8u) & 0xFFu) / 255.0, f32((c >> 16u) & 0xFFu) / 255.0, f32(c >> 24u) / 128.0);
}

struct Show {
    x: u32,
    y: u32,
    halved: u32,
    is16: u32,
}

@group(0) @binding(0) var shown: texture_2d<f32>;
@group(0) @binding(1) var<uniform> show: Show;

// The displayed buffer as 8-bit RGB, like the GS path's display readout.
@fragment
fn fs_display(in: FullOut) -> @location(0) vec4<f32> {
    let p = vec2<u32>(in.position.xy);
    var y = p.y;
    if (show.halved != 0u) {
        y = y / 2u;
    }
    let size = textureDimensions(shown);
    let at = vec2<u32>(min(show.x + p.x, size.x - 1u), min(show.y + y, size.y - 1u));
    var rgb = clamp(round(textureLoad(shown, at, 0).rgb * 255.0), vec3<f32>(0.0), vec3<f32>(255.0));
    if (show.is16 != 0u) {
        rgb = floor(rgb / 8.0) * 8.0;
    }
    return vec4<f32>(rgb / 255.0, 1.0);
}

// Format conversions between a 32-bit target and its 16-bit view, per GS pixel (sub-pixels at scale kept).
// draws[i].flags = 0 CT16 / 1 CT16S, tex_size.y = the view's first page row in the 32-bit target.
struct ConvertOut {
    @builtin(position) position: vec4<f32>,
    @location(0) @interpolate(flat) draw: u32,
}

@vertex
fn vs_convert(@builtin(vertex_index) i: u32, @builtin(instance_index) n: u32) -> ConvertOut {
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    var o: ConvertOut;
    o.position = vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
    o.draw = n;
    return o;
}

@group(1) @binding(0) var convert_src: texture_2d<f32>;
@group(1) @binding(1) var<storage, read> lut: array<u32>;

@fragment
fn fs_to16(in: ConvertOut) -> @location(0) vec4<f32> {
    let d = draws[in.draw];
    let s = u32(SCALE);
    let p = vec2<u32>(in.position.xy);
    let g = p / s;
    let e = lut[d.flags * 4096u + (g.y & 63u) * 64u + (g.x & 63u)];
    let at = vec2<u32>((g.x & ~63u) + (e & 0xFFu), (u32(d.tex_size.y) + g.y / 64u) * 32u + ((e >> 8u) & 0xFFu));
    let v = pack32(textureLoad(convert_src, at * s + p % s, 0));
    return unpack32(from16(select(v & 0xFFFFu, v >> 16u, (e >> 16u) != 0u)));
}

@fragment
fn fs_to32(in: ConvertOut) -> @location(0) vec4<f32> {
    let d = draws[in.draw];
    let s = u32(SCALE);
    let p = vec2<u32>(in.position.xy);
    let g = p / s;
    let e = lut[8192u + d.flags * 2048u + (g.y & 31u) * 64u + (g.x & 63u)];
    let base = vec2<u32>(g.x & ~63u, (g.y / 32u - u32(d.tex_size.y)) * 64u);
    let lo = base + vec2<u32>(e & 63u, (e >> 6u) & 63u);
    let hi = base + vec2<u32>((e >> 16u) & 63u, (e >> 22u) & 63u);
    let sub = p % s;
    return unpack32(to16(pack32(textureLoad(convert_src, lo * s + sub, 0))) | (to16(pack32(textureLoad(convert_src, hi * s + sub, 0))) << 16u));
}

// A target as GS pixels (1x) for read-backs into GS memory.
@group(0) @binding(0) var packed_src: texture_2d<f32>;

@fragment
fn fs_pack32(in: FullOut) -> @location(0) u32 {
    return pack32(textureLoad(packed_src, vec2<u32>(in.position.xy) * u32(SCALE), 0));
}

@fragment
fn fs_pack16(in: FullOut) -> @location(0) u32 {
    return to16(pack32(textureLoad(packed_src, vec2<u32>(in.position.xy) * u32(SCALE), 0)));
}

@group(0) @binding(0) var picture: texture_2d<f32>;
@group(0) @binding(1) var smooth_sampler: sampler;

@fragment
fn fs_blit(in: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(textureSampleLevel(picture, smooth_sampler, in.uv, 0.0).rgb, 1.0);
}
