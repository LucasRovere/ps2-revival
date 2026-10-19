#pragma once

#include "ps2/chain.hpp"

namespace ps2::chain {

extern Claim g_claim;

inline bool claims(std::uint32_t address) { return g_claim && g_claim(address); }
bool draw(std::uint32_t address, const std::uint8_t *data, std::uint32_t qwc);

}
