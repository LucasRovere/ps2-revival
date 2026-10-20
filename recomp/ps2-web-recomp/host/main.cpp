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
#include <iterator>
#include <string>
#include <vector>

void register_generated_code();
void register_generated_vu();
void register_chain_handlers();

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

// One value of the folder's flat settings.json: "key": "text" or "key": 3 / true.
std::string setting(const std::string &json, const std::string &key) {
    auto at = json.find("\"" + key + "\"");
    if (at == std::string::npos || (at = json.find(':', at)) == std::string::npos) return {};
    at = json.find_first_not_of(" \t\r\n", at + 1);
    if (at == std::string::npos) return {};
    if (json[at] == '"') return json.substr(at + 1, json.find('"', at + 1) - at - 1);
    return json.substr(at, json.find_first_of(",} \t\r\n", at) - at);
}

// Environment variables already set (e.g. by play.py) win over the file.
void default_env(const char *name, const std::string &value) {
    if (value.empty() || std::getenv(name)) return;
#ifdef _WIN32
    _putenv_s(name, value.c_str());
#else
    setenv(name, value.c_str(), 0);
#endif
}

// settings.json next to ps2run (written by port.py --folder): aspect, scale, textures, mods, memcard, fullscreen;
// "gpu_mesh": false turns the GPU mesh path off (T48).
bool apply_folder_settings(const std::filesystem::path &dir) {
    std::ifstream in(dir / "settings.json");
    const std::string json((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    default_env("PS2_ASPECT", setting(json, "aspect"));
    default_env("PS2_SCALE", setting(json, "scale"));
    if (const auto textures = setting(json, "textures"); !textures.empty()) default_env("PS2_TEXTURES", (dir / textures).string());
    if (const auto mods = setting(json, "mods"); !mods.empty()) default_env("PS2_MODS", (dir / mods).string());
    if (setting(json, "gpu_mesh") == "false") default_env("PS2_GPU_MESH", "0");
    if (const auto card = setting(json, "memcard"); !card.empty()) ps2::g_options.memcard_path = (dir / card).string();
    return setting(json, "fullscreen") == "true";
}

}

int main(int argc, char **argv) {
    // No ELF argument: run the port folder ps2run sits in (T37); no arguments at all opens the window.
    const bool folder = argc < 2 || argv[1][0] == '-';
    std::string elf = folder ? std::string() : argv[1];
    bool fullscreen_setting = false;
    if (folder) {
        std::filesystem::path dir = std::filesystem::path(argv[0]).parent_path();
        if (dir.empty()) dir = ".";
        elf = folder_elf(dir);
        if (elf.empty()) return usage();
        ps2::g_options.disc_path = dir.string();
        ps2::g_options.memcard_path = (dir / "memcard.ps2").string();
        fullscreen_setting = apply_folder_settings(dir);
    }
    std::vector<std::string> args{elf};
    // The settings' fullscreen only applies to a start with no arguments (double-click).
    [[maybe_unused]] bool window = argc < 2, fullscreen = window && fullscreen_setting;
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
    register_chain_handlers();
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
