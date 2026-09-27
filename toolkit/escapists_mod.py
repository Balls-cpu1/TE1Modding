#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
escapists_mod.py — инструмент для моддинга контента The Escapists 1 (PC / Clickteam Fusion).

Что умеет:
  detect     — определить, зашифрован ли .dat-файл игры
  dec        — расшифровать файл (Blowfish ECB, ключ "mothking", little-endian)
  enc        — зашифровать обратно (можно сохранить исходный размер, чтобы val.dat остался валидным)
  val        — пересобрать val.dat под изменённые data_*/items_*/speech_*.dat
  items      — проанализировать items_*.dat: список, свободные ID, записи "empty"
  set-item   — создать/изменить/удалить запись предмета в items_*.dat
  selftest   — проверка работоспособности (шифр + хеши)

Зависимости: pip install blowfish   (либо pip install pycryptodome — есть fallback)
Примеры:
  python escapists_mod.py detect items_eng.dat
  python escapists_mod.py dec items_eng.dat            # -> items_eng_decr.dat
  python escapists_mod.py enc items_eng_decr.dat       # -> items_eng_decr_encr.dat
  python escapists_mod.py enc items_eng_decr.dat -o items_eng.dat --same-size items_eng.dat
  python escapists_mod.py items items_eng_decr.dat --free
  python escapists_mod.py set-item items_eng_decr.dat --id 55 --from-id 24 \
        --set "Name=Master Key" --set "Illegal=1" --set "Weapon=5" --set "Craft=50_Crowbar, Duct Tape"
  python escapists_mod.py val ./custom_files val.dat    # создаст ./custom_files/val.dat
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

KEY = b"mothking"
LANGS = ["eng", "fre", "ger", "spa", "rus", "pol", "ita"]
KINDS = ["data", "items", "speech"]


# ----------------------------------------------------------------------------- шифр
class EscapistsCipher:
    """Blowfish ECB с little-endian порядком слов — как в The Escapists."""

    def __init__(self, key: bytes = KEY):
        self.backend = None
        force_pc = os.environ.get("ESCAPISTS_FORCE_PYCRYPTODOME") == "1"
        if not force_pc:
            try:
                import blowfish  # type: ignore
                self._impl = blowfish.Cipher(key, byte_order="little")
                self.backend = "python-blowfish"
                return
            except ImportError:
                pass
        try:
            from Crypto.Cipher import Blowfish  # type: ignore
        except ImportError:
            raise SystemExit(
                "Нужен один из пакетов:\n"
                "  pip install blowfish      (рекомендуется, проверено на игре)\n"
                "  pip install pycryptodome  (fallback)"
            )
        self._impl = Blowfish.new(key, Blowfish.MODE_ECB)
        self.backend = "pycryptodome"

    @staticmethod
    def _swap4(b: bytes) -> bytes:
        if len(b) % 4:
            raise ValueError("размер должен быть кратен 4")
        return b"".join(b[i:i + 4][::-1] for i in range(0, len(b), 4))

    def encrypt(self, data: bytes) -> bytes:
        if len(data) % 8:
            raise ValueError("длина данных должна быть кратна 8 (Blowfish-блок)")
        if self.backend == "python-blowfish":
            return b"".join(self._impl.encrypt_ecb(data))
        return self._swap4(self._impl.encrypt(self._swap4(data)))

    def decrypt(self, data: bytes) -> bytes:
        if len(data) % 8:
            raise ValueError("длина шифротекста должна быть кратна 8")
        if self.backend == "python-blowfish":
            return b"".join(self._impl.decrypt_ecb(data))
        return self._swap4(self._impl.decrypt(self._swap4(data)))


# ----------------------------------------------------------------------------- утилиты
def read_bytes(path) -> bytes:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"Файл не найден: {p}")
    return p.read_bytes()


