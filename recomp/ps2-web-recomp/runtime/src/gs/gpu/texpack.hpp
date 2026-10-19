#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

// Texture packs: replacement PNGs named by a key built from hashes of the bytes the game uploads.
namespace ps2::gs::texpack {

struct Image {
    std::uint32_t width = 0, height = 0;
    std::vector<std::uint32_t> texels;
};

// Reads PS2_TEXTURES (pack folder) and PS2_TEX_DUMP (dump folder); true if either is set.
bool init();
bool dumping();
// Setups (gpu.cpp layout) whose texture format and wrap modes the replacement path handles.
bool replaceable(const std::uint32_t *setup);
// Image transfer of width x height pixels at (x, y): tags the GS memory it writes. False for formats without tags.
bool tag_upload(std::uint32_t bp, std::uint32_t bw, std::uint32_t psm, std::uint32_t x, std::uint32_t y, std::uint32_t width, std::uint32_t height, const std::uint8_t *data, std::size_t size);
void tag_clut(std::uint64_t tex0, std::uint64_t texclut);
// Memory loaded from a save state has no tags.
void clear_tags();
// Key parts; 0 when some of the texture or its CLUT has no tag.
std::uint64_t texel_key(const std::uint32_t *setup);
std::uint64_t palette_key(const std::uint32_t *setup);
std::uint64_t combine(std::uint64_t texels, std::uint64_t palette);
// The pack image for key (loaded on first use), or null.
const Image *find(std::uint64_t key);
// Writes the texture as <dump folder>/<key>.png, decoded from gs::memory() (needs the CPU copy, see gpu::texture_dump()).
void dump(std::uint64_t key, const std::uint32_t *setup, const std::uint32_t *clut);

}
