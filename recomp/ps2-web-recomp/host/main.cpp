#include "ps2/system.hpp"

#ifdef PS2_WINDOW
#include "window.hpp"
#endif
#ifdef PS2_PROFILE
#include "profile.hpp"
#endif

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

void register_generated_code();
void register_generated_vu();

namespace {

int usage() {
    std::fprintf(stderr,
                 "usage: ps2run [<elf>] [--arg text]... [--frames n] [--ntsc] [--misses file]\n"
                 "              [--disc image.iso | folder] [--memcard card.ps2] [--pal | --ntsc] [--trace-syscalls] [--trace-io] [--trace-threads]\n"
                 "              [--trace-iop] [--trace-iop-hle] [--frames-dir dir] [--frame-every n]\n"
                 "              [--press frame:button[+button][:frames]]... [--window] [--fullscreen]\n"
                 "              [--save-state frame:file] [--load-state file]\n");
    return 2;
}

// The boot ELF a port folder holds next to ps2run, named as in the disc's SYSTEM.CNF (BOOT2 = cdrom0:\NAME;1).
std::string folder_elf(const std::filesystem::path &dir) {
    std::ifstream cnf(dir / "disc" / "SYSTEM.CNF");
    std::string line;
    while (std::getline(cnf, line)) {
        if (line.rfind("BOOT2", 0) != 0) continue;
        std::string name = line.substr(line.find_last_of("\\:") + 1);
        return (dir / name.substr(0, name.find_first_of(";\r "))).string();
    }
    return {};
}

}

int main(int argc, char **argv) {
    // No ELF argument: run the port folder ps2run sits in (T37); no arguments at all opens the window.
    const bool folder = argc < 2 || argv[1][0] == '-';
    std::string elf = folder ? std::string() : argv[1];
    if (folder) {
        std::filesystem::path dir = std::filesystem::path(argv[0]).parent_path();
        if (dir.empty()) dir = ".";
        elf = folder_elf(dir);
        if (elf.empty()) return usage();
        ps2::g_options.disc_path = dir.string();
        ps2::g_options.memcard_path = (dir / "memcard.ps2").string();
    }
    std::vector<std::string> args{elf};
    [[maybe_unused]] bool window = argc < 2, fullscreen = false;
    std::string load_path;
    for (int i = folder ? 1 : 2; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--arg" && i + 1 < argc) args.push_back(argv[++i]);
        else if (a == "--frames" && i + 1 < argc) ps2::g_options.max_frames = std::strtoull(argv[++i], nullptr, 10);
        else if (a == "--ntsc" || a == "--pal") {
            ps2::g_options.pal = a == "--pal";
            ps2::g_options.rate_forced = true;
        }
        else if (a == "--misses" && i + 1 < argc) ps2::g_options.misses_path = argv[++i];
        else if (a == "--trace-syscalls") ps2::g_options.trace_syscalls = true;
        else if (a == "--trace-io") ps2::g_options.trace_io = true;
        else if (a == "--trace-threads") ps2::g_options.trace_threads = true;
        else if (a == "--disc" && i + 1 < argc) ps2::g_options.disc_path = argv[++i];
        else if (a == "--memcard" && i + 1 < argc) ps2::g_options.memcard_path = argv[++i];
        else if (a == "--trace-iop") ps2::g_options.trace_iop_modules = true;
        else if (a == "--trace-iop-hle") ps2::g_options.trace_iop_hle = true;
        else if (a == "--frames-dir" && i + 1 < argc) ps2::g_options.frames_dir = argv[++i];
        else if (a == "--press" && i + 1 < argc) {
            ps2::Press press;
            if (!ps2::parse_press(argv[++i], press)) return usage();
            ps2::g_options.presses.push_back(press);
        }
#ifdef PS2_WINDOW
        else if (a == "--window") window = true;
        else if (a == "--fullscreen") window = fullscreen = true;
#endif
        else if (a == "--frame-every" && i + 1 < argc) ps2::g_options.frame_every = static_cast<std::uint32_t>(std::strtoul(argv[++i], nullptr, 10));
        else if (a == "--save-state" && i + 1 < argc) {
            const std::string spec = argv[++i];
            const auto colon = spec.find(':');
            if (colon == std::string::npos) return usage();
            ps2::g_options.save_state_frame = std::strtoull(spec.substr(0, colon).c_str(), nullptr, 10);
            ps2::g_options.save_state_path = spec.substr(colon + 1);
        }
        else if (a == "--load-state" && i + 1 < argc) load_path = argv[++i];
        else return usage();
    }

#ifdef PS2_WINDOW
    if (window && !open_window(fullscreen)) return 1;
#endif
    register_generated_code();
    register_generated_vu();
    const auto emulate = [&]() -> int {
        std::uint32_t entry = 0;
        if (!ps2::load_elf(elf, entry)) {
            std::fprintf(stderr, "cannot load %s\n", elf.c_str());
            return 1;
        }
        ps2::boot(entry, args);
        if (!load_path.empty() && !ps2::load_state(load_path)) return 1;
#ifdef PS2_PROFILE
        const char *profile = std::getenv("PS2_PROFILE");
        const char *profile_from = std::getenv("PS2_PROFILE_FROM");
        if (profile) start_profile(profile_from ? std::strtoull(profile_from, nullptr, 10) : 0);
        const int result = ps2::run();
        if (profile) write_profile(profile);
        return result;
#else
        return ps2::run();
#endif
    };
#ifdef PS2_WINDOW
    if (window) return run_window(emulate);
#endif
    return emulate();
}
