#include "ps2/disc.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>

namespace ps2::disc {

namespace {

std::FILE *g_file = nullptr;
Reader g_reader;
Probe g_probe;
std::uint64_t g_size = 0;
std::uint32_t g_layer1 = 0;
std::map<std::string, Entry> g_index;

// Where each file's directory record sits on the disc (byte offset) and its layer's first sector.
struct Record {
    std::uint64_t offset;
    std::uint32_t base;
};
std::map<std::string, Record> g_records;

std::uint32_t u32(const std::uint8_t *p) {
    std::uint32_t v;
    std::memcpy(&v, p, 4);
    return v;
}

std::string upper(std::string s) {
    for (char &c : s) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return s;
}

void walk(std::uint32_t base, std::uint32_t lba, std::uint32_t size, const std::string &prefix, int depth) {
    if (depth > 16) return;
    std::vector<std::uint8_t> data((size + kSector - 1) / kSector * kSector);
    if (!read(base + lba, static_cast<std::uint32_t>(data.size() / kSector), data.data())) return;
    std::size_t off = 0;
    while (off < size) {
        const std::uint8_t length = data[off];
        if (!length) {
            off = (off / kSector + 1) * kSector;
            continue;
        }
        const std::uint8_t *rec = &data[off];
        const std::uint64_t rec_offset = static_cast<std::uint64_t>(base + lba) * kSector + off;
        off += length;
        const std::uint8_t name_len = rec[32];
        std::string name(reinterpret_cast<const char *>(rec + 33), name_len);
        if (name_len == 1 && (name[0] == 0 || name[0] == 1)) continue;
        const auto semi = name.find(';');
        if (semi != std::string::npos) name = name.substr(0, semi);
        const std::string path = prefix + upper(name);
        const bool dir = rec[25] & 2;
        const Entry entry{base + u32(rec + 2), u32(rec + 10), dir};
        g_index[path] = entry;
        g_records[path] = {rec_offset, base};
        if (dir) walk(base, u32(rec + 2), u32(rec + 10), path + "/", depth + 1);
    }
}

// Port folder (T37): disc/ holds each file at its disc path, layout.txt each file's sector and size,
// sectors.bin every other non-zero sector (volume descriptors, path tables, directory records).
struct Span {
    std::uint32_t sector;
    std::uint64_t size;
    std::string path;
    std::uint64_t offset;
};

void seek(std::FILE *file, std::uint64_t offset) {
#if defined(_WIN32)
    _fseeki64(file, static_cast<long long>(offset), SEEK_SET);
#else
    fseeko(file, static_cast<off_t>(offset), SEEK_SET);
#endif
}

struct Folder {
    std::uint64_t size = 0;
    std::vector<Span> files, rest;
    std::string open_path;
    std::FILE *open_file = nullptr;

    std::FILE *handle(const std::string &path) {
        if (path != open_path) {
            if (open_file) std::fclose(open_file);
            open_file = std::fopen(path.c_str(), "rb");
            open_path = path;
        }
        return open_file;
    }

    void copy(const std::vector<Span> &spans, std::uint64_t offset, std::uint8_t *out, std::size_t bytes) {
        const std::uint64_t end = offset + bytes;
        for (const Span &s : spans) {
            const std::uint64_t first = static_cast<std::uint64_t>(s.sector) * kSector;
            const std::uint64_t lo = std::max(offset, first), hi = std::min(end, first + s.size);
            if (lo >= hi) continue;
            std::FILE *file = handle(s.path);
            if (!file) continue;
            seek(file, s.offset + lo - first);
            std::fread(out + (lo - offset), 1, static_cast<std::size_t>(hi - lo), file);
        }
    }

