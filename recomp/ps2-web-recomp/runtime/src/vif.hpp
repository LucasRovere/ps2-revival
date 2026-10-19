#pragma once

#include "ps2/chain.hpp"

#include <cstdint>

namespace ps2::state {
class Stream;
}

namespace ps2::vif {

void state(ps2::state::Stream &s);

void reset();
void reset_vu_side();
void stats();
void transfer(int unit, const std::uint8_t *data, std::uint32_t qwc);
// A claimed chain's words (T46): to the VU thread as one packet, there to the chain handler or VIF1.
void transfer_chain(std::uint32_t address, const std::uint8_t *data, std::uint32_t qwc);
void run_hooked(const std::uint8_t *data, std::uint32_t qwc, ps2::chain::VuHook vu);
bool stalled(int unit);
std::uint32_t read(int unit, std::uint32_t reg);
void write(int unit, std::uint32_t reg, std::uint32_t value);

}
