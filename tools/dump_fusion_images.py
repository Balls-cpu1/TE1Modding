#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_fusion_images.py — вытаскивает образ картинок (image bank) из exe игры на Clickteam Fusion 2.5.

Реализация формата по исходникам CTFAK 2.0:
  * точка входа: секция .extra, иначе конец последней секции PE;
  * PackData: заголовок + список упакованных файлов (PAME/PAMU);
  * далее поток чанков: i16 id, i16 flags, i32 size (flags: 0=raw, 1=zlib, 2/3=шифрованные);
  * чанк 26214 (0x6666) — образ картинок:
      - Fusion 2.5+ ("2.5+ Object Headers", чанк 8787): LZ4-блоки;
      - иначе NormalImage: zlib-блоки с флагами RLE/LZX и т.п.

Использование:
    python dump_fusion_images.py TheEscapists_eur.exe --out dump [--chunks] [--min 8] [--max 128]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import lz4.block
import os
import struct
import sys
import zlib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

CHUNK_NAMES = {
    8739: "App Header", 8740: "App Name", 8741: "App Author", 8742: "App Menu",
    8743: "Ext Path", 8747: "Frame Handles", 8748: "Ext Data", 8750: "Editor Filename",
    8751: "Target Filename", 8754: "Global Values", 8755: "Global Strings",
    8763: "Copyright", 8767: "Frame Items 2", 8787: "2.5+ Object Headers",
    8788: "2.5+ Object Names", 8790: "2.5+ Object Properties", 8745: "Frame Items",
    13107: "Frame", 26214: "Images", 32639: "Last Chunk",
}
IMG_CHUNK = 26214


