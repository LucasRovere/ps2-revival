// Identity chain handler (T46 check): claims every VIF1 call and runs the chain itself through chain::run with
// the VU1 programs unchanged. Frames and cycle counts must equal a run without a handler.
#include "ps2/chain.hpp"

namespace {

bool claim(std::uint32_t) { return true; }
bool keep(std::uint32_t) { return false; }

bool draw(std::uint32_t, const std::uint8_t *data, std::uint32_t qwc) {
    ps2::chain::run(data, qwc, keep);
    return true;
}

}

void register_chain_handlers() { ps2::chain::register_handler(claim, draw); }
