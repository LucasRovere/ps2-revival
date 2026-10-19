"""Read-only ISO9660 reader (primary volume descriptor only, no Joliet/UDF)."""

import struct
from dataclasses import dataclass

SECTOR = 2048
PVD_SECTOR = 16


@dataclass
class Entry:
    path: str
    lba: int
    size: int
    is_dir: bool


class Iso:
    def __init__(self, path):
        self.f = open(path, "rb")
        pvd = self._sector(PVD_SECTOR)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            self.f.close()
            raise ValueError(f"{path}: no ISO9660 primary volume descriptor at sector {PVD_SECTOR}")
        self.volume_size = struct.unpack_from("<I", pvd, 80)[0] * SECTOR
        root = parse_record(pvd, 156)
        self.root = Entry("", root[0], root[1], True)
        self.entries = list(self._walk(self.root))
        self.by_path = {e.path.upper(): e for e in self.entries}

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def files(self):
        return [e for e in self.entries if not e.is_dir]

    def read(self, path):
        e = self.by_path[path.strip("/").upper()]
        self.f.seek(e.lba * SECTOR)
        return self.f.read(e.size)

    def head(self, entry, n):
        self.f.seek(entry.lba * SECTOR)
        return self.f.read(min(n, entry.size))

    def _sector(self, lba, count=1):
        self.f.seek(lba * SECTOR)
        return self.f.read(count * SECTOR)

    def _walk(self, d):
        data = self._sector(d.lba, (d.size + SECTOR - 1) // SECTOR)
        pos = 0
        while pos < d.size:
            length = data[pos]
            if length == 0:  # records never cross a sector boundary; rest of sector is padding
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            lba, size, is_dir, name = parse_record(data, pos)
            pos += length
            if name in ("\x00", "\x01"):  # "." and ".."
                continue
            e = Entry(f"{d.path}/{name}".lstrip("/"), lba, size, is_dir)
            yield e
            if is_dir:
                yield from self._walk(e)


def parse_record(buf, pos):
    lba = struct.unpack_from("<I", buf, pos + 2)[0]
    size = struct.unpack_from("<I", buf, pos + 10)[0]
    is_dir = bool(buf[pos + 25] & 2)
    name_len = buf[pos + 32]
    name = buf[pos + 33:pos + 33 + name_len].decode("ascii", "replace").split(";")[0]
    return lba, size, is_dir, name
