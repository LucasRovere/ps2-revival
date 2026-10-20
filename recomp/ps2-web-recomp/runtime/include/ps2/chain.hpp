#pragma once

#include "cpu.hpp"

#include <cstdint>

// Chain handlers (T46): game code that takes over a VIF1 chain at its DMA `call` (e.g. a static mesh).
namespace ps2::chain {

// EE thread, at the call tag: true when the handler wants the chain at `address` (it may read g_ram).
using Claim = bool (*)(std::uint32_t address);
// Where the chain's VIF commands would run (the VU thread in the window), with the chain's words as DMA
// delivers them. True: the handler did the chain's work and passed the words through run() itself;
// false: VIF1 runs them as usual.
using Draw = bool (*)(std::uint32_t address, const std::uint8_t *data, std::uint32_t qwc);
void register_handler(Claim claim, Draw draw);

// For Draw: runs VIF1 commands; each VU1 start (MSCAL, MSCALF, MSCNT) first calls vu(entry), which returns
// true when it did the program's work itself (VU1 memory at vu::top(), output through vu::kick).
using VuHook = bool (*)(std::uint32_t entry);
// Optional: called at each VIF1 UNPACK (mode 0/1) with the command and its VU1 address (TOPS added); true skips
// the write while the VIF state still advances (data the handler draws from its own copy).
using UnpackHook = bool (*)(std::uint32_t cmd, std::uint32_t address);
void run(const std::uint8_t *data, std::uint32_t qwc, VuHook vu, UnpackHook unpack = nullptr);

std::uint8_t *vu1_memory();
Vu0Regs &vu1_regs();
// Key of the VU1 program at `entry` in the loaded microcode (the vurecomp key, as in vu1_<key>).
std::uint64_t vu1_program(std::uint32_t entry);

// GPU mesh path (T48): static vertices kept on the GPU, a strip's GS primitives built there. A draw stands for a
// path 1 packet in stream order: GIF tag with PRE (prim), then per vertex ST, RGBAQ, XYZF2 (packed) where
// c = m[3] + m[0] x + m[1] y + m[2] z, q = 1 / c.w, ST = st * q, XYZF2 = ftoi4(c.x q), ftoi4(c.y q),
// ftoi4(c.z q) >> 4, fog 0; a vertex with ADC draws no triangle. Float results may differ from VU1's in the last bit.
struct MeshVertex {
    float x, y, z;
    std::uint32_t rgba; // R | G << 8 | B << 16 | A << 24
    float st[2][2];     // two (s, t) sets
    std::uint32_t adc;
};
struct MeshDraw {
    std::uint32_t mesh, first, count; // a strip of the mesh's vertices
    std::uint32_t prim;
    std::uint32_t st_set;
    std::uint32_t flat, rgba; // flat != 0: every vertex has colour rgba
    std::uint32_t adc[4];     // bit k: vertex k also has ADC (count <= 128)
    float matrix[4][4];
};
// True when the GPU renderer draws meshes (window and headless GPU builds; PS2_GPU_MESH=0 turns it off).
bool mesh_path();
// Copies the vertices for later draws; returns the mesh id.
std::uint32_t mesh_add(const MeshVertex *v, std::uint32_t count);
// Projects the strip's vertices on the calling thread (screen boxes for the renderer's tiles) and queues it.
void mesh_draw(const MeshDraw &d);

}

// Defined by port.py's generated chain_handlers.cpp (game.json recomp.chain_handlers); weak default: none.
void register_chain_handlers();
