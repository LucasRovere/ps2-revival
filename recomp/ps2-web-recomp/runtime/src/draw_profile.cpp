#include "draw_profile.hpp"

#include "gs/queue.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <utility>
#include <vector>

namespace ps2::draw_profile {

bool g_on = false;

namespace {

struct Cost {
    std::uint64_t count = 0, ns = 0, qw = 0;
};

const char *const g_spec = std::getenv("PS2_DRAW_PROFILE");
std::uint64_t g_from = 0, g_to = 0;
std::uint32_t g_target = 0;
std::vector<std::uint32_t> g_stack;
std::map<std::uint32_t, Cost> g_targets;
std::map<std::pair<std::uint32_t, int>, Cost> g_gif;
std::map<std::pair<std::uint32_t, std::uint32_t>, Cost> g_vu;
Cost g_roots, g_channel2;

void print() {
    const double n = static_cast<double>(g_to - g_from);
    std::fprintf(stderr, "[draw] frames %llu-%llu root chains %.2f/frame channel 2 %.4f ms %.1f qw per frame\n", static_cast<unsigned long long>(g_from),
                 static_cast<unsigned long long>(g_to), g_roots.count / n, g_channel2.ns / n / 1e6, g_channel2.qw / n);
    for (const auto &[t, c] : g_targets) std::fprintf(stderr, "[draw] target %08X calls %.2f ms %.4f qw %.1f\n", t, c.count / n, c.ns / n / 1e6, c.qw / n);
    for (const auto &[k, c] : g_gif) std::fprintf(stderr, "[draw] gif %08X path %d kicks %.2f ms %.4f qw %.1f\n", k.first, k.second, c.count / n, c.ns / n / 1e6, c.qw / n);
    for (const auto &[k, c] : g_vu) std::fprintf(stderr, "[draw] vu %08X entry %04X runs %.2f ms %.4f\n", k.first, k.second, c.count / n, c.ns / n / 1e6);
}

}

std::uint64_t now_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }

void frame(std::uint64_t frame) {
    if (!g_spec) return;
    if (!g_to) {
        g_from = std::strtoull(g_spec, nullptr, 10);
        const char *comma = std::strchr(g_spec, ',');
        g_to = g_from + (comma ? std::strtoull(comma + 1, nullptr, 10) : 100);
        // in the window the VU thread runs VU1 and the GS front end: no timing there
        if (gs::queue::active()) std::fprintf(stderr, "[draw] headless only: PS2_DRAW_PROFILE ignored in the window\n");
    }
    g_on = frame >= g_from && frame < g_to && !gs::queue::active();
    if (frame == g_to && !gs::queue::active()) print();
}

void chain_start() {
    g_target = 0;
    g_stack.clear();
    ++g_roots.count;
}

void call(std::uint32_t target) {
    g_stack.push_back(g_target);
    g_target = target;
    ++g_targets[target].count;
}

void ret() {
    if (g_stack.empty()) return;
    g_target = g_stack.back();
    g_stack.pop_back();
}

std::uint32_t target() { return g_target; }

void tag_done(std::uint32_t owner, std::uint32_t qwc, std::uint64_t ns) {
    Cost &c = g_targets[owner];
    c.ns += ns;
    c.qw += qwc + 1;
}

void gif_ran(int path, std::uint32_t qwc, std::uint64_t ns) {
    Cost &c = g_gif[{g_target, path}];
    ++c.count;
    c.ns += ns;
    c.qw += qwc;
}

void vu_ran(std::uint32_t address, std::uint64_t ns) {
    Cost &c = g_vu[{g_target, address}];
    ++c.count;
    c.ns += ns;
}

void channel2_ran(std::uint32_t qwc, std::uint64_t ns) {
    ++g_channel2.count;
    g_channel2.ns += ns;
    g_channel2.qw += qwc;
}

}
