#include "native.hpp"
#include "../ps2-web-recomp/runtime/src/gs/gpu/texpack.hpp"

#include <webgpu/webgpu.h>
#ifndef __EMSCRIPTEN__
#include <webgpu/wgpu.h>
#endif

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <unordered_map>

extern const char kNativeShader[];

namespace ps2::gs {
void swizzle_tables(std::vector<std::uint32_t> &out);
}

namespace ps2::native {

namespace {

using gs::State;
using gs::Vertex;
namespace texpack = gs::texpack;

constexpr WGPUTextureFormat kColor = WGPUTextureFormat_RGBA16Float;
constexpr WGPUTextureFormat kDepth = WGPUTextureFormat_Depth32Float;
constexpr std::uint32_t kPages = gs::kMemorySize / 8192;

WGPUStringView view(const char *s) { return {s, WGPU_STRLEN}; }

std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
    h ^= v + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2);
    return h * 0xFF51AFD7ED558CCDull;
}

bool g_on = false;
WGPUInstance g_instance = nullptr;
WGPUAdapter g_adapter = nullptr;
WGPUDevice g_device = nullptr;
WGPUQueue g_queue = nullptr;
std::uint32_t g_scale = 1;
float g_aspect_w = 4.0f, g_aspect_h = 3.0f;
bool g_packs = false;

WGPUShaderModule g_module = nullptr;
WGPUBindGroupLayout g_params_layout = nullptr, g_texture_layout = nullptr;
WGPUPipelineLayout g_draw_layout = nullptr;
WGPUBindGroupLayout g_dest_layout = nullptr, g_convert_layout = nullptr;
WGPUPipelineLayout g_convert_pipeline_layout = nullptr;
WGPURenderPipeline g_init_pipeline = nullptr, g_display_pipeline = nullptr, g_blit_pipeline = nullptr;
WGPURenderPipeline g_to16_pipeline = nullptr, g_to32_pipeline = nullptr, g_pack16_pipeline = nullptr, g_pack32_pipeline = nullptr;
WGPUBuffer g_lut = nullptr;
WGPUSampler g_near[4] = {}, g_lin[4] = {}, g_smooth = nullptr;
std::map<std::uint32_t, WGPURenderPipeline> g_pipelines;

// Counters for the exit line.
std::uint64_t g_prims = 0, g_triangles = 0, g_sprites = 0, g_skipped[8] = {}, g_decoded = 0, g_replaced = 0, g_flushes = 0;
std::uint64_t g_conversions = 0, g_read_backs = 0, g_masked = 0;
std::map<std::string, std::uint64_t> g_missing;

// PS2_NATIVE_TIME: render-thread split, counts and GPU time per present, printed every 600 presents (window).
enum Time { T_REBUILD, T_DECODE, T_UPLOAD, T_TAG, T_SUBMIT, T_PRESENT, T_ACQUIRE, T_TIMES };
enum Count { C_REBUILD, C_PASS, C_DRAW, C_COPY, C_SUBMIT, C_UPLOAD, C_COUNTS };
bool g_time = false;
double g_time_ms[T_TIMES] = {}, g_gpu_ms = 0.0;
std::uint64_t g_counts[C_COUNTS] = {}, g_gpu_frames = 0, g_timed_presents = 0;
// GPU time: a timestamp at the start and end of every command encoder, summed per present.
constexpr std::uint32_t kStamps = 512;
WGPUQuerySet g_stamps = nullptr;
WGPUBuffer g_stamp_resolve = nullptr, g_stamp_read[3] = {};
bool g_stamp_busy[3] = {};
std::uint32_t g_stamp_count = 0, g_stamp_ring = 0;

struct Timer {
    Time what;
    std::chrono::steady_clock::time_point start;
    explicit Timer(Time w) : what(w) {
        if (g_time) start = std::chrono::steady_clock::now();
    }
    ~Timer() {
        if (g_time) g_time_ms[what] += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    }
};

void count(Count c) {
    if (g_time) ++g_counts[c];
}

void missing(const std::string &what) {
    if (g_missing[what]++ == 0) std::fprintf(stderr, "[native] not done yet: %s\n", what.c_str());
}

struct Target {
    std::uint32_t fbp = 0, fbw = 0, psm = 0, width = 0, height = 0;
    WGPUTexture tex = nullptr;
    WGPUTextureView view = nullptr;
    std::uint32_t version = 0;
    std::uint64_t stamp = 0;  // when its content last changed (g_stamp): overlapping targets read back oldest first
    WGPUTexture copy = nullptr;
    WGPUTextureView copy_view = nullptr;
    std::uint32_t copy_version = ~0u;
    WGPUBindGroup group = nullptr, copy_group = nullptr, dest_group = nullptr;
    // GS pixels drawn since the copy was made (x0, y0, x1, y1).
    std::int32_t dirty[4] = {0, 0, 0, 0};
    // A 16-bit view of a 32-bit target's memory (same width, from page row prow): drawn and read as its own
    // texture, converted from the parent before use and back into it before the parent's next use.
    Target *parent = nullptr;
    std::uint32_t prow = 0, synced = ~0u;
    bool ahead = false;
    bool sixteen() const { return (psm & 0xFu) == 2u || (psm & 0xFu) == 0xAu; }
    std::uint32_t bytes() const { return (fbw * 64u) * ((height + 63u) & ~63u) * (sixteen() ? 2u : 4u); }
};

struct Depth {
    WGPUTexture tex = nullptr;
    WGPUTextureView view = nullptr;
    bool cleared = false;
};

struct Texture {
    WGPUTexture tex = nullptr;
    WGPUTextureView view = nullptr;
    WGPUBindGroup groups[4] = {};
    std::uint64_t used = 0;
};

std::unordered_map<std::uint32_t, Target> g_targets;
std::uint64_t g_stamp = 0;
std::unordered_map<std::uint64_t, Depth> g_depths;
std::unordered_map<std::uint64_t, Texture> g_textures;
std::uint64_t g_texture_clock = 0;
WGPUBindGroup g_blank_group = nullptr, g_blank_dest_group = nullptr;

// Kept alive until the commands that use them are submitted.
std::vector<WGPUTexture> g_dead_textures;
std::vector<WGPUTextureView> g_dead_views;
std::vector<WGPUBindGroup> g_dead_groups;

struct NVertex {
    float x, y, z;
    std::uint32_t rgba;
    float s, t, q;
    std::uint32_t param;
};

struct Params {
    float target[2], scale;
    std::uint32_t flags;
    float tex_size[2], store_size[2], aref, lod_l, lod_k, mxl, ta0, ta1;
    // Masked draws: FBMSK (plus channels the draw does not write) and ALPHA | FIX << 8 | blend on << 16.
    std::uint32_t fbmsk, blend;
    bool operator==(const Params &) const = default;
};

enum : std::uint32_t {
    F_TME = 1u, F_TCC = 2u, F_ATE = 16u, F_FBA = 256u, F_MAG_LINEAR = 512u, F_LCM = 8192u, F_REPEAT_U = 16384u,
    F_REPEAT_V = 32768u, F_SOURCE16 = 65536u, F_SRC_ONE = 131072u, F_AEM = 262144u, F_SOURCE_TARGET = 524288u,
    F_MASKED = 1048576u, F_TARGET16 = 2097152u,
};

enum class OpKind { pass, draw, copy, init, convert };

struct Op {
    OpKind kind;
    WGPUTextureView color = nullptr, depth = nullptr;
    bool clear_depth = false;
    WGPURenderPipeline pipeline = nullptr;
    WGPUBindGroup group = nullptr, dest = nullptr;
    std::uint32_t first = 0, count = 0, param = 0;
    std::uint32_t scissor[4] = {};
    float fix = 0.0f;
    WGPUTexture src = nullptr, dst = nullptr;
    std::uint32_t width = 0, height = 0;
};

std::vector<Op> g_ops;
std::vector<NVertex> g_vertices;
std::vector<Params> g_params;
WGPUBuffer g_vertex_buffer = nullptr, g_param_buffer = nullptr;
std::uint64_t g_vertex_capacity = 0, g_param_capacity = 0;
WGPUBindGroup g_param_group = nullptr;
const Target *g_pass_target = nullptr;
const Depth *g_pass_depth = nullptr;

// Uploads change GS memory pages; textures are keyed by a hash of the pages under them.
std::uint32_t g_page_gen[kPages], g_page_hashed[kPages];
std::uint64_t g_page_hash[kPages];
std::uint32_t g_upload_serial = 1, g_clut_version = 1;

struct Upload {
    bool active = false;
    std::uint32_t bp = 0, bw = 0, psm = 0, x = 0, y = 0, w = 0, h = 0;
    std::size_t expected = 0;
    std::vector<std::uint8_t> bytes;
    std::uint32_t lo = 0, hi = 0;
    std::vector<Target *> targets;  // targets whose memory it writes: read back first, refilled after
} g_upload;

// Draw state rebuilt when a GS register other than a vertex register changes (gs::g_setup_generation).
// The registers a draw state depends on, to skip rebuilding when a write left them as they were.
struct Regs {
    std::uint64_t attr, tex0, clamp, tex1, xyoffset, miptbp1, miptbp2, scissor, alpha, test, fba, frame, zbuf, texa, dthe, pabe, colclamp;
    bool operator==(const Regs &) const = default;
};

Regs regs_of(const State &st, std::uint64_t attr) {
    const gs::Context &c = st.ctx[(attr >> 9) & 1u];
    return {attr, c.tex0, c.clamp, c.tex1, c.xyoffset, c.miptbp1, c.miptbp2, c.scissor, c.alpha, c.test, c.fba, c.frame, c.zbuf, st.texa, st.dthe, st.pabe, st.colclamp};
}

struct Current {
    bool valid = false, skip = false, textured = false;
    Regs regs{};
    std::uint32_t generation = 0, clut = 0, upload = 0;
    std::uint64_t attr = 0;
    Target *target = nullptr;
    Depth *depth = nullptr;
    WGPURenderPipeline pipeline = nullptr;
    WGPUBindGroup group = nullptr, dest = nullptr;
    bool masked = false;
    Params params{};
    std::uint32_t param = ~0u;
    std::uint32_t scissor[4] = {};
    std::int32_t scissor_y1 = 0;
    float fix = 0.0f;
    float ofx = 0, ofy = 0, inv_tw = 1, inv_th = 1, z_scale = 1;
    std::uint32_t z_max = 0xFFFFFFu;
    bool fst = false, iip = false;
} g_cur;

std::uint32_t bits_per_pixel(std::uint32_t psm) {
    switch (psm) {
    case gs::PSMCT24: case gs::PSMZ24: return 24;
    case gs::PSMCT16: case gs::PSMCT16S: case gs::PSMZ16: case gs::PSMZ16S: return 16;
    case gs::PSMT8: case gs::PSMT8H: return 8;
    case gs::PSMT4: case gs::PSMT4HL: case gs::PSMT4HH: return 4;
    default: return 32;
    }
}

void page_size(std::uint32_t psm, std::uint32_t &pw, std::uint32_t &ph) {
    const std::uint32_t bits = bits_per_pixel(psm);
    pw = bits <= 8 && psm != gs::PSMT8H && psm != gs::PSMT4HL && psm != gs::PSMT4HH ? 128 : 64;
    ph = bits == 4 && psm == gs::PSMT4 ? 128 : (bits == 16 || psm == gs::PSMT8) ? 64 : 32;
}

// Calls f with each page under a w x h image at block pointer bp (an image need not start on a page).
template <typename F>
void for_pages(std::uint32_t bp, std::uint32_t bw, std::uint32_t psm, std::uint32_t x, std::uint32_t y, std::uint32_t w, std::uint32_t h, F &&f) {
    std::uint32_t pw, ph;
    page_size(psm, pw, ph);
    const std::uint32_t per_row = std::max<std::uint32_t>(1, bw * 64 / pw);
    for (std::uint32_t py = y / ph; py <= (y + std::max(h, 1u) - 1) / ph; ++py)
        for (std::uint32_t px = x / pw; px <= (x + std::max(w, 1u) - 1) / pw; ++px) {
            const std::uint64_t at = bp * 256ull + (px + py * per_row) * 8192ull;
            f(static_cast<std::uint32_t>(at >> 13) % kPages);
            if (bp & 31u) f(static_cast<std::uint32_t>((at + 8191) >> 13) % kPages);
        }
}

std::uint64_t page_hash(std::uint32_t page) {
    if (g_page_hashed[page] != g_page_gen[page]) {
        const std::uint8_t *p = gs::memory() + page * 8192u;
        std::uint64_t h = 0xCBF29CE484222325ull;
        for (std::uint32_t i = 0; i < 8192; i += 8) {
            std::uint64_t v;
            std::memcpy(&v, p + i, 8);
            h = (h ^ v) * 0x100000001B3ull;
        }
        g_page_hash[page] = h ^ (h >> 29);
        g_page_hashed[page] = g_page_gen[page];
    }
    return g_page_hash[page];
}

WGPUBuffer make_buffer(std::uint64_t size, WGPUBufferUsage usage) {
    WGPUBufferDescriptor d = WGPU_BUFFER_DESCRIPTOR_INIT;
    d.size = size;
    d.usage = usage;
    return wgpuDeviceCreateBuffer(g_device, &d);
}

WGPUTexture make_texture(std::uint32_t w, std::uint32_t h, WGPUTextureFormat format, WGPUTextureUsage usage, std::uint32_t levels = 1) {
    WGPUTextureDescriptor d = WGPU_TEXTURE_DESCRIPTOR_INIT;
    d.size = {std::max(w, 1u), std::max(h, 1u), 1};
    d.format = format;
    d.usage = usage;
    d.mipLevelCount = levels;
    return wgpuDeviceCreateTexture(g_device, &d);
}

WGPUTextureView make_view(WGPUTexture t) { return wgpuTextureCreateView(t, nullptr); }

void write_texture(WGPUTexture t, std::uint32_t level, std::uint32_t w, std::uint32_t h, const void *data) {
    WGPUTexelCopyTextureInfo dst = WGPU_TEXEL_COPY_TEXTURE_INFO_INIT;
    dst.texture = t;
    dst.mipLevel = level;
    WGPUTexelCopyBufferLayout layout = WGPU_TEXEL_COPY_BUFFER_LAYOUT_INIT;
    layout.bytesPerRow = w * 4;
    layout.rowsPerImage = h;
    const WGPUExtent3D size{w, h, 1};
    wgpuQueueWriteTexture(g_queue, &dst, data, static_cast<std::size_t>(w) * h * 4, &layout, &size);
}

WGPUBindGroup texture_group(WGPUTextureView v, std::uint32_t wrap) {
    WGPUBindGroupEntry e[3] = {WGPU_BIND_GROUP_ENTRY_INIT, WGPU_BIND_GROUP_ENTRY_INIT, WGPU_BIND_GROUP_ENTRY_INIT};
    e[0].binding = 0;
    e[0].textureView = v;
    e[1].binding = 1;
    e[1].sampler = g_near[wrap];
    e[2].binding = 2;
    e[2].sampler = g_lin[wrap];
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = g_texture_layout;
    d.entryCount = 3;
    d.entries = e;
    return wgpuDeviceCreateBindGroup(g_device, &d);
}

// ---- GS memory decode (textures and new targets read what uploads put there) ----

