#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
append_item.py — добавить СВОЙ предмет в The Escapists 1 (items_*.dat в открытом виде)
и синхронно обновить val.dat (валдиатор проверяет только РАЗМЕР файла).

Использование (в папке Data игры, или укажи пути):
    python append_item.py --items "Data/items_rus.dat" --val "Data/val.dat" \
        --block item_279_block.txt

Что делает:
  1. бэкап: items_rus.dat.bak / val.dat.bak
  2. дописывает блок [ID] в конец items_*.dat (как есть, с твоими \n)
  3. пересчитывает для val.dat хеш items языка r (или e): md5("l0l_" + новый_размер)
     и подменяет средний токен в строке r= (формат: data_items_speech)

Если твой items_*.dat ЗАШИФРОВАН (detect скажет), сначала:
    python escapists_mod.py dec items_rus.dat
и работай с расшифрованным, а в конце enc --same-size НЕ подойдёт (размер вырос) —
тогда обязательно обнови val.dat этим скриптом.
"""
import argparse, hashlib, shutil, sys, re

def md5_size(sz):
    return hashlib.md5(("l0l_%d" % sz).encode()).hexdigest()

def sniff_enc(b):
    if b.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if b.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if b[:400].count(b"\x00") > 40:  # много нулей => UTF-16 без BOM
        return "utf-16-le"
    return "utf-8"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--val", default=None)
    ap.add_argument("--block", required=True)
    ap.add_argument("--lang", default="r", help="буква языка в val.dat (r/e/...)")
    ap.add_argument("--no-val", action="store_true")
    a = ap.parse_args()

    raw_block = open(a.block, "rb").read()
    data = open(a.items, "rb").read()

    enc = sniff_enc(data)
    # блок у нас в UTF-8; перекодируем в кодировку самого файла (UTF-16 или UTF-8)
    try:
        btxt = raw_block.decode("utf-8-sig")
    except Exception:
        btxt = raw_block.decode("utf-16-le", "replace")
    if enc.startswith("utf-16"):
        btxt = btxt.replace("\r\n", "\n")
        block = btxt.encode("utf-16-le")
        nl = b"\n\x00"
    else:
        block = btxt.encode("utf-8")
        nl = b"\n"

    shutil.copy(a.items, a.items + ".bak")
    if not data.endswith(nl):
        data += nl
    new = data + block
    open(a.items, "wb").write(new)
    print(f"items: было {len(data)} -> стало {len(new)}  (+{len(new)-len(data)})  [кодировка {enc}]")

    if a.val and not a.no_val:
        shutil.copy(a.val, a.val + ".bak")
        raw = open(a.val, "rb").read()
        # val.dat — UTF-16
        try:
            txt = raw.decode("utf-16-le")
        except Exception:
            txt = raw.decode("utf-8", "replace")
        h = md5_size(len(new))
        pat = re.compile(r"(^|\n)(%s=)([0-9a-f]{32})_([0-9a-f]{32})_([0-9a-f]{32})" % a.lang)
        m = pat.search(txt)
        if not m:
            print("!! не нашёл строку", a.lang, "в val.dat — обнови вручную:", h)
        else:
            txt = pat.sub(lambda m: m.group(1)+m.group(2)+m.group(3)+"_"+h+"_"+m.group(5), txt, count=1)
            open(a.val, "wb").write(txt.encode("utf-16-le"))
            print(f"val.dat [{a.lang}] items-хеш -> {h}")
    print("Готово. Переключи игру на нужный язык и запусти.")

if __name__ == "__main__":
    main()
