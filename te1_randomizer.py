#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
te1_randomizer.py - randomizer predmetov dlya The Escapists 1 (PC / Steam).

Odin fail, bez zavisimostej krome Python 3.

REZHIMY:
  py te1_randomizer.py            obychnyj: odin raz peretasovat i vyjti
  py te1_randomizer.py --auto     AVTO: zapustit igru i tasovat PERED KAZDOJ
                                  zagruzkoj karty (mezhdu dnyami NE tasuet)
  py te1_randomizer.py --restore  vernut' original

KAK RABOTAET AVTO-REZHIM
------------------------
V bajtkode igry (frejm `game`, gruppa #425, uslovie "nachalo frejma") est':

    INI_ITEMS: otkryt' fail "Data\items_" + <yazyk> + ".dat"

Eto edinstvennoe mesto, gde chitaetsya items_*.dat. Ono vypolnyaetsya
ODIN RAZ pri vhode vo frejm `game`, to est' pri kazdoj zagruzke karty.
Mezhdu dnyami fail NE perechityvaetsya.

Poetomu skript derzhit v items_*.dat svezhuyu sluchajnuyu versiyu:
  zagruzil kartu  -> igra prochitala tekushchuyu versiyu  -> novye statty
  idut dni        -> fail ne chitaetsya                   -> statty te zhe
  vyshel, zashyol -> frejm nachalsya snova                 -> snova tasovanie

Razmer faila derzhitsya POSTOYANNYM (dobivaetsya pustymi strokami),
poetomu val.dat trogat' ne nuzhno i validator ne rugaetsya.
Zapis' atomarnaya (vremennyj fail + rename), tak chto igra ne mozhet
popast' na napologvinu zapisanij fail.
"""
from __future__ import annotations

import collections
import hashlib
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "2.0"

GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\The Escapists"
FALLBACK_DIRS = [
    r"C:\Program Files\Steam\steamapps\common\The Escapists",
    r"D:\Steam\steamapps\common\The Escapists",
    r"D:\SteamLibrary\steamapps\common\The Escapists",
    r"E:\SteamLibrary\steamapps\common\The Escapists",
]

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

# Что НЕ трогаем никогда: Name (имя), Craft (текст рецепта), Found, Desk,
# NPC_carry, Outfit, Info, CamDis. Трогаем только игровые статы из STAT_POOLS
# плюс Illegal (нелегальность) на уровне хаоса >= 2.


# ------------------------------------------------------------------ консоль
def _fix_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_console()


def say(*a, end="\n"):
    print(*a, end=end, flush=True)


def ask(prompt, default=None):
    try:
        s = input(prompt + (f" [{default}]: " if default is not None else ": ")).strip()
    except (EOFError, OSError):
        s = ""                                # ввод закрыт - берём значение по умолчанию
    return s or (default if default is not None else "")


def pause():
    """Ждём Enter, но не падаем, если ввод уже закрыт."""
    try:
        input("\n[Enter] - выход...")
    except (EOFError, OSError):
        pass


# ------------------------------------------------------------------ кодировки
def detect_plain(raw: bytes):
    if not raw:
        return False, None
    if raw.startswith(b"\xff\xfe"):
        return True, "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return True, "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return True, "utf-8-sig"
    head = raw[:2048]
    if head.count(b"\x00") > len(head) * 0.15:
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
    if sum(1 for c in head if c >= 0x80) > len(head) * 0.10:
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
    return hashlib.md5(("l0l_%d" % size).encode()).hexdigest()


def rebuild_val(data_dir: Path):
    import re
    vpath = data_dir / "val.dat"
    if not vpath.exists():
        return 0
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
    vpath.write_bytes((("\ufeff" if bom else "") + txt).encode("utf-16-le"))
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
        m = re.match(r"^\s*([A-Za-z_]+)\s*=(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)   # значение дословно, с пробелами
    return items, order


def build_text(header: str, items: dict, order: list, newline: str) -> str:
    """Собирает INI обратно. Блоки разделены пустой строкой, как в оригинале;
    перед первым блоком пустой строки нет и хвостового перевода строки тоже,
    чтобы пересборка без правок давала байт-в-байт тот же файл."""
    blocks = []
    for iid in order:
        lines = [f"[{iid}]"]
        for k, v in items[iid].items():
            lines.append(f"{k}={v}")
        blocks.append(newline.join(lines))
    body = (newline + newline).join(blocks)
    if header.strip():
        return header.rstrip("\r\n") + newline + newline + body
    return body


# ------------------------------------------------------------------ генерация
def _block_len(iid, props, enc, nl):
    """Длина блока [id] в байтах. Блоки в файле разделены фиксированными
    разделителями, поэтому по дельте блока точно видно дельту всего файла."""
    s = f"[{iid}]" + "".join(f"{nl}{k}={v}" for k, v in props.items())
    return len(s.encode(enc, "replace"))


# Поля, значения которых переставляются между предметами (не выдумываются
# заново, а берутся из уже имеющихся в файле - так нельзя получить
# несуществующее значение). Craft не трогаем: это текст рецепта.
SHUFFLE_FIELDS = ("Found", "Outfit", "Desk", "NPC_carry", "NPC_Carry",
                  "Carry", "CamDis")

# Из алфавита исключены = [ ] ; и переводы строк: они ломают разбор INI.
NAME_CHARS = ("абвгдежзийклмнопрстуфхцчшщъыьэюя"
              "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
              "abcdefghijklmnopqrstuvwxyz0123456789%.,!?@#$&*+-~^_")


def random_text(target_bytes: int, enc: str, rnd: random.Random):
    """Случайная строка РОВНО в target_bytes байт в кодировке enc.

    Размер обязан совпасть точно, иначе съедет размер всего файла и
    валидатор val.dat не пустит игру. В utf-16 любой символ стоит 2 байта,
    в utf-8/cp1251 кириллица дороже латиницы - поэтому символы набираются
    по одному с контролем оставшегося бюджета.
    """
    if target_bytes <= 0:
        return None
    out, left = [], target_bytes
    for _ in range(target_bytes + 8):
        if left <= 0:
            break
        c = rnd.choice(NAME_CHARS)
        n = len(c.encode(enc, "replace"))
        if n > left:
            c, n = ".", 1                     # точка - 1 байт в utf-8/cp1251
            if len(c.encode(enc, "replace")) > left:
                continue
            n = len(c.encode(enc, "replace"))
        out.append(c)
        left -= n
    if left != 0:
        return None
    return "".join(out)


def make_version(orig_text: str, seed, chaos: int, enc: str, target_size: int,
                 scramble: bool = False):
    """Случайная версия файла, подогнанная РОВНО под target_size байт.

    Размер обязан остаться прежним: валидатор val.dat проверяет именно его.
    Свободных байт в файле нет, поэтому место под новые поля (без них
    предмет не получит новую способность) берётся из Info: его текст всё
    равно заменяется на случайный, так что укоротить его не жалко.
    Возвращает (bytes, изменено_предметов, лог) или (None, 0, []).
    """
    nl = "\r\n" if "\r\n" in orig_text else "\n"
    nlb = nl.encode(enc)
    step = 2 if enc in ("utf-16-le", "utf-16-be") else 1
    header = orig_text.split("[", 1)[0]
    items, order = parse_items(orig_text)
    rnd = random.Random(seed)
    keys = list(STAT_POOLS)
    usable = [i for i in order
              if (items[i].get("Name") or "").strip().lower() not in ("", "empty", "none")]

    # --- названия в случайный набор знаков, ровно в ту же байтовую длину
    if scramble:
        for iid in usable:
            old = items[iid].get("Name")
            if old:
                new = random_text(len(old.encode(enc, "replace")), enc, rnd)
                if new:
                    items[iid]["Name"] = new

    def size_of():
        return len(build_text(header, items, order, nl).encode(enc, "replace"))

    def assign(nfields):
        """Раздать предметы по nfields случайных статов, включая новые поля."""
        touched, log = 0, []
        for iid in usable:
            it = items[iid]
            before = {k: it.get(k) for k in keys}
            for k in keys:
                it.pop(k, None)
            for k in rnd.sample(keys, min(nfields, len(keys))):
                v = rnd.choice(STAT_POOLS[k])
                if v:
                    it[k] = str(v)
            if rnd.random() < 0.5:
                it["Illegal"] = "1" if rnd.random() < 0.7 else "0"
            diff = [f"{k}={it.get(k) or 0}" for k in keys if it.get(k) != before[k]]
            if diff:
                touched += 1
                if len(log) < 18:
                    log.append(f"    [{iid:>3}] {(it.get('Name') or '?').strip()[:26]:26} "
                               + ", ".join(diff[:6]))
        return touched, log

    def shuffle_fields():
        for key in SHUFFLE_FIELDS:
            holders = [i for i in order if key in items[i]]
            if len(holders) < 2:
                continue
            vals = [items[i][key] for i in holders]
            rnd.shuffle(vals)
            for i, v in zip(holders, vals):
                items[i][key] = v

    def squeeze_info(need: int) -> int:
        """Укоротить Info на need байт; возвращает, сколько не хватило."""
        for iid in order:
            if need <= 0:
                break
            it = items[iid]
            if "Info" not in it:
                continue
            cur = len(it["Info"].encode(enc, "replace"))
            take = min(cur, need)
            take -= take % step
            if take <= 0:
                continue
            it["Info"] = random_text(cur - take, enc, rnd) or ""
            need -= take
        return max(0, need)

    # --- подбираем число статов так, чтобы влезло даже при пустых Info
    orig_items = {i: dict(items[i]) for i in order}
    touched, log = 0, []
    for nfields in range(2 + chaos, 0, -1):
        for i in order:
            items[i] = dict(orig_items[i])
        touched, log = assign(nfields)
        shuffle_fields()
        if size_of() - sum(len(items[i].get("Info", "").encode(enc, "replace"))
                           for i in order) <= target_size:
            break
    else:
        return None, 0, []

    # --- теперь доводим размер до точного: Info в случайный текст нужной длины
    for iid in order:
        if "Info" in items[iid]:
            old = items[iid]["Info"]
            new = random_text(len(old.encode(enc, "replace")), enc, rnd)
            if new:
                items[iid]["Info"] = new

    data = build_text(header, items, order, nl).encode(enc, "replace")
    if len(data) > target_size:
        if squeeze_info(len(data) - target_size):
            return None, 0, []
        data = build_text(header, items, order, nl).encode(enc, "replace")
    if len(data) > target_size:
        return None, 0, []
    reps, rem = divmod(target_size - len(data), len(nlb))
    data = data + nlb * reps + b" " * rem
    return (data, touched, log) if len(data) == target_size else (None, 0, [])


def atomic_write(path: Path, data: bytes):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)          # атомарно: игра не увидит полфайла


# ------------------------------------------------------------------ пути
def find_game_dir(arg=None):
    for c in ([arg] if arg else []) + [GAME_DIR] + FALLBACK_DIRS + [os.getcwd()]:
        if c and os.path.isdir(os.path.join(c, "Data")):
            return Path(c)
    return None


def say_no_access(path):
    say("")
    say("  ! НЕТ ПРАВ НА ЗАПИСЬ в папку игры:")
    say(f"      {path}")
    say("")
    say("    Игра стоит в Program Files, а Windows запрещает писать туда")
    say("    без прав администратора. Закрой это окно и запусти так:")
    say("")
    say("      1. Пуск -> набери  cmd")
    say("      2. правой кнопкой на \"Командная строка\" -> Запуск от имени администратора")
    say("      3. в открывшемся окне:")
    say('           cd /d "' + str(path.parent.parent) + '"')
    say("           py te1_randomizer.py --auto")
    say("")
    say("    Либо правой кнопкой на .bat-файле -> Запуск от имени администратора.")
    say("")


def writable(data_dir: Path) -> bool:
    """Ранняя проба: можно ли вообще писать в папку игры.

    Без неё случай «игра в Program Files, консоль без прав администратора»
    выглядит как вечно занятой файл, и совет получается неверный.
    """
    probe = data_dir / ".te1_write_test"
    try:
        probe.write_bytes(b"x")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def get_original(data_dir: Path, lang: str):
    """Оригинальный текст items_<lang>.dat (из .bak, если он есть).

    Обязательно проверяем, что decode->encode даёт те же байты: например,
    в cp1251 байт 0x98 не определён и через errors='replace' молча
    превратился бы в '?', испортив файл при сохранении того же размера.
    """
    f = data_dir / f"items_{lang}.dat"
    bak = data_dir / f"items_{lang}.dat.bak"
    src = bak if bak.exists() else f
    try:
        raw = src.read_bytes()
    except OSError as e:
        say(f"  ! не смог прочитать {src.name}: {e}")
        return None, None, 0
    plain, enc = detect_plain(raw)
    if not plain:
        say(f"  ! items_{lang}.dat зашифрован - этот скрипт такие не правит")
        return None, None, 0

    text = raw.decode(enc, "replace")
    if text.encode(enc, "replace") != raw:
        say(f"  ! items_{lang}.dat: не удалось разобрать без потерь ({enc}) -")
        say("    пропускаю, иначе файл бы повредился. Пришли мне этот файл.")
        return None, None, 0

    if not bak.exists():
        try:
            shutil.copy2(f, bak)
        except OSError:
            say_no_access(bak)
            return None, None, 0
        say(f"  бэкап создан: {bak.name}")
    return text, enc, src.stat().st_size


def pick_languages(data_dir: Path):
    """Все языки, для которых есть items_<язык>.dat.

    Игра подставляет язык из глобальной переменной gv[6], которая задаётся
    в рантайме, - по exe нельзя сказать, какой именно файл она прочитает.
    Поэтому правим сразу все: какой бы ни читался, он будет рандомизирован.
    """
    langs = []
    for f in sorted(data_dir.glob("items_*.dat")):
        parts = f.stem.split("_")
        if len(parts) == 2 and len(parts[1]) == 3:
            langs.append(parts[1])
    return langs


# ------------------------------------------------------------------ режимы
def mode_once(data_dir: Path, langs, chaos: int, seed):
    say("\n=== Разовая рандомизация ===")
    if not writable(data_dir):
        say_no_access(data_dir / "items_*.dat")
        return False

    prepared = []
    for lang in langs:
        text, enc, size = get_original(data_dir, lang)
        if text is None:
            continue
        data, touched, log = make_version(text, seed, chaos, enc, size)
        if data is None:
            say(f"  ! items_{lang}.dat: версия не влезла в размер - снизь хаос")
            continue
        prepared.append((lang, data, size, touched, log))
        say(f"  items_{lang}.dat: {len(parse_items(text)[1])} предметов, "
            f"изменено {touched}, {size} байт, {enc}")

    if not prepared:
        say("  ! нечего применять")
        return False

    say(f"\n  примеры (сид {seed}):")
    say("\n".join(prepared[0][4][:14]))
    if ask("\nПрименить? (y/n)", "n").lower() != "y":
        say("  отменено")
        return True

    ok = True
    for lang, data, size, touched, _ in prepared:
        try:
            atomic_write(data_dir / f"items_{lang}.dat", data)
            say(f"  записан items_{lang}.dat ({touched} предметов, размер {size} не изменился)")
        except OSError:
            say_no_access(data_dir / f"items_{lang}.dat")
            ok = False
    say("  val.dat трогать не нужно (валидатор проверяет только размер)")
    say("\n  ВАЖНО: это разовая версия - при следующей загрузке карты")
    say("  предметы будут ТЕ ЖЕ. Для авто-режима: py te1_randomizer.py --auto")
    return ok


def mode_quick(data_dir: Path, langs):
    """Один запуск = одна полная рандомизация. Без вопросов, без ожидания.

    Именно это вызывает randomize.bat: открыл - перетасовалось - закрылось.
    Чтобы в следующий раз получить другой набор, запусти ещё раз.
    """
    say("\n=== БЫСТРАЯ РАНДОМИЗАЦИЯ (всё подряд, включая названия) ===")
    if not writable(data_dir):
        say_no_access(data_dir / "items_*.dat")
        return False

    seed = random.randrange(1, 2 ** 31)
    total, done = 0, 0
    for lang in langs:
        text, enc, size = get_original(data_dir, lang)
        if text is None:
            continue
        data, touched, log = make_version(text, seed, 4, enc, size, scramble=True)
        if data is None:
            say(f"  ! items_{lang}.dat: не удалось уложить в размер - пропущен")
            continue
        try:
            atomic_write(data_dir / f"items_{lang}.dat", data)
        except OSError:
            say_no_access(data_dir / f"items_{lang}.dat")
            continue
        done += 1
        total += touched
        say(f"  items_{lang}.dat: перетасовано {touched} предметов, размер {size} не изменился")
        for line in log[:6]:
            say(line)

    if not done:
        say("  ! ни один файл не записан")
        return False
    say(f"\n  готово: файлов {done}, предметов {total}, сид {seed}")
    say("  в игре зайди на карту заново - статы подхватятся при загрузке")
    say("  ещё раз = новый набор. Вернуть оригинал: restore.bat")
    return True


def mode_auto(data_dir: Path, langs, chaos: int, interval: float, launch: bool):
    say("\n=== АВТО-РЕЖИМ: рандомизация при каждой загрузке карты ===")
    if not writable(data_dir):
        say_no_access(data_dir / "items_*.dat")
        return False

    srcs = []
    for lang in langs:
        text, enc, size = get_original(data_dir, lang)
        if text is None:
            continue
        srcs.append((lang, text, enc, size, data_dir / f"items_{lang}.dat"))
        say(f"  items_{lang}.dat: {len(parse_items(text)[1])} предметов, "
            f"{size} байт, {enc}")
    if not srcs:
        say("  ! ни один items_*.dat не подошёл - смотри сообщения выше")
        return False

    say(f"  файлов в работе: {len(srcs)}, хаос {chaos}, "
        f"обновление раз в {interval:g} сек")
    say("")
    say("  Как это работает:")
    say("    игра читает items_*.dat только при входе во фрейм `game`,")
    say("    то есть при загрузке карты. Между днями файл не читается.")
    say("    Поэтому: зашёл на карту -> новые статы; дни -> те же статы;")
    say("    вышел и зашёл снова -> опять новые.")
    say("")
    say("  Держи это окно открытым, пока играешь.")
    say("  Остановка: Ctrl+C  (оригинал вернётся командой --restore)")

    exe = data_dir.parent / "TheEscapists.exe"
    if launch and exe.exists():
        say(f"\n  Запускаю игру: {exe.name}")
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except Exception as e:
            say(f"  ! не смог запустить: {e}")

    rnd = random.Random()
    count = 0
    last_err = ""
    try:
        while True:
            seed = rnd.randrange(1, 2 ** 31)
            done, touched = 0, 0
            for lang, text, enc, size, target in srcs:
                data, n, _ = make_version(text, seed, chaos, enc, size)
                if data is None:
                    continue
                try:
                    atomic_write(target, data)
                    done += 1
                    touched += n
                except PermissionError:
                    if last_err != "locked":
                        say("\n  (файл занят игрой - подожду)")
                        last_err = "locked"
                except OSError as e:
                    if str(e) != last_err:
                        say(f"\n  ! {e}")
                        last_err = str(e)
            if done:
                count += 1
                last_err = ""
                say(f"\r  [{time.strftime('%H:%M:%S')}] версия #{count} "
                    f"(сид {seed}, файлов {done}, предметов {touched})   ", end="")
            time.sleep(interval)
    except KeyboardInterrupt:
        say("\n\n  остановлено")
        try:
            want = ask("  Вернуть оригинальный items_*.dat? (y/n)", "y").lower() == "y"
        except (EOFError, OSError):
            want = True                      # ввод недоступен - чиним молча
        if want:
            do_restore(data_dir)
    return True


def mode_mark(data_dir: Path, langs):
    """Диагностический режим: меняет имена предметов местами.

    Обмен значениями Name ничего не стоит по размеру (тот же набор байтов,
    просто переставлен), а в игре это видно сразу: если «Подушка» вдруг
    называется как другой предмет - файл читается, значит, и рандомайзер
    работает. Если имена прежние - игра этот файл не читает.
    """
    say("\n=== МЕТКА: обмен именами предметов ===")
    if not writable(data_dir):
        say_no_access(data_dir / "items_*.dat")
        return False
    for lang in langs:
        text, enc, size = get_original(data_dir, lang)
        if text is None:
            continue
        items, order = parse_items(text)
        named = [i for i in order if (items[i].get("Name") or "").strip()]
        if len(named) < 2:
            say(f"  ! items_{lang}.dat: слишком мало имён")
            continue
        pairs = list(zip(named[0::2], named[1::2]))[:6]
        for a, b in pairs:
            items[a]["Name"], items[b]["Name"] = items[b]["Name"], items[a]["Name"]
        nl = "\r\n" if "\r\n" in text else "\n"
        data = build_text(text.split("[", 1)[0], items, order, nl).encode(enc, "replace")
        if len(data) != size:
            say(f"  ! items_{lang}.dat: размер сбился ({len(data)} != {size}) - пропускаю")
            continue
        try:
            atomic_write(data_dir / f"items_{lang}.dat", data)
        except OSError:
            say_no_access(data_dir / f"items_{lang}.dat")
            continue
        say(f"  items_{lang}.dat: обменено {len(pairs)} пар имён, размер {size} не изменился")
        for a, b in pairs:
            say(f"     [{a}] <-> [{b}]")
    say("")
    say("  Теперь зайди в игру и посмотри на названия предметов.")
    say("  Если они перепутаны - файл читается, рандомайзер работает.")
    say("  Если названия обычные - игра этот файл НЕ читает.")
    say("  Вернуть имена: py te1_randomizer.py --restore")
    return True


def mode_diff(data_dir: Path, langs):
    """Показывает, что именно изменилось относительно оригинала (.bak)."""
    say("\n=== ЧТО ИЗМЕНИЛОСЬ ===")
    STAT = list(STAT_POOLS)
    for lang in langs:
        f = data_dir / f"items_{lang}.dat"
        bak = data_dir / f"items_{lang}.dat.bak"
        if not f.exists():
            continue
        if not bak.exists():
            say(f"  items_{lang}.dat: бэкапа нет - сравнивать не с чем")
            continue
        raw, bakraw = f.read_bytes(), bak.read_bytes()
        if raw == bakraw:
            say(f"  items_{lang}.dat: НЕ изменён (совпадает с оригиналом)")
            continue
        _, enc = detect_plain(bakraw)
        enc = enc or "utf-8"
        i0, o0 = parse_items(bakraw.decode(enc, "replace"))
        i1, _ = parse_items(raw.decode(enc, "replace"))
        n_name = n_info = n_stat = n_shuf = 0
        stat_hits, shuf_hits = collections.Counter(), collections.Counter()
        for iid in o0:
            a, b = i0.get(iid, {}), i1.get(iid, {})
            if a.get("Name") != b.get("Name"):
                n_name += 1
            if a.get("Info") != b.get("Info"):
                n_info += 1
            for k in STAT:
                if a.get(k) != b.get(k):
                    n_stat += 1
                    stat_hits[k] += 1
            for k in SHUFFLE_FIELDS:
                if a.get(k) != b.get(k):
                    n_shuf += 1
                    shuf_hits[k] += 1
        say(f"\n  items_{lang}.dat ({len(o0)} предметов):")
        say(f"    переименовано предметов : {n_name}")
        say(f"    изменено описаний Info  : {n_info}")
        say(f"    изменено значений статов: {n_stat}")
        for k, c in stat_hits.most_common():
            say(f"        {k:12} {c}")
        say(f"    переставлено Found/Outfit/Desk/... : {n_shuf}")
        for k, c in shuf_hits.most_common():
            say(f"        {k:12} {c}")
        ex = [i for i in o0 if i0[i].get("Name") != i1.get(i, {}).get("Name")][:5]
        if ex:
            say("    примеры:")
            for i in ex:
                say(f"      [{i}] {(i0[i].get('Name') or '?').strip()[:26]:26} "
                    f"-> {(i1[i].get('Name') or '?').strip()[:20]}")
                d = [f"{k}:{i0[i].get(k)}->{i1[i].get(k)}"
                     for k in STAT + list(SHUFFLE_FIELDS)
                     if i0[i].get(k) != i1.get(i, {}).get(k)]
                if d:
                    say(f"           статы: {', '.join(d[:8])}")


def mode_diag(data_dir: Path):
    """Печатает состояние папки Data - чтобы понять, почему ничего не меняется."""
    say("\n=== Диагностика ===")
    say(f"  папка: {data_dir}")
    say(f"  доступна для записи: {writable(data_dir)}")
    exe = data_dir.parent / "TheEscapists.exe"
    say(f"  TheEscapists.exe рядом: {exe.exists()}")
    say("")
    found = sorted(data_dir.glob("items_*.dat"))
    if not found:
        say("  ! в этой папке нет items_*.dat - значит, папка игры найдена неверно")
        return
    for f in found:
        raw = f.read_bytes()
        plain, enc = detect_plain(raw)
        bak = f.with_name(f.name + ".bak")
        if plain:
            n = len(parse_items(raw.decode(enc, "replace"))[1])
            kind = f"открытый текст, {enc}, предметов {n}"
        else:
            kind = "ЗАШИФРОВАН (этот скрипт такие не правит)"
        same = ""
        if bak.exists():
            same = " | СЕЙЧАС ИЗМЕНЁН" if bak.read_bytes() != raw else " | = оригиналу"
        say(f"  {f.name:22} {len(raw):7} байт | {kind}")
        say(f"  {'':22} бэкап: {'есть' if bak.exists() else 'нет'}{same}")
    say("")
    v = data_dir / "val.dat"
    if v.exists():
        say(f"  val.dat: {v.stat().st_size} байт")
        for f in found:
            h = md5_size(f.stat().st_size)
            ok = h in v.read_bytes().decode("utf-16-le", "replace")
            say(f"    хеш размера {f.name}: {'совпадает' if ok else 'НЕ СОВПАДАЕТ'}")
    else:
        say("  val.dat: нет")


def do_restore(data_dir: Path) -> bool:
    say("\n=== Откат ===")
    n, failed = 0, 0
    for bak in sorted(data_dir.glob("*.dat.bak")):
        target = data_dir / bak.name[:-4]
        try:
            shutil.copy2(bak, target)
        except OSError as e:
            say(f"  ! не смог восстановить {target.name}: {e}")
            say_no_access(target)
            failed += 1
            continue
        say(f"  восстановлен {target.name}")
        n += 1
    if n == 0:
        say("  бэкапов (.bak) не найдено")
        return failed == 0
    rebuild_val(data_dir)
    say(f"  готово, восстановлено: {n}")
    return failed == 0


# ------------------------------------------------------------------ main
def choose_langs(data_dir: Path, langs, argv):
    """Какие языки править. По умолчанию только русский: игра читает один
    файл, а переписывать все семь - лишний риск испортить чужие переводы."""
    if "--all-langs" in argv:
        return langs
    default = "rus" if "rus" in langs else langs[0]
    s = ask(f"Язык(и) для правки, через пробел (или 'all') [{default}]")
    if not s.strip():
        return [default]
    if s.strip().lower() == "all":
        return langs
    picked, bad = [], []
    for tok in s.replace(",", " ").split():
        tok = tok.strip().lower()
        (picked if tok in langs else bad).append(tok)
    if bad:
        say(f"  ! в Data нет таких языков: {', '.join(bad)}")
        say(f"    доступны: {', '.join(langs)}")
    picked = [l for l in langs if l in picked]      # порядок как в Data
    return picked or [default]


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    say("\n" + "=" * 60)
    say("  THE ESCAPISTS 1 - РАНДОМАЙЗЕР ПРЕДМЕТОВ  v" + VERSION)
    say("=" * 60)

    gd = find_game_dir()
    if not gd:
        p = ask("\nПапка игры не найдена. Путь (где лежит Data\\)")
        gd = find_game_dir(p)
    if not gd:
        say("  ! не нашёл папку с Data\\ - выход")
        return 1
    say(f"\n  Папка игры: {gd}")
    data = gd / "Data"

    if "--restore" in argv:
        ok = do_restore(data)
        if not ok:
            pause()   # при ошибке окно не закрываем
        return 0 if ok else 1

    langs = pick_languages(data)
    if not langs:
        say("  ! в Data нет items_*.dat")
        return 1
    say(f"  Языки в Data: {', '.join(langs)}")

    if "--quick" in argv:
        # без вопросов: русский, если он есть, иначе все найденные языки
        quick = ["rus"] if "rus" in langs else langs
        say(f"  Правим: {', '.join('items_' + l + '.dat' for l in quick)}")
        ok = mode_quick(data, quick)
        if not ok:
            pause()   # при ошибке окно не закрываем
        return 0 if ok else 1

    if "--diff" in argv:
        mode_diff(data, ["rus"] if "rus" in langs else langs)
        pause()
        return 0

    if "--diag" in argv:
        mode_diag(data)
        pause()
        return 0

    if "--mark" in argv:
        langs = choose_langs(data, langs, argv)
        if not langs:
            return 1
        ok = mode_mark(data, langs)
        pause()
        return 0 if ok else 1

    langs = choose_langs(data, langs, argv)
    if not langs:
        return 1
    say(f"  Правим: {', '.join('items_' + l + '.dat' for l in langs)}")

    auto = "--auto" in argv
    chaos = ask("Уровень хаоса 1-4 (1=мягко, 4=полный)", "2")
    try:
        chaos = max(1, min(4, int(chaos)))
    except ValueError:
        chaos = 2

    if auto:
        iv = ask("Обновлять файл раз в N секунд", "2")
        try:
            iv = max(0.5, float(iv))
        except ValueError:
            iv = 2.0
        lc = ask("Запустить игру сейчас? (y/n)", "y").lower() == "y"
        return 0 if mode_auto(data, langs, chaos, iv, lc) else 1

    s = ask("Сид (число = повторяемо, пусто = случайный)")
    seed = int(s) if s.lstrip("-").isdigit() else random.randrange(1, 2 ** 31)
    ok = mode_once(data, langs, chaos, seed)
    if ok:
        say("\n  Хочешь, чтобы рандомизация была при КАЖДОЙ загрузке карты?")
        say("  Тогда: py te1_randomizer.py --auto")
    pause()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nпрервано")
        sys.exit(1)
