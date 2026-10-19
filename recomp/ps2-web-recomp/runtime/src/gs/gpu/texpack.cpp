#include "texpack.hpp"
#include "../gs.hpp"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace ps2::gs::texpack {

namespace {

namespace fs = std::filesystem;

fs::path g_pack_dir, g_dump_dir;
std::unordered_map<std::uint64_t, fs::path> g_index;
std::unordered_map<std::uint64_t, std::unique_ptr<Image>> g_loaded;
std::unordered_set<std::uint64_t> g_dumped;

std::uint64_t mix(std::uint64_t h, std::uint64_t v) {
    h ^= v;
    h *= 0x9E3779B97F4A7C15ull;
    return h ^ (h >> 29);
}

// GS block order inside a page: 8x4 blocks for the 32-bit and 8-bit layouts, 4x8 for 16-bit and 4-bit.
const std::uint8_t kBlocks32[32] = {0, 1, 4, 5, 16, 17, 20, 21, 2, 3, 6, 7, 18, 19, 22, 23, 8, 9, 12, 13, 24, 25, 28, 29, 10, 11, 14, 15, 26, 27, 30, 31};
const std::uint8_t kBlocks16[32] = {0, 2, 8, 10, 1, 3, 9, 11, 4, 6, 12, 14, 5, 7, 13, 15, 16, 18, 24, 26, 17, 19, 25, 27, 20, 22, 28, 30, 21, 23, 29, 31};
const std::uint8_t kBlocks16S[32] = {0, 2, 16, 18, 1, 3, 17, 19, 8, 10, 24, 26, 9, 11, 25, 27, 4, 6, 20, 22, 5, 7, 21, 23, 12, 14, 28, 30, 13, 15, 29, 31};

// A block is 4 columns of 64 bytes, each bw x bh/4 pixels.
struct Layout {
    std::uint32_t pw, ph, bw, bh, cols, bpp;
    const std::uint8_t *blocks;
};

bool layout(std::uint32_t psm, Layout &l) {
    switch (psm) {
    case PSMCT32: l = {64, 32, 8, 8, 8, 32, kBlocks32}; return true;
    case PSMCT24: l = {64, 32, 8, 8, 8, 24, kBlocks32}; return true;
    case PSMCT16: l = {64, 64, 16, 8, 4, 16, kBlocks16}; return true;
    case PSMCT16S: l = {64, 64, 16, 8, 4, 16, kBlocks16S}; return true;
    case PSMT8: l = {128, 64, 16, 16, 8, 8, kBlocks32}; return true;
    case PSMT4: l = {128, 128, 32, 16, 4, 4, kBlocks16}; return true;
    default: return false;
    }
}

// Tag of each 64-byte GS column: a hash of the bytes the last upload wrote to all of it; 0 = unknown.
std::vector<std::uint64_t> g_tags(kMemorySize / 64);
// Tag of each 16-entry group of the CLUT buffer: the source columns of the load that wrote it.
std::uint64_t g_clut_tags[32] = {};
std::vector<std::uint64_t> g_acc;

std::uint64_t &tag(std::uint32_t bp, std::uint32_t bw, const Layout &l, std::uint32_t x, std::uint32_t y) {
    // Shifts instead of divisions: this runs for every column an upload writes.
    const int pws = std::countr_zero(l.pw), phs = std::countr_zero(l.ph), bws = std::countr_zero(l.bw), bhs = std::countr_zero(l.bh);
    const std::uint32_t per_row = std::max<std::uint32_t>(1, (bw * 64) >> pws);
    const std::uint32_t block = bp + ((x >> pws) + (y >> phs) * per_row) * 32 + l.blocks[((y & (l.ph - 1)) >> bhs) * l.cols + ((x & (l.pw - 1)) >> bws)];
    return g_tags[(block * 4 + ((y & (l.bh - 1)) >> (bhs - 2))) & (kMemorySize / 64 - 1)];
}

// Mixes the column tags of a rectangle, in row order; 0 if one is unknown.
std::uint64_t columns(std::uint32_t bp, std::uint32_t bw, const Layout &l, std::uint32_t x0, std::uint32_t y0, std::uint32_t x1, std::uint32_t y1, std::uint64_t h) {
    const std::uint32_t ch = l.bh / 4;
    for (std::uint32_t y = y0 / ch * ch; y <= y1; y += ch)
        for (std::uint32_t x = x0 / l.bw * l.bw; x <= x1; x += l.bw) {
            const std::uint64_t t = tag(bp, bw, l, x, y);
            if (!t) return 0;
            h = mix(h, t);
        }
    return h | 1;
}

bool paletted(std::uint32_t psm) { return psm == PSMT8 || psm == PSMT4; }

std::uint32_t expand16(std::uint32_t c, const std::uint32_t *w) {
    std::uint32_t a = w[20] & 0xFFu;
    if (c & 0x8000u) a = (w[20] >> 8) & 0xFFu;
    else if ((w[0] & 32768u) && !(c & 0x7FFFu)) a = 0;
    return ((c & 0x1Fu) << 3) | (((c >> 5) & 0x1Fu) << 11) | (((c >> 10) & 0x1Fu) << 19) | (a << 24);
}

// Same conversion as the shader's convert().
std::uint32_t texel(const std::uint32_t *w, const std::uint32_t *clut, std::uint32_t x, std::uint32_t y) {
    const std::uint32_t psm = w[14], raw = read_pixel(psm, w[12], w[13], x, y);
    switch (psm) {
    case PSMCT24: return raw | (((w[0] & 32768u) && !raw ? 0u : w[20] & 0xFFu) << 24);
    case PSMCT16: return expand16(raw, w);
    case PSMT8:
    case PSMT4: {
        const std::uint32_t e = psm == PSMT8 ? clut[raw & 255u] : clut[((w[17] & 15u) * 16u + raw) & 511u];
        return w[16] == PSMCT32 || w[16] == PSMCT24 ? e : expand16(e, w);
    }
    default: return raw;
    }
}

std::uint32_t crc32(const std::uint8_t *p, std::size_t n, std::uint32_t c) {
    for (std::size_t i = 0; i < n; ++i) {
        c ^= p[i];
        for (int k = 0; k < 8; ++k) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return c;
}

void put32(std::vector<std::uint8_t> &out, std::uint32_t v) {
    for (int s = 24; s >= 0; s -= 8) out.push_back(static_cast<std::uint8_t>(v >> s));
}

void chunk(std::vector<std::uint8_t> &out, const char *type, const std::vector<std::uint8_t> &data) {
    put32(out, static_cast<std::uint32_t>(data.size()));
    const std::size_t start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    put32(out, ~crc32(out.data() + start, out.size() - start, ~0u));
}

// RGBA PNG with stored (uncompressed) deflate blocks.
void write_png(const fs::path &path, std::uint32_t width, std::uint32_t height, const std::vector<std::uint32_t> &texels) {
    std::vector<std::uint8_t> raw;
    for (std::uint32_t y = 0; y < height; ++y) {
        raw.push_back(0);
        for (std::uint32_t x = 0; x < width; ++x)
            for (int s = 0; s < 32; s += 8) raw.push_back(static_cast<std::uint8_t>(texels[y * width + x] >> s));
    }
    std::vector<std::uint8_t> z = {0x78, 0x01};
    std::uint32_t a = 1, b = 0;
    for (std::uint8_t v : raw) {
        a = (a + v) % 65521;
        b = (b + a) % 65521;
    }
    for (std::size_t at = 0; at < raw.size(); at += 65535) {
        const std::size_t n = std::min<std::size_t>(65535, raw.size() - at);
        z.push_back(at + n == raw.size() ? 1 : 0);
        for (std::uint32_t v : {static_cast<std::uint32_t>(n), static_cast<std::uint32_t>(~n & 0xFFFFu)}) {
            z.push_back(static_cast<std::uint8_t>(v));
            z.push_back(static_cast<std::uint8_t>(v >> 8));
        }
        z.insert(z.end(), raw.begin() + static_cast<std::ptrdiff_t>(at), raw.begin() + static_cast<std::ptrdiff_t>(at + n));
    }
    put32(z, (b << 16) | a);
    std::vector<std::uint8_t> header;
    put32(header, width);
    put32(header, height);
    header.insert(header.end(), {8, 6, 0, 0, 0});
    std::vector<std::uint8_t> out = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    chunk(out, "IHDR", header);
    chunk(out, "IDAT", z);
    chunk(out, "IEND", {});
    std::ofstream(path, std::ios::binary).write(reinterpret_cast<const char *>(out.data()), static_cast<std::streamsize>(out.size()));
}

struct Bits {
    const std::uint8_t *p, *end;
    std::uint64_t buf = 0;
    int n = 0, past = 0;
    bool bad = false;

    void fill() {
        while (n <= 56) {
            if (p < end) buf |= static_cast<std::uint64_t>(*p++) << n;
            else bad = bad || ++past > 8;
            n += 8;
        }
    }
    std::uint32_t take(int k) {
        if (n < k) fill();
        const std::uint32_t v = static_cast<std::uint32_t>(buf & ((1ull << k) - 1));
        buf >>= k;
        n -= k;
        return v;
    }
};

// Canonical Huffman code as a 15-bit lookup table: entry = symbol << 4 | code length.
struct Huffman {
    std::vector<std::uint16_t> table;

    void build(const std::uint8_t *lengths, int count) {
        table.assign(1u << 15, 0);
        int counts[16] = {}, next[16] = {};
        for (int i = 0; i < count; ++i) ++counts[lengths[i]];
        counts[0] = 0;
        for (int bits = 1, code = 0; bits < 16; ++bits) next[bits] = code = (code + counts[bits - 1]) << 1;
        for (int sym = 0; sym < count; ++sym) {
            const int len = lengths[sym];
            if (!len) continue;
            const int code = next[len]++;
            int rev = 0;
            for (int i = 0; i < len; ++i) rev |= ((code >> i) & 1) << (len - 1 - i);
            for (int k = rev; k < (1 << 15); k += 1 << len) table[static_cast<std::size_t>(k)] = static_cast<std::uint16_t>(sym << 4 | len);
        }
    }
    int decode(Bits &in) const {
        if (in.n < 15) in.fill();
        const std::uint16_t e = table[in.buf & 0x7FFFu];
        if (!(e & 15u)) {
            in.bad = true;
            return 0;
        }
        in.buf >>= e & 15u;
        in.n -= e & 15u;
        return e >> 4;
    }
};

bool inflate(const std::uint8_t *data, std::size_t size, std::vector<std::uint8_t> &out) {
    static const std::uint16_t kLenBase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
    static const std::uint8_t kLenExtra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
    static const std::uint16_t kDistBase[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
    static const std::uint8_t kDistExtra[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};
    static const std::uint8_t kOrder[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    Bits in{data, data + size};
    Huffman lit, dist;
    for (bool last = false; !last && !in.bad;) {
        last = in.take(1);
        const std::uint32_t type = in.take(2);
        if (type == 0) {
            in.take(in.n % 8);
            const std::uint32_t len = in.take(16);
            in.take(16);
            for (std::uint32_t i = 0; i < len && !in.bad; ++i) out.push_back(static_cast<std::uint8_t>(in.take(8)));
            continue;
        }
        std::uint8_t lengths[320] = {};
        if (type == 1) {
            for (int i = 0; i < 288; ++i) lengths[i] = i < 144 ? 8 : i < 256 ? 9 : i < 280 ? 7 : 8;
            for (int i = 288; i < 320; ++i) lengths[i] = 5;
            lit.build(lengths, 288);
            dist.build(lengths + 288, 30);
        } else if (type == 2) {
            const int hlit = static_cast<int>(in.take(5)) + 257, hdist = static_cast<int>(in.take(5)) + 1, hclen = static_cast<int>(in.take(4)) + 4;
            std::uint8_t cl[19] = {};
            for (int i = 0; i < hclen; ++i) cl[kOrder[i]] = static_cast<std::uint8_t>(in.take(3));
            Huffman code;
            code.build(cl, 19);
            for (int i = 0; i < hlit + hdist && !in.bad;) {
                const int sym = code.decode(in);
                if (sym < 16) {
                    lengths[i++] = static_cast<std::uint8_t>(sym);
                    continue;
                }
                const std::uint8_t value = sym == 16 && i ? lengths[i - 1] : 0;
                const int repeat = sym == 16 ? 3 + static_cast<int>(in.take(2)) : sym == 17 ? 3 + static_cast<int>(in.take(3)) : 11 + static_cast<int>(in.take(7));
                if (i + repeat > hlit + hdist) return false;
                for (int k = 0; k < repeat; ++k) lengths[i++] = value;
            }
            lit.build(lengths, hlit);
            dist.build(lengths + hlit, hdist);
        } else {
            return false;
        }
        while (!in.bad) {
            const int sym = lit.decode(in);
            if (sym < 256) {
                out.push_back(static_cast<std::uint8_t>(sym));
                continue;
            }
            if (sym == 256) break;
            if (sym > 285) return false;
            const std::size_t len = kLenBase[sym - 257] + in.take(kLenExtra[sym - 257]);
            const int d = dist.decode(in);
            if (d > 29) return false;
            const std::size_t back = kDistBase[d] + in.take(kDistExtra[d]);
            if (back > out.size()) return false;
            for (std::size_t i = 0; i < len; ++i) out.push_back(out[out.size() - back]);
        }
    }
    return !in.bad;
}

std::uint32_t be32(const std::uint8_t *p) { return (static_cast<std::uint32_t>(p[0]) << 24) | (p[1] << 16) | (p[2] << 8) | p[3]; }

// 8-bit RGB or RGBA, not interlaced (what textures/ and Pillow write).
bool read_png(const fs::path &path, Image &img) {
    std::ifstream f(path, std::ios::binary);
    const std::vector<std::uint8_t> file((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (file.size() < 33 || std::memcmp(file.data(), "\x89PNG\r\n\x1A\n", 8) != 0) return false;
    std::vector<std::uint8_t> idat;
    std::uint32_t color = 0;
    for (std::size_t at = 8; at + 12 <= file.size();) {
        const std::uint32_t len = be32(file.data() + at);
        const char *type = reinterpret_cast<const char *>(file.data() + at + 4);
        const std::uint8_t *data = file.data() + at + 8;
        if (at + 12 + len > file.size()) return false;
        if (std::memcmp(type, "IHDR", 4) == 0) {
            img.width = be32(data);
            img.height = be32(data + 4);
            color = data[9];
            if (data[8] != 8 || (color != 2 && color != 6) || data[12] != 0) return false;
        } else if (std::memcmp(type, "IDAT", 4) == 0) {
            idat.insert(idat.end(), data, data + len);
        } else if (std::memcmp(type, "IEND", 4) == 0) {
            break;
        }
        at += 12 + len;
    }
    const std::size_t bpp = color == 6 ? 4 : 3, stride = img.width * bpp;
    std::vector<std::uint8_t> raw;
    raw.reserve((stride + 1) * img.height);
    if (!img.width || idat.size() < 2 || !inflate(idat.data() + 2, idat.size() - 2, raw) || raw.size() < (stride + 1) * img.height) return false;
    std::vector<std::uint8_t> prev(stride, 0), row(stride);
    img.texels.resize(static_cast<std::size_t>(img.width) * img.height);
    for (std::uint32_t y = 0; y < img.height; ++y) {
        const std::uint8_t *in = raw.data() + y * (stride + 1);
        for (std::size_t i = 0; i < stride; ++i) {
            const int a = i >= bpp ? row[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
            int pred = 0;
            switch (in[0]) {
            case 1: pred = a; break;
            case 2: pred = b; break;
            case 3: pred = (a + b) / 2; break;
            case 4: {
                const int p = a + b - c, pa = std::abs(p - a), pb = std::abs(p - b), pc = std::abs(p - c);
                pred = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
                break;
            }
            default: break;
            }
            row[i] = static_cast<std::uint8_t>(in[1 + i] + pred);
        }
        for (std::uint32_t x = 0; x < img.width; ++x) {
            const std::uint8_t *px = row.data() + x * bpp;
            img.texels[y * img.width + x] = px[0] | (px[1] << 8) | (px[2] << 16) | (static_cast<std::uint32_t>(bpp == 4 ? px[3] : 0x80) << 24);
        }
        prev.swap(row);
    }
    return true;
}

std::string name(std::uint64_t key) {
    char s[24];
    std::snprintf(s, sizeof s, "%016llx.png", static_cast<unsigned long long>(key));
    return s;
}

}

bool init() {
    if (const char *dir = std::getenv("PS2_TEXTURES"); dir && *dir) {
        g_pack_dir = dir;
        std::error_code ec;
        for (const auto &e : fs::directory_iterator(g_pack_dir, ec)) {
            const std::string stem = e.path().stem().string();
            char *end = nullptr;
            const std::uint64_t key = std::strtoull(stem.c_str(), &end, 16);
            if (stem.size() == 16 && *end == 0 && e.path().extension() == ".png") g_index[key] = e.path();
        }
        std::fprintf(stderr, "[tex] pack %s: %zu textures%s\n", dir, g_index.size(), ec ? " (folder not readable)" : "");
    }
    if (const char *dir = std::getenv("PS2_TEX_DUMP"); dir && *dir) {
        g_dump_dir = dir;
        fs::create_directories(g_dump_dir);
        std::fprintf(stderr, "[tex] dumping new textures to %s\n", dir);
    }
    return !g_pack_dir.empty() || !g_dump_dir.empty();
}

bool dumping() { return !g_dump_dir.empty(); }

bool replaceable(const std::uint32_t *w) {
    const std::uint32_t psm = w[14], mu = (w[7] >> 24) & 3u, mv = (w[7] >> 26) & 3u;
    return (psm == PSMCT32 || psm == PSMCT24 || psm == PSMCT16 || psm == PSMT8 || psm == PSMT4) && mu != 3 && mv != 3;
}

bool tag_upload(std::uint32_t bp, std::uint32_t bw, std::uint32_t psm, std::uint32_t x0, std::uint32_t y0, std::uint32_t width, std::uint32_t height, const std::uint8_t *data, std::size_t size) {
    Layout l;
    if (!layout(psm, l)) return false;
    const std::uint32_t ch = l.bh / 4, cx0 = x0 / l.bw, cy0 = y0 / ch;
    const std::uint32_t cols = (x0 + width - 1) / l.bw - cx0 + 1, rows = (y0 + height - 1) / ch - cy0 + 1;
    const std::size_t row_bytes = static_cast<std::size_t>(width) * l.bpp / 8;
    const bool bytes = width * l.bpp % 8 == 0 && x0 * l.bpp % 8 == 0 && row_bytes * height <= size;
    g_acc.assign(static_cast<std::size_t>(cols) * rows, 0x2545F4914F6CDD1Dull);
    // Rows arrive in order, so each fully written column gets its ch row pieces in order.
    // A bijection per word: pieces of equal length never collide.
    const auto hash = [](std::uint64_t &a, const std::uint8_t *p, std::size_t n) {
        std::uint64_t v = 0;
        std::size_t i = 0;
        for (; i + 8 <= n; i += 8) {
            std::memcpy(&v, p + i, 8);
            a = (a ^ v) * 0x9E3779B97F4A7C15ull;
        }
        if (i < n) {
            v = 0;
            std::memcpy(&v, p + i, n - i);
            a = (a ^ v) * 0x9E3779B97F4A7C15ull;
        }
    };
    const std::size_t piece = l.bw * l.bpp / 8, first = (l.bw - x0 % l.bw) % l.bw * l.bpp / 8;
    for (std::uint32_t row = 0; bytes && row < height; ++row) {
        std::uint64_t *a = g_acc.data() + ((y0 + row) / ch - cy0) * cols;
        const std::uint8_t *src = data + row * row_bytes, *end = src + row_bytes;
        if (first) {
            hash(*a++, src, std::min<std::size_t>(first, row_bytes));
            src += first;
        }
        for (; src + piece <= end; src += piece) hash(*a++, src, piece);
        if (src < end) hash(*a, src, static_cast<std::size_t>(end - src));
    }
    for (std::uint32_t cy = 0; cy < rows; ++cy)
        for (std::uint32_t cx = 0; cx < cols; ++cx) {
            const std::uint32_t x = (cx0 + cx) * l.bw, y = (cy0 + cy) * ch;
            const bool whole = bytes && x >= x0 && x + l.bw <= x0 + width && y >= y0 && y + ch <= y0 + height;
            tag(bp, bw, l, x, y) = whole ? mix(g_acc[cy * cols + cx], 0) | 1 : 0;
        }
    return true;
}

// Same entries as gs.cpp's load_clut().
void tag_clut(std::uint64_t tex0, std::uint64_t texclut) {
    const std::uint32_t psm = (tex0 >> 20) & 0x3Fu, cpsm = (tex0 >> 51) & 0xFu, csm = (tex0 >> 55) & 1u, csa = (tex0 >> 56) & 0x1Fu, cbp = (tex0 >> 37) & 0x3FFFu;
    const std::uint32_t tc = static_cast<std::uint32_t>(texclut), cou = (tc >> 6) & 0x3Fu, cov = (tc >> 12) & 0x3FFu;
    const bool eight = psm == PSMT8 || psm == PSMT8H;
    const std::uint32_t count = eight ? 256 : 16;
    Layout l;
    std::uint64_t h = 0;
    if (layout(cpsm == 0 ? PSMCT32 : cpsm, l))
        h = csm ? columns(cbp, tc & 0x3Fu, l, cou * 16, cov, cou * 16 + count - 1, cov, mix(cpsm, 2))
                : columns(cbp, 1, l, 0, 0, eight ? 15 : 7, eight ? 15 : 1, mix(cpsm, 1));
    const std::uint32_t first = csm ? csa : eight ? 0 : csa & 15u;
    for (std::uint32_t g = 0; g < count / 16; ++g) g_clut_tags[(first + g) & 31u] = h ? mix(h, g) | 1 : 0;
}

void clear_tags() {
    std::fill(g_tags.begin(), g_tags.end(), 0);
    std::fill(std::begin(g_clut_tags), std::end(g_clut_tags), 0);
}

std::uint64_t texel_key(const std::uint32_t *w) {
    Layout l;
    layout(w[14], l);
    return columns(w[12], w[13], l, 0, 0, (1u << (w[15] & 0xFFu)) - 1, (1u << (w[15] >> 8)) - 1, mix(mix(0x5432u, w[14]), w[15]));
}

std::uint64_t palette_key(const std::uint32_t *w) {
    const std::uint32_t psm = w[14];
    std::uint64_t h = 1;
    if (paletted(psm)) {
        h = mix(h, w[16]);
        const std::uint32_t first = psm == PSMT8 ? 0 : w[17] & 15u, count = psm == PSMT8 ? 16 : 1;
        for (std::uint32_t g = first; g < first + count; ++g) {
            if (!g_clut_tags[g]) return 0;
            h = mix(h, g_clut_tags[g]);
        }
    }
    if (psm == PSMCT24 || psm == PSMCT16 || (paletted(psm) && w[16] != PSMCT32 && w[16] != PSMCT24)) h = mix(h ^ 2, w[20] | ((w[0] & 32768u) << 1));
    return h | 1;
}

std::uint64_t combine(std::uint64_t texels, std::uint64_t palette) { return texels && palette ? mix(texels, palette) : 0; }


const Image *find(std::uint64_t key) {
    const auto it = g_index.find(key);
    if (it == g_index.end()) return nullptr;
    auto [slot, fresh] = g_loaded.try_emplace(key);
    if (fresh) {
        auto img = std::make_unique<Image>();
        if (read_png(it->second, *img)) slot->second = std::move(img);
        else std::fprintf(stderr, "[tex] cannot read %s (8-bit RGB/RGBA PNG expected)\n", it->second.string().c_str());
    }
    return slot->second.get();
}

void dump(std::uint64_t key, const std::uint32_t *w, const std::uint32_t *clut) {
    if (!g_dumped.insert(key).second) return;
    const std::uint32_t width = 1u << (w[15] & 0xFFu), height = 1u << (w[15] >> 8);
    std::vector<std::uint32_t> texels(static_cast<std::size_t>(width) * height);
    for (std::uint32_t y = 0; y < height; ++y)
        for (std::uint32_t x = 0; x < width; ++x) texels[y * width + x] = texel(w, clut, x, y);
    write_png(g_dump_dir / name(key), width, height, texels);
}

}
