#pragma once

#include "../ps2-web-recomp/runtime/src/gs/gs.hpp"

#include <cstdint>
#include <vector>

// Native renderer (T57, D37): GS primitives drawn by WebGPU render pipelines into native render
// targets, no GS memory raster. PS2_RENDERER=native; the GS front end (gs.cpp) feeds it.
namespace ps2::native {

bool on();
// True when PS2_RENDERER=native and the WebGPU device is up.
bool init();
void reset();
void draw(const gs::State &s, const gs::Vertex *v, int count);
void image_begin(const gs::State &s);
void image_data(const std::uint8_t *data, std::size_t bytes);
// Downloads (TRXDIR 1): targets under the source go into GS memory for gs.cpp to read. Local copies (2): counted.
void transfer(std::uint32_t dir);
void load_clut(std::uint64_t tex0, std::uint64_t texclut);
void flush();
void wait_idle();
bool display(const gs::DisplayRegs &r, std::vector<std::uint32_t> &rgba, std::uint32_t &width, std::uint32_t &height);
bool attach_surface(int kind, void *display, std::uint64_t window, void *surface, std::uint32_t width, std::uint32_t height);
void resize_surface(std::uint32_t width, std::uint32_t height);
bool present(const gs::DisplayRegs &r);
void stats(std::uint64_t gs_raster);

}