std::uint32_t expand16(std::uint32_t c, std::uint32_t ta0, std::uint32_t ta1, bool aem) {
    std::uint32_t a = ta0;
    if (c & 0x8000u) a = ta1;
    else if (aem && !(c & 0x7FFFu)) a = 0;
    return ((c & 0x1Fu) << 3) | (((c >> 5) & 0x1Fu) << 11) | (((c >> 10) & 0x1Fu) << 19) | (a << 24);
}

struct TexFormat {
    std::uint32_t psm, cpsm, csa, ta0, ta1;
    bool aem;
};

void decode(const TexFormat &f, std::uint32_t bp, std::uint32_t bw, std::uint32_t w, std::uint32_t h, std::vector<std::uint32_t> &out) {
    out.resize(static_cast<std::size_t>(w) * h);
    const std::uint32_t *clut = gs::g_state.clut;
    const bool clut16 = f.cpsm != gs::PSMCT32 && f.cpsm != gs::PSMCT24;
    for (std::uint32_t y = 0; y < h; ++y)
        for (std::uint32_t x = 0; x < w; ++x) {
            const std::uint32_t raw = gs::read_pixel(f.psm, bp, bw, x, y);
            std::uint32_t c;
            switch (f.psm) {
            case gs::PSMCT32: c = raw; break;
            case gs::PSMCT24: c = raw | (((f.aem && !raw) ? 0u : f.ta0) << 24); break;
            case gs::PSMCT16: case gs::PSMCT16S: c = expand16(raw, f.ta0, f.ta1, f.aem); break;
            case gs::PSMT8: case gs::PSMT8H: c = clut[raw & 255u]; break;
            default: c = clut[((f.csa & 15u) * 16u + (raw & 15u)) & 511u]; break;
            }
            if (clut16 && (bits_per_pixel(f.psm) <= 8)) c = expand16(c, f.ta0, f.ta1, f.aem);
            out[static_cast<std::size_t>(y) * w + x] = c;
        }
}

// ---- Uploads and CLUT loads into the CPU copy of GS memory ----

namespace swz {
std::vector<std::uint32_t> g_tables;
const std::uint32_t *off32, *offz32, *off16, *off16s, *offz16, *offz16s, *off8, *off4;
}

void load_tables() {
    using namespace swz;
    gs::swizzle_tables(g_tables);
    const std::uint32_t *t = g_tables.data();
    off32 = t, t += 32 * 64;
    offz32 = t, t += 32 * 64;
    off16 = t, t += 64 * 64;
    off16s = t, t += 64 * 64;
    offz16 = t, t += 64 * 64;
    offz16s = t, t += 64 * 64;
    off8 = t, t += 64 * 128;
    off4 = t;
}

// Where 16-bit pixels sit in 32-bit ones within a page (CT16, then CT16S): 4096 entries per format
// for a 64x64 16-bit page (32-bit pixel x | y << 8 | upper half << 16), then 2048 per format for a 64x32
// 32-bit page (the 16-bit pixels in its lower and upper half, x | y << 6 each, upper << 16).
WGPUBuffer make_lut() {
    using namespace swz;
    std::vector<std::uint32_t> lut(2 * 4096 + 2 * 2048, 0), at32(2048);
    for (std::uint32_t i = 0; i < 2048; ++i) at32[off32[i] / 4] = i;
    for (std::uint32_t f = 0; f < 2; ++f) {
        const std::uint32_t *o16 = f ? off16s : off16;
        for (std::uint32_t i = 0; i < 4096; ++i) {
            const std::uint32_t p = at32[o16[i] / 4], upper = (o16[i] >> 1) & 1u;
            lut[f * 4096 + i] = (p & 63u) | ((p >> 6) << 8) | (upper << 16);
            lut[8192 + f * 2048 + p] |= i << (upper * 16);
        }
    }
    WGPUBuffer b = make_buffer(lut.size() * 4, WGPUBufferUsage_Storage | WGPUBufferUsage_CopyDst);
    wgpuQueueWriteBuffer(g_queue, b, 0, lut.data(), lut.size() * 4);
    return b;
}

// One row of an image transfer into GS memory (page widths and heights are powers of two).
template <std::uint32_t Bits>
void write_row(std::uint8_t *mem, const std::uint8_t *d, std::size_t bit, const std::uint32_t *trow, std::uint32_t base, std::uint32_t x0, std::uint32_t w, std::uint32_t pws) {
    const std::uint32_t pmask = (1u << pws) - 1;
    for (std::uint32_t col = 0; col < w; ++col, bit += Bits) {
        const std::uint32_t x = (x0 + col) & 0x7FFu;
        const std::uint32_t at = trow[x & pmask];
        const std::uint32_t page = base + (x >> pws) * 8192u;
        if constexpr (Bits == 4) {
            const std::uint32_t v = (d[bit / 8] >> (bit & 4)) & 15u;
            std::uint8_t &b = mem[(page + at / 2) & (gs::kMemorySize - 1)];
            b = (at & 1u) ? static_cast<std::uint8_t>((b & 0x0Fu) | (v << 4)) : static_cast<std::uint8_t>((b & 0xF0u) | v);
        } else {
            std::memcpy(mem + ((page + at) & (gs::kMemorySize - 1)), d + bit / 8, Bits / 8);
        }
    }
}

// PSMT4 rectangles aligned to 8 x 4: the byte holding pixel (x, y) also holds (x ^ 4, y ^ 2) (low nibble when y & 2
// is 0), and from x % 32 == 0 the word holding (x, y) holds x, x + 8, x + 16, x + 24 in its bytes: whole bytes or words
// instead of nibbles (T4 uploads were the slowest part of the upload copy).
void write_t4(const Upload &u, std::uint8_t *mem, std::uint32_t per_row, std::uint32_t pws, std::uint32_t phs, std::uint32_t pw, std::uint32_t ph) {
    const std::uint8_t *d = u.bytes.data();
    const std::uint32_t w = u.w;
    const auto byte = [&](std::uint32_t row, std::uint32_t col) {
        const std::size_t i = static_cast<std::size_t>(row) * w + col, j = static_cast<std::size_t>(row + 2) * w + (col ^ 4u);
        return ((d[i / 2] >> ((i & 1u) * 4)) & 15u) | (((d[j / 2] >> ((j & 1u) * 4)) & 15u) << 4);
    };
    for (std::uint32_t row = 0; row < u.h; ++row) {
        const std::uint32_t y = (u.y + row) & 0x7FFu;
        if (y & 2u) continue;
        const std::uint32_t base = u.bp * 256u + (y >> phs) * per_row * 8192u;
        const std::uint32_t *trow = swz::off4 + (y & (ph - 1)) * pw;
        std::uint32_t col = 0;
        for (; u.x % 32 == 0 && col + 32 <= w; col += 32)
            for (std::uint32_t j = 0; j < 8; ++j) {
                const std::uint32_t x = (u.x + col + j) & 0x7FFu;
                const std::uint32_t at = base + (x >> pws) * 8192u + trow[x & (pw - 1)] / 2;
                const std::uint32_t word = byte(row, col + j) | byte(row, col + j + 8) << 8 | byte(row, col + j + 16) << 16 | byte(row, col + j + 24) << 24;
                std::memcpy(mem + (at & (gs::kMemorySize - 4)), &word, 4);
            }
        for (; col < w; ++col) {
            const std::uint32_t x = (u.x + col) & 0x7FFu;
            mem[(base + (x >> pws) * 8192u + trow[x & (pw - 1)] / 2) & (gs::kMemorySize - 1)] = static_cast<std::uint8_t>(byte(row, col));
        }
    }
}

// Writes a finished image transfer as gs.cpp's per-pixel transfer would.
void write_upload(const Upload &u) {
    using namespace swz;
    std::uint8_t *mem = gs::memory();
    const std::uint8_t *d = u.bytes.data();
    std::uint32_t pw, ph;
    page_size(u.psm, pw, ph);
    const std::uint32_t per_row = std::max<std::uint32_t>(1, u.bw * 64 / pw), bits = bits_per_pixel(u.psm);
    const std::uint32_t pws = static_cast<std::uint32_t>(std::countr_zero(pw)), phs = static_cast<std::uint32_t>(std::countr_zero(ph));
    const std::uint32_t *table = nullptr;
    switch (u.psm) {
    case gs::PSMCT32: case gs::PSMCT24: table = off32; break;
    case gs::PSMZ32: case gs::PSMZ24: table = offz32; break;
    case gs::PSMCT16: table = off16; break;
    case gs::PSMCT16S: table = off16s; break;
    case gs::PSMZ16: table = offz16; break;
    case gs::PSMZ16S: table = offz16s; break;
    case gs::PSMT8: table = off8; break;
    case gs::PSMT4: table = off4; break;
    default: break;
    }
    const std::size_t row_bits = static_cast<std::size_t>(u.w) * bits;
    const std::uint32_t rows = static_cast<std::uint32_t>(std::min<std::size_t>(u.h, u.bytes.size() * 8 / std::max<std::size_t>(row_bits, 1)));
    if (u.psm == gs::PSMT4 && rows == u.h && u.x % 8 == 0 && u.w % 8 == 0 && u.y % 4 == 0 && u.h % 4 == 0) {
        write_t4(u, mem, per_row, pws, phs, pw, ph);
        return;
    }
    for (std::uint32_t row = 0; row < rows; ++row) {
        const std::uint32_t y = (u.y + row) & 0x7FFu;
        const std::size_t bit = row * row_bits;
        if (!table) {
            for (std::uint32_t col = 0; col < u.w; ++col) {
                std::uint32_t v = 0;
                const std::size_t b = bit + static_cast<std::size_t>(col) * bits;
                if (bits == 4) v = (d[b / 8] >> (b & 4)) & 15u;
                else std::memcpy(&v, d + b / 8, bits / 8);
                gs::write_pixel(u.psm, u.bp, u.bw, (u.x + col) & 0x7FFu, y, v);
            }
            continue;
        }
        const std::uint32_t base = u.bp * 256u + (y >> phs) * per_row * 8192u;
        const std::uint32_t *trow = table + (y & (ph - 1)) * pw;
        switch (bits) {
        case 32: write_row<32>(mem, d, bit, trow, base, u.x, u.w, pws); break;
        case 24: write_row<24>(mem, d, bit, trow, base, u.x, u.w, pws); break;
        case 16: write_row<16>(mem, d, bit, trow, base, u.x, u.w, pws); break;
        case 8: write_row<8>(mem, d, bit, trow, base, u.x, u.w, pws); break;
        default: write_row<4>(mem, d, bit, trow, base, u.x, u.w, pws); break;
        }
    }
}

struct ClutLoad {
    std::uint64_t tex0 = 0, texclut = 0;
    std::uint32_t upload = 0;
} g_last_clut;

// gs.cpp's CLUT load (CSM1 and CSM0), skipped when it repeats the last one with no upload since.
void read_clut(std::uint64_t tex0, std::uint64_t texclut) {
    const std::uint64_t fields = tex0 & 0x1FFFFFE000000000ull, tc = texclut & 0x3FFFFFu;
    const std::uint32_t psm = static_cast<std::uint32_t>(tex0 >> 20) & 0x3Fu;
    if (g_last_clut.tex0 == (fields | psm) && g_last_clut.texclut == tc && g_last_clut.upload == g_upload_serial) return;
    g_last_clut = {fields | psm, tc, g_upload_serial};
    const std::uint32_t cbp = static_cast<std::uint32_t>(tex0 >> 37) & 0x3FFFu, cpsm = static_cast<std::uint32_t>(tex0 >> 51) & 0xFu;
    const std::uint32_t csm = static_cast<std::uint32_t>(tex0 >> 55) & 1u, csa = static_cast<std::uint32_t>(tex0 >> 56) & 0x1Fu;
    const bool eight = psm == gs::PSMT8 || psm == gs::PSMT8H;
    const std::uint32_t entries = eight ? 256u : 16u, cbw = static_cast<std::uint32_t>(tc) & 0x3Fu;
    const std::uint32_t cou = (static_cast<std::uint32_t>(tc) >> 6) & 0x3Fu, cov = (static_cast<std::uint32_t>(tc) >> 12) & 0x3FFu;
    std::uint32_t *clut = gs::g_state.clut;
    bool changed = false;
    for (std::uint32_t i = 0; i < entries; ++i) {
        std::uint32_t x, y, slot;
        if (csm) {
            x = cou * 16 + i, y = cov, slot = (csa * 16 + i) & 511u;
        } else if (eight) {
            const std::uint32_t j = (i & ~0x18u) | ((i & 0x08u) << 1) | ((i & 0x10u) >> 1);
            x = j & 15u, y = j >> 4, slot = i;
        } else {
            x = i & 7u, y = i >> 3, slot = ((csa & 15u) * 16u + i) & 255u;
        }
        const std::uint32_t c = gs::read_pixel(cpsm == 0 ? gs::PSMCT32 : cpsm, cbp, csm ? cbw : 1u, x, y);
        changed = changed || clut[slot] != c;
        clut[slot] = c;
    }
    if (changed) ++g_clut_version;
}

// ---- Render targets ----

void submit_ops();
void submit_commands(WGPUCommandEncoder enc);
void read_pixels(WGPUTexture tex, std::uint32_t width, std::uint32_t height, std::vector<std::uint32_t> &out);

WGPUCommandEncoder encoder() {
    WGPUCommandEncoder enc = wgpuDeviceCreateCommandEncoder(g_device, nullptr);
#ifndef __EMSCRIPTEN__
    if (g_stamps && g_stamp_count + 2 <= kStamps) wgpuCommandEncoderWriteTimestamp(enc, g_stamps, g_stamp_count++);
#endif
    return enc;
}

std::uint32_t target_key(std::uint32_t fbp, std::uint32_t fbw, std::uint32_t psm) { return fbp | (fbw << 9) | (psm << 15); }

Target *find_target(std::uint32_t fbp, std::uint32_t psm) {
    Target *best = nullptr;
    for (auto &[key, t] : g_targets)
        if (t.fbp == fbp && (t.psm == psm || (bits_per_pixel(t.psm) >= 24 && bits_per_pixel(psm) >= 24))) best = &t;
    return best;
}

// Does [lo, hi) of GS memory overlap a target's memory?
const Target *target_under(std::uint32_t lo, std::uint32_t hi) {
    for (auto &[key, t] : g_targets) {
        const std::uint32_t tlo = t.fbp * 8192u, thi = tlo + t.bytes();
        if (lo < thi && tlo < hi) return &t;
    }
    return nullptr;
}

// Targets over [lo, hi) of GS memory, oldest content first: read back in this order, the newest wins.
std::vector<Target *> targets_under(std::uint32_t lo, std::uint32_t hi) {
    std::vector<Target *> out;
    for (auto &[key, t] : g_targets)
        if (t.tex && lo < t.fbp * 8192u + t.bytes() && t.fbp * 8192u < hi) out.push_back(&t);
    std::sort(out.begin(), out.end(), [](const Target *a, const Target *b) { return a->stamp < b->stamp; });
    return out;
}

void drop_texture(WGPUTexture &t, WGPUTextureView &v) {
    if (t) g_dead_textures.push_back(t);
    if (v) g_dead_views.push_back(v);
    t = nullptr;
    v = nullptr;
}

void drop_group(WGPUBindGroup &g) {
    if (g) g_dead_groups.push_back(g);
    g = nullptr;
}

void end_pass() { g_pass_target = nullptr, g_pass_depth = nullptr; }

