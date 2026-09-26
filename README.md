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
| Свои тайл-текстуры | ✅ официально: `Data/images/custom/` |
| Своя иконка (байт-патч exe / Fusion) | ⚠️ маршрут известен, не доведён |
| **Байткод событий (вся логика игры)** | ✅ **расшифрован, читается и ПАТЧИТСЯ** — см. `docs/EVENTS_BREAKTHROUGH.md` |
| Новая механика «дверь по форме» в любой тюрьме | ✅ `tools/te1_patch.py outfitdoor` (собрано и проверено парсером) |

## Структура репо

```
docs/          — вся документация (читать отсюда)
  MODDING_THE_ESCAPISTS.md  — главный документ: устройство игры, форматы, маршруты A/B/C
  EXE_ANALYSIS.md           — что внутри TheEscapists.exe (чанки, PackData, объекты)
  NEXT_STEPS.md             — таблицы val.dat, паспорт файлов Data
  RESULTS.md                — итог прошлой сессии (иконки расшифрованы)
  MECHANICS.md              — механики (события Fusion): дверь по форме и т.п.
  EVENTS_BREAKTHROUGH.md    — ★ НОВЫЙ: формат событий + как патчить exe (читать для механик)
toolkit/       — РАБОЧИЕ ИНСТРУМЕНТЫ + гайды (GUIDE.md — с него начинаешь)
tools/         — скрипты: дампер картинок, te1_frames/te1_events/te1_patch (события), исходники CTFAK
dumps/         — game_events.txt: ВСЯ логика фрейма game в читаемом виде (5473 группы)
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

## Новая механика (дверь по форме) — уже работает

```bash
python3 tools/te1_patch.py outfitdoor exe/TheEscapists_eur.exe.txt \
    --map perks --outfit 38 --x 512 --y 320 -o work/perks_medicdoor.exe.txt
```

Ставит `Door - outfit` (handle 501) в Center Perks; проход только в
Infirmary Overalls (ID 38). Подробности и список форм — `docs/EVENTS_BREAKTHROUGH.md`.

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

## Единый инструмент: `te1_mod.py`

Один файл, без зависимостей (Blowfish встроен и проверен стандартным тест-вектором).
Запуск: `py te1_mod.py` — дальше меню:

```
 1. Создать папку mods/ + лаунчер (.bat)
 2. Применить моды из mods/
 3. Откатить (восстановить оригиналы)
 4. Аудит файлов (диагностика)
 5. Мод: Русский перевод          (items_rus.dat)
 6. Мод: Рандомайзер предметов
 7. Мод: Фикс крафта (лимит 200 -> 281)   [патч exe]
 8. Мод: Добавить свой рецепт             [патч exe]
 9. Мод: Дверь по форме                   [патч exe]
10. Самопроверка (Blowfish + round-trip exe)
```

Разбор бага с крафтом и две его причины — `docs/CRAFT_BUG.md`.
Таблица всех 97 захардкоженных рецептов — `reference/recipes_hardcoded.json`.

## Рандомайзер предметов: `te1_randomizer.py`

Отдельный один файл, без зависимостей. Запуск:

```
py te1_randomizer.py             перетасовать один раз и выйти
py te1_randomizer.py --auto      тасовать при КАЖДОЙ загрузке карты
py te1_randomizer.py --restore   вернуть оригинал из .bak
```

`--auto` — это то, что нужно для «рандом на каждую карту»: рандомизация
срабатывает при запуске карты и при перезаходе, но **не между днями**.

**Пошаговый гайд по запуску (с картинками команд и решением проблем) —
[`docs/GUIDE_RANDOMIZER.md`](docs/GUIDE_RANDOMIZER.md).**

Двойным щелчком: `randomizer_auto.bat` (запуск) и `randomizer_restore.bat`
(откат). Оба сами запрашивают права администратора — они нужны, потому что
игра лежит в `Program Files`.

Почему это работает. В байткоде игры, фрейм `game`, группа #425
(условие «начало фрейма») есть единственное чтение списка предметов:

```
INI_ITEMS: act86("Data\items_" + <язык> + ".dat")
```

Оно выполняется один раз при входе во фрейм `game`, то есть при каждой
загрузке карты; между днями файл не перечитывается. Скрипт держит в
`items_*.dat` свежую случайную версию, поэтому игра подхватывает её ровно
в момент загрузки карты.

Две важные детали реализации:

- **Размер файла не меняется** (случайная версия добивается до исходного
  размера). Валидатор `val.dat` проверяет именно размер, поэтому `val.dat`
  трогать не нужно и игра не ругается.
- **Запись атомарная** (временный файл + `os.replace`), так что игра не
  может прочитать файл наполовину записанным. Если файл занят игрой,
  скрипт ловит `PermissionError` и повторяет позже.

Трогаются только игровые статы (`Weapon`, `Digging`, `Chipping`, `Cutting`,
`Unscrewing`, `HP`, `FAT`, `Gift`, `Decay`, `Buy`) плюс `Illegal` на хаосе
≥ 2. `Name`, `Craft`, `Found`, `Desk`, `NPC_carry`, `Outfit`, `Info`,
`CamDis` не меняются никогда.
