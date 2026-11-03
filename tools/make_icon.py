"""Generate the Retvia application icon (PNG + ICO) with no third-party deps.

The mark is a simple geometric retail/growth glyph on a navy rounded square.
Reproducible: running this script always produces byte-identical output.

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

SIZE = 256
NAVY = (31, 58, 95, 255)
NAVY_DARK = (22, 43, 72, 255)
WHITE = (255, 255, 255, 255)
ACCENT = (16, 185, 129, 255)
TRANSPARENT = (0, 0, 0, 0)


def _rounded_square_mask(size: int, radius: int) -> list[list[bool]]:
    mask = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            if dx >= radius or dy >= radius:
                mask[y][x] = True
            else:
                cx, cy = radius - dx, radius - dy
                mask[y][x] = (cx * cx + cy * cy) <= radius * radius
    return mask


def render(size: int = SIZE) -> list[list[tuple[int, int, int, int]]]:
    scale = size / SIZE
    mask = _rounded_square_mask(size, int(48 * scale))
    pixels = [[TRANSPARENT] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            if mask[y][x]:
                # subtle vertical gradient
                t = y / max(1, size - 1)
                pixels[y][x] = (
                    int(NAVY[0] + (NAVY_DARK[0] - NAVY[0]) * t),
                    int(NAVY[1] + (NAVY_DARK[1] - NAVY[1]) * t),
                    int(NAVY[2] + (NAVY_DARK[2] - NAVY[2]) * t),
                    255,
                )

    def rect(x0: float, y0: float, x1: float, y1: float, colour: tuple[int, int, int, int]) -> None:
        for y in range(int(y0 * scale), int(y1 * scale)):
            for x in range(int(x0 * scale), int(x1 * scale)):
                if 0 <= x < size and 0 <= y < size and mask[y][x]:
                    pixels[y][x] = colour

    # Three ascending bars: stock, sales, growth.
    rect(64, 150, 96, 196, WHITE)
    rect(112, 122, 144, 196, WHITE)
    rect(160, 86, 192, 196, ACCENT)
    # Upward trend line above the bars.
    for step in range(26):
        x = 150 + step
        y = 78 - step
        rect(x, y, x + 6, y + 6, ACCENT)
    return pixels


def write_png(path: Path, pixels: list[list[tuple[int, int, int, int]]]) -> None:
    size = len(pixels)
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def write_ico(path: Path, png_files: list[Path], sizes: list[int]) -> None:
    """ICO container holding PNG payloads (supported from Windows Vista)."""
    count = len(png_files)
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    payloads = bytearray()
    offset = 6 + 16 * count
    for size, png_path in zip(sizes, png_files, strict=True):
        data = png_path.read_bytes()
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        payloads += data
        offset += len(data)
    path.write_bytes(header + bytes(entries) + bytes(payloads))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    assets = root / "retvia" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    temporary = root / "build" / "icons"
    temporary.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    png_paths = []
    for size in sizes:
        target = temporary / f"icon-{size}.png"
        write_png(target, render(size))
        png_paths.append(target)
    write_png(assets / "icon.png", render(256))
    write_ico(assets / "icon.ico", png_paths, sizes)
    print(f"icon.png ({(assets / 'icon.png').stat().st_size} bytes)")
    print(f"icon.ico ({(assets / 'icon.ico').stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
