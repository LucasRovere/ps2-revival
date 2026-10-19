#pragma once

#include <cstdint>

// PS2_DRAW_PROFILE=<from>,<count> (headless): cost of the VIF1 DMA list per call target,
// VU1 time per program entry and GS front-end time per GIF path, printed after frame from+count.
namespace ps2::draw_profile {

extern bool g_on;

std::uint64_t now_ns();
void frame(std::uint64_t frame);
void chain_start();
void call(std::uint32_t target);
void ret();
std::uint32_t target();
void tag_done(std::uint32_t owner, std::uint32_t qwc, std::uint64_t ns);
void gif_ran(int path, std::uint32_t qwc, std::uint64_t ns);
void vu_ran(std::uint32_t address, std::uint64_t ns);
void channel2_ran(std::uint32_t qwc, std::uint64_t ns);

}
