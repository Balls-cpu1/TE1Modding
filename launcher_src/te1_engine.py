#!/usr/bin/env python3
# -*- coding: ascii -*-
#
# te1_engine.py - mod engine for "The Escapists 1" (PC / Steam).
#
# This file is NOT run directly. It is embedded inside TE1_Mod_Launcher.bat
# and unpacked to mods\te1_engine.py at run time. It is deliberately
# pure ASCII: every Russian string it writes lives in the FIXES database
# (a JSON document stored with \uXXXX escapes), so the .bat file itself
# never needs a code page and can never be mangled by cmd.exe.
#
# No third-party modules: Python 3 standard library only.
#
# Commands (all of them are driven by the launcher menu):
#   --game DIR        game folder (folder that holds TheEscapists.exe)
#   --menu            interactive menu (default)
#   --apply           install enabled mods into Data\ and exit
#   --restore         put the original Data\*.dat files back and exit
#   --status          print what is installed and exit
#   --report          dry run of "Better Translate", print the diff, exit
#
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE_VERSION = "1.0"
EXE_NAME = "TheEscapists.exe"

# Language files the two mods touch.
MODS = [
    ("randomizer", "Randomizer"),
    ("better_translate", "Better Translate"),
]

# ---------------------------------------------------------------- FIXES data
# Filled in by tools/build_launcher.py from launcher_src/fixes_rus.json.
_FIXES_JSON = r"""
<<<FIXES_JSON>>>
"""

FIXES = json.loads(_FIXES_JSON)


# ------------------------------------------------------------------ console
def _fix_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_console()


def say(*a):
    print(*a, flush=True)


def rule(ch="-", n=66):
    say(ch * n)


class EndOfInput(Exception):
    """Raised when there is nobody left to answer the menus."""


def ask(prompt, default=None):
    try:
        s = input(prompt + (" [%s]: " % default if default is not None else ": ")).strip()
    except (EOFError, OSError, KeyboardInterrupt):
        raise EndOfInput()
    return s or (default if default is not None else "")


def pause(msg="Press Enter to continue..."):
    try:
        input("\n" + msg)
    except (EOFError, OSError, KeyboardInterrupt):
        pass


# ------------------------------------------------------------- .dat encoding
def looks_text(t):
    if not t:
        return False
    head = t[:4096]
    good = sum(1 for c in head if c.isprintable() or c in "\r\n\t")
    if good / len(head) < 0.85:
        return False
    return head.count("[") + head.count("=") >= 3 or len(t) < 64


def decode_dat(raw):
    """-> (text, encoding, bom) or (None, None, False) when unreadable."""
    if not raw:
        return "", "utf-8", False
    if raw[:2] == b"\xff\xfe":
        try:
            return raw.decode("utf-16-le")[1:], "utf-16-le", True
        except UnicodeDecodeError:
            return None, None, False
    if raw[:2] == b"\xfe\xff":
        try:
            return raw.decode("utf-16-be")[1:], "utf-16-be", True
        except UnicodeDecodeError:
            return None, None, False
    if raw[:3] == b"\xef\xbb\xbf":
        try:
            return raw.decode("utf-8")[1:], "utf-8", True
        except UnicodeDecodeError:
            return None, None, False
    for enc in ("utf-8", "cp1252", "cp1251", "latin-1"):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if looks_text(t):
            return t, enc, False
    return None, None, False


def encode_dat(text, enc, bom):
    if bom:
        text = "\ufeff" + text
    return text.encode(enc, "strict")


