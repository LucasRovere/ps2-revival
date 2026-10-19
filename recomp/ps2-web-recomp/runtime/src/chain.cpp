#include "chain.hpp"

#include "hw.hpp"
#include "vif.hpp"
#include "vu_micro.hpp"

#include <cstdio>
#include <cstdlib>

namespace ps2::chain {

Claim g_claim = nullptr;

namespace {
Draw g_draw = nullptr;
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

void run(const std::uint8_t *data, std::uint32_t qwc, VuHook vu) { vif::run_hooked(data, qwc, vu); }

std::uint8_t *vu1_memory() { return g_vu1_mem; }
Vu0Regs &vu1_regs() { return vu::regs(1); }
std::uint64_t vu1_program(std::uint32_t entry) { return vu::program_key(entry); }

}

__attribute__((weak)) void register_chain_handlers() {}
