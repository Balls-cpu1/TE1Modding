# TE1Modding — моддинг The Escapists 1 (PC / Steam)

Всё, что нужно для своего контента в The Escapists 1. Игра сделана на
**Clickteam Fusion 2.5**: «код» игры и все спрайты/иконки зашиты в `TheEscapists.exe`,
снаружи — только данные (`Data/*.dat`) и текстуры тайлов.

## Что уже сделано (главное)

| Задача | Статус |
|---|---|
| Шифрование `.dat` (Blowfish ECB, ключ `mothking`, little-endian) | ✅ `toolkit/escapists_mod.py` |
| «Валидатор» `val.dat` (проверяет только РАЗМЕР: `md5("l0l_"+size)`) | ✅ вскрыт, пересобирается |
| Правка/добавление предметов (`items_*.dat`) | ✅ `escapists_mod.py set-item` |
| Свой предмет ID 279 (+ `mods/` лоадер) | ✅ `toolkit/GUIDE.md` |
| Расшифровка чанков exe (порт CTFAK-Native) | ✅ `toolkit/te_crypto.py` |
| Карта «ID предмета → иконка в exe» (281 слот, проверено визуально) | ✅ `toolkit/te1_icons.py`, `toolkit/item_icon_map.json` |
| События фрейма `game` (2.4 МБ байткода механик) | ✅ расшифрованы (`docs/MECHANICS.md`), правка — отдельная задача |
| Свои тайл-текстуры | ✅ официально: `Data/images/custom/` |
| Своя иконка (байт-патч exe / Fusion) | ⚠️ маршрут известен, не доведён |

## Структура репо

```
docs/          — вся документация (читать отсюда)
  MODDING_THE_ESCAPISTS.md  — главный документ: устройство игры, форматы, маршруты A/B/C
  EXE_ANALYSIS.md           — что внутри TheEscapists.exe (чанки, PackData, объекты)
  NEXT_STEPS.md             — таблицы val.dat, паспорт файлов Data
  RESULTS.md                — итог прошлой сессии (иконки расшифрованы)
  MECHANICS.md              — механики (события Fusion): дверь по форме и т.п.
toolkit/       — РАБОЧИЕ ИНСТРУМЕНТЫ + гайды (GUIDE.md — с него начинаешь)
tools/         — исследовательские скрипты (дампер картинок, парсер чанков, исходники CTFAK)
reference/     — справочники: все 279 предметов (csv/json), 774 объекта игры
imagebank/     — 3948 PNG из TheEscapists_eur.exe + images.csv (индекс хендлов)
exe/           — сами exe (переименованы в .txt): main / eur / rus
data_samples/  — образцы Data: легаси items/speech, data_eng, val
sheets/        — контакт-листы банка картинок (смотреть глазами)
fusion_pack/   — 35 расширений Fusion + DLL, извлечённые из exe (нужны для декомпиляции в MFA)
```

## Быстрый старт (свой предмет за 10 минут)

См. `toolkit/GUIDE.md`. Коротко, на машине с игрой (Windows):

```powershell
py te_modloader.py install "C:\Program Files (x86)\Steam\steamapps\common\The Escapists"
Copy-Item "$g\Data\items_rus.dat" "$g\mods\items_rus.dat"
py append_item.py --items "$g\mods\items_rus.dat" --block item_279_block.txt --no-val
# запуск: Запустить_с_модами.bat
```

## Зависимости

```bash
pip install blowfish        # или pycryptodome
pip install pillow          # для работы с иконками
```

## Проверено в этой песочнице

- `toolkit/escapists_mod.py selftest` — OK
- `toolkit/escapists_mod.py detect data_samples/*` — файлы распознаются
- `toolkit/te1_icons.py exe/TheEscapists_eur.exe.txt --dump-dir imagebank --id 25`
  → `ID 25: handle=14 anim=0 dir=25 png=00014.png` (Crowbar, сходится с гайдом)
