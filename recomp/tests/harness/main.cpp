// Runs recompiled test vectors (written by recomp/tests/harness.py) and prints each end state as one JSON line.
#include "ps2/generated.hpp"
#include "ps2/system.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>

struct Case {
    void (*register_code)();
    void (*init)(ps2::Cpu &c);
};

extern const Case kCases[];
extern const std::size_t kCaseCount;

namespace {

constexpr std::uint32_t kCodeBase = 0x00100000u;
constexpr std::int32_t kBudget = 100000;

void reset(ps2::Cpu &c) {
    c = ps2::Cpu{};
    c.vu0.vf[0].w[3] = 0x3F800000u;
    c.budget = kBudget;
    std::memset(ps2::g_ram, 0, ps2::kRamSize);
}

void hex128(const char *name, const ps2::Reg128 &r) {
    std::printf("\"%s\":\"%016llx%016llx\",", name, static_cast<unsigned long long>(r.d[1]), static_cast<unsigned long long>(r.d[0]));
}

void hex32(const char *name, std::uint32_t v) { std::printf("\"%s\":\"%08x\",", name, v); }

void dump_memory() {
    std::printf("\"mem\":{");
    const char *sep = "";
    for (std::uint32_t a = 0; a < ps2::kRamSize; a += 16) {
        std::uint64_t block[2];
        std::memcpy(block, ps2::g_ram + a, 16);
        if (!block[0] && !block[1]) continue;
        std::printf("%s\"%08x\":\"", sep, a);
        for (int i = 0; i < 16; ++i) std::printf("%02x", ps2::g_ram[a + i]);
        std::printf("\"");
        sep = ",";
    }
    std::printf("}");
}

void dump(std::size_t index, const ps2::Cpu &c) {
    char name[8];
    std::printf("{\"case\":%zu,\"pc\":\"%08x\",", index, c.pc);
    for (int i = 0; i < 32; ++i) std::snprintf(name, sizeof name, "r%d", i), hex128(name, c.r[i]);
    hex128("hi", c.hi);
    hex128("lo", c.lo);
    hex32("sa", c.sa);
    hex32("fcr31", c.fcr31);
    for (int i = 0; i < 32; ++i) std::snprintf(name, sizeof name, "f%d", i), hex32(name, c.f[i]);
    hex32("facc", c.facc);
    for (int i = 0; i < 32; ++i) std::snprintf(name, sizeof name, "vf%d", i), hex128(name, c.vu0.vf[i]);
    for (int i = 0; i < 16; ++i) std::snprintf(name, sizeof name, "vi%d", i), hex32(name, c.vu0.vi[i]);
    hex32("q", c.vu0.q);
    hex128("acc", c.vu0.acc);
    dump_memory();
    std::printf("}\n");
}

}

int main(int argc, char **argv) {
    // A halted runtime makes preempt() unwind, so a case that runs out of budget stops instead of looping.
    ps2::halt("harness");
    ps2::Cpu &c = ps2::g_cpu;
    for (std::size_t i = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 0; i < kCaseCount; ++i) {
        reset(c);
        kCases[i].register_code();
        kCases[i].init(c);
        c.pc = kCodeBase;
        std::fprintf(stderr, "[case %zu]\n", i);
        ps2::dispatch(c, 0, 0);
        std::fflush(stderr);
        dump(i, c);
        std::fflush(stdout);
    }
    return 0;
}
