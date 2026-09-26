#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
te1_randomizer.py - randomizer predmetov dlya The Escapists 1 (PC / Steam).

Odin fail, nikakih zavisimostej krome Python 3.
Zapusk:  py te1_randomizer.py

U kazhdogo predmeta sluchajno menyayutsya svojstva: uron, kopka, dolbezka,
rezka, otkruchivanie, lechenie, snyatie ustalosti, legalnost, cena, iznos,
cennost kak podarka. Podushkoj dejstvitelno mozhno lomata steny ili sest' ee.

Bezopasnost:
  * pered zapisiyu delaet backup items_*.dat i val.dat;
  * sam peresobiraet val.dat (inache igra ne zapustitsya - ona
    proveryaet RAZMER failov);
  * otkat: py te1_randomizer.py --restore
"""
from __future__ import annotations

import hashlib
import os
import random
import shutil
import sys
from pathlib import Path

VERSION = "1.0"

# папка игры по умолчанию (твоя)
GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\The Escapists"

# возможные пути, если стандартный не подойдёт
FALLBACK_DIRS = [
    r"C:\Program Files\Steam\steamapps\common\The Escapists",
    r"D:\Steam\steamapps\common\The Escapists",
    r"D:\SteamLibrary\steamapps\common\The Escapists",
    r"E:\SteamLibrary\steamapps\common\The Escapists",
]

# какие поля рандомизируем и из каких значений
STAT_POOLS = {
    "Weapon":     [0, 1, 1, 2, 2, 3, 3, 4, 5],
    "Digging":    [0, 0, 1, 1, 2, 2, 3, 5],
    "Chipping":   [0, 0, 1, 1, 2, 2, 3, 5],
    "Cutting":    [0, 0, 1, 1, 2, 2, 3, 5],
    "Unscrewing": [0, 0, 1, 1, 2, 3],
    "HP":         [0, 0, 0, 5, 10, 15, 25, 40],
    "FAT":        [0, 0, 0, 5, 10, 20],
    "Gift":       [0, 1, 1, 2, 2, 3, 5],
    "Decay":      [0, 1, 2, 2, 5, 5, 10],
    "Buy":        [0, 5, 10, 20, 30, 50, 75, 100],
}

# эти поля НЕ трогаем: они отвечают за появление предмета в мире
PROTECTED = {"Name", "Craft", "Found", "Desk", "NPC_carry", "Outfit", "Info",
             "CamDis", "Illegal"}


# ------------------------------------------------------------------ консоль
def _fix_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_console()


def say(*a):
    print(*a)


def ask(prompt, default=None):
    s = input(prompt + (f" [{default}]: " if default is not None else ": ")).strip()
    return s or (default if default is not None else "")


# ------------------------------------------------------------------ кодировки
def detect_plain(raw: bytes):
    """(открытый_текст?, кодировка). UTF-16 содержит нули, поэтому
    обычная проверка «много ли печатных байтов» его отвергает."""
    if not raw:
        return False, None
    if raw.startswith(b"\xff\xfe"):
        return True, "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return True, "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return True, "utf-8-sig"

    head = raw[:2048]
    nulls = head.count(b"\x00")

    if nulls > len(head) * 0.15:                    # похоже на UTF-16
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                t = head.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
            pr = sum(1 for c in t if c.isprintable() or c in "\r\n\t")
            if t and pr / len(t) > 0.85:
                return True, enc
        return False, None

    textish = sum(1 for c in head if 32 <= c < 127 or c in (9, 10, 13))
    if textish / len(head) > 0.85:
        for enc in ("utf-8", "cp1251"):
            try:
                raw.decode(enc)
                return True, enc
            except UnicodeDecodeError:
                continue
        return True, "latin-1"

    high = sum(1 for c in head if c >= 0x80)        # кириллица без BOM
    if high > len(head) * 0.10:
        try:
            raw.decode("utf-8")
            return True, "utf-8"
        except UnicodeDecodeError:
            pass
        try:
            t = head.decode("cp1251")
        except UnicodeDecodeError:
            return False, None
        if t.count("[") + t.count("=") + t.count("\n") >= 8:
            return True, "cp1251"
    return False, None


# ------------------------------------------------------------------ val.dat
def md5_size(size: int) -> str:
    """Ровно тот хеш, который проверяет игра."""
    return hashlib.md5(("l0l_%d" % size).encode()).hexdigest()


def rebuild_val(data_dir: Path):
    vpath = data_dir / "val.dat"
    if not vpath.exists():
        say("  ! val.dat не найден - пропускаю (игра может не запуститься)")
        return 0
    import re
    txt = vpath.read_bytes().decode("utf-16-le", "replace")
    bom = txt.startswith("\ufeff")
    if bom:
        txt = txt[1:]
    langs = {"e": "eng", "f": "fre", "g": "ger", "s": "spa",
             "r": "rus", "p": "pol", "i": "ita"}
    kinds = ["data", "items", "speech"]
    changed = 0
    for letter, lang in langs.items():
        m = re.search(r"(^|\n)(%s=)([0-9a-f]{32})_([0-9a-f]{32})_([0-9a-f]{32})"
                      % letter, txt)
        if not m:
            continue
        toks = [m.group(3), m.group(4), m.group(5)]
        for i, kind in enumerate(kinds):
            fp = data_dir / f"{kind}_{lang}.dat"
            if fp.exists():
                toks[i] = md5_size(fp.stat().st_size)
        txt = txt[:m.start()] + m.group(1) + m.group(2) + "_".join(toks) + txt[m.end():]
        changed += 1
    out = ("\ufeff" if bom else "") + txt
    vpath.write_bytes(out.encode("utf-16-le"))
    return changed


# ------------------------------------------------------------------ INI
def parse_items(text: str):
    import re
    items, order, cur = {}, [], None
    for line in text.splitlines():
        m = re.match(r"^\s*\[(\d+)\]\s*$", line)
        if m:
            cur = {}
            items[int(m.group(1))] = cur
            order.append(int(m.group(1)))
            continue
        m = re.match(r"^\s*([A-Za-z_]+)\s*=\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    return items, order


def build_text(header: str, items: dict, order: list, newline: str) -> str:
    out = [header.rstrip("\r\n")] if header.strip() else []
    for iid in order:
        out.append("")
        out.append(f"[{iid}]")
        for k, v in items[iid].items():
            out.append(f"{k}={v}")
    return newline.join(out) + newline


# ------------------------------------------------------------------ ядро
def find_game_dir(arg=None):
    cands = ([arg] if arg else []) + [GAME_DIR] + FALLBACK_DIRS + [os.getcwd()]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "Data")):
            return Path(c)
    return None


def randomize(items: dict, order: list, rnd: random.Random, chaos: int):
    """→ список строк-примеров того, что изменилось."""
    keys = list(STAT_POOLS)
    log = []
    touched = 0
    for iid in order:
        it = items[iid]
        nm = (it.get("Name") or "").strip().lower()
        if nm in ("", "empty", "none"):
            continue

        before = {k: it.get(k) for k in keys}
        n = min(rnd.randint(1, 2 + chaos), len(keys))
        for k in rnd.sample(keys, n):
            v = rnd.choice(STAT_POOLS[k])
            if v == 0:
                it.pop(k, None)
            else:
                it[k] = str(v)

        if chaos >= 2 and rnd.random() < 0.4:
            it["Illegal"] = "1" if rnd.random() < 0.5 else "0"

        diff = []
        for k in keys:
            if it.get(k) != before[k]:
                diff.append(f"{k}={it.get(k) or 0}")
        if diff:
            touched += 1
            if len(log) < 20:
                log.append(f"    [{iid:>3}] {it.get('Name','?')[:30]:30} {', '.join(diff)}")
    return touched, log


def do_randomize(data_dir: Path, lang: str, seed, chaos: int, apply_it: bool):
    f = data_dir / f"items_{lang}.dat"
    if not f.exists():
        say(f"  ! файл не найден: {f}")
        return False

    raw = f.read_bytes()
    plain, enc = detect_plain(raw)
    if not plain:
        say("  ! файл зашифрован (Blowfish). Этот скрипт работает только с")
        say("    открытыми .dat - возьми te1_mod.py, он умеет расшифровывать.")
        return False

    text = raw.decode(enc, "replace")
    items, order = parse_items(text)
    if not items:
        say("  ! не похоже на items_*.dat (нет блоков [ID])")
        return False

    say(f"  файл:      {f.name}")
    say(f"  кодировка: {enc}")
    say(f"  предметов: {len(items)} (ID {min(order)}..{max(order)})")
    say(f"  сид:       {seed if seed is not None else 'случайный'}")
    say(f"  хаос:      {chaos}")

    rnd = random.Random(seed)
    touched, log = randomize(items, order, rnd, chaos)

    say(f"\n  изменено предметов: {touched}")
    say("  примеры:")
    say("\n".join(log))
    if touched > len(log):
        say(f"    ... и ещё {touched - len(log)}")

    if not apply_it:
        say("\n  (это был предпросмотр - файл НЕ изменён)")
        return True

    # бэкапы
    for p in (f, data_dir / "val.dat"):
        if p.exists():
            bak = p.with_name(p.name + ".bak")
            if not bak.exists():
                shutil.copy2(p, bak)
                say(f"\n  бэкап: {bak.name}")

    nl = "\r\n" if "\r\n" in text else "\n"
    header = text.split("[", 1)[0]
    new_text = build_text(header, items, order, nl)
    f.write_bytes(new_text.encode(enc, "replace"))
    say(f"  записано: {f.name} ({f.stat().st_size} байт)")

    n = rebuild_val(data_dir)
    say(f"  val.dat пересобран ({n} языков) - валидатор не будет ругаться")
    say("\n  Готово. Запускай игру.")
    say("  Откат:  py te1_randomizer.py --restore")
    return True


def do_restore(data_dir: Path):
    say("\n=== Откат ===")
    n = 0
    for bak in sorted(data_dir.glob("*.dat.bak")):
        target = data_dir / bak.name[:-4]
        shutil.copy2(bak, target)
        say(f"  восстановлен {target.name}")
        n += 1
    if n == 0:
        say("  бэкапов (.bak) не найдено")
        return
    rebuild_val(data_dir)
    say(f"  готово, восстановлено файлов: {n}")


# ------------------------------------------------------------------ запуск
def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])

    say("\n" + "=" * 58)
    say("  THE ESCAPISTS 1 - РАНДОМАЙЗЕР ПРЕДМЕТОВ  v" + VERSION)
    say("=" * 58)

    restore = "--restore" in argv
    gd = find_game_dir()
    if not gd:
        p = ask("\nПапка игры не найдена. Введи путь (где лежит Data\\)")
        gd = find_game_dir(p)
    if not gd:
        say("  ! не нашёл папку с Data\\ - выход")
        return 1
    say(f"\n  Папка игры: {gd}")

    data = gd / "Data"
    if restore:
        do_restore(data)
        input("\n[Enter] - выход...")
        return 0

    # язык
    langs = [f.stem.split("_")[1] for f in data.glob("items_*.dat")]
    langs = [l for l in langs if len(l) == 3]
    if "rus" in langs:
        default_lang = "rus"
    elif langs:
        default_lang = langs[0]
    else:
        say("  ! в Data нет ни одного items_*.dat")
        return 1
    say(f"  Найденные языки: {', '.join(langs)}")
    lang = ask("Язык (какой файл правим)", default_lang)

    chaos = ask("Уровень хаоса 1-4 (1=мягко, 4=полный)", "2")
    try:
        chaos = max(1, min(4, int(chaos)))
    except ValueError:
        chaos = 2

    s = ask("Сид (число - для повторимости, пусто = случайный)")
    seed = int(s) if s.lstrip("-").isdigit() else None

    say("")
    do_randomize(data, lang, seed, chaos, apply_it=False)

    if ask("\nПрименить? (y/n)", "n").lower() != "y":
        say("  отменено, файлы не тронуты")
        input("\n[Enter] - выход...")
        return 0

    say("")
    do_randomize(data, lang, seed, chaos, apply_it=True)
    input("\n[Enter] - выход...")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nпрервано")
        sys.exit(1)