// GS memory's content drawn into rows [from_row, to_row) of a target (new targets, state loads, uploads).
void fill_target(Target &t, std::uint32_t from_row, std::uint32_t to_row) {
    const std::uint32_t w = t.width, h = t.height;
    std::vector<std::uint32_t> rgba(static_cast<std::size_t>(w) * h);
    for (std::uint32_t y = from_row; y < to_row; ++y)
        for (std::uint32_t x = 0; x < w; ++x) {
            std::uint32_t c = gs::read_pixel(t.psm, t.fbp * 32u, t.fbw, x, y);
            if (t.sixteen()) c = expand16(c, 0, 0x80, false);
            else if (bits_per_pixel(t.psm) == 24) c |= 0x80000000u;
            rgba[static_cast<std::size_t>(y) * w + x] = c;
        }
    WGPUTexture staging = make_texture(w, h, WGPUTextureFormat_RGBA8Unorm, WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopyDst);
    write_texture(staging, 0, w, h, rgba.data());
    WGPUTextureView staging_view = make_view(staging);
    WGPUBindGroupEntry e = WGPU_BIND_GROUP_ENTRY_INIT;
    e.binding = 0;
    e.textureView = staging_view;
    WGPUBindGroupLayout layout = wgpuRenderPipelineGetBindGroupLayout(g_init_pipeline, 0);
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = layout;
    d.entryCount = 1;
    d.entries = &e;
    Op op{OpKind::init};
    op.group = wgpuDeviceCreateBindGroup(g_device, &d);
    wgpuBindGroupLayoutRelease(layout);
    op.color = t.view;
    op.scissor[1] = from_row * g_scale;
    op.scissor[3] = to_row * g_scale;
    op.width = w * g_scale;
    op.height = t.height * g_scale;
    g_ops.push_back(op);
    g_dead_groups.push_back(op.group);
    g_dead_views.push_back(staging_view);
    g_dead_textures.push_back(staging);
    end_pass();
}

// ---- Format reinterpretation: 16-bit views of 32-bit targets ----

// One conversion pass over the page rows a view shares with its parent (lookup tables from the GS swizzles).
void push_convert(Target &v, bool into_view) {
    Target &p = *v.parent;
    const std::uint32_t rows = std::min(p.height / 32u > v.prow ? p.height / 32u - v.prow : 0u, v.height / 64u);
    if (!rows) return;
    Params q{};
    q.flags = v.psm == gs::PSMCT16S ? 1u : 0u;
    q.tex_size[1] = static_cast<float>(v.prow);
    g_params.push_back(q);
    WGPUBindGroupEntry e[2] = {WGPU_BIND_GROUP_ENTRY_INIT, WGPU_BIND_GROUP_ENTRY_INIT};
    e[0].binding = 0;
    e[0].textureView = into_view ? p.view : v.view;
    e[1].binding = 1;
    e[1].buffer = g_lut;
    e[1].size = WGPU_WHOLE_SIZE;
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = g_convert_layout;
    d.entryCount = 2;
    d.entries = e;
    Op op{OpKind::convert};
    op.pipeline = into_view ? g_to16_pipeline : g_to32_pipeline;
    op.group = wgpuDeviceCreateBindGroup(g_device, &d);
    g_dead_groups.push_back(op.group);
    op.color = into_view ? v.view : p.view;
    op.param = static_cast<std::uint32_t>(g_params.size() - 1);
    op.scissor[1] = into_view ? 0u : v.prow * 32u * g_scale;
    op.scissor[2] = v.width * g_scale;
    op.scissor[3] = rows * (into_view ? 64u : 32u) * g_scale;
    g_ops.push_back(op);
    end_pass();
    (into_view ? v : p).stamp = ++g_stamp;
    ++g_conversions;
}

void write_back(Target &p, const Target *except) {
    for (auto &[key, v] : g_targets)
        if (v.parent == &p && v.ahead && &v != except) {
            push_convert(v, false);
            v.ahead = false;
            v.synced = ++p.version;
        }
}

// Before a target is drawn, read, shown or read back: views drawn since go into their parent first,
// and a view gets the parent's content when the parent changed.
void resolve(Target &t) {
    if (!t.parent) {
        write_back(t, nullptr);
        return;
    }
    write_back(*t.parent, &t);
    if (!t.ahead && t.synced != t.parent->version) {
        push_convert(t, true);
        t.synced = t.parent->version;
        ++t.version;
    }
}

// The 32-bit target (CT32/CT24, same width) whose memory a 16-bit frame or texture at fbp lies in, from a page row.
Target *parent_of(std::uint32_t fbp, std::uint32_t fbw, std::uint32_t psm) {
    if ((psm != gs::PSMCT16 && psm != gs::PSMCT16S) || !fbw) return nullptr;
    for (auto &[key, p] : g_targets)
        if (p.tex && (p.psm & ~1u) == 0 && p.fbw == fbw && fbp >= p.fbp && (fbp - p.fbp) % fbw == 0 && (fbp - p.fbp) / fbw < p.height / 32u) return &p;
    return nullptr;
}

void make_target_texture(Target &t, std::uint32_t height) {
    const WGPUTexture old = t.tex;
    const std::uint32_t old_height = t.height;
    if (t.parent && t.ahead) {
        push_convert(t, false);
        t.ahead = false;
        ++t.parent->version;
    }
    WGPUTexture tex = make_texture(t.width * g_scale, height * g_scale, kColor,
                                   WGPUTextureUsage_RenderAttachment | WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopySrc | WGPUTextureUsage_CopyDst);
    if (old) {
        Op op{OpKind::copy};
        op.src = old;
        op.dst = tex;
        op.width = t.width * g_scale;
        op.height = old_height * g_scale;
        g_ops.push_back(op);
        end_pass();
    }
    drop_texture(t.tex, t.view);
    drop_texture(t.copy, t.copy_view);
    drop_group(t.group);
    drop_group(t.copy_group);
    drop_group(t.dest_group);
    t.copy_version = ~0u;
    t.tex = tex;
    t.view = make_view(tex);
    t.height = height;
    if (t.parent) t.synced = ~0u;
    else fill_target(t, old ? old_height : 0, height);
    ++t.version;
}

Target &target_for(std::uint32_t fbp, std::uint32_t fbw, std::uint32_t psm) {
    Target &t = g_targets[target_key(fbp, fbw, psm)];
    if (!t.tex) {
        t.fbp = fbp;
        t.fbw = fbw;
        t.psm = psm;
        t.width = fbw * 64u;
        if ((t.parent = parent_of(fbp, fbw, psm))) t.prow = (fbp - t.parent->fbp) / fbw;
    }
    return t;
}

void ensure_height(Target &t, std::uint32_t rows) {
    const std::uint32_t align = t.parent ? 63u : 31u;  // views convert whole 16-bit page rows
    rows = std::min<std::uint32_t>((rows + align) & ~align, 2048u);
    if (t.tex && rows <= t.height) return;
    make_target_texture(t, std::max(rows, t.height));
    g_cur.valid = false;
}

// t.copy = t as drawn so far (textures read from the target being drawn, masked draws' destination).
void copy_target(Target &t) {
    if (!t.copy) {
        t.copy = make_texture(t.width * g_scale, t.height * g_scale, kColor, WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopyDst);
        t.copy_view = make_view(t.copy);
    }
    Op op{OpKind::copy};
    op.src = t.tex;
    op.dst = t.copy;
    op.width = t.width * g_scale;
    op.height = t.height * g_scale;
    g_ops.push_back(op);
    end_pass();
    t.copy_version = t.version;
    std::memset(t.dirty, 0, sizeof t.dirty);
}

WGPUBindGroup dest_group(Target &t) {
    if (!t.dest_group) {
        WGPUBindGroupEntry e = WGPU_BIND_GROUP_ENTRY_INIT;
        e.binding = 0;
        e.textureView = t.copy_view;
        WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
        d.layout = g_dest_layout;
        d.entryCount = 1;
        d.entries = &e;
        t.dest_group = wgpuDeviceCreateBindGroup(g_device, &d);
    }
    return t.dest_group;
}

// Writes a target's pixels into the CPU copy of GS memory (downloads, uploads into its memory).
void read_back(Target &t) {
    resolve(t);
    submit_ops();
    WGPUTexture packed = make_texture(t.width, t.height, WGPUTextureFormat_R32Uint, WGPUTextureUsage_RenderAttachment | WGPUTextureUsage_CopySrc);
    WGPUTextureView packed_view = make_view(packed);
    const WGPURenderPipeline pipe = t.sixteen() ? g_pack16_pipeline : g_pack32_pipeline;
    WGPUBindGroupEntry e = WGPU_BIND_GROUP_ENTRY_INIT;
    e.binding = 0;
    e.textureView = t.view;
    WGPUBindGroupLayout layout = wgpuRenderPipelineGetBindGroupLayout(pipe, 0);
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = layout;
    d.entryCount = 1;
    d.entries = &e;
    WGPUBindGroup group = wgpuDeviceCreateBindGroup(g_device, &d);
    wgpuBindGroupLayoutRelease(layout);
    WGPUCommandEncoder enc = encoder();
    WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
    ca.view = packed_view;
    ca.loadOp = WGPULoadOp_Clear;
    ca.storeOp = WGPUStoreOp_Store;
    WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
    pd.colorAttachmentCount = 1;
    pd.colorAttachments = &ca;
    WGPURenderPassEncoder p = wgpuCommandEncoderBeginRenderPass(enc, &pd);
    wgpuRenderPassEncoderSetPipeline(p, pipe);
    wgpuRenderPassEncoderSetBindGroup(p, 0, group, 0, nullptr);
    wgpuRenderPassEncoderDraw(p, 3, 1, 0, 0);
    wgpuRenderPassEncoderEnd(p);
    wgpuRenderPassEncoderRelease(p);
    submit_commands(enc);
    std::vector<std::uint32_t> pixels;
    read_pixels(packed, t.width, t.height, pixels);
    for (std::uint32_t y = 0; y < t.height; ++y)
        for (std::uint32_t x = 0; x < t.width; ++x) gs::write_pixel(t.psm, t.fbp * 32u, t.fbw, x, y, pixels[static_cast<std::size_t>(y) * t.width + x]);
    for_pages(t.fbp * 32u, t.fbw, t.psm, 0, 0, t.width, t.height, [](std::uint32_t pg) { ++g_page_gen[pg]; });
    wgpuBindGroupRelease(group);
    wgpuTextureViewRelease(packed_view);
    wgpuTextureRelease(packed);
    ++g_read_backs;
}

Depth &depth_for(std::uint32_t zbp, const Target &t) {
    Depth &z = g_depths[zbp | (static_cast<std::uint64_t>(t.width) << 16) | (static_cast<std::uint64_t>(t.height) << 32)];
    if (!z.tex) {
        z.tex = make_texture(t.width * g_scale, t.height * g_scale, kDepth, WGPUTextureUsage_RenderAttachment);
        z.view = make_view(z.tex);
    }
    return z;
}

// ---- Textures ----

struct Memo {
    std::uint64_t fields[4] = {};
    std::uint32_t clut = 0;
    std::uint64_t pages = 0, key = 0;
    bool valid = false;
} g_memo[64];

std::uint32_t wrap_index(std::uint64_t clamp) {
    return ((clamp & 3u) != 0 ? 1u : 0u) | (((clamp >> 2) & 3u) != 0 ? 2u : 0u);
}

Texture *texture_entry(std::uint64_t key) {
    const auto it = g_textures.find(key);
    if (it == g_textures.end()) return nullptr;
    it->second.used = ++g_texture_clock;
    return &it->second;
}

Texture &add_texture(std::uint64_t key, std::uint32_t w, std::uint32_t h, std::uint32_t levels) {
    if (g_textures.size() >= 4096) {
        std::vector<std::pair<std::uint64_t, std::uint64_t>> order;
        for (auto &[k, t] : g_textures) order.emplace_back(t.used, k);
        std::sort(order.begin(), order.end());
        for (std::size_t i = 0; i < order.size() / 2; ++i) {
            Texture &t = g_textures[order[i].second];
            drop_texture(t.tex, t.view);
            for (WGPUBindGroup &g : t.groups) drop_group(g);
            g_textures.erase(order[i].second);
        }
    }
    Texture &t = g_textures[key];
    t.tex = make_texture(w, h, WGPUTextureFormat_RGBA8Unorm, WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopyDst, levels);
    t.view = make_view(t.tex);
    t.used = ++g_texture_clock;
    return t;
}

// Texture-pack setup words (gpu.cpp layout, the fields texpack reads).
void pack_setup(const State &st, const gs::Context &c, std::uint32_t *w) {
    std::memset(w, 0, 25 * 4);
    if ((st.texa >> 15) & 1u) w[0] |= 32768u;
    w[7] = (static_cast<std::uint32_t>(c.clamp) & 0xFu) << 24;
    w[12] = static_cast<std::uint32_t>(c.tex0) & 0x3FFFu;
    w[13] = static_cast<std::uint32_t>(c.tex0 >> 14) & 0x3Fu;
    w[14] = static_cast<std::uint32_t>(c.tex0 >> 20) & 0x3Fu;
    w[15] = std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 26) & 0xFu, 10u) | (std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 30) & 0xFu, 10u) << 8);
    w[16] = static_cast<std::uint32_t>(c.tex0 >> 51) & 0xFu;
    w[17] = static_cast<std::uint32_t>(c.tex0 >> 56) & 0x1Fu;
    w[20] = (static_cast<std::uint32_t>(st.texa) & 0xFFu) | ((static_cast<std::uint32_t>(st.texa >> 32) & 0xFFu) << 8);
}

bool tagged(std::uint32_t psm) {
    return psm == gs::PSMCT32 || psm == gs::PSMCT24 || psm == gs::PSMCT16 || psm == gs::PSMCT16S || psm == gs::PSMT8 || psm == gs::PSMT4;
}

struct Source {
    WGPUBindGroup group = nullptr;
    float store_w = 1, store_h = 1;
    std::uint32_t flags = 0;
    std::uint32_t levels = 1;
};

std::uint32_t level_bp(const gs::Context &c, std::uint32_t l, std::uint32_t &bw) {
    if (l == 0) {
        bw = static_cast<std::uint32_t>(c.tex0 >> 14) & 0x3Fu;
        return static_cast<std::uint32_t>(c.tex0) & 0x3FFFu;
    }
    const std::uint64_t r = l <= 3 ? c.miptbp1 : c.miptbp2;
    const std::uint32_t shift = ((l - 1) % 3) * 20;
    bw = static_cast<std::uint32_t>(r >> (shift + 14)) & 0x3Fu;
    return static_cast<std::uint32_t>(r >> shift) & 0x3FFFu;
}

// Texture from a render target drawn earlier: same base pointer and format class.
bool target_source(Target &t, const Target *drawing, Source &out) {
    resolve(t);
    if (&t == drawing) {
        if (t.copy_version != t.version) copy_target(t);
        if (!t.copy_group) t.copy_group = texture_group(t.copy_view, 3);
        out.group = t.copy_group;
    } else {
        if (!t.group) t.group = texture_group(t.view, 3);
        out.group = t.group;
    }
    out.store_w = static_cast<float>(t.width);
    out.store_h = static_cast<float>(t.height);
    out.flags = F_SOURCE_TARGET | (t.sixteen() ? F_SOURCE16 : 0u);
    return true;
}

