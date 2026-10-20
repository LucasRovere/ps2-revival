#pragma once

#include <cstdint>
#include <string>

namespace ps2::gs {
struct State;
}

// PS2_EMU_COUNT=<file> (headless): what emulated hardware the game uses, written per 100 frames.
namespace ps2::emu_count {

extern bool g_on;

enum Kind : std::uint32_t {
    kIopInstr,    // a: IOP pc >> 10 at the slice start
    kIopIo,       // a: register block, b: write
    kIopDma,      // a: channel; value: words
    kIopSifDma,   // a: IOP ra (IOP -> EE sceSifSetDma); value: bytes
    kSpu2KeyOn,   // a: core; value: voices
    kVu1,         // a: program key, b: entry
    kVu1Hook,     // a: entry (a chain handler did the program's work)
    kVu0,         // a: entry, b: 0 VIF0 MSCAL, 1 VCALLMS
    kVif,         // a: unit, b: command
    kDmaStart,    // a: channel
    kDma,         // a: channel, b: 1 read from the device; value: qwords
    kGif,         // a: path; value: qwords
    kGifTag,      // a: path, b: FLG
    kGsReg,       // a: register
    kGsPrim,      // a: PRIM type
    kGsMesh,      // GPU mesh path strips; value: vertices
    kGsTarget,    // a: FRAME (FBP, FBW, PSM), b: ZBUF (ZBP, PSM, ZMSK) or ~0 without a Z test
    kGsTexTarget, // a: TBP0 | PSM << 16 of a texture at a frame buffer drawn earlier, b: its frame PSM
    kGsTransfer,  // a: direction, b: DBP | DPSM << 16 (upload) or SBP | SPSM << 16 (download, copy; copy: dest << 32)
    kGsDisplay,   // a: DISPFB1 | DISPFB2 << 32 (FBP, FBW, PSM), b: PMODE; once per frame
    kEeIo,        // a: register block, b: write
    kEePc,        // a: block, b: write | pc << 1 | ra << 32 (pc: last call, return or syscall, not the access)
    kSyscall,     // a: number, b: ra
    kIntc,        // a: cause
    kDmacIrq,     // a: channel
    kSifCall,     // a: server, b: function | HLE server << 32; value: send bytes
    kSifRecv,     // as kSifCall; value: receive buffer bytes
    kSifBind,     // a: server
    kSifCmd,      // a: command id (EE -> IOP, other than bind and call)
    kSifToEe,     // a: command id (IOP -> EE)
    kKinds
};

void add(Kind kind, std::uint64_t a, std::uint64_t b = 0, std::uint64_t value = 0);
void ee_access(std::uint32_t address, bool write);
void iop_access(std::uint32_t address, bool write);
void iop_hle(const std::string &library, std::uint32_t index);
void gs_draw(const gs::State &s);
void gs_transfer(std::uint64_t trxdir, std::uint64_t bitbltbuf);
void frame(std::uint64_t frame);
void window();
void finish(std::uint64_t frame);

}