def write_bytes(path, data: bytes, force: bool) -> Path:
    p = Path(path)
    if p.exists() and not force:
        raise SystemExit(f"{p} уже существует — добавь --force, чтобы перезаписать")
    p.write_bytes(data)
    return p


def looks_plaintext(data: bytes) -> bool:
    head = data[:128]
    if not head:
        return False
    textish = sum(1 for c in head if 32 <= c < 127 or c in (9, 10, 13))
    return textish / len(head) > 0.85


def detect_text_codec(data: bytes) -> str:
    """Подбирает кодировку так, чтобы при записи файл не поменялся лишний раз
    (в частности, не появился BOM там, где его не было)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for codec in ("utf-8", "cp1252"):
        try:
            data.decode(codec)
            return codec
        except UnicodeDecodeError:
            continue
    return "latin-1"


def file_hash(path) -> str:
    """Ровно тот же хеш, что проверяет игра: md5('l0l_' + размер_файла)."""
    size = Path(path).stat().st_size
    return hashlib.md5(("l0l_" + str(size)).encode("utf8")).hexdigest()


# ----------------------------------------------------------------------------- команды
def cmd_detect(args):
    data = read_bytes(args.file)
    plain = looks_plaintext(data)
    print(f"файл:      {args.file}")
    print(f"размер:    {len(data)} байт (кратно 8: {'да' if len(data) % 8 == 0 else 'нет'})")
    print(f"состояние: {'ОТКРЫТЫЙ ТЕКСТ' if plain else 'ЗАШИФРОВАН (Blowfish)'}")
    if plain:
        text = data.decode(detect_text_codec(data), errors="replace")
        print("первые строки:")
        for line in text.splitlines()[:5]:
            print("   ", line)
    else:
        cipher = EscapistsCipher(args.key.encode())
        try:
            text = cipher.decrypt(data[:1024]).rstrip(b"\0").decode("utf-8", "replace")
            print("проверка расшифровки (первые строки):")
            for line in text.splitlines()[:5]:
                print("   ", line)
        except Exception as exc:  # noqa: BLE001
            print("не удалось расшифровать с этим ключом:", exc)


def _decrypt_bytes(data: bytes, keep_null: bool) -> bytes:
    if len(data) % 8:
        raise SystemExit("Длина файла не кратна 8 — это не Blowfish-шифротекст игры.")
    out = EscapistsCipher().decrypt(data)
    return out if keep_null else out.rstrip(b"\0")


def cmd_dec(args):
    data = _decrypt_bytes(read_bytes(args.file), args.keep_null)
    out = args.output or str(Path(args.file).with_name(Path(args.file).stem + "_decr" + Path(args.file).suffix))
    print(f"расшифровано -> {write_bytes(out, data, args.force)} ({len(data)} байт)")


def cmd_enc(args):
    plain = read_bytes(args.file)
    pad = (8 - len(plain) % 8) % 8
    if args.same_size:
        target = Path(args.same_size).stat().st_size
        if len(plain) > target:
            raise SystemExit(
                f"Файл длиннее оригинала ({len(plain)} > {target}): сохранить размер невозможно.\n"
                "Тогда вариант два: обычное шифрование + пересборка val.dat (команда val)."
            )
        plain = plain + b"\n" * (target - len(plain))
        pad = 0
        print(f"дополнено \\n до исходного размера {target} байт — val.dat останется валидным")
    plain = plain + b"\0" * pad
    out = args.output or str(Path(args.file).with_name(Path(args.file).stem + "_encr" + Path(args.file).suffix))
    print(f"зашифровано -> {write_bytes(out, EscapistsCipher().encrypt(plain), args.force)} ({len(plain)} байт)")


def cmd_val(args):
    directory = Path(args.directory)
    if not directory.is_dir():
        raise SystemExit(f"Не папка: {directory}")

    raw = Path(args.val_base).read_bytes()
    text = raw.decode("utf-16")

    for lang in LANGS:
        key = lang[0]
        line_re = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(\S+)(\s*)$", re.MULTILINE)
        m = line_re.search(text)
        if not m:
            print(f"  [{lang}] ключ '{key}' не найден в val.dat — пропуск")
            continue
        parts = m.group(2).split("_")
        while len(parts) < 3:
            parts.append(parts[-1] if parts else "")
        changed = []
        for kind in KINDS:
            candidate = directory / f"{kind}_{lang}.dat"
            if candidate.is_file():
                parts[KINDS.index(kind)] = file_hash(candidate)
                changed.append(candidate.name)
        if changed:
            text = text[: m.start()] + m.group(1) + "_".join(parts) + m.group(3) + text[m.end():]
            print(f"  [{lang}] обновлено: {', '.join(changed)}")

    out = directory / "val.dat"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} уже существует — добавь --force")
    out.write_bytes(text.encode("utf-16"))
    print(f"Готово: {out}")


def cmd_val_decode(args):
    """Обратная операция: превращает хеши val.dat в таблицу ожидаемых размеров
    и сопоставляет их с файлами из --dir."""
    raw = read_bytes(args.file)
    try:
        text = raw.decode("utf-16")
    except UnicodeError:
        text = raw.decode(detect_text_codec(raw))
    text = text.replace("\r\n", "\n")
    keys = dict(re.findall(r"^(\w+)\s*=\s*(\S+)\s*$", text, re.M))
    if not keys:
        raise SystemExit("Не вижу строк вида 'e=хеш_хеш_хеш' — это точно val.dat?")

    directory = Path(args.dir)
    candidates = {}
    if directory.is_dir():
        for f in sorted(directory.iterdir()):
            if f.is_file():
                candidates[file_hash(f)] = (f.name, f.stat().st_size)

    components = []
    for key, value in keys.items():
        for i, comp in enumerate(value.split("_")):
            components.append((key, KINDS[i] if i < 3 else f"#{i}", comp))

    # быстрый путь: совпадение с реальными файлами
    resolved = {}
    unresolved = []
    for key, kind, comp in components:
        if comp in candidates:
            resolved[(key, kind)] = candidates[comp]
        else:
            unresolved.append((key, kind, comp))

    # медленный путь: перебор размеров
    if unresolved:
        targets = {comp: (key, kind) for key, kind, comp in unresolved}
        for size in range(args.max + 1):
            h = file_hash_of_size(size)
            if h in targets:
                key, kind = targets.pop(h)
                resolved[(key, kind)] = (f"<нет файла>", size)
                if not targets:
                    break

    kind_names = {"data": "data", "items": "items", "speech": "speech"}
    langs = {l[0]: l for l in LANGS}
    print(f"{'яз':4} | {'data':>22} | {'items':>22} | {'speech':>22}")
    print("-" * 84)
    for key in keys:
        lang = langs.get(key, "?")
        row = []
        for kind in KINDS:
            entry = resolved.get((key, kind))
            row.append(f"{entry[1]} ({entry[0]})" if entry else "?")
        print(f"{lang:4} | {row[0]:>22} | {row[1]:>22} | {row[2]:>22}")
    print("\nформат: размер_байт (файл с таким размером в папке или '<нет файла>')")
    print("если для языка указан файл — значит игра проверяет именно его (размер обязан совпадать)")


def file_hash_of_size(size: int) -> str:
    return hashlib.md5(("l0l_" + str(size)).encode("utf8")).hexdigest()


def parse_items(text: str):
    """→ список (id:int, key:str, value:str, raw_line:str) и порядок блоков."""
    entries = []          # [(id, dict)]
    order = []
    current = None
    for line in text.splitlines():
        m = re.match(r"^\s*\[(\d+)\]\s*$", line)
        if m:
            current = {}
            entries.append((int(m.group(1)), current))
            order.append(int(m.group(1)))
            continue
        m = re.match(r"^\s*([A-Za-z_]+)\s*=\s*(.*)$", line)
        if m and current is not None:
            current[m.group(1)] = m.group(2)
    return entries, order


def cmd_items(args):
    data = read_bytes(args.file)
    if not looks_plaintext(data):
        raise SystemExit("Файл зашифрован. Сначала: python escapists_mod.py dec " + str(args.file))
    text = data.decode(detect_text_codec(data))
    entries, order = parse_items(text)
    by_id = dict(entries)
    if not entries:
        raise SystemExit("Не похоже на items_*.dat (нет блоков [ID]).")

    if args.free:
        top = max(order)
        gaps = [i for i in range(0, top + 1) if i not in by_id]
        empty = [i for i in order if by_id[i].get("Name", "").strip().lower() in ("empty", "none", "")]
        print(f"всего записей: {len(entries)}, диапазон ID: {min(order)}..{top}")
        print(f"свободные ID (нет записи вообще): {gaps}")
        print(f"ID с именем empty: {empty}")
        print(f"можно добавлять новые ID начиная с: {top + 1}")
        return

    if args.unused:
        acquire = ("Desk", "Buy", "NPC_carry", "NPC_Carry", "Found", "Craft")
        cands = [
            (iid, kv) for iid, kv in entries
            if not any(k in kv for k in acquire)
            and kv.get("Name", "").strip().lower() not in ("", "empty", "none")
        ]
        print(f"кандидаты на переиспользование (нигде не выдаются игроку): {len(cands)}")
        for iid, kv in cands:
            print(f"[{iid}] {kv.get('Name', '?')} " + " ".join(f"{k}={v}" for k, v in kv.items() if k != "Name"))
        return

    selected = [(iid, kv) for iid, kv in entries if iid >= (args.from_id or 0)]
    if args.limit:
        selected = selected[: args.limit]
    for iid, kv in selected:
        name = kv.get("Name", "?")
        extras = " ".join(f"{k}={v}" for k, v in kv.items() if k != "Name")
        print(f"[{iid}] {name} {extras}".rstrip())


def cmd_set_item(args):
    path = Path(args.file)
    data = read_bytes(path)
    if not looks_plaintext(data):
        raise SystemExit("Файл зашифрован. Сначала: python escapists_mod.py dec " + str(path))
    codec = detect_text_codec(data)
    text = data.decode(codec)
    newline = "\r\n" if "\r\n" in text else "\n"
    entries, order = parse_items(text)

    # разделяем файл на «шапку», блоки и хвост
    blocks = re.split(r"(?m)(?=^\s*\[\d+\]\s*$)", text)
    header = blocks[0] if not re.match(r"^\s*\[\d+\]\s*$", blocks[0]) else ""

    def block_of(iid):
        for blk in blocks:
            m = re.match(r"^\s*\[(\d+)\]\s*$", blk.splitlines()[0] if blk.strip() else "")
            if m and int(m.group(1)) == iid:
                return blk
        return None

    target = block_of(args.id)
    if target is None and not args.create:
        raise SystemExit(f"ID {args.id} отсутствует в файле. Добавь --create, чтобы создать новую запись.")

    base = {}
    if args.from_id is not None:
        src = block_of(args.from_id)
        if src is None:
            raise SystemExit(f"Нет записи с ID {args.from_id} для копирования.")
        base = dict(parse_items(src)[0][0][1])

    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"--set ожидает Вид=Значение, получено: {item}")
        k, v = item.split("=", 1)
        base[k.strip()] = v.strip()
    for k in args.unset or []:
        base.pop(k.strip(), None)

    lines = [f"[{args.id}]"]
    # сохраняем порядок ключей: сначала Name, затем из шаблона/правок
    keys = list(base.keys())
    if "Name" in keys:
        keys.remove("Name")
        keys.insert(0, "Name")
    for k in keys:
        lines.append(f"{k}={base[k]}")
    new_block = newline.join(lines) + newline

    if target is None:
        text = text.rstrip("\r\n") + newline + new_block
    else:
        text = text.replace(target, new_block)

    if args.dry_run:
        print(new_block)
        return
    write_bytes(path, text.encode(codec), force=True)
    print(f"ID {args.id}: запись {'обновлена' if target else 'создана'} в {path} (кодировка {codec})")
    print("Не забудь: зашифровать обратно (enc) и обновить val.dat (val).")


def cmd_selftest(args):
    cipher = EscapistsCipher()
    print("бэкенд шифра:", cipher.backend)
    plain = b"WARNING: If you edit this file , the game will not work!" + b"\n[0]\nName=Cell Key\n"
    plain += b"\0" * ((8 - len(plain) % 8) % 8)
    assert cipher.decrypt(cipher.encrypt(plain)) == plain, "round-trip шифра не сошёлся"
    print("round-trip шифра: OK")
    tmp = Path("_selftest.bin")
    tmp.write_bytes(b"x" * 1234)
    h = file_hash(tmp)
    expected = hashlib.md5(b"l0l_1234").hexdigest()
    tmp.unlink()
    assert h == expected, "формула хеша не совпала"
    print("формула val.dat (md5('l0l_'+size)): OK ->", h)


# ----------------------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(description="Моддинг-инструмент The Escapists 1", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("detect", help="зашифрован файл или нет")
    p.add_argument("file")
    p.add_argument("--key", default=KEY.decode())
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("dec", help="расшифровать")
    p.add_argument("file")
    p.add_argument("-o", "--output")
    p.add_argument("-f", "--force", action="store_true")
    p.add_argument("-n", "--keep-null", action="store_true", help="не обрезать хвостовые нули")
    p.set_defaults(func=cmd_dec)

    p = sub.add_parser("enc", help="зашифровать")
    p.add_argument("file")
    p.add_argument("-o", "--output")
    p.add_argument("-f", "--force", action="store_true")
    p.add_argument("--same-size", metavar="ОРИГИНАЛ", help="добить файл до размера оригинала, чтобы val.dat остался валидным")
    p.set_defaults(func=cmd_enc)

    p = sub.add_parser("val", help="пересобрать val.dat под изменённые файлы")
    p.add_argument("directory", help="папка с изменёнными data_*/items_*/speech_*.dat")
    p.add_argument("val_base", help="исходный val.dat (как образец структуры)")
    p.add_argument("-f", "--force", action="store_true")
    p.set_defaults(func=cmd_val)

    p = sub.add_parser("val-decode", help="показать, какие файлы и размеры проверяет val.dat")
    p.add_argument("file", nargs="?", default="val.dat", help="val.dat (или его копия)")
    p.add_argument("--dir", default=".", help="папка с файлами игры для сопоставления")
    p.add_argument("--max", type=int, default=2_000_000, help="до какого размера перебирать (байт)")
    p.set_defaults(func=cmd_val_decode)

    p = sub.add_parser("items", help="анализ items_*.dat (уже расшифрованного)")
    p.add_argument("file")
    p.add_argument("--free", action="store_true", help="показать свободные/пустые ID")
    p.add_argument("--unused", action="store_true", help="показать предметы, недоступные игроку (кандидаты на переиспользование)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--from-id", type=int, default=0)
    p.set_defaults(func=cmd_items)

    p = sub.add_parser("set-item", help="создать/изменить запись предмета")
    p.add_argument("file", help="расшифрованный items_*.dat")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--from-id", type=int, help="скопировать запись другого предмета как шаблон")
    p.add_argument("--set", action="append", metavar="КЛЮЧ=ЗНАЧЕНИЕ")
    p.add_argument("--unset", action="append", metavar="КЛЮЧ")
    p.add_argument("--create", action="store_true", help="разрешить создание нового ID")
    p.add_argument("--dry-run", action="store_true", help="только показать результат")
    p.set_defaults(func=cmd_set_item)

    p = sub.add_parser("selftest", help="проверить шифр и хеши")
    p.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