bool texture_source(const State &st, const gs::Context &c, const Target *drawing, Source &out) {
    const std::uint32_t tbp = static_cast<std::uint32_t>(c.tex0) & 0x3FFFu;
    const std::uint32_t psm = static_cast<std::uint32_t>(c.tex0 >> 20) & 0x3Fu;
    const std::uint32_t tw = std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 26) & 0xFu, 10u);
    const std::uint32_t th = std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 30) & 0xFu, 10u);
    if (tbp % 32u == 0) {
        if (Target *t = find_target(tbp / 32u, psm)) return target_source(*t, drawing, out);
        const std::uint32_t tbw = static_cast<std::uint32_t>(c.tex0 >> 14) & 0x3Fu;
        if (Target *p = parent_of(tbp / 32u, tbw, psm)) {
            Target &v = target_for(tbp / 32u, tbw, psm);
            ensure_height(v, (p->height / 32u - v.prow) * 64u);
            return target_source(v, drawing, out);
        }
    }
    const std::uint32_t lo = tbp * 256u;
    if (const Target *t = target_under(lo, lo + 1)) {
        missing(std::string("texture inside a render target in another format (fbp ") + std::to_string(t->fbp) + ")");
    }
    const std::uint32_t mmin = static_cast<std::uint32_t>(c.tex1 >> 6) & 7u;
    const std::uint32_t levels = mmin >= 2 ? std::min<std::uint32_t>(std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex1 >> 2) & 7u, 6u), std::max(tw, th)) + 1 : 1;
    const bool paletted = bits_per_pixel(psm) <= 8;
    const std::uint64_t fields[4] = {c.tex0 & 0x7FFFFFFFFFFFFFFull, levels > 1 ? c.miptbp1 : 0, levels > 1 ? c.miptbp2 : 0,
                                     (st.texa & 0xFF000080FFull) | (static_cast<std::uint64_t>(levels) << 60) | (c.clamp & 0xFu) << 40};
    Memo &m = g_memo[(tbp ^ (tbp >> 5) ^ (static_cast<std::uint32_t>(c.tex0 >> 20) * 7u)) & 63u];
    std::uint64_t pages = 0;
    for (std::uint32_t l = 0; l < levels; ++l) {
        std::uint32_t bw;
        const std::uint32_t bp = level_bp(c, l, bw);
        for_pages(bp, bw, psm, 0, 0, std::max(1u, (1u << tw) >> l), std::max(1u, (1u << th) >> l), [&](std::uint32_t p) { pages = mix(pages, g_page_gen[p]); });
    }
    const bool memo_ok = m.valid && m.pages == pages && (!paletted || m.clut == g_clut_version) && std::memcmp(m.fields, fields, sizeof fields) == 0;
    std::uint64_t key = m.key;
    const TexFormat fmt{psm, static_cast<std::uint32_t>(c.tex0 >> 51) & 0xFu, static_cast<std::uint32_t>(c.tex0 >> 56) & 0x1Fu,
                        static_cast<std::uint32_t>(st.texa) & 0xFFu, static_cast<std::uint32_t>(st.texa >> 32) & 0xFFu, ((st.texa >> 15) & 1u) != 0};
    if (!memo_ok) {
        key = 0;
        std::uint32_t w[25];
        if (g_packs && !target_under(lo, lo + 1)) {
            pack_setup(st, c, w);
            if (texpack::replaceable(w)) {
                const std::uint64_t pk = texpack::combine(texpack::texel_key(w), texpack::palette_key(w));
                if (pk) {
                    const texpack::Image *img = texpack::find(pk);
                    const std::uint32_t tex_w = 1u << tw, tex_h = 1u << th;
                    if (img && img->width % tex_w == 0 && img->height % tex_h == 0 && img->width / tex_w == img->height / tex_h) {
                        key = mix(pk, 0x7061636Bull);
                        if (!texture_entry(key)) {
                            Texture &t = add_texture(key, img->width, img->height, 1);
                            write_texture(t.tex, 0, img->width, img->height, img->texels.data());
                            ++g_replaced;
                        }
                    }
                }
            }
        }
        if (!key) {
            key = mix(mix(fields[0] & 0x1FF80007FFFFC000ull, fields[3]), levels);
            for (std::uint32_t l = 0; l < levels; ++l) {
                std::uint32_t bw;
                const std::uint32_t bp = level_bp(c, l, bw);
                // Upload content tags (D25) when the level has them: the same texture uploaded again keeps its key.
                std::uint64_t content = 0;
                if (tagged(psm)) {
                    std::uint32_t lw[25] = {};
                    lw[12] = bp;
                    lw[13] = bw;
                    lw[14] = psm;
                    lw[15] = (tw > l ? tw - l : 0) | ((th > l ? th - l : 0) << 8);
                    content = texpack::texel_key(lw);
                }
                if (content) key = mix(key, content);
                else for_pages(bp, bw, psm, 0, 0, std::max(1u, (1u << tw) >> l), std::max(1u, (1u << th) >> l), [&](std::uint32_t p) { key = mix(key, page_hash(p)); });
            }
            if (paletted) {
                const std::uint32_t first = psm == gs::PSMT8 || psm == gs::PSMT8H ? 0u : (fmt.csa & 15u) * 16u, count = first ? 16u : (psm == gs::PSMT8 || psm == gs::PSMT8H ? 256u : 16u);
                for (std::uint32_t i = 0; i < count; ++i) key = mix(key, gs::g_state.clut[(first + i) & 511u]);
            }
            if (!texture_entry(key)) {
                const Timer timer(T_DECODE);
                Texture &t = add_texture(key, 1u << tw, 1u << th, levels);
                std::vector<std::uint32_t> texels;
                for (std::uint32_t l = 0; l < levels; ++l) {
                    std::uint32_t bw;
                    const std::uint32_t bp = level_bp(c, l, bw);
                    const std::uint32_t lw = std::max(1u, (1u << tw) >> l), lh = std::max(1u, (1u << th) >> l);
                    decode(fmt, bp, bw, lw, lh, texels);
                    write_texture(t.tex, l, lw, lh, texels.data());
                }
                ++g_decoded;
            }
        }
        std::memcpy(m.fields, fields, sizeof fields);
        m.pages = pages;
        m.clut = g_clut_version;
        m.key = key;
        m.valid = true;
    }
    Texture *t = texture_entry(key);
    if (!t) {
        m.valid = false;
        return false;
    }
    const std::uint32_t wrap = wrap_index(c.clamp);
    if (!t->groups[wrap]) t->groups[wrap] = texture_group(t->view, wrap);
    out.group = t->groups[wrap];
    out.store_w = static_cast<float>(1u << tw);
    out.store_h = static_cast<float>(1u << th);
    out.flags = 0;
    out.levels = levels;
    return true;
}

// ---- Pipelines ----

struct Coef {
    int one = 0, c = 0;
};

// GS blend Cv = (A - B) * C + D as WebGPU factors (dual source: blend_src 1 alpha is As).
bool blend_state(std::uint32_t alpha, WGPUBlendComponent &out, bool &src_one) {
    const std::uint32_t a = alpha & 3u, b = (alpha >> 2) & 3u, c = (alpha >> 4) & 3u, d = (alpha >> 6) & 3u;
    Coef s, t;
    if (a == 0) ++s.c;
    if (a == 1) ++t.c;
    if (b == 0) --s.c;
    if (b == 1) --t.c;
    if (d == 0) ++s.one;
    if (d == 1) ++t.one;
    const WGPUBlendFactor cf = c == 0 ? WGPUBlendFactor_Src1Alpha : c == 1 ? WGPUBlendFactor_DstAlpha : WGPUBlendFactor_Constant;
    const WGPUBlendFactor inv = c == 0 ? WGPUBlendFactor_OneMinusSrc1Alpha : c == 1 ? WGPUBlendFactor_OneMinusDstAlpha : WGPUBlendFactor_OneMinusConstant;
    src_one = false;
    const auto factor = [&](Coef k, WGPUBlendFactor &f, bool &negative) {
        negative = false;
        if (k.one == 0 && k.c == 0) f = WGPUBlendFactor_Zero;
        else if (k.one == 1 && k.c == 0) f = WGPUBlendFactor_One;
        else if (k.one == 0 && k.c == 1) f = cf;
        else if (k.one == 0 && k.c == -1) f = cf, negative = true;
        else if (k.one == 1 && k.c == -1) f = inv;
        else return false;
        return true;
    };
    bool ns = false, nd = false;
    WGPUBlendFactor fs = WGPUBlendFactor_Zero, fd = WGPUBlendFactor_Zero;
    if (!factor(t, fd, nd)) {
        // Cd * (1 + C): the fragment outputs 1, src factor = Cd, dst factor = C.
        if (t.one != 1 || t.c != 1 || s.one != 0 || s.c != 0) return false;
        src_one = true;
        out = {WGPUBlendOperation_Add, WGPUBlendFactor_Dst, cf};
        return true;
    }
    if (!factor(s, fs, ns)) return false;
    WGPUBlendOperation op = WGPUBlendOperation_Add;
    if (ns && nd) fs = fd = WGPUBlendFactor_Zero;  // negative result: the GS clamps to 0
    else if (ns) op = WGPUBlendOperation_ReverseSubtract;
    else if (nd) op = WGPUBlendOperation_Subtract;
    out = {op, fs, fd};
    return true;
}

// key: bits 0-7 ALPHA (A, B, C, D), 8 blend on, 9-12 colour write mask, 13-15 depth compare, 16 depth write.
WGPURenderPipeline pipeline(std::uint32_t key) {
    if (const auto it = g_pipelines.find(key); it != g_pipelines.end()) return it->second;
    WGPUVertexAttribute attrs[4] = {WGPU_VERTEX_ATTRIBUTE_INIT, WGPU_VERTEX_ATTRIBUTE_INIT, WGPU_VERTEX_ATTRIBUTE_INIT, WGPU_VERTEX_ATTRIBUTE_INIT};
    attrs[0] = {nullptr, WGPUVertexFormat_Float32x3, 0, 0};
    attrs[1] = {nullptr, WGPUVertexFormat_Unorm8x4, 12, 1};
    attrs[2] = {nullptr, WGPUVertexFormat_Float32x3, 16, 2};
    attrs[3] = {nullptr, WGPUVertexFormat_Uint32, 28, 3};
    WGPUVertexBufferLayout vb = WGPU_VERTEX_BUFFER_LAYOUT_INIT;
    vb.stepMode = WGPUVertexStepMode_Vertex;
    vb.arrayStride = sizeof(NVertex);
    vb.attributeCount = 4;
    vb.attributes = attrs;
    WGPUBlendState blend = WGPU_BLEND_STATE_INIT;
    blend.alpha = {WGPUBlendOperation_Add, WGPUBlendFactor_One, WGPUBlendFactor_Zero};
    blend.color = {WGPUBlendOperation_Add, WGPUBlendFactor_One, WGPUBlendFactor_Zero};
    bool src_one = false;
    if (key & 0x100u) blend_state(key & 0xFFu, blend.color, src_one);
    WGPUColorTargetState color = WGPU_COLOR_TARGET_STATE_INIT;
    color.format = kColor;
    color.blend = &blend;
    color.writeMask = static_cast<WGPUColorWriteMask>((key >> 9) & 0xFu);
    WGPUFragmentState fragment = WGPU_FRAGMENT_STATE_INIT;
    fragment.module = g_module;
    fragment.entryPoint = view("fs");
    fragment.targetCount = 1;
    fragment.targets = &color;
    WGPUDepthStencilState depth = WGPU_DEPTH_STENCIL_STATE_INIT;
    depth.format = kDepth;
    const WGPUCompareFunction compares[5] = {WGPUCompareFunction_Always, WGPUCompareFunction_Never, WGPUCompareFunction_Always,
                                             WGPUCompareFunction_GreaterEqual, WGPUCompareFunction_Greater};
    depth.depthCompare = compares[std::min((key >> 13) & 7u, 4u)];
    depth.depthWriteEnabled = (key >> 16) & 1u ? WGPUOptionalBool_True : WGPUOptionalBool_False;
    WGPURenderPipelineDescriptor d = WGPU_RENDER_PIPELINE_DESCRIPTOR_INIT;
    d.layout = g_draw_layout;
    d.vertex.module = g_module;
    d.vertex.entryPoint = view("vs");
    d.vertex.bufferCount = 1;
    d.vertex.buffers = &vb;
    WGPUConstantEntry constant = WGPU_CONSTANT_ENTRY_INIT;
    constant.key = view("SCALE");
    constant.value = static_cast<double>(g_scale);
    d.vertex.constantCount = 1;
    d.vertex.constants = &constant;
    fragment.constantCount = 1;
    fragment.constants = &constant;
    d.primitive.topology = WGPUPrimitiveTopology_TriangleList;
    d.primitive.cullMode = WGPUCullMode_None;
    d.depthStencil = &depth;
    d.fragment = &fragment;
    WGPURenderPipeline p = wgpuDeviceCreateRenderPipeline(g_device, &d);
    g_pipelines[key] = p;
    return p;
}

WGPURenderPipeline full_pipeline(const char *entry, WGPUTextureFormat format) {
    WGPUColorTargetState color = WGPU_COLOR_TARGET_STATE_INIT;
    color.format = format;
    WGPUFragmentState fragment = WGPU_FRAGMENT_STATE_INIT;
    fragment.module = g_module;
    fragment.entryPoint = view(entry);
    fragment.targetCount = 1;
    fragment.targets = &color;
    WGPUConstantEntry constant = WGPU_CONSTANT_ENTRY_INIT;
    constant.key = view("SCALE");
    constant.value = static_cast<double>(g_scale);
    fragment.constantCount = 1;
    fragment.constants = &constant;
    WGPURenderPipelineDescriptor d = WGPU_RENDER_PIPELINE_DESCRIPTOR_INIT;
    d.vertex.module = g_module;
    d.vertex.entryPoint = view("vs_full");
    d.fragment = &fragment;
    return wgpuDeviceCreateRenderPipeline(g_device, &d);
}

WGPURenderPipeline convert_pipeline(const char *entry) {
    WGPUColorTargetState color = WGPU_COLOR_TARGET_STATE_INIT;
    color.format = kColor;
    WGPUFragmentState fragment = WGPU_FRAGMENT_STATE_INIT;
    fragment.module = g_module;
    fragment.entryPoint = view(entry);
    fragment.targetCount = 1;
    fragment.targets = &color;
    WGPUConstantEntry constant = WGPU_CONSTANT_ENTRY_INIT;
    constant.key = view("SCALE");
    constant.value = static_cast<double>(g_scale);
    fragment.constantCount = 1;
    fragment.constants = &constant;
    WGPURenderPipelineDescriptor d = WGPU_RENDER_PIPELINE_DESCRIPTOR_INIT;
    d.layout = g_convert_pipeline_layout;
    d.vertex.module = g_module;
    d.vertex.entryPoint = view("vs_convert");
    d.fragment = &fragment;
    return wgpuDeviceCreateRenderPipeline(g_device, &d);
}

// ---- Draw state ----

std::uint64_t prim_attr(const State &st) { return (st.prmodecont & 1u) ? st.prim : (st.prim & 7u) | (st.prmode & ~7ull); }

