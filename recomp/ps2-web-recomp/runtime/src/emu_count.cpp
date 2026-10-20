#include "emu_count.hpp"

#include "gs/gs.hpp"
#include "iop/kernel.hpp"
#include "ps2/system.hpp"

#include <array>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <unordered_map>
#include <utility>

namespace ps2::emu_count {

bool g_on = std::getenv("PS2_EMU_COUNT") != nullptr;

namespace {

const char *const kNames[kKinds] = {
    "iop_instr", "iop_io", "iop_dma", "iop_sif_dma", "spu2_key_on", "vu1", "vu1_hook", "vu0", "vif", "dma_start",
    "dma", "gif", "gif_tag", "gs_reg", "gs_prim", "gs_mesh", "gs_target", "gs_tex_target", "gs_transfer", "gs_display",
    "ee_io", "ee_pc", "syscall", "intc", "dmac_irq", "sif_call", "sif_recv", "sif_bind", "sif_cmd", "sif_to_ee",
};

struct Key {
    std::uint32_t kind;
    std::uint64_t a, b;
    bool operator==(const Key &o) const { return kind == o.kind && a == o.a && b == o.b; }
};

struct KeyHash {
    std::size_t operator()(const Key &k) const { return k.kind * 0x9E3779B97F4A7C15ull ^ k.a * 0xC2B2AE3D27D4EB4Full ^ k.b * 0x165667B19E3779F9ull; }
};

struct Count {
    std::uint64_t n = 0, sum = 0, max = 0;
};

// prim, tex0, tex1, clamp, texa, alpha, test, fba, frame, zbuf, pabe, dthe, colclamp, scanmsk (mode bits, no addresses)
using GsState = std::array<std::uint64_t, 14>;

std::FILE *g_file = nullptr;
std::uint64_t g_from = 0;
std::unordered_map<Key, Count, KeyHash> g_counts;
std::map<GsState, std::uint64_t> g_states;
std::map<std::pair<std::string, std::uint32_t>, std::uint64_t> g_hle;
std::map<std::uint32_t, std::uint32_t> g_drawn; // frame buffer block -> PSM, until an upload replaces it

std::uint32_t ee_block(std::uint32_t a) {
    if (a >= 0x12000000u) return 0x12000000u;
    if (a >= 0x11000000u) return 0x11000000u;
    if (a < 0x10002000u) return 0x10000000u;
    if (a < 0x10003000u) return 0x10002000u;
    if (a < 0x10003800u) return 0x10003000u;
    if (a < 0x10004000u) return a & ~0x3FFu;
    if (a < 0x10008000u) return a & ~0xFFFu;
    if (a < 0x1000F000u) return 0x10008000u;
    return a & ~0xFFu;
}

std::uint32_t iop_block(std::uint32_t a) {
    if (a >= 0x1F900000u && a < 0x1F900800u) return 0x1F900000u;
    if (a >= 0x1F801600u && a < 0x1F801660u) return 0x1F801600u;
    if (a >= 0x1F808200u && a < 0x1F808280u) return 0x1F808200u;
    if ((a >= 0x1F801080u && a < 0x1F801100u) || (a >= 0x1F801500u && a < 0x1F801580u)) return 0x1F801080u;
    if ((a >= 0x1F801100u && a < 0x1F801130u) || (a >= 0x1F801480u && a < 0x1F8014B0u)) return 0x1F801100u;
    return a & ~0xFu;
}

void write_section(std::uint64_t to) {
    std::fprintf(g_file, "section %llu %llu\n", static_cast<unsigned long long>(g_from), static_cast<unsigned long long>(to));
    for (const auto &[k, c] : g_counts)
        std::fprintf(g_file, "c %s %llx %llx %llu %llu %llu\n", kNames[k.kind], static_cast<unsigned long long>(k.a), static_cast<unsigned long long>(k.b),
                     static_cast<unsigned long long>(c.n), static_cast<unsigned long long>(c.sum), static_cast<unsigned long long>(c.max));
    for (const auto &[s, n] : g_states) {
        std::fprintf(g_file, "gsstate %llu", static_cast<unsigned long long>(n));
        for (const std::uint64_t v : s) std::fprintf(g_file, " %llx", static_cast<unsigned long long>(v));
        std::fprintf(g_file, "\n");
    }
    for (const auto &[h, n] : g_hle) std::fprintf(g_file, "hle %s %u %llu\n", h.first.c_str(), h.second, static_cast<unsigned long long>(n));
    g_counts.clear();
    g_states.clear();
    g_hle.clear();
    g_from = to;
}

}

void add(Kind kind, std::uint64_t a, std::uint64_t b, std::uint64_t value) {
    Count &c = g_counts[Key{kind, a, b}];
    ++c.n;
    c.sum += value;
    if (value > c.max) c.max = value;
}

void ee_access(std::uint32_t address, bool write) {
    const std::uint32_t block = ee_block(address);
    add(kEeIo, block, write);
    add(kEePc, block, (write ? 1u : 0u) | static_cast<std::uint64_t>(g_cpu.pc & 0x7FFFFFFFu) << 1 | static_cast<std::uint64_t>(g_cpu.r[31].w[0]) << 32);
}

void iop_access(std::uint32_t address, bool write) { add(kIopIo, iop_block(address), write); }

void iop_hle(const std::string &library, std::uint32_t index) { ++g_hle[{library, index}]; }

void gs_draw(const gs::State &s) {
    const std::uint64_t prim = (s.prmodecont & 1u) ? (s.prim & 0x7FFu) : ((s.prim & 7u) | (s.prmode & 0x7F8u));
    const gs::Context &c = s.ctx[(prim >> 9) & 1u];
    const bool tme = prim & 0x10u, abe = prim & 0x40u;
    constexpr std::uint64_t kTex0 = (0x3Full << 20) | (7ull << 34) | (0x1Full << 51);
    constexpr std::uint64_t kFrame = (0x3Full << 24) | (0xFFFFFFFFull << 32);
    constexpr std::uint64_t kZbuf = (0xFull << 24) | (1ull << 32);
    ++g_states[GsState{prim, tme ? c.tex0 & kTex0 : 0, tme ? c.tex1 : 0, tme ? c.clamp & 0xFu : 0, tme ? s.texa : 0, abe ? c.alpha : 0, c.test,
                       c.fba & 1u, c.frame & kFrame, c.zbuf & kZbuf, s.pabe & 1u, s.dthe & 1u, s.colclamp & 1u, s.scanmsk & 3u}];
    add(kGsPrim, prim & 7u);
    add(kGsTarget, c.frame & 0x3F3F01FFu, ((c.test >> 16) & 1u) ? (c.zbuf & 0x10F0001FFull) : ~0ull);
    if (tme) {
        const std::uint32_t tbp = static_cast<std::uint32_t>(c.tex0) & 0x3FFFu;
        const auto it = g_drawn.find(tbp);
        if (it != g_drawn.end()) add(kGsTexTarget, tbp | ((c.tex0 >> 20) & 0x3Fu) << 16, it->second);
    }
    g_drawn[(static_cast<std::uint32_t>(c.frame) & 0x1FFu) * 32u] = static_cast<std::uint32_t>(c.frame >> 24) & 0x3Fu;
}

void gs_transfer(std::uint64_t trxdir, std::uint64_t bitbltbuf) {
    const std::uint64_t src = (bitbltbuf & 0x3FFFu) | ((bitbltbuf >> 24) & 0x3Fu) << 16;
    const std::uint64_t dst = ((bitbltbuf >> 32) & 0x3FFFu) | ((bitbltbuf >> 56) & 0x3Fu) << 16;
    const std::uint32_t dbp = static_cast<std::uint32_t>(dst & 0x3FFFu);
    switch (trxdir & 3u) {
    case 0:
        add(kGsTransfer, 0, dst);
        g_drawn.erase(dbp);
        break;
    case 1: add(kGsTransfer, 1, src); break;
    case 2:
        add(kGsTransfer, 2, src | dst << 32);
        if (g_drawn.count(static_cast<std::uint32_t>(src & 0x3FFFu))) g_drawn[dbp] = static_cast<std::uint32_t>(dst >> 16);
        else g_drawn.erase(dbp);
        break;
    default: break;
    }
}

void frame(std::uint64_t frame) {
    if (!g_on) return;
    if (!g_file) {
        const char *path = std::getenv("PS2_EMU_COUNT");
        g_file = std::fopen(path, "w");
        if (!g_file) {
            std::fprintf(stderr, "[emucount] cannot write %s\n", path);
            g_on = false;
            return;
        }
        std::fprintf(g_file, "# ps2 emu_count 1\n");
        g_from = frame;
    }
    const gs::DisplayRegs r = gs::display_regs();
    add(kGsDisplay, (r.dispfb[0] & 0xFFFFFu) | (r.dispfb[1] & 0xFFFFFu) << 32, r.pmode & 0xFFFFu);
    if (frame % 100 == 0 && frame > g_from) write_section(frame);
}

void window() {
    if (!g_on) return;
    std::fprintf(stderr, "[emucount] headless only: PS2_EMU_COUNT ignored in the window\n");
    g_on = false;
}

void finish(std::uint64_t frame) {
    if (!g_file) return;
    if (frame > g_from) write_section(frame);
    for (const auto &[id, m] : iop::kernel::modules()) std::fprintf(g_file, "iopmodule %x %x %s\n", m.base, m.size, m.name.c_str());
    std::fclose(g_file);
    g_file = nullptr;
    g_on = false;
}

}
