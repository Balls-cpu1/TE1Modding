#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
te1_patch.py — патчер байткода событий The Escapists 1: правка событий фрейма
`game` прямо в TheEscapists.exe с корректной пересборкой PE (поток чанков Fusion
лежит в оверлее, поэтому файл можно свободно удлинять).

Команды:
  identity  — пересобрать exe без изменений (проверка round-trip, должен совпасть байт-в-байт)
  outfitdoor — добавить «дверь по форме» в выбранную тюрьму:
      --map perks        имя карты (глобальная строка 0), напр. perks/stalagflucht/shanktonstatepen
      --outfit 38        ID предмета-формы, которая ОТКРЫВАЕТ дверь (напр. 38 = Infirmary Overalls)
      --x 1152 --y 512   координаты двери (пиксели сетки карты, кратно 16)
      --exe exe/TheEscapists_eur.exe.txt -o work/TheEscapists_eur_outfitdoor.exe.txt

Технические детали (все проверены на сборке build 288):
  * zlib-сжатие чанков — level 9 (совпадает с оригиналом байт-в-байт);
  * чанк flag=3 = [u32 размер_распакованных][xor-байт при нечётном id][RC4-поток(cipher)[u32 размер_сжатых][zlib]];
  * группа событий хранит размер как ОТРИЦАТЕЛЬНОЕ i16, включающее само поле размера;
  * размер параметра/условия — положительный u16, тоже включающий поле размера.