// Channels FBMSK leaves writable; partial when it masks bits inside a channel (then the shader merges bits).
std::uint32_t write_mask(const gs::Context &c, const Target &t, bool &partial) {
    const std::uint32_t fbmsk = static_cast<std::uint32_t>(c.frame >> 32);
    const std::uint32_t channel[4] = {0xFFu, 0xFF00u, 0xFF0000u, 0xFF000000u};
    const std::uint32_t channel16[4] = {0xF8u, 0xF800u, 0xF80000u, 0x80000000u};
    std::uint32_t mask = 0;
    partial = false;
    for (int i = 0; i < 4; ++i) {
        const std::uint32_t bits = t.sixteen() ? channel16[i] : channel[i];
        if ((fbmsk & bits) == bits) continue;
        if (fbmsk & bits) partial = true;
        mask |= 1u << i;
    }
    return mask;
}

void rebuild(const State &st, std::uint64_t attr) {
    const Timer timer(T_REBUILD);
    count(C_REBUILD);
    Current &cur = g_cur;
    cur.valid = true;
    cur.skip = false;
    cur.generation = gs::g_setup_generation;
    cur.attr = attr;
    cur.clut = g_clut_version;
    cur.upload = g_upload_serial;
    cur.regs = regs_of(st, attr);
    const gs::Context &c = st.ctx[(attr >> 9) & 1u];
    const std::uint32_t fbp = static_cast<std::uint32_t>(c.frame) & 0x1FFu, fbw = static_cast<std::uint32_t>(c.frame >> 16) & 0x3Fu;
    const std::uint32_t fpsm = static_cast<std::uint32_t>(c.frame >> 24) & 0x3Fu;
    if (!fbw) {
        missing("frame width 0");
        cur.skip = true;
        return;
    }
    Target &t = target_for(fbp, fbw, fpsm);
    const std::int32_t scax0 = static_cast<std::int32_t>(c.scissor & 0x7FFu), scax1 = static_cast<std::int32_t>((c.scissor >> 16) & 0x7FFu);
    const std::int32_t scay0 = static_cast<std::int32_t>((c.scissor >> 32) & 0x7FFu), scay1 = static_cast<std::int32_t>((c.scissor >> 48) & 0x7FFu);
    cur.scissor_y1 = scay1;
    if (!t.tex) ensure_height(t, std::min<std::uint32_t>(static_cast<std::uint32_t>(scay1) + 1, 512u));
    resolve(t);
    cur.target = &t;
    cur.ofx = static_cast<float>(c.xyoffset & 0xFFFFu);
    cur.ofy = static_cast<float>((c.xyoffset >> 32) & 0xFFFFu);
    cur.fst = (attr & 0x100u) != 0;
    cur.iip = (attr & 0x8u) != 0;
    cur.textured = (attr & 0x10u) != 0;

    const std::uint32_t zpsm = 0x30u | (static_cast<std::uint32_t>(c.zbuf >> 24) & 0xFu);
    cur.z_max = zpsm == gs::PSMZ32 ? 0xFFFFFFFFu : (zpsm == gs::PSMZ24 ? 0xFFFFFFu : 0xFFFFu);
    cur.z_scale = 1.0f / (static_cast<float>(cur.z_max) + 1.0f);
    cur.depth = &depth_for(static_cast<std::uint32_t>(c.zbuf) & 0x1FFu, t);

    const std::uint64_t test = c.test;
    const bool ate = test & 1u, zte = (test >> 16) & 1u;
    const std::uint32_t atst = static_cast<std::uint32_t>(test >> 1) & 7u, afail = static_cast<std::uint32_t>(test >> 12) & 3u;
    const std::uint32_t ztst = static_cast<std::uint32_t>(test >> 17) & 3u;
    bool partial = false;
    std::uint32_t mask = write_mask(c, t, partial);
    bool zwrite = zte && !((c.zbuf >> 32) & 1u) && ztst != 0;
    std::uint32_t flags = 0;
    if (ate && atst == 0) {
        switch (afail) {
        case 0: cur.skip = true; return;
        case 1: zwrite = false; break;
        case 2: mask = 0; break;
        default: mask &= 7u, zwrite = false; break;
        }
    } else if (ate && atst != 1) {
        if (afail != 0) missing("alpha test with a fail mode other than KEEP");
        flags |= F_ATE | (atst << 5);
    }
    if ((test >> 14) & 1u) missing("destination alpha test (DATE)");
    if (attr & 0x20u) missing("fog");
    if (st.dthe & 1u) missing("dithering (DTHE)");
    if (st.pabe & 1u) missing("PABE");
    if (!(st.colclamp & 1u)) missing("COLCLAMP off");

    const bool abe = (attr & 0x40u) != 0;
    const std::uint32_t alpha = static_cast<std::uint32_t>(c.alpha) & 0xFFu, fix = static_cast<std::uint32_t>(c.alpha >> 32) & 0xFFu;
    bool src_one = false;
    if (abe && !partial) {
        WGPUBlendComponent unused;
        if (!blend_state(alpha, unused, src_one)) missing("blend equation " + std::to_string(alpha));
    }
    if (src_one) flags |= F_SRC_ONE;
    const std::uint32_t depth_mode = zte ? ztst + 1 : 0;
    Params &p = cur.params;
    p = Params{};
    cur.masked = partial && mask != 0;
    cur.dest = g_blank_dest_group;
    if (cur.masked) {
        // Bits masked inside a channel: the shader reads the destination (a copy), blends and merges bits.
        p.fbmsk = static_cast<std::uint32_t>(c.frame >> 32);
        for (std::uint32_t i = 0; i < 4; ++i)
            if (!(mask & (1u << i))) p.fbmsk |= 0xFFu << (8 * i);
        p.blend = abe ? alpha | (fix << 8) | 0x10000u : 0u;
        flags |= F_MASKED | (t.sixteen() ? F_TARGET16 : 0u);
        if (t.copy_version != t.version) copy_target(t);
        cur.dest = dest_group(t);
        cur.pipeline = pipeline((0xFu << 9) | (depth_mode << 13) | (zwrite ? 1u << 16 : 0u));
    } else {
        cur.pipeline = pipeline((abe ? (alpha | 0x100u) : 0u) | (mask << 9) | (depth_mode << 13) | (zwrite ? 1u << 16 : 0u));
    }
    cur.fix = static_cast<float>(fix) / 128.0f;

    p.target[0] = static_cast<float>(t.width * g_scale);
    p.target[1] = static_cast<float>(t.height * g_scale);
    p.scale = static_cast<float>(g_scale);
    p.aref = static_cast<float>((test >> 4) & 0xFFu);
    if (c.fba & 1u) flags |= F_FBA;
    cur.group = g_blank_group;
    if (cur.textured) {
        Source src;
        if (texture_source(st, c, &t, src)) {
            const std::uint32_t tw = std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 26) & 0xFu, 10u);
            const std::uint32_t th = std::min<std::uint32_t>(static_cast<std::uint32_t>(c.tex0 >> 30) & 0xFu, 10u);
            const std::uint64_t tex1 = c.tex1;
            cur.group = src.group;
            flags |= F_TME | src.flags;
            if ((c.tex0 >> 34) & 1u) flags |= F_TCC;
            flags |= (static_cast<std::uint32_t>(c.tex0 >> 35) & 3u) << 2;
            if ((tex1 >> 5) & 1u) flags |= F_MAG_LINEAR;
            flags |= (static_cast<std::uint32_t>(tex1 >> 6) & 7u) << 10;
            if (tex1 & 1u) flags |= F_LCM;
            if ((st.texa >> 15) & 1u) flags |= F_AEM;
            if (src.flags & F_SOURCE_TARGET) {
                if ((c.clamp & 3u) == 0) flags |= F_REPEAT_U;
                if (((c.clamp >> 2) & 3u) == 0) flags |= F_REPEAT_V;
            }
            if ((c.clamp & 2u) || ((c.clamp >> 2) & 2u)) missing("region clamp modes");
            p.tex_size[0] = static_cast<float>(1u << tw);
            p.tex_size[1] = static_cast<float>(1u << th);
            p.store_size[0] = src.store_w;
            p.store_size[1] = src.store_h;
            p.lod_l = static_cast<float>(1u << (static_cast<std::uint32_t>(tex1 >> 19) & 3u));
            p.lod_k = static_cast<float>(static_cast<std::int32_t>(static_cast<std::uint32_t>(tex1 >> 32) << 20) >> 20) / 16.0f;
            p.mxl = static_cast<float>(src.levels - 1);
            p.ta0 = static_cast<float>(st.texa & 0xFFu);
            p.ta1 = static_cast<float>((st.texa >> 32) & 0xFFu);
            cur.inv_tw = 1.0f / p.tex_size[0];
            cur.inv_th = 1.0f / p.tex_size[1];
        } else {
            cur.textured = false;
        }
    }
    p.flags = flags;
    if (g_params.empty() || !(g_params.back() == p)) g_params.push_back(p);
    cur.param = static_cast<std::uint32_t>(g_params.size() - 1);

    const std::int32_t w = static_cast<std::int32_t>(t.width), h = static_cast<std::int32_t>(t.height);
    const std::int32_t x0 = std::clamp(scax0, 0, w), x1 = std::clamp(scax1 + 1, 0, w), y0 = std::clamp(scay0, 0, h), y1 = std::clamp(scay1 + 1, 0, h);
    if (x1 <= x0 || y1 <= y0) {
        cur.skip = true;
        return;
    }
    cur.scissor[0] = static_cast<std::uint32_t>(x0) * g_scale;
    cur.scissor[1] = static_cast<std::uint32_t>(y0) * g_scale;
    cur.scissor[2] = static_cast<std::uint32_t>(x1 - x0) * g_scale;
    cur.scissor[3] = static_cast<std::uint32_t>(y1 - y0) * g_scale;
}

NVertex make_vertex(const Vertex &v, const Vertex &color) {
    const Current &cur = g_cur;
    NVertex o;
    o.param = cur.param;
    o.x = (static_cast<float>(v.x) - cur.ofx) / 16.0f;
    o.y = (static_cast<float>(v.y) - cur.ofy) / 16.0f;
    o.z = static_cast<float>(std::min(v.z, cur.z_max)) * cur.z_scale;
    o.rgba = color.r | (color.g << 8) | (color.b << 16) | (static_cast<std::uint32_t>(color.a) << 24);
    if (cur.fst) {
        o.s = static_cast<float>(v.u) / 16.0f * cur.inv_tw;
        o.t = static_cast<float>(v.v) / 16.0f * cur.inv_th;
        o.q = 1.0f;
    } else {
        o.s = v.s;
        o.t = v.t;
        o.q = v.q == 0.0f ? 1.0f : v.q;
    }
    return o;
}

void add_vertices(const NVertex *v, std::uint32_t n, const std::int32_t *box) {
    Current &cur = g_cur;
    Target &t = *cur.target;
    if (t.dirty[2] <= t.dirty[0]) std::memcpy(t.dirty, box, sizeof t.dirty);
    else t.dirty[0] = std::min(t.dirty[0], box[0]), t.dirty[1] = std::min(t.dirty[1], box[1]), t.dirty[2] = std::max(t.dirty[2], box[2]), t.dirty[3] = std::max(t.dirty[3], box[3]);
    if (t.parent) t.ahead = true;
    t.stamp = ++g_stamp;
    if (g_pass_target != &t || g_pass_depth != cur.depth) {
        Op op{OpKind::pass};
        op.color = t.view;
        op.depth = cur.depth->view;
        op.clear_depth = !cur.depth->cleared;
        cur.depth->cleared = true;
        g_ops.push_back(op);
        g_pass_target = &t;
        g_pass_depth = cur.depth;
    }
    const std::uint32_t first = static_cast<std::uint32_t>(g_vertices.size());
    g_vertices.insert(g_vertices.end(), v, v + n);
    Op &last = g_ops.back();
    if (last.kind == OpKind::draw && last.pipeline == cur.pipeline && last.group == cur.group && last.dest == cur.dest && last.fix == cur.fix &&
        std::memcmp(last.scissor, cur.scissor, sizeof cur.scissor) == 0 && last.first + last.count == first) {
        last.count += n;
        return;
    }
    Op op{OpKind::draw};
    op.pipeline = cur.pipeline;
    op.group = cur.group;
    op.dest = cur.dest;
    op.first = first;
    op.count = n;
    op.param = cur.param;
    op.fix = cur.fix;
    std::memcpy(op.scissor, cur.scissor, sizeof op.scissor);
    g_ops.push_back(op);
    ++t.version;
}

// ---- Encode and submit ----

