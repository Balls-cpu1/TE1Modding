#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self test for TE1_Mod_Launcher.bat / the embedded mod engine.

Builds a throwaway game folder out of data_samples/, unpacks the engine
from the .bat exactly the way PowerShell does, runs both mods, and checks
the result. Run:  python3 tools/test_launcher.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work" / "selftest"
ENGINE = WORK / "te1_engine.py"
BAT = ROOT / "TE1_Mod_Launcher.bat"
SAMPLES = ROOT / "data_samples"

BEGIN = "#<ENGINE>"
END = "#</ENGINE>"

ok = True


def check(label, cond, extra=""):
    global ok
    print("  %-4s %s%s" % ("OK" if cond else "FAIL", label,
                           ("  -- " + extra) if extra and not cond else ""))
    if not cond:
        ok = False


def unpack_engine():
    """Same job as the PowerShell one-liner in the .bat."""
    with open(str(BAT), "r", encoding="ascii", newline="") as fh:
        lines = fh.read().split("\r\n")
    i = lines.index(BEGIN)
    j = lines.index(END)
    ENGINE.parent.mkdir(parents=True, exist_ok=True)
    ENGINE.write_text("\n".join(lines[i + 1:j]) + "\n", encoding="ascii")


def make_game():
    game = WORK / "game"
    data = game / "Data"
    if data.exists():
        import shutil
        shutil.rmtree(data)
    data.mkdir(parents=True)
    for f in sorted(SAMPLES.glob("*.dat")):
        (data / f.name).write_bytes(f.read_bytes())
    (game / "TheEscapists.exe").write_bytes(b"not a real exe\n")
    return game


def run(game, *args):
    p = subprocess.run([sys.executable, str(ENGINE), "--game", str(game)] + list(args),
                       capture_output=True, text=True, encoding="utf-8")
    return p


def main():
    if WORK.exists():
        import shutil
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    print("1. unpack the engine out of the .bat")
    unpack_engine()
    check("engine extracted", ENGINE.exists())
    check("engine is pure ASCII",
          all(ord(c) < 127 for c in ENGINE.read_text(encoding="ascii")))
    body = ENGINE.read_text(encoding="ascii")
    check("FIXES database present", '"items"' in body and '"speech"' in body)
    check("FIXES are \\u escaped, not raw Cyrillic", "\\u041a" in body)

    print("2. build a fake game folder from data_samples")
    game = make_game()
    data = game / "Data"
    before = {f.name: f.read_bytes() for f in data.glob("*.dat")}
    check("game folder ready", (game / "TheEscapists.exe").exists())

    print("3. install both mods")
    state = game / "mods" / "mods.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"randomizer": True, "better_translate": True}),
                     encoding="utf-8")
    p = run(game, "--apply")
    print("     " + "\n     ".join(p.stdout.strip().splitlines()))
    check("apply exited cleanly", p.returncode == 0, p.stderr[-400:])

    print("4. backups and results")
    orig = game / "mods" / "original"
    check("originals backed up", (orig / "items_rus.dat").exists())
    check("backup == pre-mod bytes",
          (orig / "items_rus.dat").read_bytes() == before["items_rus.dat"])
    after = {f.name: f.read_bytes() for f in data.glob("*.dat")}
    check("items_rus.dat changed", after["items_rus.dat"] != before["items_rus.dat"])
    check("data_rus.dat changed", after["data_rus.dat"] != before["data_rus.dat"])
    check("speech_rus.dat changed", after["speech_rus.dat"] != before["speech_rus.dat"])
    check("val.dat rebuilt", after["val.dat"] != before["val.dat"])
    check("data_eng.dat untouched",
          after["data_eng.dat"] == before["data_eng.dat"])

    print("5. Better Translate: spot checks")
    ir = (data / "items_rus.dat").read_bytes().decode("utf-16")
    dr = (data / "data_rus.dat").read_bytes().decode("utf-16")
    sr = (data / "speech_rus.dat").read_bytes().decode("utf-16")
    check("no untranslated English item descriptions",
          "Unlocks yellow doors" not in ir)
    check("no untranslated English item names", "Dirty Tux Outfit" not in ir)
    check("machine word order fixed",
          "Пластиковый ключ рабочего" in ir and "Пластиковый работа ключевая" not in ir)
    check("File -> Напильник everywhere",
          "Напильник" in ir and ir.count("Файл") == 0)
    check("no stray English 'Rope' in recipes", ", Rope" not in ir)
    check("no NBSP left", "\u00a0" not in dr and "\u00a0" not in sr)
    import re as _re
    check("no stray LF inside values",
          not _re.search(r"(?<!\r)\n", dr) and not _re.search(r"(?<!\r)\n", sr))
    check("homoglyph fixed (К тому же)", "К тому же.." in dr)
    check("homoglyph fixed (продажу)", "на продажу." in dr)
    check("$combat restored in the Mac tutorial", "$combat" in dr and "$бой" not in dr)
    check("tutorial prefix synced", "1@Подойди к своему столу" in dr)
    check("UI labels capitalised", "\r\n2=Новая игра\r\n" in dr)
    check("credits translated", "Mouldy Toof Studios" not in dr.split("[Misc]")[1][:4000]
          or "Разработано Mouldy Toof Studios" in dr)
    check("Store -> Магазин", "54=Магазин" in dr)
    check("MedStaff refilled", "наш последний пациент умер" in sr)
    check("MedStaff Count updated", "[MedStaff]\r\nCount=24" in sr)
    check("OnDesk refilled", "[OnDesk]\r\nCount=3" in sr)
    check("Sheets refilled", "[Sheets]\r\nCount=10" in sr)
    check("no trailing spaces left in speech lines",
          not any(l.endswith(" ") for l in sr.split("\r\n") if "=" in l))

    print("6. Randomizer")
    p2 = run(game, "--apply")
    a = (data / "items_rus.dat").read_bytes()
    check("second apply produced a different roll", a != after["items_rus.dat"])
    check("names survived the randomizer",
          "Ключ от камеры" in a.decode("utf-16"))
    check("craft recipes survived",
          "80_Легкая лопата, Лист металла, Клейкая лента" in a.decode("utf-16"))

    print("7. restore")
    p3 = run(game, "--restore")
    check("restore exited cleanly", p3.returncode == 0)
    restored = {f.name: f.read_bytes() for f in data.glob("*.dat")}
    diff = [n for n in before if before[n] != restored.get(n)]
    check("every .dat is byte-identical again", not diff, str(diff))

    print("8. dry-run report on a clean tree")
    p4 = run(game, "--report")
    check("report exited cleanly", p4.returncode == 0, p4.stderr[-400:])
    print("     " + "\n     ".join(p4.stdout.strip().splitlines()))

    print()
    print("ALL GOOD" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