"""
from __future__ import annotations
import argparse, struct, sys, zlib, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "toolkit"))
import te1_events as TE
from te1_frames import load_exe, find_frame, dechunk, decode_sub, CH_END
from te1_icons import read_chunks, find_stream, universal, zdec
from te_crypto import Cipher


# ------------------------------------------------------------------ байтовые утилиты
def w16(v): return struct.pack("<h", v)
def W16(v): return struct.pack("<H", v)
def w32(v): return struct.pack("<i", v)


def expr_long(v):
    return b"\xff\xff\x00\x00" + w16(10) + w32(v)


def expr_str(s):
    return b"\xff\xff\x03\x00" + w16(6 + (len(s) + 1) * 2) + s.encode("utf-16-le") + b"\0\0"


def expr_global_string(idx):
    # otype=-1 num=50 (глобальная строка), loader = 4 байта индекса
    return b"\xff\xff\x32\x00" + w16(10) + w32(idx)


EXPR_TERMINATOR = b"\x00\x00\x00\x00"  # otype=0 + num=0

# выражение «Named variable object:80 <имя>» — чтение именованной переменной
# otype=36 (extension), num=80, objinfo=180, list=0
def expr_named_var_index():
    return struct.pack("<hhhh", 36, 80, 10, 180) + w16(0)


def param(code: int, payload: bytes) -> bytes:
    """Параметр: [size u16 = 2+len(payload)+2? НЕТ: size включает себя сам]
    Фактически: size = 2 (size) + 2 (code) + len(payload)."""
    return W16(4 + len(payload)) + W16(code) + payload


def param_expr(cmp_code: int, exprs: bytes) -> bytes:
    return param(22 if cmp_code == 0 else 23, W16(cmp_code) + exprs + EXPR_TERMINATOR)


def param_on_group(name: str) -> bytes:
    """Условие «при активации группы <name>»: код 45, expr cmp=0, одна строка."""
    return param(45, W16(0) + expr_str(name) + EXPR_TERMINATOR)


def param_object(obj_info: int, obj_type: int = 2, obj_info_list: int = 0) -> bytes:
    return param(1, w16(obj_info_list) + W16(obj_info) + w16(obj_type))


def param_create(x: int, y: int, obj_info: int, layer: int = 1, inst: int = 6000, flags: int = 8) -> bytes:
    pos = (W16(0xFFFF) + W16(flags) + w16(x) + w16(y) + w16(0) + w16(0) +
           w32(0) + w16(0) + w16(0) + w16(layer))
    return param(9, pos + W16(inst) + W16(obj_info) + b"\0\0\0\0")


def condition(num: int, params: list, obj_type: int = -1, obj_info: int = 0,
              obj_info_list: int = 0, flags: int = 0x20, other: int = 0,
              def_type: int = 0, identifier: int = 0) -> bytes:
    params_b = b"".join(params)
    head = (w16(obj_type) + w16(num) + W16(obj_info) + w16(obj_info_list) +
            struct.pack("<bb", flags, other) + bytes([len(params)]) + bytes([def_type]) +
            w16(identifier))
    payload = head + params_b
    return W16(2 + len(payload)) + payload


def action(num: int, params: list, obj_type: int = -1, obj_info: int = 0,
           obj_info_list: int = 0, flags: int = 0, other: int = 0, def_type: int = 0) -> bytes:
    head = (w16(obj_type) + w16(num) + W16(obj_info) + w16(obj_info_list) +
            struct.pack("<bb", flags, other) + bytes([len(params)]) + bytes([def_type]))
    payload = head + b"".join(params)
    return W16(2 + len(payload)) + payload


def group(conditions: list, actions: list, flags: int = 0x2000, line: int = 0) -> bytes:
    body = (bytes([len(conditions), len(actions)]) + W16(flags) + w16(line) +
            w32(0) + w32(0) + b"".join(conditions) + b"".join(actions))
    return w16(-(2 + len(body))) + body


# ------------------------------------------------------------------ surgical-патчи raw-параметров
def patch_expr_string(param_raw: bytes, old: str, new: str) -> bytes:
    """Заменяет строковый литерал внутри expr-параметра, пересчитывая размеры."""
    assert len(param_raw) >= 8
    b = param_raw
    size, code = struct.unpack_from("<H", b, 0)[0], struct.unpack_from("<H", b, 2)[0]
    payload = bytearray(b[4:size])
    oldb = old.encode("utf-16-le") + b"\0\0"
    newb = new.encode("utf-16-le") + b"\0\0"
    off = payload.find(oldb)
    assert off != -1, f"строка {old!r} не найдена в параметре"
    # перед строкой: [expr header: otype(2) num(2) esize(2)]; esize = 6 + len(str bytes)
    esize_off = off - 2
    old_esize = struct.unpack_from("<H", payload, esize_off)[0]
    assert old_esize == 6 + len(oldb), (old_esize, len(oldb))
    payload[esize_off:esize_off + 2] = W16(6 + len(newb))
    payload[off:off + len(oldb)] = newb
    return W16(4 + len(payload)) + W16(code) + bytes(payload)


def patch_expr_long_after_string(param_raw: bytes, anchor: str, value: int) -> bytes:
    """Заменяет long-литерал, идущий в выражении ПОСЛЕ строкового литерала anchor
    (в условии-подстроке это длина: <строка "Outfit"> sys-2 sys-3 long<N> ...)."""
    b = param_raw
    size, code = struct.unpack_from("<H", b, 0)[0], struct.unpack_from("<H", b, 2)[0]
    payload = bytearray(b[4:size])
    anchorb = anchor.encode("utf-16-le") + b"\0\0"
    off = payload.find(anchorb) + len(anchorb)
    # ищем шаблон long-литерала: ff ff 00 00 0a 00 <i32>
    pat_idx = payload.find(b"\xff\xff\x00\x00\x0a\x00", off)
    assert pat_idx != -1, "long-литерал после якоря не найден"
    struct.pack_into("<i", payload, pat_idx + 6, value)
    return W16(4 + len(payload)) + W16(code) + bytes(payload)


def patch_create_xy(param_raw: bytes, x: int, y: int) -> bytes:
    """В param code=9 (Create) меняем X/Y (i16 на смещении 4..8 от начала записи)."""
    b = bytearray(param_raw)
    struct.pack_into("<hh", b, 4 + 4, x, y)  # 2(size)+2(code) + parent(2)+flags(2)
    return bytes(b)


def resize_condition(cond_raw: bytes) -> bytes:
    """Пересчитывает u16 размера условия (после правки параметров)."""
    b = bytearray(cond_raw)
    struct.pack_into("<H", b, 0, len(b))
    return bytes(b)


def build_group_from_parts(conds: list, acts: list, flags: int = 0x2000, line: int = 0) -> bytes:
    return group(conds, acts, flags=flags, line=line)


# ------------------------------------------------------------------ работа с exe
def load_all(exe_path):
    d = open(exe_path, "rb").read()
    stream_off = find_stream(d)
    chunks = read_chunks(d, stream_off)
    by = {}
    for c in chunks:
        by.setdefault(c[0], []).append(c)
    name = universal(zdec(by[8740][0][2])).strip("\0")
    cop = universal(zdec(by[8763][0][2])).strip("\0")
    ed = universal(zdec(by[8750][0][2])).strip("\0")
    cipher = Cipher(name, cop, ed)
    return d, stream_off, chunks, cipher


def frame_chunks(chunks, cipher, frame_name="game"):
    """→ (индекс в списке chunks, [(cid,flag,raw)]) для фрейма."""
    for i, (cid, flag, data) in enumerate(chunks):
        if cid != 13107:
            continue
        subs = dechunk(data)
        plain = {}
        for scid, sflag, sraw in subs:
            try:
                plain[scid] = decode_sub(scid, sflag, sraw, cipher)
            except Exception:
                plain[scid] = None
        nm = plain.get(13109)
        nm = nm.decode("utf-16-le", "replace").strip("\0") if nm else "?"
        if nm == frame_name:
            return i, subs
    raise SystemExit(f"фрейм {frame_name!r} не найден")


def encode_sub3(cid: int, plain: bytes, cipher: Cipher) -> bytes:
    """Собирает чанк flag=3 из распакованных данных."""
    compressed = zlib.compress(plain, 9)
    t = w32(len(compressed)) + compressed
    body = bytearray(cipher.transform(t))
    if cid & 1:
        body[0] ^= (cid & 0xFF) ^ (cid >> 8)
    return w32(len(plain)) + bytes(body)


def rebuild_frame(subs: list, new_events: bytes, cipher: Cipher) -> bytes:
    """Собирает тело чанка 13107 с заменённым 13117."""
    out = []
    for scid, sflag, sraw in subs:
        if scid == CH_END:
            out.append(struct.pack("<hhi", scid, sflag, len(sraw)) + sraw)
        elif scid == 13117:
            raw = encode_sub3(scid, new_events, cipher)
            out.append(struct.pack("<hhi", scid, sflag, len(raw)) + raw)
        else:
            out.append(struct.pack("<hhi", scid, sflag, len(sraw)) + sraw)
    return b"".join(out)


def rebuild_exe(d: bytes, stream_off: int, chunks: list, cipher: Cipher,
                frame_idx: int, new_frame_body: bytes) -> bytes:
    out = [d[:stream_off]]
    for i, (cid, flag, data) in enumerate(chunks):
        if i == frame_idx:
            data = new_frame_body
        out.append(struct.pack("<hhi", cid, flag, len(data)) + data)
    return b"".join(out)


# ------------------------------------------------------------------ вставка групп в события
def append_groups(events: bytes, new_groups: list) -> bytes:
    """Дописывает группы в конец блока ERev (перед <<ER) и правит размеры ERes/ERev."""
    er = events.rindex(b"<<ER")
    assert events[events.rindex(b"ERev", 0, er):er].startswith(b"ERev")
    erev_off = events.rindex(b"ERev", 0, er)
    groups_end = er  # группы занимают [erev_off+8, er)
    add = b"".join(new_groups)
    out = bytearray(events[:groups_end] + add + events[groups_end:])
    struct.pack_into("<i", out, erev_off + 4, (groups_end - (erev_off + 8)) + len(add))
    # ERes = размер блока групп
    eres_off = events.rindex(b"ERes", 0, erev_off)
    val = struct.unpack_from("<i", out, eres_off + 4)[0]
    struct.pack_into("<i", out, eres_off + 4, val + len(add))
    return bytes(out)


# ------------------------------------------------------------------ high-level операции
def find_named_group_def(groups, name):
    """Ищет группу-определение с именем name (условие num=-10, param code=38)."""
    for g in groups:
        for c in g.conditions:
            if c.num == -10 and c.params:
                d = c.params[0].data or {}
                if d.get("kind") == "group" and d.get("name") == name:
                    return g
    return None


def build_outfitdoor_groups(events: bytes, map_name: str, outfit_id: int, x: int, y: int):
    info, groups = TE.parse_events(events)
    src_create = groups[773]   # DTAF: создать Door - outfit
    src_check = groups[1017]   # DTAF: проверка формы

    # условие «глобальная строка 0 == <имя карты>»: левый параметр (код 22) берём как есть
    # из игры (см. группу #4989 с "perks"), правый собираем сами (код 23)
    PARAM_GSTR0 = bytes.fromhex("160016000000ffff32000c0000000000000000000000")
    cond_mapname = condition(-3, [PARAM_GSTR0, param_expr(0, expr_str(map_name))],
                             obj_type=-1, flags=0x20, identifier=-32000)

    # --- группа создания двери ---
    cond_onmap = condition(
        -16, [patch_expr_string(src_create.conditions[0].params[0].raw, "setup_DTAF", "grab_map_data")],
        obj_type=-1, flags=0, identifier=-32002)

    act_create = src_create.actions[0]
    create_raw = patch_create_xy(act_create.params[0].raw, x, y)
    act_create_bytes = action(0, [create_raw], obj_type=act_create.obj_type)

    g_create = group([cond_onmap, cond_mapname], [act_create_bytes], flags=0x2080)

    # --- группа проверки формы ---
    cc = src_check.conditions
    cond_movechk = condition(
        -16, [patch_expr_string(cc[0].params[0].raw, "move_check_doors", "move_check")],
        obj_type=-1, flags=0, identifier=-32003)
    cond_collide = resize_condition(cc[2].raw)
    # проверка формы: p0 = подстрока "Outfit" (длина = len(lit)), p1 = сравнение с литералом, cmp=1 (не равно)
    lit = f"{outfit_id}_"
    p0 = patch_expr_long_after_string(cc[3].params[0].raw, "Outfit", len(lit))
    p1 = patch_expr_string(cc[3].params[1].raw, "228_", lit)
    cond_outfit = resize_condition(condition(
        -3, [p0, p1], obj_type=-1, flags=cc[3].flags, identifier=-32001))
    act_blocked = src_check.actions[0].raw
    g_check = group([cond_movechk, cond_mapname, cond_collide, cond_outfit],
                    [act_blocked], flags=0x2000)
    return [g_create, g_check]


# ------------------------------------------------------------------ CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["identity", "outfitdoor"])
    ap.add_argument("exe")
    ap.add_argument("--frame", default="game")
    ap.add_argument("--map", default="perks", help="имя карты (глобальная строка 0)")
    ap.add_argument("--outfit", type=int, default=38, help="ID формы, открывающей дверь")
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    d, stream_off, chunks, cipher = load_all(a.exe)
    fi, subs = frame_chunks(chunks, cipher, a.frame)

    # текущие события
    raw13117 = dict((s[0], s[2]) for s in subs)[13117]
    body = bytearray(raw13117[4:])
    if 13117 & 1:
        body[0] ^= (13117 & 0xFF) ^ (13117 >> 8)
    t = cipher.transform(bytes(body))
    cs, = struct.unpack_from("<I", t, 0)
    events = zlib.decompress(t[4:4 + cs])

    if a.cmd == "identity":
        new_events = events
    else:
        new_groups = build_outfitdoor_groups(events, a.map, a.outfit, a.x, a.y)
        print(f"новых групп: {len(new_groups)} ({sum(len(g) for g in new_groups)} байт)")
        new_events = append_groups(events, new_groups)

    new_body = rebuild_frame(subs, new_events, cipher)
    out = rebuild_exe(d, stream_off, chunks, cipher, fi, new_body)
    open(a.out, "wb").write(out)
    print(f"exe: {len(d)} -> {len(out)} байт ({len(out)-len(d):+d}) -> {a.out}")

    # контрольная проверка: перечитываем события из нового exe
    d2, so2, ch2, ci2 = load_all(a.out)
    fi2, subs2 = frame_chunks(ch2, ci2, a.frame)
    raw2 = dict((s[0], s[2]) for s in subs2)[13117]
    b2 = bytearray(raw2[4:])
    if 13117 & 1:
        b2[0] ^= (13117 & 0xFF) ^ (13117 >> 8)
    t2 = ci2.transform(bytes(b2))
    cs2, = struct.unpack_from("<I", t2, 0)
    events2 = zlib.decompress(t2[4:4 + cs2])
    info, groups2 = TE.parse_events(events2)
    print(f"проверка: событий {len(events)} -> {len(events2)} байт, групп {len(groups2)}, "
          f"потреблено {info['consumed']}/{info['total']}")
    if a.cmd == "identity":
        same = out == d
        ev_same = events2 == events
        print(f"round-trip: exe {'ИДЕНТИЧЕН ✓' if same else 'ОТЛИЧАЕТСЯ ✗'}; события {'✓' if ev_same else '✗'}")
        sys.exit(0 if (same and ev_same) else 1)


if __name__ == "__main__":
    main()