void submit_ops() {
    if (g_ops.empty()) return;
    const Timer timer(T_SUBMIT);
    ++g_flushes;
    const std::uint64_t vbytes = std::max<std::uint64_t>(g_vertices.size() * sizeof(NVertex), 16);
    if (vbytes > g_vertex_capacity) {
        if (g_vertex_buffer) wgpuBufferRelease(g_vertex_buffer);
        g_vertex_capacity = std::max<std::uint64_t>(vbytes * 2, 1u << 20);
        g_vertex_buffer = make_buffer(g_vertex_capacity, WGPUBufferUsage_Vertex | WGPUBufferUsage_CopyDst);
    }
    const std::uint64_t pbytes = std::max<std::uint64_t>(g_params.size() * sizeof(Params), sizeof(Params));
    if (pbytes > g_param_capacity) {
        if (g_param_buffer) wgpuBufferRelease(g_param_buffer);
        if (g_param_group) wgpuBindGroupRelease(g_param_group);
        g_param_capacity = std::max<std::uint64_t>(pbytes * 2, 1u << 16);
        g_param_buffer = make_buffer(g_param_capacity, WGPUBufferUsage_Storage | WGPUBufferUsage_CopyDst);
        WGPUBindGroupEntry e = WGPU_BIND_GROUP_ENTRY_INIT;
        e.binding = 0;
        e.buffer = g_param_buffer;
        e.size = WGPU_WHOLE_SIZE;
        WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
        d.layout = g_params_layout;
        d.entryCount = 1;
        d.entries = &e;
        g_param_group = wgpuDeviceCreateBindGroup(g_device, &d);
    }
    if (!g_vertices.empty()) wgpuQueueWriteBuffer(g_queue, g_vertex_buffer, 0, g_vertices.data(), g_vertices.size() * sizeof(NVertex));
    if (!g_params.empty()) wgpuQueueWriteBuffer(g_queue, g_param_buffer, 0, g_params.data(), g_params.size() * sizeof(Params));
    WGPUCommandEncoder enc = encoder();
    WGPURenderPassEncoder pass = nullptr;
    WGPURenderPipeline bound_pipeline = nullptr;
    WGPUBindGroup bound_group = nullptr, bound_dest = nullptr;
    std::uint32_t bound_scissor[4] = {~0u};
    float bound_fix = -1.0f;
    const auto close = [&] {
        if (!pass) return;
        wgpuRenderPassEncoderEnd(pass);
        wgpuRenderPassEncoderRelease(pass);
        pass = nullptr;
    };
    for (const Op &op : g_ops) {
        switch (op.kind) {
        case OpKind::pass: {
            close();
            WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
            ca.view = op.color;
            ca.loadOp = WGPULoadOp_Load;
            ca.storeOp = WGPUStoreOp_Store;
            WGPURenderPassDepthStencilAttachment da = WGPU_RENDER_PASS_DEPTH_STENCIL_ATTACHMENT_INIT;
            da.view = op.depth;
            da.depthLoadOp = op.clear_depth ? WGPULoadOp_Clear : WGPULoadOp_Load;
            da.depthStoreOp = WGPUStoreOp_Store;
            da.depthClearValue = 0.0f;
            WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
            pd.colorAttachmentCount = 1;
            pd.colorAttachments = &ca;
            pd.depthStencilAttachment = &da;
            pass = wgpuCommandEncoderBeginRenderPass(enc, &pd);
            count(C_PASS);
            wgpuRenderPassEncoderSetVertexBuffer(pass, 0, g_vertex_buffer, 0, g_vertex_capacity);
            wgpuRenderPassEncoderSetBindGroup(pass, 0, g_param_group, 0, nullptr);
            wgpuRenderPassEncoderSetBindGroup(pass, 2, bound_dest = g_blank_dest_group, 0, nullptr);
            bound_pipeline = nullptr;
            bound_group = nullptr;
            bound_scissor[0] = ~0u;
            bound_fix = -1.0f;
            break;
        }
        case OpKind::draw: {
            if (!pass) break;
            if (bound_pipeline != op.pipeline) wgpuRenderPassEncoderSetPipeline(pass, bound_pipeline = op.pipeline);
            if (bound_group != op.group) wgpuRenderPassEncoderSetBindGroup(pass, 1, bound_group = op.group, 0, nullptr);
            if (bound_dest != op.dest) wgpuRenderPassEncoderSetBindGroup(pass, 2, bound_dest = op.dest, 0, nullptr);
            if (std::memcmp(bound_scissor, op.scissor, sizeof bound_scissor) != 0) {
                std::memcpy(bound_scissor, op.scissor, sizeof bound_scissor);
                wgpuRenderPassEncoderSetScissorRect(pass, op.scissor[0], op.scissor[1], op.scissor[2], op.scissor[3]);
            }
            if (bound_fix != op.fix) {
                bound_fix = op.fix;
                const WGPUColor c{op.fix, op.fix, op.fix, op.fix};
                wgpuRenderPassEncoderSetBlendConstant(pass, &c);
            }
            wgpuRenderPassEncoderDraw(pass, op.count, 1, op.first, 0);
            count(C_DRAW);
            break;
        }
        case OpKind::copy: {
            close();
            WGPUTexelCopyTextureInfo src = WGPU_TEXEL_COPY_TEXTURE_INFO_INIT, dst = WGPU_TEXEL_COPY_TEXTURE_INFO_INIT;
            src.texture = op.src;
            dst.texture = op.dst;
            const WGPUExtent3D size{op.width, op.height, 1};
            wgpuCommandEncoderCopyTextureToTexture(enc, &src, &dst, &size);
            count(C_COPY);
            break;
        }
        case OpKind::init: {
            close();
            WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
            ca.view = op.color;
            ca.loadOp = op.scissor[1] || op.scissor[3] < op.height ? WGPULoadOp_Load : WGPULoadOp_Clear;
            ca.storeOp = WGPUStoreOp_Store;
            WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
            pd.colorAttachmentCount = 1;
            pd.colorAttachments = &ca;
            WGPURenderPassEncoder p = wgpuCommandEncoderBeginRenderPass(enc, &pd);
            wgpuRenderPassEncoderSetScissorRect(p, 0, op.scissor[1], op.width, op.scissor[3] - op.scissor[1]);
            wgpuRenderPassEncoderSetPipeline(p, g_init_pipeline);
            wgpuRenderPassEncoderSetBindGroup(p, 0, op.group, 0, nullptr);
            wgpuRenderPassEncoderDraw(p, 3, 1, 0, 0);
            wgpuRenderPassEncoderEnd(p);
            wgpuRenderPassEncoderRelease(p);
            break;
        }
        case OpKind::convert: {
            close();
            WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
            ca.view = op.color;
            ca.loadOp = WGPULoadOp_Load;
            ca.storeOp = WGPUStoreOp_Store;
            WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
            pd.colorAttachmentCount = 1;
            pd.colorAttachments = &ca;
            WGPURenderPassEncoder p = wgpuCommandEncoderBeginRenderPass(enc, &pd);
            wgpuRenderPassEncoderSetScissorRect(p, op.scissor[0], op.scissor[1], op.scissor[2], op.scissor[3]);
            wgpuRenderPassEncoderSetPipeline(p, op.pipeline);
            wgpuRenderPassEncoderSetBindGroup(p, 0, g_param_group, 0, nullptr);
            wgpuRenderPassEncoderSetBindGroup(p, 1, op.group, 0, nullptr);
            wgpuRenderPassEncoderDraw(p, 3, 1, 0, op.param);
            wgpuRenderPassEncoderEnd(p);
            wgpuRenderPassEncoderRelease(p);
            break;
        }
        }
    }
    close();
    submit_commands(enc);
    for (WGPUBindGroup g : g_dead_groups) wgpuBindGroupRelease(g);
    for (WGPUTextureView v : g_dead_views) wgpuTextureViewRelease(v);
    for (WGPUTexture t : g_dead_textures) wgpuTextureRelease(t);
    g_dead_groups.clear();
    g_dead_views.clear();
    g_dead_textures.clear();
    g_ops.clear();
    g_vertices.clear();
    g_params.clear();
    end_pass();
    g_cur.valid = false;
}

void submit_commands(WGPUCommandEncoder enc) {
#ifndef __EMSCRIPTEN__
    if (g_stamps && (g_stamp_count & 1u)) wgpuCommandEncoderWriteTimestamp(enc, g_stamps, g_stamp_count++);
#endif
    count(C_SUBMIT);
    WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(enc, nullptr);
    wgpuQueueSubmit(g_queue, 1, &cmd);
    wgpuCommandBufferRelease(cmd);
    wgpuCommandEncoderRelease(enc);
}

// ---- Display ----

struct Shown {
    Target *target = nullptr;
    std::uint32_t x = 0, y = 0, width = 0, height = 0;
    bool halved = false;
};

bool shown_buffer(const gs::DisplayRegs &r, Shown &out) {
    const int circuit = (r.pmode & 2u) ? 1 : (r.pmode & 1u) ? 0 : -1;
    if (circuit < 0) return false;
    const std::uint64_t fb = r.dispfb[circuit], disp = r.display[circuit];
    const std::uint32_t magh = (static_cast<std::uint32_t>(disp >> 23) & 0xFu) + 1, magv = (static_cast<std::uint32_t>(disp >> 27) & 3u) + 1;
    out.width = ((static_cast<std::uint32_t>(disp >> 32) & 0xFFFu) + 1) / magh;
    out.height = ((static_cast<std::uint32_t>(disp >> 44) & 0x7FFu) + 1) / magv;
    if (!out.width || !out.height || out.width > 2048 || out.height > 2048) return false;
    const std::uint32_t fbp = static_cast<std::uint32_t>(fb) & 0x1FFu, fbw = static_cast<std::uint32_t>(fb >> 9) & 0x3Fu, psm = static_cast<std::uint32_t>(fb >> 15) & 0x1Fu;
    out.x = static_cast<std::uint32_t>(fb >> 32) & 0x7FFu;
    out.y = static_cast<std::uint32_t>(fb >> 43) & 0x7FFu;
    out.halved = (r.smode2 & 3u) == 3u;
    out.target = find_target(fbp, psm);
    if (!out.target && fbw) {
        // Nothing drawn there yet: show what GS memory holds (uploads).
        Target &t = target_for(fbp, fbw, psm);
        ensure_height(t, out.y + (out.halved ? out.height / 2 : out.height));
        out.target = &t;
    }
    if (out.target) resolve(*out.target);
    return out.target != nullptr;
}

WGPUTexture g_shown = nullptr;
WGPUTextureView g_shown_view = nullptr;
std::uint32_t g_shown_w = 0, g_shown_h = 0;
WGPUBuffer g_show_params = nullptr, g_readback = nullptr;
std::uint64_t g_readback_size = 0;

// Draws the shown buffer as rgba8 at scale into g_shown.
bool render_shown(const gs::DisplayRegs &r, std::uint32_t &w, std::uint32_t &h) {
    Shown s;
    if (!shown_buffer(r, s)) return false;
    submit_ops();
    w = s.width * g_scale;
    h = s.height * g_scale;
    if (w != g_shown_w || h != g_shown_h) {
        if (g_shown_view) wgpuTextureViewRelease(g_shown_view);
        if (g_shown) wgpuTextureRelease(g_shown);
        g_shown = make_texture(w, h, WGPUTextureFormat_RGBA8Unorm, WGPUTextureUsage_RenderAttachment | WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopySrc);
        g_shown_view = make_view(g_shown);
        g_shown_w = w;
        g_shown_h = h;
    }
    const std::uint32_t show[4] = {s.x * g_scale, s.y * g_scale, s.halved ? 1u : 0u, s.target->sixteen() ? 1u : 0u};
    wgpuQueueWriteBuffer(g_queue, g_show_params, 0, show, sizeof show);
    WGPUBindGroupEntry e[2] = {WGPU_BIND_GROUP_ENTRY_INIT, WGPU_BIND_GROUP_ENTRY_INIT};
    e[0].binding = 0;
    e[0].textureView = s.target->view;
    e[1].binding = 1;
    e[1].buffer = g_show_params;
    e[1].size = 16;
    WGPUBindGroupLayout layout = wgpuRenderPipelineGetBindGroupLayout(g_display_pipeline, 0);
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = layout;
    d.entryCount = 2;
    d.entries = e;
    WGPUBindGroup group = wgpuDeviceCreateBindGroup(g_device, &d);
    wgpuBindGroupLayoutRelease(layout);
    WGPUCommandEncoder enc = encoder();
    WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
    ca.view = g_shown_view;
    ca.loadOp = WGPULoadOp_Clear;
    ca.storeOp = WGPUStoreOp_Store;
    WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
    pd.colorAttachmentCount = 1;
    pd.colorAttachments = &ca;
    WGPURenderPassEncoder p = wgpuCommandEncoderBeginRenderPass(enc, &pd);
    wgpuRenderPassEncoderSetPipeline(p, g_display_pipeline);
    wgpuRenderPassEncoderSetBindGroup(p, 0, group, 0, nullptr);
    wgpuRenderPassEncoderDraw(p, 3, 1, 0, 0);
    wgpuRenderPassEncoderEnd(p);
    wgpuRenderPassEncoderRelease(p);
    submit_commands(enc);
    wgpuBindGroupRelease(group);
    return true;
}

WGPUSurface g_surface = nullptr;
WGPUTextureFormat g_surface_format = WGPUTextureFormat_BGRA8Unorm;
WGPUPresentMode g_present_mode = WGPUPresentMode_Fifo;
std::uint32_t g_surface_width = 0, g_surface_height = 0;

void configure_surface() {
    WGPUSurfaceConfiguration config = WGPU_SURFACE_CONFIGURATION_INIT;
    config.device = g_device;
    config.format = g_surface_format;
    config.usage = WGPUTextureUsage_RenderAttachment;
    config.width = std::max(g_surface_width, 1u);
    config.height = std::max(g_surface_height, 1u);
    config.presentMode = g_present_mode;
    config.alphaMode = WGPUCompositeAlphaMode_Auto;
    wgpuSurfaceConfigure(g_surface, &config);
}

void pump() {
#ifndef __EMSCRIPTEN__
    wgpuDevicePoll(g_device, true, nullptr);
#endif
}

// A 4-byte-per-texel texture read back to the CPU (waits for the GPU).
void read_pixels(WGPUTexture tex, std::uint32_t width, std::uint32_t height, std::vector<std::uint32_t> &rgba) {
    const std::uint32_t row = (width * 4 + 255) & ~255u;
    const std::uint64_t bytes = static_cast<std::uint64_t>(row) * height;
    if (bytes > g_readback_size) {
        if (g_readback) wgpuBufferRelease(g_readback);
        g_readback = make_buffer(bytes, WGPUBufferUsage_MapRead | WGPUBufferUsage_CopyDst);
        g_readback_size = bytes;
    }
    WGPUCommandEncoder enc = encoder();
    WGPUTexelCopyTextureInfo src = WGPU_TEXEL_COPY_TEXTURE_INFO_INIT;
    src.texture = tex;
    WGPUTexelCopyBufferInfo dst = WGPU_TEXEL_COPY_BUFFER_INFO_INIT;
    dst.buffer = g_readback;
    dst.layout.bytesPerRow = row;
    dst.layout.rowsPerImage = height;
    const WGPUExtent3D size{width, height, 1};
    wgpuCommandEncoderCopyTextureToBuffer(enc, &src, &dst, &size);
    submit_commands(enc);
    bool mapped = false;
    WGPUBufferMapCallbackInfo cb = WGPU_BUFFER_MAP_CALLBACK_INFO_INIT;
    cb.mode = WGPUCallbackMode_AllowProcessEvents;
    cb.callback = [](WGPUMapAsyncStatus, WGPUStringView, void *flag, void *) { *static_cast<bool *>(flag) = true; };
    cb.userdata1 = &mapped;
    wgpuBufferMapAsync(g_readback, WGPUMapMode_Read, 0, bytes, cb);
    while (!mapped) pump();
    const auto *p = static_cast<const std::uint8_t *>(wgpuBufferGetConstMappedRange(g_readback, 0, bytes));
    rgba.resize(static_cast<std::size_t>(width) * height);
    if (p)
        for (std::uint32_t y = 0; y < height; ++y) std::memcpy(rgba.data() + static_cast<std::size_t>(y) * width, p + static_cast<std::size_t>(y) * row, width * 4);
    wgpuBufferUnmap(g_readback);
}

// Reads the last presents' GPU timestamps (no wait: a ring of map buffers) and prints the split every 600 presents.
void time_present() {
#ifndef __EMSCRIPTEN__
    if (g_stamps && g_stamp_count >= 2 && !g_stamp_busy[g_stamp_ring]) {
        const std::uint32_t n = g_stamp_count & ~1u;
        WGPUCommandEncoder enc = wgpuDeviceCreateCommandEncoder(g_device, nullptr);
        wgpuCommandEncoderResolveQuerySet(enc, g_stamps, 0, n, g_stamp_resolve, 0);
        wgpuCommandEncoderCopyBufferToBuffer(enc, g_stamp_resolve, 0, g_stamp_read[g_stamp_ring], 0, n * 8ull);
        WGPUCommandBuffer cmd = wgpuCommandEncoderFinish(enc, nullptr);
        wgpuQueueSubmit(g_queue, 1, &cmd);
        wgpuCommandBufferRelease(cmd);
        wgpuCommandEncoderRelease(enc);
        g_stamp_busy[g_stamp_ring] = true;
        WGPUBufferMapCallbackInfo cb = WGPU_BUFFER_MAP_CALLBACK_INFO_INIT;
        cb.mode = WGPUCallbackMode_AllowProcessEvents;
        cb.callback = [](WGPUMapAsyncStatus status, WGPUStringView, void *slot, void *stamps) {
            const std::size_t i = reinterpret_cast<std::size_t>(slot), n = reinterpret_cast<std::size_t>(stamps);
            if (status == WGPUMapAsyncStatus_Success) {
                const auto *t = static_cast<const std::uint64_t *>(wgpuBufferGetConstMappedRange(g_stamp_read[i], 0, n * 8));
                std::uint64_t ticks = 0;
                for (std::size_t k = 0; t && k < n; k += 2) ticks += t[k + 1] > t[k] ? t[k + 1] - t[k] : 0;
                g_gpu_ms += static_cast<double>(ticks) * wgpuQueueGetTimestampPeriod(g_queue) / 1e6;
                ++g_gpu_frames;
                wgpuBufferUnmap(g_stamp_read[i]);
            }
            g_stamp_busy[i] = false;
        };
        cb.userdata1 = reinterpret_cast<void *>(static_cast<std::size_t>(g_stamp_ring));
        cb.userdata2 = reinterpret_cast<void *>(static_cast<std::size_t>(n));
        wgpuBufferMapAsync(g_stamp_read[g_stamp_ring], WGPUMapMode_Read, 0, n * 8ull, cb);
        g_stamp_ring = (g_stamp_ring + 1) % 3;
    }
    g_stamp_count = 0;
    wgpuDevicePoll(g_device, false, nullptr);
#endif
    if (++g_timed_presents % 600) return;
    const double n = 600.0;
    std::fprintf(stderr, "[native] ms per present: rebuild %.2f, decode %.2f, upload %.2f (tags %.2f), submit %.2f, present %.2f (acquire %.2f); "
                 "per present: rebuilds %.0f, uploads %.0f, passes %.0f, draws %.0f, copies %.0f, submits %.0f; GPU %.2f ms\n",
                 g_time_ms[T_REBUILD] / n, g_time_ms[T_DECODE] / n, g_time_ms[T_UPLOAD] / n, g_time_ms[T_TAG] / n, g_time_ms[T_SUBMIT] / n, g_time_ms[T_PRESENT] / n,
                 g_time_ms[T_ACQUIRE] / n, g_counts[C_REBUILD] / n, g_counts[C_UPLOAD] / n, g_counts[C_PASS] / n, g_counts[C_DRAW] / n, g_counts[C_COPY] / n,
                 g_counts[C_SUBMIT] / n, g_gpu_frames ? g_gpu_ms / static_cast<double>(g_gpu_frames) : 0.0);
    std::memset(g_time_ms, 0, sizeof g_time_ms);
    std::memset(g_counts, 0, sizeof g_counts);
    g_gpu_ms = 0.0;
    g_gpu_frames = 0;
}

}

