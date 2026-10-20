#include "chain.hpp"

#include "gs/gs.hpp"
#include "hw.hpp"
#include "vif.hpp"
#include "vu_micro.hpp"

#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace ps2::chain {

Claim g_claim = nullptr;

namespace {
Draw g_draw = nullptr;
std::atomic<std::uint32_t> g_meshes{0};
// Each mesh's positions (x, y, z), on the thread that adds and draws meshes.
std::vector<std::vector<float>> g_positions;
}

void register_handler(Claim claim, Draw draw) {
    if (g_claim) {
        std::fprintf(stderr, "[chain] a chain handler is already registered\n");
        std::exit(1);
    }
    g_claim = claim;
    g_draw = draw;
    std::fprintf(stderr, "[chain] handler registered\n");
}

bool draw(std::uint32_t address, const std::uint8_t *data, std::uint32_t qwc) { return g_draw(address, data, qwc); }

void run(const std::uint8_t *data, std::uint32_t qwc, VuHook vu, UnpackHook unpack) { vif::run_hooked(data, qwc, vu, unpack); }

std::uint8_t *vu1_memory() { return g_vu1_mem; }
Vu0Regs &vu1_regs() { return vu::regs(1); }
std::uint64_t vu1_program(std::uint32_t entry) { return vu::program_key(entry); }

bool mesh_path() { return gs::mesh_path(); }

std::uint32_t mesh_add(const MeshVertex *v, std::uint32_t count) {
    const std::uint32_t id = g_meshes.fetch_add(1);
    if (id >= g_positions.size()) g_positions.resize(id + 1);
    std::vector<float> &p = g_positions[id];
    p.resize(static_cast<std::size_t>(count) * 3);
    for (std::uint32_t i = 0; i < count; ++i) {
        p[i * 3] = v[i].x;
        p[i * 3 + 1] = v[i].y;
        p[i * 3 + 2] = v[i].z;
    }
    gs::mesh_add(id, v, count);
    return id;
}

// Screen position c.xy / c.w of each vertex (NaN behind the camera), for binning only: the GPU builds the records.
void mesh_draw(const MeshDraw &d) {
    if (d.mesh >= g_positions.size() || d.count > 128 || (d.first + d.count) * 3ull > g_positions[d.mesh].size()) return;
    const float(&m)[4][4] = d.matrix;
    const float *p = g_positions[d.mesh].data() + d.first * 3;
    float screen[256];
    for (std::uint32_t k = 0; k < d.count; ++k, p += 3) {
        const float w = m[3][3] + m[0][3] * p[0] + m[1][3] * p[1] + m[2][3] * p[2];
        const bool front = w > 0.0f;
        screen[k * 2] = front ? (m[3][0] + m[0][0] * p[0] + m[1][0] * p[1] + m[2][0] * p[2]) / w : std::nanf("");
        screen[k * 2 + 1] = front ? (m[3][1] + m[0][1] * p[0] + m[1][1] * p[1] + m[2][1] * p[2]) / w : std::nanf("");
    }
    gs::mesh_draw(d, screen);
}

}

__attribute__((weak)) void register_chain_handlers() {}
