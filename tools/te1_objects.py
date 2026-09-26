#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
te1_objects.py — разбор объектов (ObjectInfo/ObjectCommon) из exe Clickteam Fusion 2.5.

Даёт то, что нужно для маршрута B: имя объекта → список картинок (хендлов) его кадров.
Плюс реализация дешифровки чанков CTFAK (Decryption.MakeKey/TransformChunk/DecodeMode3).

Использование:
    python te1_objects.py game.exe            # сводка объектов
    python te1_objects.py game.exe --dump 623 # выгрузить картинки кадров объекта
"""
from __future__ import annotations

import argparse
import json
import lz4.block
import struct
import sys
import zlib
from pathlib import Path

MAGIC = 54


# ----------------------------------------------------------------- PE / pack / chunks
def entry_point(d: bytes) -> int:
    off = struct.unpack_from("<I", d, 0x3C)[0]
    num_sec, = struct.unpack_from("<H", d, off + 6)
    opt_size, = struct.unpack_from("<H", d, off + 20)
    sec_off = off + 24 + opt_size
    pos = last_end = None
    for i in range(num_sec):
        e = sec_off + i * 40
        name = d[e:e + 8].rstrip(b"\0").decode("latin1")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", d, e + 8)
        last_end = rawptr + rawsize
        if name == ".extra":
            pos = rawptr
    return pos if pos is not None else last_end


def parse_pack_header(d: bytes, pos: int):
    start = pos
    r = pos + 16
    fmt_ver, _, check, count = struct.unpack_from("<IIII", d, r)
    r += 16
    uheader = d[start + 2930568 - 32: start + 2930568 - 28]  # запасной путь
    return fmt_ver, count


def read_chunks(d: bytes, pos: int):
    """ищем поток чанков и читаем (id, flag, size, data, offset)"""
    def walks(off):
        r = off
        for _ in range(3000):
            if r + 8 > len(d):
                return False
            cid, flag, size = struct.unpack_from("<hhi", d, r)
            if not (0 <= flag <= 3) or not (0 <= size < 6_000_000):
                return False
            r += 8 + size
            if cid == 32639:
                return True
        return False

    stream = None
    if walks(pos):
        stream = pos
    else:
        for off in range(pos, min(pos + 8192, len(d) - 8)):
            cid, flag, size = struct.unpack_from("<hhi", d, off)
            if cid == 8739 and 0 <= flag <= 3 and walks(off):
                stream = off
                break
    if stream is None:
        raise RuntimeError("поток чанков не найден")

    out = []
    r = stream
    while r + 8 <= len(d):
        cid, flag, size = struct.unpack_from("<hhi", d, r)
        out.append(dict(id=cid, flag=flag, size=size, raw=d[r + 8:r + 8 + size], offset=r))
        r += 8 + size
        if cid == 32639:
            break
    return out, stream


def yuniversal(data: bytes, unicode: bool) -> str:
    # в этих чанках перед длиной идёт 1 служебный байт
    for shift in (1, 0, 2):
        try:
            ln, = struct.unpack_from("<H", data, shift)
        except struct.error:
            continue
        if not (0 < ln < 200):
            continue
        if unicode:
            s = data[shift + 2:shift + 2 + ln * 2].decode("utf-16-le", "replace").rstrip("\0")
        else:
            s = data[shift + 2:shift + 2 + ln].decode("latin1", "replace").rstrip("\0")
        if s and all(ch.isprintable() for ch in s):
            return s
    return ""


# ----------------------------------------------------------------- шифрование чанков
class ChunkCrypto:
    def __init__(self, name: str, copyright_: str, editor: str, build: int):
        self.build = build
        self.table = None
        data1, data2, data3 = (editor, name, copyright_) if build <= 284 else (name, copyright_, editor)
        blob = self._key_string(data1) + self._key_string(data2) + self._key_string(data3)
        key = self._make_key(blob)
        self._init_table(key)

    @staticmethod
    def _key_string(s: str) -> bytes:
        out = bytearray()
        for ch in s:
            c = ord(ch)
            if c & 0xFF:
                out.append(c & 0xFF)
            if (c >> 8) & 0xFF:
                out.append((c >> 8) & 0xFF)
        return bytes(out)

    @staticmethod
    def _make_key(data: bytes) -> bytes:
        data = bytearray(data)
        data_len = len(data)
        data.extend(b"\0" * (256 - len(data)))
        last = MAGIC
        v = MAGIC
        for i in range(data_len + 1):
            v = ((v << 7) + (v >> 1)) & 0xFF
            data[i] ^= v
            last = (last + data[i] * ((v & 1) + 2)) & 0xFF
        data[data_len + 1] = last
        return bytes(data)

    def _init_table(self, key: bytes):
        buf = bytearray(range(256))
        rot = lambda x: ((x << 7) | (x >> 1)) & 0xFF
        accum = MAGIC
        h = MAGIC
        never_reset = True
        i2 = 0
        k = 0
        for i in range(256):
            h = rot(h)
            if never_reset:
                accum = (accum + (2 if (h & 1) == 0 else 3)) & 0xFF
                accum = (accum * key[k]) & 0xFF
            if h == key[k]:
                h = rot(MAGIC)
                k = 0
                never_reset = False
            i2 = (i2 + ((h ^ key[k]) + buf[i])) & 0xFF
            buf[i2], buf[i] = buf[i], buf[i2]
            k = (k + 1) & 0xFF
        self.table = buf

    def transform(self, chunk: bytearray):
        tmp = bytearray(self.table)
        i = i2 = 0
        for j in range(len(chunk)):
            i = (i + 1) & 0xFF
            i2 = (i2 + tmp[i]) & 0xFF
            tmp[i2], tmp[i] = tmp[i], tmp[i2]
            xor = tmp[(tmp[i] + tmp[i2]) & 0xFF]
            chunk[j] ^= xor

    def decode(self, data: bytes, chunk_id: int, flag: int) -> bytes:
        if flag == 1:
            decomp_size, comp_size = struct.unpack_from("<II", data, 0)
            return zlib.decompress(data[8:8 + comp_size])
        if flag == 2:
            buf = bytearray(data)
            self.transform(buf)
            return bytes(buf)
        if flag == 3:
            decomp_size, = struct.unpack_from("<I", data, 0)
            raw = bytearray(data[4:])
            if (chunk_id & 1) == 1 and self.build > 284:
                raw[0] ^= (chunk_id & 0xFF) ^ (chunk_id >> 8)
            self.transform(raw)
            comp_size, = struct.unpack_from("<I", raw, 0)
            return zlib.decompress(bytes(raw[4:4 + comp_size]))
        return data


# ----------------------------------------------------------------- объекты
def parse_object(subchunks, unicode: bool, crypto: ChunkCrypto):
    handle = otype = None
    name = None
    props = None
    for cid, flag, raw in subchunks:
        try:
            data = crypto.decode(raw, cid, flag)
        except Exception:
            continue
        if cid == 17476:
            handle, otype, oflags = struct.unpack_from("<hhh", data, 0)
        elif cid == 17477:
            name = yuniversal(data, unicode)
        elif cid == 17478:
            props = data
    return handle, otype, name, props


def find_animations(props: bytes):
    """ищем структуру Animations без знания layout заголовка ObjectCommon"""
    n = len(props)
    for off in range(0, min(n - 4, 512), 2):
        size, count = struct.unpack_from("<hh", props, off)
        if not (1 <= count <= 32) or size <= 4 or size > 4096:
            continue
        if off + 4 + count * 2 > n:
            continue
        offsets = struct.unpack_from(f"<{count}h", props, off + 4)
        if any(o <= 0 or off + o + 4 > n for o in offsets):
            continue
        frames_all = []
        ok = True
        for o in offsets:
            base = off + o
            try:
                dir_offsets = struct.unpack_from("<32h", props, base)
            except struct.error:
                ok = False
                break
            any_dir = False
            for d_o in dir_offsets:
                if d_o == 0:
                    continue
                b2 = base + d_o
                if b2 + 8 > n:
                    continue
                mins, maxs, repeat, back, fc = struct.unpack_from("<bbhhH", props, b2)
                if not (0 < fc <= 400) or b2 + 8 + fc * 2 > n:
                    continue
                hs = struct.unpack_from(f"<{fc}H", props, b2 + 8)
                if any(h > 5000 for h in hs):
                    continue
                frames_all.extend(hs)
                any_dir = True
            if not any_dir:
                ok = False
        if ok and frames_all:
            return frames_all
    return []


def load_game(path: str):
    d = Path(path).read_bytes()
    pos = entry_point(d)
    # PackData: читаем шапку, чтобы узнать конец
    header_size, data_size = struct.unpack_from("<II", d, pos + 8)
    pack_end = pos + data_size
    chunks, stream = read_chunks(d, pack_end - 32)
    by_id = {}
    for c in chunks:
        by_id.setdefault(c["id"], []).append(c)

    def text_of(chunk_id):
        c = by_id.get(chunk_id, [None])[0]
        if not c:
            return ""
        try:
            raw = c["raw"]
            if c["flag"] == 1:
                decomp_size, comp_size = struct.unpack_from("<II", raw, 0)
                raw = zlib.decompress(raw[8:8 + comp_size])
            return raw.decode("utf-16-le" if b"\0" in raw[:40] and raw[0] != 0 else "latin1", "replace").strip("\0\r\n ")
        except Exception:
            return ""

    app_name = text_of(8740)
    copyright_ = text_of(8763)
    editor = text_of(8750)

    hdr = by_id.get(8739, [None])[0]
    build = 284
    if hdr:
        raw = hdr["raw"]
        if hdr["flag"] == 1:
            decomp_size, comp_size = struct.unpack_from("<II", raw, 0)
            raw = zlib.decompress(raw[8:8 + comp_size])
        # AppHeader: productBuild последним int32 (по CTFAK)
        try:
            size, = struct.unpack_from("<i", raw, 0)
            build = struct.unpack_from("<i", raw, 4 + size + 4 + 4 + 8 + 8 + 2 + 8)[0] if False else build
        except Exception:
            pass
    # build ищем проще: у 2.5 обычно 284/288/292
    build = 288

    unicode = b"PAMU" in d[pos:pos + data_size]
    crypto = ChunkCrypto(app_name, copyright_, editor, build)
    return d, chunks, by_id, crypto, unicode, dict(app_name=app_name, copyright=copyright_,
                                                   editor=editor, build=build, unicode=unicode)


def iter_objects(by_id, crypto, unicode):
    for c in by_id.get(8745, []):
        data = c["raw"]
        count, = struct.unpack_from("<i", data, 0)
        pos = 4
        for _ in range(count):
            subs = []
            while pos + 8 <= len(data):
                cid, flag, size = struct.unpack_from("<hhi", data, pos)
                if cid == 32639:
                    pos += 8
                    break
                subs.append((cid, flag, data[pos + 8:pos + 8 + size]))
                pos += 8 + size
            if not subs:
                break
            yield parse_object(subs, unicode, crypto)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--json", default="objects.json")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    d, chunks, by_id, crypto, unicode, meta = load_game(args.exe)
    print("мета:", json.dumps(meta, ensure_ascii=False))
    objs = []
    for handle, otype, name, props in iter_objects(by_id, crypto, unicode):
        frames = find_animations(props) if props else []
        objs.append(dict(handle=handle, type=otype, name=name, frames=frames))
    named = [o for o in objs if o["name"]]
    print(f"объектов: {len(objs)}, с именем: {len(named)}, с кадрами: {sum(1 for o in objs if o['frames'])}")
    Path(args.json).write_text(json.dumps(objs, ensure_ascii=False, indent=1))
    print("\nобъекты с наибольшим числом кадров:")
    for o in sorted(objs, key=lambda x: -len(x["frames"]))[:args.top]:
        uniq = len(set(o["frames"]))
        print(f"  handle={str(o['handle']):>5} type={o['type']} кадров={len(o['frames']):>4} уникальных={uniq:>4}  {o['name']!r}")
    print(f"\nвсё записано: {args.json}")


if __name__ == "__main__":
    main()
