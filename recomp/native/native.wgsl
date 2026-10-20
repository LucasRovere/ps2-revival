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
    pad0: f32,
    pad1: f32,
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

@group(0) @binding(0) var<storage, read> draws: array<Draw>;
@group(1) @binding(0) var tex: texture_2d<f32>;
@group(1) @binding(1) var near: sampler;
@group(1) @binding(2) var lin: sampler;

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

fn texel(d: Draw, stq: vec3<f32>) -> vec4<f32> {
    let st = stq.xy / stq.z;
    var t = st * d.tex_size;
    if (has(d, F_REPEAT_U)) {
        t.x = t.x - floor(t.x / d.tex_size.x) * d.tex_size.x;
    }
    if (has(d, F_REPEAT_V)) {
        t.y = t.y - floor(t.y / d.tex_size.y) * d.tex_size.y;
    }
    let uv = t / d.store_size;
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
    var c: vec4<f32>;
    if (linear) {
        c = textureSampleLevel(tex, lin, uv, level);
    } else {
        c = textureSampleLevel(tex, near, uv, level);
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
    var c = floor(in.color);
    if (has(d, F_TME)) {
        let t = floor(texel(d, in.stq));
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
    var written = c.a;
    if (has(d, F_FBA) && written < 128.0) {
        written = written + 128.0;
    }
    var o: FragmentOut;
    o.color = vec4<f32>(select(c.rgb / 255.0, vec3<f32>(1.0), has(d, F_SRC_ONE)), written / 128.0);
    o.blend = vec4<f32>(0.0, 0.0, 0.0, c.a / 128.0);
    return o;
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

// A new target starts with what GS memory holds there (rgba8 staging image, 1x, PS2 alpha).
@group(0) @binding(0) var staging: texture_2d<f32>;

@fragment
fn fs_init(in: FullOut) -> @location(0) vec4<f32> {
    let c = textureLoad(staging, vec2<i32>(in.position.xy / SCALE), 0);
    return vec4<f32>(c.rgb, c.a * 255.0 / 128.0);
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

@group(0) @binding(0) var picture: texture_2d<f32>;
@group(0) @binding(1) var smooth_sampler: sampler;

@fragment
fn fs_blit(in: FullOut) -> @location(0) vec4<f32> {
    return vec4<f32>(textureSampleLevel(picture, smooth_sampler, in.uv, 0.0).rgb, 1.0);
}