bool on() { return g_on; }

bool init() {
    const char *wanted = std::getenv("PS2_RENDERER");
    if (!wanted || std::strcmp(wanted, "native") != 0) return false;
#ifndef __EMSCRIPTEN__
    WGPUInstanceExtras extras = {};
    extras.chain.sType = static_cast<WGPUSType>(WGPUSType_InstanceExtras);
    extras.backends = WGPUInstanceBackend_Primary;
    WGPUInstanceDescriptor id = WGPU_INSTANCE_DESCRIPTOR_INIT;
    id.nextInChain = &extras.chain;
    g_instance = wgpuCreateInstance(&id);
#else
    g_instance = wgpuCreateInstance(nullptr);
#endif
    if (!g_instance) return false;
    bool done = false;
    WGPURequestAdapterOptions options = WGPU_REQUEST_ADAPTER_OPTIONS_INIT;
    options.powerPreference = WGPUPowerPreference_HighPerformance;
    WGPURequestAdapterCallbackInfo acb = WGPU_REQUEST_ADAPTER_CALLBACK_INFO_INIT;
    acb.mode = WGPUCallbackMode_AllowSpontaneous;
    acb.callback = [](WGPURequestAdapterStatus status, WGPUAdapter a, WGPUStringView, void *out, void *flag) {
        if (status == WGPURequestAdapterStatus_Success) *static_cast<WGPUAdapter *>(out) = a;
        *static_cast<bool *>(flag) = true;
    };
    acb.userdata1 = &g_adapter;
    acb.userdata2 = &done;
    wgpuInstanceRequestAdapter(g_instance, &options, acb);
    while (!done) wgpuInstanceProcessEvents(g_instance);
    if (!g_adapter || !wgpuAdapterHasFeature(g_adapter, WGPUFeatureName_DualSourceBlending)) {
        std::fprintf(stderr, "[native] no adapter with dual-source blending, using the GS renderer\n");
        return false;
    }
    WGPUAdapterInfo info = WGPU_ADAPTER_INFO_INIT;
    if (wgpuAdapterGetInfo(g_adapter, &info) == WGPUStatus_Success) {
        std::fprintf(stderr, "[native] %.*s\n", static_cast<int>(info.device.length), info.device.data);
        wgpuAdapterInfoFreeMembers(info);
    }
    WGPUDeviceDescriptor dd = WGPU_DEVICE_DESCRIPTOR_INIT;
    WGPUFeatureName features[3] = {WGPUFeatureName_DualSourceBlending};
    dd.requiredFeatureCount = 1;
    g_time = std::getenv("PS2_NATIVE_TIME") != nullptr;
    bool stamps = false;
#ifndef __EMSCRIPTEN__
    const auto inside = static_cast<WGPUFeatureName>(WGPUNativeFeature_TimestampQueryInsideEncoders);
    stamps = g_time && wgpuAdapterHasFeature(g_adapter, WGPUFeatureName_TimestampQuery) && wgpuAdapterHasFeature(g_adapter, inside);
    if (stamps) features[1] = WGPUFeatureName_TimestampQuery, features[2] = inside, dd.requiredFeatureCount = 3;
#endif
    dd.requiredFeatures = features;
    dd.uncapturedErrorCallbackInfo.callback = [](WGPUDevice const *, WGPUErrorType type, WGPUStringView message, void *, void *) {
        std::fprintf(stderr, "[native] error %d: %.*s\n", static_cast<int>(type), static_cast<int>(message.length == WGPU_STRLEN ? std::strlen(message.data) : message.length), message.data);
    };
    done = false;
    WGPURequestDeviceCallbackInfo dcb = WGPU_REQUEST_DEVICE_CALLBACK_INFO_INIT;
    dcb.mode = WGPUCallbackMode_AllowSpontaneous;
    dcb.callback = [](WGPURequestDeviceStatus status, WGPUDevice d, WGPUStringView, void *out, void *flag) {
        if (status == WGPURequestDeviceStatus_Success) *static_cast<WGPUDevice *>(out) = d;
        *static_cast<bool *>(flag) = true;
    };
    dcb.userdata1 = &g_device;
    dcb.userdata2 = &done;
    wgpuAdapterRequestDevice(g_adapter, &dd, dcb);
    while (!done) wgpuInstanceProcessEvents(g_instance);
    if (!g_device) return false;
    g_queue = wgpuDeviceGetQueue(g_device);
    if (stamps) {
        WGPUQuerySetDescriptor qd = WGPU_QUERY_SET_DESCRIPTOR_INIT;
        qd.type = WGPUQueryType_Timestamp;
        qd.count = kStamps;
        g_stamps = wgpuDeviceCreateQuerySet(g_device, &qd);
        g_stamp_resolve = make_buffer(kStamps * 8, WGPUBufferUsage_QueryResolve | WGPUBufferUsage_CopySrc);
        for (WGPUBuffer &b : g_stamp_read) b = make_buffer(kStamps * 8, WGPUBufferUsage_MapRead | WGPUBufferUsage_CopyDst);
    }
    if (g_time) std::fprintf(stderr, "[native] timing on (%s)\n", stamps ? "GPU timestamps" : "no GPU timestamps");
    if (const char *scale = std::getenv("PS2_SCALE")) g_scale = std::clamp<std::uint32_t>(static_cast<std::uint32_t>(std::atoi(scale)), 1u, 3u);
    if (const char *aspect = std::getenv("PS2_ASPECT"); aspect && std::strcmp(aspect, "16:9") == 0) g_aspect_w = 16.0f, g_aspect_h = 9.0f;

    WGPUShaderSourceWGSL source = WGPU_SHADER_SOURCE_WGSL_INIT;
    source.code = view(kNativeShader);
    WGPUShaderModuleDescriptor md = WGPU_SHADER_MODULE_DESCRIPTOR_INIT;
    md.nextInChain = &source.chain;
    g_module = wgpuDeviceCreateShaderModule(g_device, &md);

    WGPUBindGroupLayoutEntry pe = WGPU_BIND_GROUP_LAYOUT_ENTRY_INIT;
    pe.binding = 0;
    pe.visibility = WGPUShaderStage_Vertex | WGPUShaderStage_Fragment;
    pe.buffer.type = WGPUBufferBindingType_ReadOnlyStorage;
    WGPUBindGroupLayoutDescriptor ld = WGPU_BIND_GROUP_LAYOUT_DESCRIPTOR_INIT;
    ld.entryCount = 1;
    ld.entries = &pe;
    g_params_layout = wgpuDeviceCreateBindGroupLayout(g_device, &ld);
    WGPUBindGroupLayoutEntry te[3] = {WGPU_BIND_GROUP_LAYOUT_ENTRY_INIT, WGPU_BIND_GROUP_LAYOUT_ENTRY_INIT, WGPU_BIND_GROUP_LAYOUT_ENTRY_INIT};
    te[0].binding = 0;
    te[0].visibility = WGPUShaderStage_Fragment;
    te[0].texture.sampleType = WGPUTextureSampleType_Float;
    te[0].texture.viewDimension = WGPUTextureViewDimension_2D;
    for (int i = 1; i < 3; ++i) {
        te[i].binding = static_cast<std::uint32_t>(i);
        te[i].visibility = WGPUShaderStage_Fragment;
        te[i].sampler.type = WGPUSamplerBindingType_Filtering;
    }
    ld.entryCount = 3;
    ld.entries = te;
    g_texture_layout = wgpuDeviceCreateBindGroupLayout(g_device, &ld);
    ld.entryCount = 1;
    g_dest_layout = wgpuDeviceCreateBindGroupLayout(g_device, &ld);
    const WGPUBindGroupLayout layouts[3] = {g_params_layout, g_texture_layout, g_dest_layout};
    WGPUPipelineLayoutDescriptor pld = WGPU_PIPELINE_LAYOUT_DESCRIPTOR_INIT;
    pld.bindGroupLayoutCount = 3;
    pld.bindGroupLayouts = layouts;
    g_draw_layout = wgpuDeviceCreatePipelineLayout(g_device, &pld);
    te[1].sampler.type = WGPUSamplerBindingType_BindingNotUsed;
    te[1].buffer.type = WGPUBufferBindingType_ReadOnlyStorage;
    ld.entryCount = 2;
    g_convert_layout = wgpuDeviceCreateBindGroupLayout(g_device, &ld);
    const WGPUBindGroupLayout convert_layouts[2] = {g_params_layout, g_convert_layout};
    pld.bindGroupLayoutCount = 2;
    pld.bindGroupLayouts = convert_layouts;
    g_convert_pipeline_layout = wgpuDeviceCreatePipelineLayout(g_device, &pld);

    for (std::uint32_t i = 0; i < 4; ++i) {
        WGPUSamplerDescriptor sd = WGPU_SAMPLER_DESCRIPTOR_INIT;
        sd.addressModeU = (i & 1u) ? WGPUAddressMode_ClampToEdge : WGPUAddressMode_Repeat;
        sd.addressModeV = (i & 2u) ? WGPUAddressMode_ClampToEdge : WGPUAddressMode_Repeat;
        sd.mipmapFilter = WGPUMipmapFilterMode_Linear;
        sd.lodMaxClamp = 16.0f;
        g_near[i] = wgpuDeviceCreateSampler(g_device, &sd);
        sd.magFilter = sd.minFilter = WGPUFilterMode_Linear;
        g_lin[i] = wgpuDeviceCreateSampler(g_device, &sd);
    }
    WGPUSamplerDescriptor sd = WGPU_SAMPLER_DESCRIPTOR_INIT;
    sd.magFilter = sd.minFilter = WGPUFilterMode_Linear;
    g_smooth = wgpuDeviceCreateSampler(g_device, &sd);
    g_init_pipeline = full_pipeline("fs_init", kColor);
    g_display_pipeline = full_pipeline("fs_display", WGPUTextureFormat_RGBA8Unorm);
    g_show_params = make_buffer(16, WGPUBufferUsage_Uniform | WGPUBufferUsage_CopyDst);
    WGPUTexture blank = make_texture(1, 1, WGPUTextureFormat_RGBA8Unorm, WGPUTextureUsage_TextureBinding | WGPUTextureUsage_CopyDst);
    const std::uint32_t white = 0xFFFFFFFFu;
    write_texture(blank, 0, 1, 1, &white);
    WGPUTextureView blank_view = make_view(blank);
    g_blank_group = texture_group(blank_view, 0);
    WGPUBindGroupEntry be = WGPU_BIND_GROUP_ENTRY_INIT;
    be.binding = 0;
    be.textureView = blank_view;
    WGPUBindGroupDescriptor bd = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    bd.layout = g_dest_layout;
    bd.entryCount = 1;
    bd.entries = &be;
    g_blank_dest_group = wgpuDeviceCreateBindGroup(g_device, &bd);
    g_to16_pipeline = convert_pipeline("fs_to16");
    g_to32_pipeline = convert_pipeline("fs_to32");
    g_pack16_pipeline = full_pipeline("fs_pack16", WGPUTextureFormat_R32Uint);
    g_pack32_pipeline = full_pipeline("fs_pack32", WGPUTextureFormat_R32Uint);
    if (!g_module || !g_init_pipeline || !g_display_pipeline || !g_to16_pipeline || !g_to32_pipeline || !g_pack16_pipeline || !g_pack32_pipeline) return false;
    load_tables();
    g_lut = make_lut();
    g_packs = texpack::init();
    for (std::uint32_t p = 0; p < kPages; ++p) g_page_gen[p] = 1;
    std::fprintf(stderr, "[native] renderer on, scale %u, aspect %.0f:%.0f\n", g_scale, g_aspect_w, g_aspect_h);
    g_on = true;
    return true;
}

void reset() {
    submit_ops();
    for (auto &[k, t] : g_targets) {
        drop_texture(t.tex, t.view);
        drop_texture(t.copy, t.copy_view);
        drop_group(t.group);
        drop_group(t.copy_group);
    }
    for (auto &[k, z] : g_depths) drop_texture(z.tex, z.view);
    for (auto &[k, t] : g_textures) {
        drop_texture(t.tex, t.view);
        for (WGPUBindGroup &g : t.groups) drop_group(g);
    }
    g_targets.clear();
    g_depths.clear();
    g_textures.clear();
    for (Memo &m : g_memo) m.valid = false;
    for (std::uint32_t p = 0; p < kPages; ++p) ++g_page_gen[p];
    ++g_upload_serial;
    ++g_clut_version;
    g_cur.valid = false;
    g_upload = Upload{};
    g_last_clut = ClutLoad{};
    texpack::clear_tags();
    for (WGPUBindGroup g : g_dead_groups) wgpuBindGroupRelease(g);
    for (WGPUTextureView v : g_dead_views) wgpuTextureViewRelease(v);
    for (WGPUTexture t : g_dead_textures) wgpuTextureRelease(t);
    g_dead_groups.clear();
    g_dead_views.clear();
    g_dead_textures.clear();
}

