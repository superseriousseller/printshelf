"""Generate placeholder PNG icons for the PrintShelf Chrome extension.

Pure stdlib — no PIL needed. Produces a solid #ff6a3d square with a white
"P" centered in it, at 16/48/128 px.

Re-run this any time the brand mark changes.
"""
import os
import struct
import zlib

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

ACCENT = (0xFF, 0x6A, 0x3D)
WHITE = (0xFF, 0xFF, 0xFF)

# 5x7 bitmap of the letter "P" — scaled up per icon size.
P_BITMAP = [
    "11110",
    "10001",
    "10001",
    "11110",
    "10000",
    "10000",
    "10000",
]


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: str, size: int) -> None:
    rows: list[bytes] = []
    pad_x = max(1, size // 8)
    pad_y = max(1, size // 8)
    inner_w = size - 2 * pad_x
    inner_h = size - 2 * pad_y
    cell_w = max(1, inner_w // len(P_BITMAP[0]))
    cell_h = max(1, inner_h // len(P_BITMAP))
    glyph_w = cell_w * len(P_BITMAP[0])
    glyph_h = cell_h * len(P_BITMAP)
    glyph_x = (size - glyph_w) // 2
    glyph_y = (size - glyph_h) // 2

    for y in range(size):
        row = b"\x00"  # filter byte: None
        for x in range(size):
            color = ACCENT
            if glyph_x <= x < glyph_x + glyph_w and glyph_y <= y < glyph_y + glyph_h:
                cx = (x - glyph_x) // cell_w
                cy = (y - glyph_y) // cell_h
                if 0 <= cy < len(P_BITMAP) and 0 <= cx < len(P_BITMAP[0]) and P_BITMAP[cy][cx] == "1":
                    color = WHITE
            row += bytes(color)
        rows.append(row)

    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(raw, 9)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", idat)
        + png_chunk(b"IEND", b"")
    )

    with open(path, "wb") as f:
        f.write(png)


def main() -> None:
    for size in (16, 48, 128):
        out = os.path.join(OUT_DIR, f"icon{size}.png")
        write_png(out, size)
        print(f"wrote {out} ({size}x{size})")


if __name__ == "__main__":
    main()
