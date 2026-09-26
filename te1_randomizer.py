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
    s = input(prompt + (f" [{default}]: " if default is not None else ": ")).strip()
    return s or (default if default is not None else "")


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


def make_version(orig_text: str, seed, chaos: int, enc: str, target_size: int):
    """Случайная версия файла, подогнанная РОВНО под target_size байт.

    Размер обязан остаться прежним: тогда val.dat трогать не нужно и
    валидатор игры не ругается. Предметы берутся в случайном порядке и
    правятся один за другим, пока хватает байтового бюджета; удаление
    поля (стат = 0) бюджет освобождает.
    Возвращает (bytes, изменено_предметов, лог) или (None, 0, []).
    """
    nl = "\r\n" if "\r\n" in orig_text else "\n"
    nlb = nl.encode(enc)
    header = orig_text.split("[", 1)[0]
    items, order = parse_items(orig_text)
    base = build_text(header, items, order, nl)
    used = len(base.encode(enc, "replace"))
    if used > target_size:
        return None, 0, []

    rnd = random.Random(seed)
    keys = list(STAT_POOLS)
    log, touched = [], 0
    changed = set()

    def note(iid, it, bk):
        nonlocal touched
        diff = [f"{k}={it.get(k) or 0}" for k in keys if it.get(k) != bk[k]]
        if diff:
            touched += 1
            changed.add(iid)
            if len(log) < 18:
                log.append(f"    [{iid:>3}] {(it.get('Name') or '?').strip()[:30]:30} "
                           + ", ".join(diff))
        return bool(diff)

    def usable(iid):
        return (items[iid].get("Name") or "").strip().lower() not in ("", "empty", "none")

    # --- фаза 1: перетасовать значения УЖЕ СУЩЕСТВУЮЩИХ полей.
    # Новых строк не появляется, поэтому размер почти не растёт и правки
    # достаются практически каждому предмету.
    ph1 = order[:]
    rnd.shuffle(ph1)
    for iid in ph1:
        it = items[iid]
        if not usable(iid):
            continue
        present = [k for k in keys if k in it]
        if not present:
            continue
        before = dict(it)
        bk = {k: it.get(k) for k in keys}
        for k in rnd.sample(present, max(1, len(present) - rnd.randint(0, 1))):
            v = rnd.choice(STAT_POOLS[k])
            if v == 0:
                it.pop(k, None)            # поле исчезает -> освобождает байты
            else:
                it[k] = str(v)
        delta = _block_len(iid, it, enc, nl) - _block_len(iid, before, enc, nl)
        if used + delta > target_size:
            items[iid] = before
            continue
        used += delta
        note(iid, it, bk)

    # --- фаза 2: на оставшийся бюджет раздаём предметы новыми полями
    ph2 = [i for i in order if i not in changed]
    rnd.shuffle(ph2)
    for iid in ph2:
        it = items[iid]
        if not usable(iid):
            continue
        before = dict(it)
        bk = {k: it.get(k) for k in keys}
        n = min(rnd.randint(1, 2 + chaos), len(keys))
        for k in rnd.sample(keys, n):
            v = rnd.choice(STAT_POOLS[k])
            if v == 0:
                it.pop(k, None)
            else:
                it[k] = str(v)
        if chaos >= 2 and rnd.random() < 0.4:
            it["Illegal"] = "1" if rnd.random() < 0.5 else "0"
        delta = _block_len(iid, it, enc, nl) - _block_len(iid, before, enc, nl)
        if used + delta > target_size:
            items[iid] = before
            continue
        used += delta
        note(iid, it, bk)

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


def do_restore(data_dir: Path):
    say("\n=== Откат ===")
    n = 0
    for bak in sorted(data_dir.glob("*.dat.bak")):
        target = data_dir / bak.name[:-4]
        try:
            shutil.copy2(bak, target)
        except OSError as e:
            say(f"  ! не смог восстановить {target.name}: {e}")
            say_no_access(target)
            continue
        say(f"  восстановлен {target.name}")
        n += 1
    if n == 0:
        say("  бэкапов (.bak) не найдено")
        return
    rebuild_val(data_dir)
    say(f"  готово, восстановлено: {n}")


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
        do_restore(data)
        input("\n[Enter] - выход...")
        return 0

    langs = pick_languages(data)
    if not langs:
        say("  ! в Data нет items_*.dat")
        return 1
    say(f"  Языки в Data: {', '.join(langs)}")

    if "--diag" in argv:
        mode_diag(data)
        input("\n[Enter] - выход...")
        return 0

    if "--mark" in argv:
        langs = choose_langs(data, langs, argv)
        if not langs:
            return 1
        ok = mode_mark(data, langs)
        input("\n[Enter] - выход...")
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
    input("\n[Enter] - выход...")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nпрервано")
        sys.exit(1)