void draw(const State &st, const Vertex *v, int) {
    const std::uint32_t prim = static_cast<std::uint32_t>(st.prim) & 7u;
    if (prim < 3 || prim == 7) {
        ++g_skipped[prim];
        missing(prim == 0 ? "points" : prim == 7 ? "primitive kind 7" : "lines");
        return;
    }
    const std::uint64_t attr = prim_attr(st);
    Current &cur = g_cur;
    const bool inputs = (attr & 0x10u) && (cur.upload != g_upload_serial || cur.clut != g_clut_version);
    if (!cur.valid || inputs || cur.attr != attr) {
        rebuild(st, attr);
    } else if (cur.generation != gs::g_setup_generation) {
        if (regs_of(st, attr) == cur.regs) cur.generation = gs::g_setup_generation;
        else rebuild(st, attr);
    }
    if (cur.skip) {
        ++g_skipped[prim];
        return;
    }
    NVertex out[6];
    std::uint32_t n;
    if (prim == 6) {
        const Vertex &a = v[0], &b = v[1];
        Vertex c0 = b, c1 = b, c2 = b, c3 = b;
        c0.x = a.x, c0.y = a.y, c0.u = a.u, c0.v = a.v, c0.s = a.s, c0.t = a.t;
        c1.y = a.y, c1.v = a.v, c1.t = a.t;
        c2.x = a.x, c2.u = a.u, c2.s = a.s;
        out[0] = make_vertex(c0, b);
        out[1] = make_vertex(c1, b);
        out[2] = make_vertex(c2, b);
        out[3] = out[1];
        out[4] = make_vertex(c3, b);
        out[5] = out[2];
        n = 6;
        ++g_sprites;
    } else {
        for (int i = 0; i < 3; ++i) out[i] = make_vertex(v[i], cur.iip ? v[i] : v[2]);
        n = 3;
        ++g_triangles;
    }
    float minx = out[0].x, miny = out[0].y, maxx = out[0].x, maxy = out[0].y;
    for (std::uint32_t i = 1; i < n; ++i) minx = std::min(minx, out[i].x), miny = std::min(miny, out[i].y), maxx = std::max(maxx, out[i].x), maxy = std::max(maxy, out[i].y);
    const std::int32_t rows = std::min(static_cast<std::int32_t>(std::ceil(maxy)), cur.scissor_y1 + 1);
    if (rows > static_cast<std::int32_t>(cur.target->height)) {
        ensure_height(*cur.target, static_cast<std::uint32_t>(rows));
        rebuild(st, attr);
        if (cur.skip) return;
        for (std::uint32_t i = 0; i < n; ++i) out[i].param = cur.param;
    }
    const std::int32_t box[4] = {static_cast<std::int32_t>(std::floor(minx)), static_cast<std::int32_t>(std::floor(miny)),
                                 static_cast<std::int32_t>(std::ceil(maxx)) + 1, static_cast<std::int32_t>(std::ceil(maxy)) + 1};
    if (cur.masked) {
        // The destination copy must hold what earlier primitives drew under this one.
        const std::int32_t *d = cur.target->dirty;
        if (d[2] > d[0] && box[0] < d[2] && d[0] < box[2] && box[1] < d[3] && d[1] < box[3]) copy_target(*cur.target);
        ++g_masked;
    }
    ++g_prims;
    add_vertices(out, n, box);
}

void finish_upload() {
    Upload &u = g_upload;
    if (!u.active) return;
    const Timer timer(T_UPLOAD);
    count(C_UPLOAD);
    write_upload(u);
    {
        const Timer tag(T_TAG);
        texpack::tag_upload(u.bp, u.bw, u.psm, u.x, u.y, u.w, u.h, u.bytes.data(), u.bytes.size());
    }
    // Targets under the upload get the rows it touched back from memory; views convert from their parent.
    for (Target *t : u.targets) {
        if (t->parent) {
            t->ahead = false;
            t->synced = ~0u;
            continue;
        }
        const std::int32_t first = static_cast<std::int32_t>(u.lo / 8192u) - static_cast<std::int32_t>(t->fbp);
        const std::int32_t last = static_cast<std::int32_t>((u.hi - 1) / 8192u) - static_cast<std::int32_t>(t->fbp);
        const std::uint32_t ph = t->sixteen() ? 64u : 32u;
        const std::uint32_t from = static_cast<std::uint32_t>(std::max(first, 0)) / t->fbw * ph;
        const std::uint32_t to = std::min(static_cast<std::uint32_t>(last / static_cast<std::int32_t>(t->fbw) + 1) * ph, t->height);
        if (from < to) fill_target(*t, from, to);
        ++t->version;
        t->stamp = ++g_stamp;
    }
    if (!u.targets.empty()) g_cur.valid = false;
    u.targets.clear();
    u.active = false;
    u.bytes.clear();
}

void image_begin(const State &s) {
    finish_upload();
    const std::uint64_t buf = s.bitbltbuf, pos = s.trxpos, reg = s.trxreg;
    Upload &u = g_upload;
    u.bp = static_cast<std::uint32_t>(buf >> 32) & 0x3FFFu;
    u.bw = static_cast<std::uint32_t>(buf >> 48) & 0x3Fu;
    u.psm = static_cast<std::uint32_t>(buf >> 56) & 0x3Fu;
    u.x = static_cast<std::uint32_t>(pos >> 32) & 0x7FFu;
    u.y = static_cast<std::uint32_t>(pos >> 48) & 0x7FFu;
    u.w = static_cast<std::uint32_t>(reg) & 0xFFFu;
    u.h = static_cast<std::uint32_t>(reg >> 32) & 0xFFFu;
    if (!u.w || !u.h) return;
    ++g_upload_serial;
    std::uint32_t lo = ~0u, hi = 0;
    for_pages(u.bp, u.bw, u.psm, u.x, u.y, u.w, u.h, [&](std::uint32_t p) {
        ++g_page_gen[p];
        lo = std::min(lo, p * 8192u);
        hi = std::max(hi, p * 8192u + 8192u);
    });
    u.lo = lo;
    u.hi = hi;
    u.targets = targets_under(lo, hi);
    for (Target *t : u.targets) read_back(*t);
    u.expected = static_cast<std::size_t>(u.w) * u.h * bits_per_pixel(u.psm) / 8;
    u.active = true;
}

void image_data(const std::uint8_t *data, std::size_t bytes) {
    Upload &u = g_upload;
    if (!u.active) return;
    u.bytes.insert(u.bytes.end(), data, data + bytes);
    if (u.bytes.size() >= u.expected) finish_upload();
}

void transfer(std::uint32_t dir) {
    if (dir != 1) {
        missing("local copies");
        return;
    }
    // Download: targets under the source rectangle go into the CPU memory copy, which gs.cpp then reads.
    finish_upload();
    const std::uint64_t buf = gs::g_state.bitbltbuf, pos = gs::g_state.trxpos, reg = gs::g_state.trxreg;
    const std::uint32_t w = static_cast<std::uint32_t>(reg) & 0xFFFu, h = static_cast<std::uint32_t>(reg >> 32) & 0xFFFu;
    if (!w || !h) return;
    std::uint32_t lo = ~0u, hi = 0;
    for_pages(static_cast<std::uint32_t>(buf) & 0x3FFFu, static_cast<std::uint32_t>(buf >> 16) & 0x3Fu, static_cast<std::uint32_t>(buf >> 24) & 0x3Fu,
              static_cast<std::uint32_t>(pos) & 0x7FFu, static_cast<std::uint32_t>(pos >> 16) & 0x7FFu, w, h, [&](std::uint32_t p) {
                  lo = std::min(lo, p * 8192u);
                  hi = std::max(hi, p * 8192u + 8192u);
              });
    for (Target *t : targets_under(lo, hi)) read_back(*t);
}

void load_clut(std::uint64_t tex0, std::uint64_t texclut) {
    finish_upload();
    read_clut(tex0, texclut);
    texpack::tag_clut(tex0, texclut);
}

void flush() { submit_ops(); }

void wait_idle() {
    submit_ops();
    pump();
}

bool display(const gs::DisplayRegs &r, std::vector<std::uint32_t> &rgba, std::uint32_t &width, std::uint32_t &height) {
    if (!render_shown(r, width, height)) return false;
    read_pixels(g_shown, width, height, rgba);
    return true;
}

bool attach_surface(int kind, void *display, std::uint64_t window, void *surface, std::uint32_t width, std::uint32_t height) {
#ifdef __EMSCRIPTEN__
    (void)kind, (void)display, (void)window, (void)surface, (void)width, (void)height;
    return false;
#else
    WGPUSurfaceDescriptor sd = WGPU_SURFACE_DESCRIPTOR_INIT;
    WGPUSurfaceSourceXlibWindow xlib = WGPU_SURFACE_SOURCE_XLIB_WINDOW_INIT;
    WGPUSurfaceSourceWaylandSurface wayland = WGPU_SURFACE_SOURCE_WAYLAND_SURFACE_INIT;
    WGPUSurfaceSourceWindowsHWND hwnd = WGPU_SURFACE_SOURCE_WINDOWS_HWND_INIT;
    if (kind == 3) {
        hwnd.hinstance = display;
        hwnd.hwnd = reinterpret_cast<void *>(window);
        sd.nextInChain = &hwnd.chain;
    } else if (kind == 0) {
        xlib.display = display;
        xlib.window = window;
        sd.nextInChain = &xlib.chain;
    } else if (kind == 1) {
        wayland.display = display;
        wayland.surface = surface;
        sd.nextInChain = &wayland.chain;
    } else {
        return false;
    }
    g_surface = wgpuInstanceCreateSurface(g_instance, &sd);
    if (!g_surface) return false;
    WGPUSurfaceCapabilities caps = WGPU_SURFACE_CAPABILITIES_INIT;
    if (wgpuSurfaceGetCapabilities(g_surface, g_adapter, &caps) != WGPUStatus_Success || !caps.formatCount) {
        wgpuSurfaceRelease(g_surface);
        g_surface = nullptr;
        return false;
    }
    g_surface_format = caps.formats[0];
    for (std::size_t i = 0; i < caps.formatCount; ++i)
        if (caps.formats[i] == WGPUTextureFormat_BGRA8Unorm || caps.formats[i] == WGPUTextureFormat_RGBA8Unorm) {
            g_surface_format = caps.formats[i];
            break;
        }
    g_present_mode = WGPUPresentMode_Fifo;
    for (const WGPUPresentMode m : {WGPUPresentMode_Immediate, WGPUPresentMode_Mailbox})
        for (std::size_t i = 0; i < caps.presentModeCount; ++i)
            if (caps.presentModes[i] == m) g_present_mode = m;
    wgpuSurfaceCapabilitiesFreeMembers(caps);
    g_surface_width = width;
    g_surface_height = height;
    configure_surface();
    g_blit_pipeline = full_pipeline("fs_blit", g_surface_format);
    return g_blit_pipeline != nullptr;
#endif
}

void resize_surface(std::uint32_t width, std::uint32_t height) {
    if (!g_surface || (width == g_surface_width && height == g_surface_height)) return;
    g_surface_width = width;
    g_surface_height = height;
    configure_surface();
}

bool present(const gs::DisplayRegs &r) {
    if (!g_surface) return false;
    const Timer timer(T_PRESENT);
    if (g_time) time_present();
    Shown shown;
    if (!shown_buffer(r, shown)) {
        submit_ops();
        return true;
    }
    // Acquire before the frame's commands are submitted: the acquire waits for the GPU work submitted before it, and
    // right after the submit that is the whole frame (T59: ~5 ms of render-thread wait per present in the race intro).
    WGPUSurfaceTexture st = WGPU_SURFACE_TEXTURE_INIT;
    {
        const Timer acquire(T_ACQUIRE);
        wgpuSurfaceGetCurrentTexture(g_surface, &st);
    }
    if (st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal && st.status != WGPUSurfaceGetCurrentTextureStatus_SuccessSuboptimal) {
        if (st.texture) wgpuTextureRelease(st.texture);
        configure_surface();
        submit_ops();
        return true;
    }
    std::uint32_t w = 0, h = 0;
    render_shown(r, w, h);
    WGPUTextureView target = wgpuTextureCreateView(st.texture, nullptr);
    WGPUBindGroupEntry e[2] = {WGPU_BIND_GROUP_ENTRY_INIT, WGPU_BIND_GROUP_ENTRY_INIT};
    e[0].binding = 0;
    e[0].textureView = g_shown_view;
    e[1].binding = 1;
    e[1].sampler = g_smooth;
    WGPUBindGroupLayout layout = wgpuRenderPipelineGetBindGroupLayout(g_blit_pipeline, 0);
    WGPUBindGroupDescriptor d = WGPU_BIND_GROUP_DESCRIPTOR_INIT;
    d.layout = layout;
    d.entryCount = 2;
    d.entries = e;
    WGPUBindGroup group = wgpuDeviceCreateBindGroup(g_device, &d);
    wgpuBindGroupLayoutRelease(layout);
    WGPUCommandEncoder enc = encoder();
    WGPURenderPassColorAttachment ca = WGPU_RENDER_PASS_COLOR_ATTACHMENT_INIT;
    ca.view = target;
    ca.loadOp = WGPULoadOp_Clear;
    ca.storeOp = WGPUStoreOp_Store;
    WGPURenderPassDescriptor pd = WGPU_RENDER_PASS_DESCRIPTOR_INIT;
    pd.colorAttachmentCount = 1;
    pd.colorAttachments = &ca;
    WGPURenderPassEncoder p = wgpuCommandEncoderBeginRenderPass(enc, &pd);
    const float sw = static_cast<float>(g_surface_width), sh = static_cast<float>(g_surface_height);
    const float vw = std::min(sw, sh * g_aspect_w / g_aspect_h), vh = vw * g_aspect_h / g_aspect_w;
    wgpuRenderPassEncoderSetViewport(p, std::floor((sw - vw) / 2), std::floor((sh - vh) / 2), vw, vh, 0.0f, 1.0f);
    wgpuRenderPassEncoderSetPipeline(p, g_blit_pipeline);
    wgpuRenderPassEncoderSetBindGroup(p, 0, group, 0, nullptr);
    wgpuRenderPassEncoderDraw(p, 3, 1, 0, 0);
    wgpuRenderPassEncoderEnd(p);
    wgpuRenderPassEncoderRelease(p);
    submit_commands(enc);
    wgpuSurfacePresent(g_surface);
    wgpuBindGroupRelease(group);
    wgpuTextureViewRelease(target);
    wgpuTextureRelease(st.texture);
    return true;
}

void stats(std::uint64_t gs_raster) {
    std::fprintf(stderr, "[native] translator drew %llu primitives (%llu triangles, %llu sprites), skipped %llu; GS raster %llu; textures decoded %llu, from the pack %llu; targets %zu; submits %llu\n",
                 static_cast<unsigned long long>(g_prims), static_cast<unsigned long long>(g_triangles), static_cast<unsigned long long>(g_sprites),
                 static_cast<unsigned long long>(g_skipped[0] + g_skipped[1] + g_skipped[2] + g_skipped[3] + g_skipped[4] + g_skipped[5] + g_skipped[6] + g_skipped[7]),
                 static_cast<unsigned long long>(gs_raster), static_cast<unsigned long long>(g_decoded), static_cast<unsigned long long>(g_replaced), g_targets.size(),
                 static_cast<unsigned long long>(g_flushes));
    std::fprintf(stderr, "[native] masked primitives %llu, format conversions %llu, target read-backs %llu\n", static_cast<unsigned long long>(g_masked),
                 static_cast<unsigned long long>(g_conversions), static_cast<unsigned long long>(g_read_backs));
    for (const auto &[what, n] : g_missing) std::fprintf(stderr, "[native] not done yet: %s (%llu times)\n", what.c_str(), static_cast<unsigned long long>(n));
    for (const auto &[key, t] : g_targets)
        std::fprintf(stderr, "[native] target fbp 0x%X fbw %u psm 0x%X %ux%u%s\n", t.fbp, t.fbw, t.psm, t.width, t.height, t.parent ? " (view of a 32-bit target)" : "");
}

}
