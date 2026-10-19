// The override of the harness's override case (harness.py OVERRIDE_CASE): v0 = a0 + 0x100.
#include "ps2/generated.hpp"

namespace ovr {

bool harness_add(ps2::Cpu &c) {
    c.r[2].sd[0] = static_cast<std::int32_t>(c.r[4].w[0] + 0x100u);
    return true;
}

}