def atomic_write(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class DatFile(object):
    """A Data\\*.dat file: text + encoding, loaded and saved as a whole."""

    def __init__(self, path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        self.text, self.enc, self.bom = decode_dat(self.raw)
        self.ok = self.text is not None

    def save(self):
        data = encode_dat(self.text, self.enc, self.bom)
        # round-trip guard: never write something we cannot read back
        back, enc2, bom2 = decode_dat(data)
        if back is None or back != self.text:
            raise ValueError("round-trip check failed for %s" % self.path.name)
        atomic_write(self.path, data)
        self.raw = data

    @property
    def size(self):
        return len(self.raw)


# ------------------------------------------------------------------ INI text
KV_RE = re.compile(r"^([0-9A-Za-z_]+)=(.*)$", re.S)
SEC_RE = re.compile(r"^\[(.*)\]$")


class Ini(object):
    """Line-preserving INI editor.

    The game files carry cosmetic blank lines, a warning header and (in
    data_*.dat) blank lines inside sections. Rebuilding the file from a
    dict would drop all of that, so we keep the original line list and
    only replace the parts that actually change.
    """

    def __init__(self, text):
        self.nl = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.split(self.nl)
        self.index = {}
        self.order = []
        self._parse()

    def _parse(self):
        self.index = {}
        self.order = []
        sec = None
        for i, line in enumerate(self.lines):
            m = SEC_RE.match(line.strip())
            if m:
                sec = m.group(1)
                continue
            if sec is None:
                continue
            m = KV_RE.match(line)
            if m and (sec, m.group(1)) not in self.index:
                self.index[(sec, m.group(1))] = i
                self.order.append((sec, m.group(1)))

    @property
    def text(self):
        return self.nl.join(self.lines)

    def sections(self):
        seen = []
        for sec, _key in self.order:
            if sec not in seen:
                seen.append(sec)
        return seen

    def keys(self, sec):
        return [k for s, k in self.order if s == sec]

    def get(self, sec, key, default=None):
        i = self.index.get((sec, key))
        if i is None:
            return default
        return KV_RE.match(self.lines[i]).group(2)

    def has(self, sec, key):
        return (sec, key) in self.index

    def set(self, sec, key, value):
        i = self.index.get((sec, key))
        if i is None:
            self.add(sec, key, value)
            return
        old = KV_RE.match(self.lines[i]).group(2)
        if old == value:
            return
        self.lines[i] = "%s=%s" % (key, value)

    def add(self, sec, key, value):
        """Insert a new key, keeping numeric keys in ascending order."""
        pos = self._insert_pos(sec, key)
        self.lines.insert(pos, "%s=%s" % (key, value))
        self._parse()

    def _insert_pos(self, sec, key):
        last = None
        best = None
        try:
            want = int(key)
        except ValueError:
            want = None
        for (s, k), i in sorted(self.index.items(), key=lambda kv: kv[1]):
            if s != sec:
                continue
            last = i
            if want is not None:
                try:
                    cur = int(k)
                except ValueError:
                    continue
                if cur < want and (best is None or cur > best[0]):
                    best = (cur, i)
        if best is not None:
            return best[1] + 1
        if last is not None:
            return last + 1
        # brand new section: append at the end of the file
        return len(self.lines)

    def rewrite_section(self, sec, pairs):
        """Replace every key line of `sec` with `pairs` (list of (k, v))."""
        idx = [i for (s, _k), i in self.index.items() if s == sec]
        if not idx:
            return
        first, last = min(idx), max(idx)
        new = ["%s=%s" % (k, v) for k, v in pairs]
        self.lines[first:last + 1] = new
        self._parse()


# ------------------------------------------------------------------ val.dat
LANGS = {"e": "eng", "f": "fre", "g": "ger", "s": "spa",
         "r": "rus", "p": "pol", "i": "ita"}
KINDS = ["data", "items", "speech"]


def md5_size(size):
    return hashlib.md5(("l0l_%d" % size).encode()).hexdigest()


def rebuild_val(data_dir):
    """val.dat only stores md5("l0l_" + file size) per file, so any edit
    that changes a file length has to be followed by this."""
    vpath = Path(data_dir) / "val.dat"
    if not vpath.exists():
        return 0
    txt = vpath.read_bytes().decode("utf-16-le", "replace")
    bom = txt.startswith("\ufeff")
    if bom:
        txt = txt[1:]
    changed = 0
    for letter, lang in LANGS.items():
        m = re.search(r"(^|\n)(%s=)([0-9a-f]{32})_([0-9a-f]{32})_([0-9a-f]{32})"
                      % letter, txt)
        if not m:
            continue
        toks = [m.group(3), m.group(4), m.group(5)]
        for i, kind in enumerate(KINDS):
            fp = Path(data_dir) / ("%s_%s.dat" % (kind, lang))
            if fp.exists():
                toks[i] = md5_size(fp.stat().st_size)
        txt = (txt[:m.start()] + m.group(1) + m.group(2) + "_".join(toks)
               + txt[m.end():])
        changed += 1
    vpath.write_bytes((("\ufeff" if bom else "") + txt).encode("utf-16-le"))
    return changed


# ------------------------------------------------------- generic RU clean-up
CYR_LOW = "\u0430\u0431\u0432\u0433\u0434\u0435\u0451\u0436\u0437\u0438\u0439\u043a\u043b\u043c\u043d\u043e\u043f\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448\u0449\u044a\u044b\u044c\u044d\u044e\u044f"

# Latin letters that people (and machine translation) keep typing instead of
# the identical-looking Cyrillic ones.
HOMOGLYPHS = {
    "A": "\u0410", "B": "\u0412", "C": "\u0421", "E": "\u0415",
    "H": "\u041d", "K": "\u041a", "M": "\u041c", "O": "\u041e",
    "P": "\u0420", "T": "\u0422", "X": "\u0425", "Y": "\u0423",
    "a": "\u0430", "c": "\u0441", "e": "\u0435", "o": "\u043e",
    "p": "\u0440", "x": "\u0445", "y": "\u0443"
}

RE_SPACED_DOTS = re.compile(r"\.(\s+\.)+")
RE_SP_BEFORE_PUNCT = re.compile(r"[ \t]+([!,.;:?])")
RE_SP_BEFORE_HASH = re.compile(r"[ \t]+#")
RE_MULTISPACE = re.compile(r"[ \t]{2,}")


def is_cyr(c):
    return "\u0400" <= c <= "\u04ff"


def fix_homoglyphs(v):
    """Latin letter adjacent to a Cyrillic one -> Cyrillic.

    Only touches characters that sit right next to a Cyrillic letter, so
    Latin brand names (VIP, DVD, Worms, Jingle Cells) are left alone.
    """
    out = None
    for i, c in enumerate(v):
        if c not in HOMOGLYPHS:
            continue
        left = i > 0 and is_cyr(v[i - 1])
        right = i + 1 < len(v) and is_cyr(v[i + 1])
        if left or right:
            if out is None:
                out = list(v)
            out[i] = HOMOGLYPHS[c]
    return "".join(out) if out is not None else v


def normalize_ru(v, eng=None, full=True):
    v = v.replace("\u00a0", " ")
    if full:
        v = v.replace("\n", "#")           # stray LF used as a line break
        v = RE_SPACED_DOTS.sub("...", v)
        v = RE_SP_BEFORE_PUNCT.sub(r"\1", v)
        v = RE_SP_BEFORE_HASH.sub("#", v)
    v = RE_MULTISPACE.sub(" ", v)
    v = v.strip()
    v = fix_homoglyphs(v)
    if full and v and eng and eng[:1].isupper() and v[0] in CYR_LOW:
        v = v[0].upper() + v[1:]
    return v


# ------------------------------------------------------------- N@ line prefix
# Tutorial / popup strings start with "N@". The Russian files drifted away
# from the English ones (2@ where the original says 1@ and so on), which
# changes how the hint is displayed.
RE_PREFIX = re.compile(r"^(\d+)@")


def sync_prefix(value, eng):
    if not eng:
        return value
    me = RE_PREFIX.match(eng)
    if not me:
        return value
    mr = RE_PREFIX.match(value)
    if mr and mr.group(1) == me.group(1):
        return value
    body = value[mr.end():] if mr else value
    return me.group(1) + "@" + body


# ----------------------------------------------------------- Better Translate
def translate_items(ini_rus, ini_eng, log):
    """items_rus.dat: names, descriptions and recipes."""
    fx = FIXES.get("items", {})
    changed = 0
    for group, keys in (("name", ("Name",)), ("info", ("Info",)), ("craft", ("Craft",))):
        table = fx.get(group, {})
        for sid, value in table.items():
            for key in keys:
                if not ini_rus.has(sid, key):
                    continue
                if ini_rus.get(sid, key) != value:
                    ini_rus.set(sid, key, value)
                    changed += 1
    # generic tidy-up of the human readable fields
    for sec in ini_rus.sections():
        for key in ini_rus.keys(sec):
            if key not in ("Name", "Info", "Craft"):
                continue
            new = normalize_ru(ini_rus.get(sec, key), None, full=False)
            if new != ini_rus.get(sec, key):
                ini_rus.set(sec, key, new)
                changed += 1
    log.append("item names / descriptions: %d fix(es)" % changed)
    return changed


def translate_generic(ini_rus, ini_eng, table, log, label):
    """data_rus.dat / speech_rus.dat: the shared pass.

    1. exact replacements from the curated table
    2. lines the English file has but the Russian one never got
    3. generic clean-up (NBSP, spacing, homoglyphs, N@ prefix, capitalisation)
    """
    changed = 0
    added = 0

    # ---- 1. curated replacements (+ the "_fix" block for speech)
    for block in (table, table.get("_fix", {})):
        for sec, pairs in block.items():
            if sec.startswith("_"):
                continue
            for key, value in pairs.items():
                if not ini_rus.has(sec, key):
                    continue
                if ini_rus.get(sec, key) != value:
                    ini_rus.set(sec, key, value)
                    changed += 1

    # ---- 2. lines missing from the Russian file
    for sec in ini_eng.sections():
        if not ini_rus.has(sec, "Count"):
            continue
        try:
            count = int(ini_eng.get(sec, "Count", "0"))
        except ValueError:
            count = 0
        for i in range(1, count + 1):
            key = str(i)
            eng = ini_eng.get(sec, key)
            if eng is None or ini_rus.has(sec, key):
                continue
            rus = table.get(sec, {}).get(key)
            if rus is None:
                continue
            ini_rus.add(sec, key, rus)
            added += 1

    # ---- 3. generic clean-up
    for sec in ini_rus.sections():
        for key in ini_rus.keys(sec):
            if key == "Count":
                continue
            old = ini_rus.get(sec, key)
            eng = ini_eng.get(sec, key)
            if eng is not None and old == eng:
                continue                      # never translated - handled above
            new = sync_prefix(old, eng)
            new = normalize_ru(new, eng, full=True)
            if new != old:
                ini_rus.set(sec, key, new)
                changed += 1

    # ---- 4. keep Count in step with the lines that are really there
    for sec in ini_rus.sections():
        if not ini_rus.has(sec, "Count"):
            continue
        nums = sorted(int(k) for k in ini_rus.keys(sec) if k.isdigit())
        if nums and nums == list(range(1, len(nums) + 1)):
            want = str(len(nums))
            if ini_rus.get(sec, "Count") != want:
                ini_rus.set(sec, "Count", want)
                changed += 1

    log.append("%s: %d line(s) fixed, %d line(s) added" % (label, changed, added))
    return changed + added


def mod_better_translate(data_dir, log, dry=False):
    """Returns the number of changed lines, or None when it cannot run."""
    pairs = [("items", translate_items), ("data", None), ("speech", None)]
    total = 0
    for kind, fn in pairs:
        f_rus = Path(data_dir) / ("%s_rus.dat" % kind)
        f_eng = Path(data_dir) / ("%s_eng.dat" % kind)
        if not f_rus.exists():
            log.append("%s_rus.dat: not found - skipped" % kind)
            continue
        if not f_eng.exists():
            log.append("%s_eng.dat: reference missing - %s_rus.dat skipped"
                       % (kind, kind))
            continue
        rus = DatFile(f_rus)
        eng = DatFile(f_eng)
        if not rus.ok or not eng.ok:
            log.append("%s_rus.dat: unreadable (encrypted?) - skipped" % kind)
            continue
        ini_rus = Ini(rus.text)
        ini_eng = Ini(eng.text)
        if kind == "items":
            n = translate_items(ini_rus, ini_eng, log)
        else:
            n = translate_generic(ini_rus, ini_eng,
                                  FIXES.get(kind, {}), log, "%s_rus.dat" % kind)
        total += n
        if n and not dry:
            rus.text = ini_rus.text
            rus.save()
    return total


# ---------------------------------------------------------------- Randomizer
STAT_POOLS = {
    "Weapon": [0, 1, 1, 2, 2, 3, 3, 4, 5],
    "Digging": [0, 0, 1, 1, 2, 2, 3, 5],
    "Chipping": [0, 0, 1, 1, 2, 2, 3, 5],
    "Cutting": [0, 0, 1, 1, 2, 2, 3, 5],
    "Unscrewing": [0, 0, 1, 1, 2, 3],
    "HP": [0, 0, 0, 5, 10, 15, 25, 40],
    "FAT": [0, 0, 0, 5, 10, 20],
    "Gift": [0, 1, 1, 2, 2, 3, 5],
    "Decay": [0, 1, 2, 2, 5, 5, 10],
    "Buy": [0, 5, 10, 20, 30, 50, 75, 100],
}
STAT_KEYS = list(STAT_POOLS)
# Name, Craft, Info, Found, Desk, Outfit, NPC_carry and CamDis are never
# touched: they carry the readable text and the prison-editor data.


def randomize_items_text(text, seed, chaos=3):
    ini = Ini(text)
    rnd = random.Random(seed)
    touched = 0
    for sec in ini.sections():
        keys = ini.keys(sec)
        name = (ini.get(sec, "Name") or "").strip().lower()
        if name in ("", "empty", "none"):
            continue
        props = [(k, ini.get(sec, k)) for k in keys
                 if k not in STAT_KEYS and k != "Illegal"]
        stats = []
        for k in rnd.sample(STAT_KEYS, min(chaos + 1, len(STAT_KEYS))):
            v = rnd.choice(STAT_POOLS[k])
            if v:
                stats.append((k, str(v)))
        extra = []
        if chaos >= 2 and rnd.random() < 0.5:
            extra.append(("Illegal", "1" if rnd.random() < 0.7 else "0"))
        # Name first, then the rolled stats, then everything else
        head = [p for p in props if p[0] == "Name"]
        tail = [p for p in props if p[0] != "Name"]
        ini.rewrite_section(sec, head + stats + tail + extra)
        touched += 1
    return ini.text, touched


def mod_randomizer(data_dir, log, seed=None):
    if seed is None:
        seed = random.randrange(1, 2 ** 31)
    total = 0
    files = sorted(Path(data_dir).glob("items_*.dat"))
    if not files:
        log.append("no items_*.dat found - nothing to randomize")
        return 0
    for f in files:
        d = DatFile(f)
        if not d.ok:
            log.append("%s: unreadable (encrypted?) - skipped" % f.name)
            continue
        new_text, touched = randomize_items_text(d.text, seed)
        if new_text != d.text:
            d.text = new_text
            d.save()
        total += touched
        log.append("%s: %d item(s) re-rolled (seed %d)" % (f.name, touched, seed))
    return total


# --------------------------------------------------------------- mod plumbing
class Launcher(object):

    def __init__(self, game_dir):
        self.game = Path(game_dir)
        self.data = self.game / "Data"
        self.mods = self.game / "mods"
        self.orig = self.mods / "original"
        self.state_path = self.mods / "mods.json"
        self.state = {"randomizer": False, "better_translate": False}

    # -- state ------------------------------------------------------------
    def load_state(self):
        try:
            self.state.update(json.loads(self.state_path.read_text("utf-8")))
        except Exception:
            pass
        return self.state

    def save_state(self):
        self.mods.mkdir(parents=True, exist_ok=True)
        atomic_write(self.state_path,
                     json.dumps(self.state, indent=2, sort_keys=True).encode("utf-8"))

    def enabled(self):
        return [m for m, _label in MODS if self.state.get(m)]

    # -- backups ----------------------------------------------------------
    def backup(self, names):
        self.orig.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = self.data / name
            dst = self.orig / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    def restore(self, quiet=False):
        """Put the pristine Data\\*.dat files back.

        This is what makes the mods launcher-only: a game started straight
        from Steam always gets the untouched files.
        """
        n = 0
        if not self.orig.exists():
            return 0
        for src in sorted(self.orig.glob("*.dat")):
            dst = self.data / src.name
            try:
                shutil.copy2(src, dst)
                n += 1
            except OSError as e:
                say("    ! could not restore %s: %s" % (src.name, e))
        if n and not quiet:
            say("    restored %d original file(s)" % n)
        return n

    def writable(self):
        probe = self.data / ".te1_write_test"
        try:
            probe.write_bytes(b"x")
            probe.unlink()
            return True
        except OSError:
            return False

    # -- applying ---------------------------------------------------------
    def files_to_touch(self):
        names = set()
        if self.state.get("better_translate"):
            for kind in ("items", "data", "speech"):
                names.add("%s_rus.dat" % kind)
        if self.state.get("randomizer"):
            for f in self.data.glob("items_*.dat"):
                names.add(f.name)
        names.add("val.dat")
        return sorted(names)

    def apply(self):
        log = []
        if not self.writable():
            say("")
            say("  ! No write access to the game folder:")
            say("      %s" % self.data)
            say("")
            say("    The game lives in Program Files. Close this window and start")
            say("    the launcher again - it will ask Windows for administrator")
            say("    rights. Alternatively right-click the .bat and pick")
            say("    \"Run as administrator\".")
            say("")
            return False, log
        self.restore(quiet=True)
        names = self.files_to_touch()
        self.backup(names)
        ok = True
        if self.state.get("better_translate"):
            try:
                n = mod_better_translate(self.data, log)
                if not n:
                    log.append("Better Translate: nothing left to fix")
            except Exception as e:
                log.append("Better Translate FAILED: %s" % e)
                ok = False
        if self.state.get("randomizer"):
            try:
                mod_randomizer(self.data, log)
            except Exception as e:
                log.append("Randomizer FAILED: %s" % e)
                ok = False
        try:
            rebuild_val(self.data)
            log.append("val.dat rebuilt for the new file sizes")
        except Exception as e:
            log.append("val.dat rebuild FAILED: %s" % e)
            ok = False
        return ok, log

    # -- launching --------------------------------------------------------
    def launch(self):
        exe = self.game / EXE_NAME
        if not exe.exists():
            say("  ! %s is gone - cannot start the game." % EXE_NAME)
            return False
        say("")
        say("  Starting %s ..." % EXE_NAME)
        say("  (this window stays open and puts your files back when you quit)")
        say("")
        try:
            proc = subprocess.Popen([str(exe)], cwd=str(self.game))
        except Exception as e:
            say("  ! could not start the game: %s" % e)
            return False
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        return True


# ------------------------------------------------------------------- screens
def header(launcher):
    say("")
    rule("=")
    say("  THE ESCAPISTS 1 - MOD LAUNCHER   (engine v%s)" % ENGINE_VERSION)
    rule("=")
    say("  Game folder : %s" % launcher.game)
    say("  Mods folder : %s" % launcher.mods)
    installed = [label for m, label in MODS if launcher.state.get(m)]
    say("  Installed   : %s" % (", ".join(installed) if installed else "none"))
    rule("-")


def screen_main(launcher):
    while True:
        header(launcher)
        say("")
        say("   1. Launch Game With Mods")
        say("   2. Mod Workshop")
        say("   3. Exit")
        say("")
        c = ask("  Choose 1-3", "1")
        if c == "1":
            screen_launch(launcher)
        elif c == "2":
            screen_workshop(launcher)
        elif c == "3":
            return
        else:
            say("  -> please type 1, 2 or 3")


def screen_launch(launcher):
    if not launcher.enabled():
        say("")
        say("  No mods are installed yet - the game would start as usual.")
        if ask("  Open the Mod Workshop instead? (y/n)", "y").lower() != "y":
            return
        screen_workshop(launcher)
        return
    say("")
    rule("-")
    say("  APPLYING MODS")
    rule("-")
    ok, log = launcher.apply()
    for line in log:
        say("   " + line)
    if not ok:
        say("")
        say("  ! Something went wrong. Your original files are being restored.")
        launcher.restore()
        pause()
        return
    say("")
    say("  Mods are active. They will be removed when the game closes.")
    if not launcher.launch():
        launcher.restore()
        pause()
        return
    say("")
    rule("-")
    say("  Game closed - restoring your original files")
    rule("-")
    launcher.restore()
    say("")
    say("  Done. The game is unmodded again.")
    pause()


def screen_workshop(launcher):
    while True:
        header(launcher)
        say("")
        say("  MOD WORKSHOP")
        say("")
        for i, (key, label) in enumerate(MODS, start=1):
            mark = "INSTALLED" if launcher.state.get(key) else "not installed"
            say("   %d. %-18s [%s]" % (i, label, mark))
        say("   %d. Back" % (len(MODS) + 1))
        say("")
        c = ask("  Choose 1-%d" % (len(MODS) + 1), str(len(MODS) + 1))
        if c.isdigit() and 1 <= int(c) <= len(MODS):
            screen_mod(launcher, MODS[int(c) - 1])
        elif c == str(len(MODS) + 1):
            return
        else:
            say("  -> please type 1, 2 or 3")


def screen_mod(launcher, mod):
    key, label = mod
    while True:
        header(launcher)
        say("")
        say("  %s" % label.upper())
        rule("-")
        state = "INSTALLED" if launcher.state.get(key) else "NOT INSTALLED"
        say("  Status: %s" % state)
        say("")
        if key == "randomizer":
            say("  Shuffles the stats of every item (damage, digging, HP, price,")
            say("  gift value, decay and more). Names, descriptions and recipes")
            say("  stay readable. Rolled again on every single launch, so you")
            say("  never get the same prison twice.")
        else:
            say("  Repairs the official Russian translation: fills in the lines")
            say("  that were never translated, fixes machine-translated item")
            say("  names, restores broken $variables, cleans up spacing and")
            say("  homoglyphs (Latin letters typed inside Russian words).")
            say("  The English files are used as the reference.")
        say("")
        say("   1. %s" % ("Uninstall" if launcher.state.get(key) else "Install"))
        say("   2. Back")
        say("")
        c = ask("  Choose 1-2", "2")
        if c == "1":
            if launcher.state.get(key):
                launcher.state[key] = False
                launcher.save_state()
                launcher.restore()
                say("")
                say("  %s uninstalled. Original files restored." % label)
            else:
                launcher.state[key] = True
                launcher.save_state()
                say("")
                say("  %s installed." % label)
                say("  It will be applied when you launch the game from here.")
            pause()
            return
        if c == "2":
            return
        say("  -> please type 1 or 2")


# ---------------------------------------------------------------------- main
def find_game_dir(arg=None):
    """Folder that holds TheEscapists.exe, always as an absolute path
    (the engine later uses it as a working directory for the game)."""
    seen = []
    if arg:
        seen.append(Path(arg))
    seen.append(Path(os.getcwd()))
    seen.append(Path(sys.argv[0]).resolve().parent.parent)
    for p in seen:
        try:
            p = Path(os.path.abspath(str(p)))
        except OSError:
            continue
        if (p / EXE_NAME).exists() and (p / "Data").exists():
            return p
    return None


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    game = None
    if "--game" in argv:
        i = argv.index("--game")
        if i + 1 < len(argv):
            game = argv[i + 1]
    gd = find_game_dir(game)
    if gd is None:
        say("")
        say("  ! %s not found." % EXE_NAME)
        say("    Put TE1_Mod_Launcher.bat in the game folder and run it there.")
        return 1
    if not (gd / "Data").exists():
        say("")
        say("  ! No Data subfolder next to %s." % EXE_NAME)
        return 1

    launcher = Launcher(gd)
    launcher.mods.mkdir(parents=True, exist_ok=True)
    launcher.load_state()
    # Safety net: if the previous run was killed before it could clean up
    # (closed console, crash, power cut), put the game files back first.
    launcher.restore(quiet=True)

    if "--status" in argv:
        say("game   : %s" % launcher.game)
        for key, label in MODS:
            say("%-20s %s" % (label, launcher.state.get(key)))
        return 0

    if "--restore" in argv:
        say("")
        n = launcher.restore()
        say("restored %d file(s)" % n)
        return 0

    if "--report" in argv:
        log = []
        say("")
        rule("-")
        say("  BETTER TRANSLATE - dry run")
        rule("-")
        n = mod_better_translate(launcher.data, log, dry=True)
        for line in log:
            say("   " + line)
        say("   total: %d change(s)" % n)
        say("")
        say("   Nothing was written - this was a dry run.")
        return 0

    if "--apply" in argv:
        ok, log = launcher.apply()
        for line in log:
            say("   " + line)
        return 0 if ok else 1

    screen_main(launcher)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except EndOfInput:
        say("")
        sys.exit(0)
    except KeyboardInterrupt:
        say("")
        say("interrupted")
        sys.exit(1)
