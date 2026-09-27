# ГАЙД (чистая Steam-установка): свой предмет + папка mods — The Escapists 1

Все инструменты — в этой папке `toolkit/`. Работает на обычной Steam-версии.
> Если скачивал toolkit раньше — **обнови `append_item.py`** (в нём фикс кодировки UTF-16,
> без него игра может виснуть при загрузке карты).

Обозначения (выполняй в **PowerShell**):
```powershell
$g = "C:\Program Files (x86)\Steam\steamapps\common\The Escapists"   # путь игры
cd C:\te1\toolkit      # куда ты положил скачанный toolkit
```
Python вызывай как **`py`** (команда `python` может не находиться — это нормально).

---

## 0. Один раз
1. Python 3 с python.org, отметь «Add Python to PATH». Проверка: `py --version`.
2. Бэкап: скопируй `$g\Data` куда-нибудь (или помни про Steam → «Проверить целостность»).
3. В чистой версии `.dat` не зашифрованы. Проверка: `py escapists_mod.py detect "$g\Data\items_rus.dat"`.

## 1. Создать mods + нейтрализовать валидатор
```powershell
py te_modloader.py install "$g"
```
Появятся: `$g\mods\`, `$g\mods\_backup\`, `$g\Запустить_с_модами.bat`, копия `te_modloader.py`.
(Валидатор не вырезается из exe — он «замолкает», т.к. `val.dat` пересобирается под размеры.)

## 2. Добавить свой предмет (ведро краски, ID 279)
```powershell
Copy-Item "$g\Data\items_rus.dat" "$g\mods\items_rus.dat"
py append_item.py --items "$g\mods\items_rus.dat" --block item_279_block.txt --no-val
```
В выводе должно быть `[кодировка utf-16-le]` — блок записан в родной кодировке файла.
Хочешь другое имя/статы — сначала отредактируй `item_279_block.txt`.

## 3. Запуск
Двойной клик по `$g\Запустить_с_модами.bat`
(он применит `mods\`, пересоберёт `val.dat`, запустит игру).
Или вручную:
```powershell
py te_modloader.py apply "$g"
Start-Process "$g\TheEscapists.exe"
```

## 4. В игре
- Язык — **русский** (правим `items_rus.dat`).
- Получить предмет: крафт «Чашка + Чернила» (интеллект 40) или Cheat Engine по ID **279**.
- Иконка у 279 — запасная из exe (решётка). Своё ведро (PNG 16×16, прозрачный фон) — маршрут C/B.

## Дальше: любые моды
Кидаешь `.dat` в `$g\mods\` → жмёшь bat. Откат: `py te_modloader.py restore "$g"`.

## Если что-то не так
- **`python` не найден** → пиши `py`.
- **Виснет при загрузке карты** → файл побит чужой кодировкой: верни чистый
  `Copy-Item "$g\mods\_backup\items_rus.dat" "$g\mods\items_rus.dat" -Force` и повтори шаг 2
  **обновлённым** `append_item.py`.
- **Ошибся с путём, написал "GAME" буквально** → всегда подставляй `$g` или полный путь.
- **Не стартует** → `py te_modloader.py restore "$g"` + Steam «проверить целостность».
