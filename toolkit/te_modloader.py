#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
te_modloader.py — «крутой» мод-лоадер для The Escapists 1 (PC).

Что делает:
  install  — создаёт папку mods/ в каталоге игры (+ mods/_backup/), пишет подсказку.
  apply    — копирует все *.dat из mods/ в Data/ (оригиналы один раз в _backup),
             затем ПЕРЕСОБИРАЕТ Data/val.dat под новые размеры файлов,
             поэтому валидатор «молчит» (он проверяет только размер).
  restore  — возвращает оригиналы из _backup и пересобирает val.dat.

Валидатор не вырезается из exe (это отдельный сложный байт-патч) — он НЕЙТРАЛИЗУЕТСЯ:
val.dat всегда приводится в соответствие с тем, что лежит в Data/, и игра стартует чисто.

Использование:
    python te_modloader.py install ["C:\\Program Files (x86)\\Steam\\steamapps\\common\\The Escapists"]
    python te_modloader.py apply   [gamedir]
    python te_modloader.py restore [gamedir]
"""
from __future__ import annotations
import argparse, hashlib, os, re, shutil, sys

LANGS = {"e": "eng", "f": "fre", "g": "ger", "s": "spa", "r": "rus", "p": "pol", "i": "ita"}
KINDS = ["data", "items", "speech"]
DEFAULT = r"C:\Program Files (x86)\Steam\steamapps\common\The Escapists"


def md5_size(sz: int) -> str:
    return hashlib.md5(("l0l_%d" % sz).encode()).hexdigest()


def find_gamedir(arg):
    cands = []
    if arg:
        cands.append(arg)
    cands.append(DEFAULT)
    cands.append(os.path.join(DEFAULT.replace("Program Files (x86)", "Program Files")))
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "Data")):
            return c
    return None


def rebuild_val(data_dir: str):
    vpath = os.path.join(data_dir, "val.dat")
    if not os.path.exists(vpath):
        print("  ! val.dat не найден, пропускаю")
        return
    raw = open(vpath, "rb").read()
    txt = raw.decode("utf-16-le", "replace")
    if txt.startswith("\ufeff"):
        txt = txt[1:]
    changed = 0
    for letter, lang in LANGS.items():
        m = re.search(r"(^|\n)(%s=)([0-9a-f]{32})_([0-9a-f]{32})_([0-9a-f]{32})" % letter, txt)
        if not m:
            continue
        toks = [m.group(3), m.group(4), m.group(5)]
        for i, kind in enumerate(KINDS):
            fp = os.path.join(data_dir, "%s_%s.dat" % (kind, lang))
            if os.path.exists(fp):
                toks[i] = md5_size(os.path.getsize(fp))
        new = m.group(1) + m.group(2) + toks[0] + "_" + toks[1] + "_" + toks[2]
        txt = txt[:m.start()] + new + txt[m.end():]
        changed += 1
    open(vpath, "wb").write(("\ufeff" + txt).encode("utf-16-le"))
    print("  val.dat пересобран (%d языков)" % changed)


def install(gd):
    mods = os.path.join(gd, "mods")
    bak = os.path.join(mods, "_backup")
    os.makedirs(bak, exist_ok=True)
    readme = os.path.join(mods, "README.txt")
    if not os.path.exists(readme):
        open(readme, "w", encoding="utf-8").write(
            "Клади сюда свои .dat (items_rus.dat, data_eng.dat, speech_*.dat ...).\n"
            "Запускай игру через 'Запустить_с_модами.bat' или:\n"
            "  python te_modloader.py apply\n"
            "Оригиналы хранятся в _backup/, откат: python te_modloader.py restore\n")
    # скопируем сам скрипт в папку игры, чтобы bat работал автономно
    try:
        shutil.copy(os.path.abspath(__file__), os.path.join(gd, "te_modloader.py"))
    except Exception as e:
        print("  ! не смог скопировать скрипт:", e)
    bat = os.path.join(gd, "Запустить_с_модами.bat")
    if not os.path.exists(bat):
        open(bat, "w", encoding="cp1251").write(
            "@echo off\r\ncd /d \"%~dp0\"\r\npython \"%~dp0te_modloader.py\" apply \"%~dp0\"\r\n"
            "if errorlevel 1 py -3 \"%~dp0te_modloader.py\" apply \"%~dp0\"\r\n"
            "start \"\" \"%~dp0TheEscapists.exe\"\r\n")
    print("install: mods/ создан в", gd)


def apply(gd):
    mods = os.path.join(gd, "mods")
    bak = os.path.join(mods, "_backup")
    data = os.path.join(gd, "Data")
    os.makedirs(bak, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(mods)):
        if not fn.lower().endswith(".dat"):
            continue
        src = os.path.join(mods, fn)
        dst = os.path.join(data, fn)
        if os.path.exists(dst) and not os.path.exists(os.path.join(bak, fn)):
            shutil.copy(dst, os.path.join(bak, fn))
        shutil.copy(src, dst)
        print("  apply:", fn, "(%d байт)" % os.path.getsize(src))
        n += 1
    print("применено файлов:", n)
    rebuild_val(data)


def restore(gd):
    bak = os.path.join(gd, "mods", "_backup")
    data = os.path.join(gd, "Data")
    n = 0
    if os.path.isdir(bak):
        for fn in os.listdir(bak):
            shutil.copy(os.path.join(bak, fn), os.path.join(data, fn))
            print("  restore:", fn)
            n += 1
    rebuild_val(data)
    print("восстановлено:", n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["install", "apply", "restore"])
    ap.add_argument("gamedir", nargs="?", default=None)
    a = ap.parse_args()
    gd = find_gamedir(a.gamedir)
    if not gd:
        print("Каталог игры с папкой Data не найден. Укажи путь явно.")
        sys.exit(1)
    print("каталог игры:", gd)
    {"install": install, "apply": apply, "restore": restore}[a.cmd](gd)


if __name__ == "__main__":
    main()