    std::size_t read(std::uint64_t offset, void *out, std::size_t bytes) {
        if (offset >= size) return 0;
        bytes = static_cast<std::size_t>(std::min<std::uint64_t>(bytes, size - offset));
        auto *dst = static_cast<std::uint8_t *>(out);
        std::memset(dst, 0, bytes);
        copy(files, offset, dst, bytes);
        // After the files: a file's last sector is in sectors.bin when its padding is not zero.
        copy(rest, offset, dst, bytes);
        return bytes;
    }
};

bool open_folder(const std::string &dir) {
    std::ifstream layout(dir + "/layout.txt");
    if (!layout) return false;
    auto folder = std::make_shared<Folder>();
    std::uint64_t blob = 0;
    std::string kind;
    while (layout >> kind) {
        Span s{};
        if (kind == "sectors") {
            layout >> folder->size;
            folder->size *= kSector;
        } else if (kind == "file") {
            layout >> s.sector >> s.size;
            layout.get();
            std::getline(layout, s.path);
            s.path = dir + "/disc/" + s.path;
            folder->files.push_back(s);
        } else if (kind == "rest") {
            std::uint32_t count = 0;
            layout >> s.sector >> count;
            s.size = static_cast<std::uint64_t>(count) * kSector;
            s.path = dir + "/sectors.bin";
            s.offset = blob;
            blob += s.size;
            folder->rest.push_back(s);
        }
    }
    return open(dir, folder->size, [folder](std::uint64_t offset, void *out, std::size_t bytes) {
        return folder->read(offset, out, bytes);
    });
}

void index_layer(std::uint32_t pvd_sector, std::uint32_t base) {
    std::uint8_t pvd[kSector];
    if (!read(pvd_sector, 1, pvd) || std::memcmp(pvd, "\x01" "CD001", 6) != 0) return;
    walk(base, u32(pvd + 158), u32(pvd + 166), "", 0);
}

void index_disc() {
    g_index.clear();
    g_records.clear();
    index_layer(16, 0);
    if (g_layer1) index_layer(g_layer1 + 16, g_layer1);
}

void put_both_endian(std::uint8_t *p, std::uint32_t v) {
    std::memcpy(p, &v, 4);
    for (int i = 0; i < 4; ++i) p[4 + i] = static_cast<std::uint8_t>(v >> (24 - 8 * i));
}

// Mods (T42): PS2_MODS names a folder of replacement files at their disc paths. A file that fits the
// original's sectors is read there; a bigger one gets sectors past the end of the disc. The new sector
// and size go into the file's directory record as read from the disc, so the index and the game's own
// directory lookups both see them.
void apply_mods(const std::string &dir) {
    if (!std::filesystem::is_directory(dir)) {
        std::fprintf(stderr, "[mods] no folder %s\n", dir.c_str());
        return;
    }
    auto mods = std::make_shared<Folder>();
    std::vector<std::pair<std::uint64_t, std::array<std::uint8_t, 16>>> records;
    auto end = static_cast<std::uint32_t>((g_size + kSector - 1) / kSector);
    for (const auto &item : std::filesystem::recursive_directory_iterator(dir)) {
        if (!item.is_regular_file()) continue;
        const std::string path = upper(item.path().lexically_relative(dir).generic_string());
        const auto entry = g_index.find(path);
        if (entry == g_index.end() || entry->second.directory) {
            std::fprintf(stderr, "[mods] not a file on the disc, skipped: %s\n", path.c_str());
            continue;
        }
        const auto size = static_cast<std::uint32_t>(item.file_size());
        const std::uint32_t sectors = (size + kSector - 1) / kSector;
        std::uint32_t sector = entry->second.sector;
        const bool moved = sectors > (entry->second.size + kSector - 1) / kSector;
        if (moved) {
            sector = end;
            end += sectors;
        }
        mods->files.push_back({sector, size, item.path().string(), 0});
        const Record &rec = g_records[path];
        std::array<std::uint8_t, 16> fields;
        put_both_endian(fields.data(), sector - rec.base);
        put_both_endian(fields.data() + 8, size);
        records.push_back({rec.offset + 2, fields});
        std::fprintf(stderr, "[mods] %s: %u bytes at sector %u%s\n", path.c_str(), size, sector, moved ? " (moved past the disc end)" : "");
    }
    g_size = std::max<std::uint64_t>(g_size, static_cast<std::uint64_t>(end) * kSector);
    g_reader = [disc = std::move(g_reader), mods, records, size = g_size](std::uint64_t offset, void *out, std::size_t bytes) {
        if (offset >= size) return std::size_t{0};
        bytes = static_cast<std::size_t>(std::min<std::uint64_t>(bytes, size - offset));
        auto *dst = static_cast<std::uint8_t *>(out);
        const std::size_t got = disc(offset, dst, bytes);
        std::memset(dst + got, 0, bytes - got);
        mods->copy(mods->files, offset, dst, bytes);
        for (const auto &[at, fields] : records) {
            const std::uint64_t lo = std::max(offset, at), hi = std::min<std::uint64_t>(offset + bytes, at + fields.size());
            if (lo < hi) std::memcpy(dst + (lo - offset), fields.data() + (lo - at), static_cast<std::size_t>(hi - lo));
        }
        return bytes;
    };
    index_disc();
    std::fprintf(stderr, "[mods] %s: %zu files\n", dir.c_str(), mods->files.size());
}

}

bool open(const std::string &path) {
    const bool folder = std::filesystem::is_directory(path);
    std::fprintf(stderr, "[disc] %s backend: %s\n", folder ? "folder" : "image", path.c_str());
    if (folder) return open_folder(path);
    g_file = std::fopen(path.c_str(), "rb");
    if (!g_file) return false;
#if defined(_WIN32)
    _fseeki64(g_file, 0, SEEK_END);
    const std::uint64_t size = static_cast<std::uint64_t>(_ftelli64(g_file));
#else
    fseeko(g_file, 0, SEEK_END);
    const std::uint64_t size = static_cast<std::uint64_t>(ftello(g_file));
#endif
    std::FILE *file = g_file;
    return open(path, size, [file](std::uint64_t offset, void *out, std::size_t bytes) {
#if defined(_WIN32)
        _fseeki64(file, static_cast<long long>(offset), SEEK_SET);
#else
        fseeko(file, static_cast<off_t>(offset), SEEK_SET);
#endif
        return std::fread(out, 1, bytes, file);
    });
}

bool open(const std::string &name, std::uint64_t size, Reader reader, Probe probe) {
    g_reader = std::move(reader);
    g_probe = std::move(probe);
    g_size = size;
    std::uint8_t pvd[kSector];
    read(16, 1, pvd);
    const std::uint32_t layer0 = u32(pvd + 80);
    for (std::uint32_t s = layer0; s < layer0 + 64 && static_cast<std::uint64_t>(s) * kSector < g_size; ++s) {
        std::uint8_t probe[kSector];
        if (read(s, 1, probe) && std::memcmp(probe, "\x01" "CD001", 6) == 0) {
            g_layer1 = s - 16;
            break;
        }
    }
    index_disc();
    if (const char *mods = std::getenv("PS2_MODS"); mods && *mods) apply_mods(mods);
    std::fprintf(stderr, "[disc] %s: %zu files, %llu sectors, layer 1 at %u\n", name.c_str(), g_index.size(),
                 static_cast<unsigned long long>(g_size / kSector), g_layer1);
    return true;
}

bool is_open() { return static_cast<bool>(g_reader); }

bool read(std::uint32_t sector, std::uint32_t count, void *out) {
    if (!g_reader) return false;
    const std::size_t want = static_cast<std::size_t>(count) * kSector;
    const std::size_t got = g_reader(static_cast<std::uint64_t>(sector) * kSector, out, want);
    if (got < want) std::memset(static_cast<std::uint8_t *>(out) + got, 0, want - got);
    return got > 0 || !count;
}

bool ready(std::uint32_t sector, std::uint32_t count) {
    return !g_probe || g_probe(static_cast<std::uint64_t>(sector) * kSector, static_cast<std::size_t>(count) * kSector);
}

std::optional<Entry> find(const std::string &raw) {
    std::string path = raw;
    const auto colon = path.find(':');
    if (colon != std::string::npos) path = path.substr(colon + 1);
    std::replace(path.begin(), path.end(), '\\', '/');
    const auto semi = path.find(';');
    if (semi != std::string::npos) path = path.substr(0, semi);
    while (!path.empty() && path.front() == '/') path.erase(path.begin());
    auto it = g_index.find(upper(path));
    if (it == g_index.end()) return std::nullopt;
    return it->second;
}

std::uint32_t layer1_start() { return g_layer1; }
std::uint64_t sector_count() { return g_size / kSector; }

}
