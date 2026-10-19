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
void run(const std::uint8_t *data, std::uint32_t qwc, VuHook vu);

std::uint8_t *vu1_memory();
Vu0Regs &vu1_regs();
// Key of the VU1 program at `entry` in the loaded microcode (the vurecomp key, as in vu1_<key>).
std::uint64_t vu1_program(std::uint32_t entry);

}

// Defined by port.py's generated chain_handlers.cpp (game.json recomp.chain_handlers); weak default: none.
void register_chain_handlers();