class R:
    """простой читатель байт (аналог CTFAK ByteReader)"""

    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def i8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u8(self):
        return self.i8()

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.p)[0]
        self.p += 2
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def bytes(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def peek_i16(self):
        return struct.unpack_from("<h", self.d, self.p)[0]

    def seek(self, p):
        self.p = p

    def tell(self):
        return self.p

    def size(self):
        return len(self.d)

    def has(self, n):
        return self.p + n <= len(self.d)


def entry_point(d: bytes):
    if d[:2] != b"MZ":
        raise SystemExit("не PE-файл")
    off = struct.unpack_from("<I", d, 0x3C)[0]
    if d[off:off + 4] != b"PE\0\0":
        raise SystemExit("не PE-файл (нет PE-сигнатуры)")
    num_sec, = struct.unpack_from("<H", d, off + 6)
    opt_size, = struct.unpack_from("<H", d, off + 20)
    sec_off = off + 24 + opt_size
    pos = None
    last_end = None
    for i in range(num_sec):
        e = sec_off + i * 40
        name = d[e:e + 8].rstrip(b"\0").decode("latin1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, e + 8)
        last_end = rawptr + rawsize
        if name == ".extra":
            pos = rawptr
    return pos if pos is not None else last_end


def read_yuniversal(r: R, n: int, unicode: bool) -> str:
    raw = r.bytes(n * 2 if unicode else n)
    if unicode:
        return raw.decode("utf-16-le", "replace").rstrip("\0")
    return raw.decode("latin1", "replace").rstrip("\0")


def parse_pack_data(d: bytes, pos: int, log):
    r = R(d, pos)
    start = r.tell()
    r.bytes(8)
    header_size = r.u32()
    data_size = r.u32()
    if header_size != 32:
        raise ValueError(f"PackData: headerSize={header_size}, ожидалось 32")
    r.seek(start + data_size - 32)
    uheader = r.bytes(4).decode("latin1")
    unicode = uheader == "PAMU"
    log(f"PackData: {uheader}, unicode={unicode}, dataSize={data_size}")
    r.seek(start + 16)
    fmt_ver = r.u32()
    r.i32()
    check = r.i32()
    count = r.u32()
    offset = r.tell()
    log(f"  formatVersion={fmt_ver}, файлов={count}")
    r.seek(offset)
    packs = []
    for i in range(count):
        if not r.has(2):
            break
        ln = r.u16()
        if not r.has(ln * (2 if unicode else 1)):
            break
        name = read_yuniversal(r, ln, unicode)
        bingo = r.i32()
        size = r.i32()
        if r.peek_i16() == -9608:
            raw = r.bytes(size)
            try:
                r2 = R(zlib.decompress(raw))
            except Exception:
                r2 = R(b"")
            packs.append((name, size, True))
        else:
            r.bytes(size)
            packs.append((name, size, False))
        log(f"    pack: {name!r:40} size={size}")
    return r.tell(), packs


def find_chunk_stream(d: bytes, pos: int, log) -> int:
    """поток чанков может начинаться не сразу за pack-данными — ищем сходимость."""
    def walks(off):
        r = off
        for _ in range(2000):
            if r + 8 > len(d):
                return False
            cid, flag, size = struct.unpack_from("<hhi", d, r)
            if not (0 <= flag <= 3) or not (0 <= size < 5_000_000):
                return False
            r += 8 + size
            if cid == 32639:
                return True
        return False

    if walks(pos):
        return pos
    for off in range(pos, min(pos + 4096, len(d) - 8)):
        cid, flag, size = struct.unpack_from("<hhi", d, off)
        if cid == 8739 and 0 <= flag <= 3 and 0 <= size < 1_000_000:
            if walks(off):
                log(f"поток чанков найден со смещением {off:#x} (+{off - pos} байт от pack-данных)")
                return off
    log("не удалось найти поток чанков")
    return pos


def read_chunks(d: bytes, pos: int, log):
    """проходит поток чанков, возвращает список (pos_data, id, flag, size, data)"""
    chunks = []
    r = R(d, pos)
    while r.has(8):
        start = r.tell()
        cid = r.i16()
        flag = r.i16()
        size = r.i32()
        if size < 0 or not r.has(size):
            log(f"чанк {cid} объявлен размером {size} — обрыв потока")
            break
        raw = r.bytes(size)
        data = raw
        err = None
        if flag == 1:
            # внутри: i32 размер_после_распаковки, i32 размер_сжатых_данных, затем zlib-поток
            try:
                b = R(raw)
                decomp_size = b.i32()
                comp_size = b.i32()
                data = zlib.decompress(raw[8:8 + comp_size])
                if len(data) != decomp_size:
                    err = f"размер не совпал: {len(data)} != {decomp_size}"
            except Exception as e:
                err = f"zlib: {e}"
        elif flag in (2, 3):
            err = "шифрованный чанк (пока не поддержан)"
        chunks.append(dict(offset=start, id=cid, flag=flag, size=size, data=data, err=err))
        if cid == 32639:
            log("достигнут Last Chunk")
            break
    return chunks


# ------------------------------------------------------------------ картинки
def get_padding(width: int, point_size: int, bytes_: int = 2, modular: bool = False) -> int:
    if modular:
        return (bytes_ - width * point_size % bytes_) % bytes_
    pad = bytes_ - width * point_size % bytes_
    if pad == bytes_:
        return 0
    return -(-pad // point_size)


def rgba_from_data(data: bytes, w: int, h: int, mode: int, alpha_flag: bool, rgba_flag: bool, transparent):
    out = bytearray(w * h * 4)
    stride = w * 4
    if mode == 8:  # Fusion 2.5: RGBA
        pad = get_padding(w, 4)
        pos = 0
        for y in range(h):
            for x in range(w):
                i = y * stride + x * 4
                r_, g_, b_, a_ = data[pos], data[pos + 1], data[pos + 2], data[pos + 3]
                out[i:i + 3] = bytes((r_, g_, b_))
                if alpha_flag or rgba_flag:
                    out[i + 3] = a_
                else:
                    out[i + 3] = 0 if (r_, g_, b_) == transparent else 255
                pos += 4
            pos += pad * 4
    elif mode == 4:  # 24-bit masked
        pad = get_padding(w, 3)
        pos = 0
        for y in range(h):
            for x in range(w):
                i = y * stride + x * 4
                r_, g_, b_ = data[pos], data[pos + 1], data[pos + 2]
                out[i:i + 3] = bytes((r_, g_, b_))
                out[i + 3] = 0 if (r_, g_, b_) == transparent else 255
                pos += 3
            pos += pad * 3
    elif mode in (6, 7):  # 15/16-битные режимы
        pad = get_padding(w, 3)
        pos = 0
        for y in range(h):
            for x in range(w):
                i = y * stride + x * 4
                v = data[pos] | (data[pos + 1] << 8)
                if mode == 7:
                    r_, g_, b_ = (v & 0xF800) >> 11, (v & 0x7E0) >> 5, v & 0x1F
                    r_, g_, b_ = r_ << 3, g_ << 2, b_ << 3
                else:
                    r_, g_, b_ = (v & 0x7C00) >> 10, (v & 0x3E0) >> 5, v & 0x1F
                    r_, g_, b_ = r_ << 3, g_ << 3, b_ << 3
                out[i:i + 3] = bytes((r_, g_, b_))
                out[i + 3] = 255
                pos += 2
            pos += pad * 2
    else:
        return None
    return bytes(out)


def parse_images_25(data: bytes, log, min_px, max_px):
    """формат Fusion 2.5+ (TwoFivePlusImage): LZ4-блоки"""
    r = R(data)
    count = r.i32()
    log(f"образ 2.5+: объявлено картинок: {count}")
    out = []
    for i in range(count):
        if not r.has(40):
            break
        start = r.tell()
        handle = r.i32() - 1
        checksum = r.i32()
        refs = r.i32()
        r.i32()
        data_size = r.i32()
        w = r.i16()
        h = r.i16()
        mode = r.u8()
        flags = r.u8()
        r.i16()
        hsx, hsy = r.i16(), r.i16()
        ax, ay = r.i16(), r.i16()
        tr, tg, tb, ta = r.u8(), r.u8(), r.u8(), r.u8()
        decomp_size = r.i32()
        raw = r.bytes(max(0, data_size - 4))
        img = None
        err = None
        try:
            if decomp_size > 0:
                dec = lz4.block.decompress(raw, uncompressed_size=decomp_size)
            else:
                dec = b""
            if 0 < w <= max_px and 0 < h <= max_px and w >= min_px and h >= min_px:
                alpha_flag = bool(flags & (1 << 4))
                rgba_flag = bool(flags & (1 << 7))
                rgba = rgba_from_data(dec, w, h, mode, alpha_flag, rgba_flag, (tr, tg, tb))
                if rgba and Image:
                    img = Image.frombytes("RGBA", (w, h), rgba)
        except Exception as e:
            err = str(e)
        out.append(dict(handle=handle, w=w, h=h, mode=mode, flags=flags, refs=refs,
                        checksum=checksum, data_size=data_size, dec_size=decomp_size,
                        offset=start, image=img, err=err))
    return out


def parse_images_normal(data: bytes, log, min_px, max_px):
    """формат NormalImage: zlib-блок на картинку"""
    r = R(data)
    count = r.i32()
    log(f"образ (normal): объявлено картинок: {count}")
    out = []
    for i in range(count):
        if not r.has(12):
            break
        start = r.tell()
        handle = r.i32()
        decompressed_size = r.i32()
        comp_size = r.i32()
        raw = r.bytes(comp_size)
        try:
            block = zlib.decompress(raw)
        except Exception as e:
            out.append(dict(handle=handle, err=f"zlib: {e}", offset=start, image=None))
            continue
        b = R(block)
        checksum = b.i32()
        refs = b.i32()
        data_size = b.i32()
        w, h = b.i16(), b.i16()
        mode = b.u8()
        flags = b.u8()
        b.i16()
        hsx, hsy, ax, ay = b.i16(), b.i16(), b.i16(), b.i16()
        tr, tg, tb, ta = b.u8(), b.u8(), b.u8(), b.u8()
        imgd = b.bytes(data_size)
        img = None
        err = None
        try:
            if 0 < w <= max_px and 0 < h <= max_px and w >= min_px and h >= min_px:
                rgba = rgba_from_data(imgd, w, h, mode, bool(flags & (1 << 4)), False, (tr, tg, tb))
                if rgba and Image:
                    img = Image.frombytes("RGBA", (w, h), rgba)
        except Exception as e:
            err = str(e)
        out.append(dict(handle=handle, w=w, h=h, mode=mode, flags=flags, refs=refs,
                        checksum=checksum, data_size=data_size, dec_size=len(block),
                        offset=start, image=img, err=err))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--out", default="dump")
    ap.add_argument("--chunks", action="store_true", help="только список чанков")
    ap.add_argument("--min", type=int, default=4)
    ap.add_argument("--max", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    d = Path(args.exe).read_bytes()
    print(f"файл: {args.exe} ({len(d):,} байт)")
    pos = entry_point(d)
    print(f"точка входа Fusion: {pos:#x}, первый short: {struct.unpack_from('<H', d, pos)[0]:#06x}")

    def log(*a):
        print(*a)

    pack_end = pos
    try:
        pack_end, packs = parse_pack_data(d, pos, log)
    except Exception as e:
        print("PackData не разобран:", e)

    stream_pos = find_chunk_stream(d, pack_end, log)
    chunks = read_chunks(d, stream_pos, log)
    print(f"\nвсего чанков: {len(chunks)}")
    seen_8787 = False
    for c in chunks:
        name = CHUNK_NAMES.get(c["id"], "?")
        if c["id"] == 8787:
            seen_8787 = True
        print(f"  {c['id']:>6} {name:22} flags={c['flag']} size={c['size']:>9} "
              f"raw={len(c['data']):>9}{' ERR: ' + c['err'] if c['err'] else ''}")
    if args.chunks:
        return

    img_chunk = next((c for c in chunks if c["id"] == IMG_CHUNK), None)
    if img_chunk is None:
        print("чанк образа картинок (26214) не найден")
        return
    if img_chunk["err"]:
        print("образ картинок не расшифрован:", img_chunk["err"])
        return

    images = None
    if seen_8787:
        try:
            images = parse_images_25(img_chunk["data"], log, args.min, args.max)
        except Exception as e:
            print("разбор 2.5+ не удался:", e)
    if not images:
        images = parse_images_normal(img_chunk["data"], log, args.min, args.max)

    ok = [i for i in images if i.get("image")]
    print(f"\nразобрано картинок: {len(images)}, с картинкой: {len(ok)}")
    if args.limit:
        ok = ok[:args.limit]

    outdir = Path(args.out) / "images"
    outdir.mkdir(parents=True, exist_ok=True)
    with open(Path(args.out) / "images.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["handle", "width", "height", "mode", "flags", "refs", "dec_size", "offset", "file"])
        for im in images:
            fn = ""
            if im.get("image"):
                fn = f"{im['handle']:05d}.png"
                im["image"].save(outdir / fn)
            wr.writerow([im.get("handle"), im.get("w"), im.get("h"), im.get("mode"),
                         im.get("flags"), im.get("refs"), im.get("dec_size"), hex(im.get("offset", 0)), fn])
    print(f"картинки: {outdir}\nотчёт: {Path(args.out) / 'images.csv'}")

    # сводка по размерам — помогает найти наборы иконок
    from collections import Counter
    cnt = Counter((i["w"], i["h"]) for i in ok)
    print("\nсамые частые размеры картинок:")
    for (w, h), n in cnt.most_common(15):
        print(f"   {w:>4}x{h:<4} — {n}")
    modes = Counter((i["mode"], i["flags"]) for i in ok)
    print("режимы (mode, flags):", dict(modes.most_common(8)))


if __name__ == "__main__":
    main()
