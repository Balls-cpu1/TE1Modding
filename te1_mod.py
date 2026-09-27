#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
te1_mod.py — универсальный мод-инструмент для The Escapists 1 (PC / Steam).

Один файл, никаких зависимостей кроме Python 3 (Blowfish встроен).
Запуск:  py te1_mod.py        (или python3 te1_mod.py)

Возможности:
  * папка mods/ + лаунчер .bat (валидатор val.dat обходится автоматически)
  * Мод «Русский перевод»      — правит items_rus.dat (имена + согласованные рецепты)
  * Мод «Рандомайзер»          — у каждого предмета случайные свойства
  * Мод «Фикс крафта»          — снимает лимит 200 предметов (патч exe)
  * Мод «Свой рецепт»          — добавляет настоящий рецепт в байткод exe
  * Мод «Дверь по форме»       — новая механика (патч exe)
  * Аудит файлов, конструктор предмета, откат

Всё, что касается exe, проверено: пересборка без правок даёт файл
байт-в-байт идентичный оригиналу (zlib level 9, шифр Fusion build 288).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import struct
import sys
import zlib
from pathlib import Path

VERSION = "1.0"

# ------------------------------------------------------------------ консоль
def _fix_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_fix_console()

def say(*a):
    print(*a)

def ask(prompt, default=None):
    s = input(f"{prompt}" + (f" [{default}]: " if default is not None else ": ")).strip()
    return s or (default if default is not None else "")

def ask_int(prompt, default=None, lo=None, hi=None):
    while True:
        s = ask(prompt, default)
        try:
            v = int(s)
        except ValueError:
            say("  -> нужно число"); continue
        if lo is not None and v < lo or hi is not None and v > hi:
            say(f"  -> вне диапазона {lo}..{hi}"); continue
        return v

def pause():
    try:
        input("\n[Enter] — продолжить...")
    except (EOFError, KeyboardInterrupt):
        pass


# =============================================================== Blowfish (LE)
class Blowfish:
    """Blowfish ECB с little-endian порядком слов — как в The Escapists.
    Проверено стандартным тест-вектором (selftest)."""

    _P = None
    _S = None

    def __init__(self, key: bytes):
        if Blowfish._P is None:
            Blowfish._init_tables()
        self.P = list(Blowfish._P)
        self.S = [list(x) for x in Blowfish._S]
        self._expand(key)

    # Полные константы Blowfish (P-array + 4 S-бокса, 1042 слова) —
    # шестнадцатеричные цифры числа π. Проверено двумя стандартными
    # тест-векторами: (key=0,pt=0)->4EF997456198DD78 и
    # (key=FF..FF,pt=FF..FF)->51866FD5B85ECB8A.
    _HEX = (
        "243f6a8885a308d313198a2e03707344a4093822299f31d0082efa98ec4e6c89"
        "452821e638d01377be5466cf34e90c6cc0ac29b7c97c50dd3f84d5b5b5470917"
        "9216d5d98979fb1bd1310ba698dfb5ac2ffd72dbd01adfb7b8e1afed6a267e96"
        "ba7c9045f12c7f9924a19947b3916cf70801f2e2858efc16636920d871574e69"
        "a458fea3f4933d7e0d95748f728eb658718bcd5882154aee7b54a41dc25a59b5"
        "9c30d5392af26013c5d1b023286085f0ca417918b8db38ef8e79dcb0603a180e"
        "6c9e0e8bb01e8a3ed71577c1bd314b2778af2fda55605c60e65525f3aa55ab94"
        "5748986263e8144055ca396a2aab10b6b4cc5c341141e8cea15486af7c72e993"
        "b3ee1411636fbc2a2ba9c55d741831f6ce5c3e169b87931eafd6ba336c24cf5c"
        "7a325381289586773b8f48986b4bb9afc4bfe81b6628219361d809ccfb21a991"
        "487cac605dec8032ef845d5de98575b1dc262302eb651b8823893e81d396acc5"
        "0f6d6ff383f442392e0b4482a484200469c8f04a9e1f9b5e21c66842f6e96c9a"
        "670c9c61abd388f06a51a0d2d8542f68960fa728ab5133a36eef0b6c137a3be4"
        "ba3bf0507efb2a98a1f1651d39af017666ca593e82430e888cee8619456f9fb4"
        "7d84a5c33b8b5ebee06f75d885c12073401a449f56c16aa64ed3aa62363f7706"
        "1bfedf72429b023d37d0d724d00a1248db0fead349f1c09b075372c980991b7b"
        "25d479d8f6e8def7e3fe501ab6794c3b976ce0bd04c006bac1a94fb6409f60c4"
        "5e5c9ec2196a246368fb6faf3e6c53b51339b2eb3b52ec6f6dfc511f9b30952c"
        "cc814544af5ebd09bee3d004de334afd660f2807192e4bb3c0cba85745c8740f"
        "d20b5f39b9d3fbdb5579c0bd1a60320ad6a100c6402c7279679f25fefb1fa3cc"
        "8ea5e9f8db3222f83c7516dffd616b152f501ec8ad0552ab323db5fafd238760"
        "53317b483e00df829e5c57bbca6f8ca01a87562edf1769dbd542a8f6287effc3"
        "ac6732c68c4f5573695b27b0bbca58c8e1ffa35db8f011a010fa3d98fd2183b8"
        "4afcb56c2dd1d35b9a53e479b6f84565d28e49bc4bfb9790e1ddf2daa4cb7e33"
        "62fb1341cee4c6e8ef20cada36774c01d07e9efe2bf11fb495dbda4dae909198"
        "eaad8e716b93d5a0d08ed1d0afc725e08e3c5b2f8e7594b78ff6e2fbf2122b64"
        "8888b812900df01c4fad5ea0688fc31cd1cff191b3a8c1ad2f2f2218be0e1777"
        "ea752dfe8b021fa1e5a0cc0fb56f74e818acf3d6ce89e299b4a84fe0fd13e0b7"
        "7cc43b81d2ada8d9165fa2668095770593cc7314211a1477e6ad206577b5fa86"
        "c75442f5fb9d35cfebcdaf0c7b3e89a0d6411bd3ae1e7e4900250e2d2071b35e"
        "226800bb57b8e0af2464369bf009b91e5563911d59dfa6aa78c14389d95a537f"
        "207d5ba202e5b9c5832603766295cfa911c819684e734a41b3472dca7b14a94a"
        "1b5100529a532915d60f573fbc9bc6e42b60a47681e6740008ba6fb5571be91f"
        "f296ec6b2a0dd915b6636521e7b9f9b6ff34052ec585566453b02d5da99f8fa1"
        "08ba47996e85076a4b7a70e9b5b32944db75092ec4192623ad6ea6b049a7df7d"
        "9cee60b88fedb266ecaa8c71699a17ff5664526cc2b19ee1193602a575094c29"
        "a0591340e4183a3e3f54989a5b429d656b8fe4d699f73fd6a1d29c07efe830f5"
        "4d2d38e6f0255dc14cdd20868470eb266382e9c6021ecc5e09686b3f3ebaefc9"
        "3c9718146b6a70a1687f358452a0e286b79c5305aa5007373e07841c7fdeae5c"
        "8e7d44ec5716f2b8b03ada37f0500c0df01c1f040200b3ffae0cf51a3cb574b2"
        "25837a58dc0921bdd19113f97ca92ff69432477322f547013ae5e58137c2dadc"
        "c8b576349af3dda7a94461460fd0030eecc8c73ea4751e41e238cd993bea0e2f"
        "3280bba1183eb3314e548b384f6db9086f420d03f60a04bf2cb8129024977c79"
        "5679b072bcaf89afde9a771fd9930810b38bae12dccf3f2e5512721f2e6b7124"
        "501adde69f84cd877a5847187408da17bc9f9abce94b7d8cec7aec3adb851dfa"
        "63094366c464c3d2ef1c18473215d908dd433b3724c2ba1612a14d432a65c451"
        "50940002133ae4dd71dff89e10314e5581ac77d65f11199b043556f1d7a3c76b"
        "3c11183b5924a509f28fe6ed97f1fbfa9ebabf2c1e153c6e86e34570eae96fb1"
        "860e5e0a5a3e2ab3771fe71c4e3d06fa2965dcb999e71d0f803e89d65266c825"
        "2e4cc9789c10b36ac6150eba94e2ea78a5fc3c531e0a2df4f2f74ea7361d2b3d"
        "1939260f19c279605223a708f71312b6ebadfe6eeac31f66e3bc4595a67bc883"
        "b17f37d1018cff28c332ddefbe6c5aa56558218568ab9802eecea50fdb2f953b"
        "2aef7dad5b6e2f841521b62829076170ecdd4775619f151013cca830eb61bd96"
        "0334fe1eaa0363cfb5735c904c70a239d59e9e0bcbaade14eecc86bc60622ca7"
        "9cab5cabb2f3846e648b1eaf19bdf0caa02369b9655abb5040685a323c2ab4b3"
        "319ee9d5c021b8f79b540b19875fa09995f7997e623d7da8f837889a97e32d77"
        "11ed935f166812810e358829c7e61fd696dedfa17858ba9957f584a51b227263"
        "9b83c3ff1ac24696cdb30aeb532e30548fd948e46dbc312858ebf2ef34c6ffea"
        "fe28ed61ee7c3c735d4a14d9e864b7e342105d14203e13e045eee2b6a3aaabea"
        "db6c4f15facb4fd0c742f442ef6abbb5654f3b1d41cd2105d81e799e86854dc7"
        "e44b476a3d816250cf62a1f25b8d2646fc8883a0c1c7b6a37f1524c369cb7492"
        "47848a0b5692b285095bbf00ad19489d1462b17423820e0058428d2a0c55f5ea"
        "1dadf43e233f70613372f0928d937e41d65fecf16c223bdb7cde3759cbee7460"
        "4085f2a7ce77326ea607808419f8509ee8efd85561d99735a969a7aac50c06c2"
        "5a04abfc800bcadc9e447a2ec3453484fdd567050e1e9ec9db73dbd3105588cd"
        "675fda79e3674340c5c43465713e38d83d28f89ef16dff20153e21e78fb03d4a"
        "e6e39f2bdb83adf7e93d5a68948140f7f64c261c94692934411520f77602d4f7"
        "bcf46b2ed4a20068d40824713320f46a43b7d4b7500061af1e39f62e97244546"
        "14214f74bf8b88404d95fc1d96b591af70f4ddd366a02f45bfbc09ec03bd9785"
        "7fac6dd031cb850496eb27b355fd3941da2547e6abca0a9a28507825530429f4"
        "0a2c86dae9b66dfb68dc1462d7486900680ec0a427a18dee4f3ffea2e887ad8c"
        "b58ce0067af4d6b6aace1e7cd3375fecce78a399406b2a4220fe9e35d9f385b9"
        "ee39d7ab3b124e8b1dc9faf74b6d185626a36631eae397b23a6efa74dd5b4332"
        "6841e7f7ca7820fbfb0af54ed8feb397454056acba48952755533a3a20838d87"
        "fe6ba9b7d096954b55a867bca1159a58cca9296399e1db33a62a4a563f3125f9"
        "5ef47e1c9029317cfdf8e80204272f7080bb155c05282ce395c11548e4c66d22"
        "48c1133fc70f86dc07f9c9ee41041f0f404779a45d886e17325f51ebd59bc0d1"
        "f2bcc18f41113564257b7834602a9c60dff8e8a31f636c1b0e12b4c202e1329e"
        "af664fd1cad181156b2395e0333e92e13b240b62eebeb92285b2a20ee6ba0d99"
        "de720c8c2da2f728d012784595b794fd647d0862e7ccf5f05449a36f877d48fa"
        "c39dfd27f33e8d1e0a476341992eff743a6f6eabf4f8fd37a812dc60a1ebddf8"
        "991be14cdb6e6b0dc67b55106d672c372765d43bdcd0e804f1290dc7cc00ffa3"
        "b5390f92690fed0b667b9ffbcedb7d9ca091cf0bd9155ea3bb132f88515bad24"
        "7b9479bf763bd6eb37392eb3cc1159798026e297f42e312d6842ada7c66a2b3b"
        "12754ccc782ef11c6a124237b79251e706a1bbe64bfb63501a6b101811caedfa"
        "3d25bdd8e2e1c3c9444216590a121386d90cec6ed5abea2a64af674eda86a85f"
        "bebfe98864e4c3fe9dbc8057f0f7c08660787bf86003604dd1fd8346f6381fb0"
        "7745ae04d736fccc83426b33f01eab71b08041873c005e5f77a057bebde8ae24"
        "55464299bf582e614e58f48ff2ddfda2f474ef388789bdc25366f9c3c8b38e74"
        "b475f25546fcd9b97aeb26618b1ddf84846a0e79915f95e2466e598e20b45770"
        "8cd55591c902de4cb90bace1bb8205d011a862487574a99eb77f19b6e0a9dc09"
        "662d09a1c4324633e85a1f0209f0be8c4a99a0251d6efe101ab93d1d0ba5a4df"
        "a186f20f2868f169dcb7da83573906fea1e2ce9b4fcd7f5250115e01a70683fa"
        "a002b5c40de6d0279af88c27773f8641c3604c0661a806b5f0177a28c0f586e0"
        "006058aa30dc7d6211e69ed72338ea6353c2dd94c2c21634bbcbee5690bcb6de"
        "ebfc7da1ce591d766f05e4094b7c018839720a3d7c927c2486e3725f724d9db9"
        "1ac15bb4d39eb8fced54557808fca5b5d83d7cd34dad0fc41e50ef5eb161e6f8"
        "a28514d96c51133c6fd5c7e756e14ec4362abfceddc6c837d79a323492638212"
        "670efa8e406000e03a39ce37d3faf5cfabc277375ac52d1b5cb0679e4fa33742"
        "d382274099bc9bbed5118e9dbf0f7315d62d1c7ec700c47bb78c1b6b21a19045"
        "b26eb1be6a366eb45748ab2fbc946e79c6a376d26549c2c8530ff8ee468dde7d"
        "d5730a1d4cd04dc62939bbdba9ba4650ac9526e8be5ee304a1fad5f06a2d519a"
        "63ef8ce29a86ee22c089c2b843242ef6a51e03aa9cf2d0a483c061ba9be96a4d"
        "8fe51550ba645bd62826a2f9a73a3ae14ba99586ef5562e9c72fefd3f752f7da"
        "3f046f6977fa0a5980e4a91587b086019b09e6ad3b3ee593e990fd5a9e34d797"
        "2cf0b7d9022b8b5196d5ac3a017da67dd1cf3ed67c7d2d281f9f25cfadf2b89b"
        "5ad6b4725a88f54ce029ac71e019a5e647b0acfded93fa9be8d3c48d283b57cc"
        "f8d5662979132e28785f0191ed756055f7960e44e3d35e8c15056dd488f46dba"
        "03a161250564f0bdc3eb9e153c9057a297271aeca93a072a1b3f6d9b1e6321f5"
        "f59c66fb26dcf3197533d928b155fdf5035634828aba3cbb28517711c20ad9f8"
        "abcc5167ccad925f4de817513830dc8e379d58629320f991ea7a90c2fb3e7bce"
        "5121ce64774fbe32a8b6e37ec3293d4648de53696413e680a2ae0810dd6db224"
        "69852dfd09072166b39a460a6445c0dd586cdecf1c20c8ae5bbef7dd1b588d40"
        "ccd2017f6bb4e3bbdda26a7e3a59ff453e350a44bcb4cdd572eacea8fa6484bb"
        "8d6612aebf3c6f47d29be463542f5d9eaec2771bf64e6370740e0d8de75b1357"
        "f8721671af537d5d4040cb084eb4e2cc34d2466a0115af84e1b0042895983a1d"
        "06b89fb4ce6ea0486f3f3b823520ab82011a1d4b277227f8611560b1e7933fdc"
        "bb3a792b344525bda08839e151ce794b2f32c9b7a01fbac9e01cc87ebcc7d1f6"
        "cf0111c3a1e8aac71a908749d44fbd9ad0dadecbd50ada380339c32ac6913667"
        "8df9317ce0b12b4ff79e59b743f5bb3af2d519ff27d9459cbf97222c15e6fc2a"
        "0f91fc719b941525fae59361ceb69cebc2a8645912baa8d1b6c1075ee3056a0c"
        "10d25065cb03a442e0ec6e0e1698db3b4c98a0be3278e9649f1f9532e0d392df"
        "d3a0342b8971f21e1b0a74414ba3348cc5be7120c37632d8df359f8d9b992f2e"
        "e60b6f470fe3f11de54cda541edad891ce6279cfcd3e7e6f1618b166fd2c1d05"
        "848fd2c5f6fb2299f523f357a632762393a8353156cccd02acf081625a75ebb5"
        "6e16369788d273ccde96629281b949d04c50901b71c65614e6c6c7bd327a140a"
        "45e1d006c3f27b9ac9aa53fd62a80f00bb25bfe235bdd2f671126905b2040222"
        "b6cbcf7ccd769c2b53113ec01640e3d338abbd602547adf0ba38209cf746ce76"
        "77afa1c52075606085cbfe4e8ae88dd87aaaf9b04cf9aa7e1948c25c02fb8a8c"
        "01c36ae4d6ebe1f990d4f869a65cdea03f09252dc208e69fb74e6132ce77e25b"
        "578fdfe33ac372e6"
    )

    @staticmethod
    def _init_tables():
        vals = [int(Blowfish._HEX[i:i + 8], 16)
                for i in range(0, len(Blowfish._HEX), 8)]
        Blowfish._P = vals[:18]
        Blowfish._S = [vals[18 + i * 256: 18 + (i + 1) * 256] for i in range(4)]

    @staticmethod
    def _f(S, x):
        return (((S[0][(x >> 24) & 0xFF] + S[1][(x >> 16) & 0xFF]) & 0xFFFFFFFF)
                ^ S[2][(x >> 8) & 0xFF]) + S[3][x & 0xFF] & 0xFFFFFFFF

    def _enc_block(self, l, r):
        for i in range(16):
            l ^= self.P[i]
            r ^= self._f(self.S, l) & 0xFFFFFFFF
            l, r = r, l
        l, r = r, l
        r ^= self.P[16]
        l ^= self.P[17]
        return l & 0xFFFFFFFF, r & 0xFFFFFFFF

    def _expand(self, key):
        klen = len(key)
        j = 0
        for i in range(18):
            v = 0
            for _ in range(4):
                v = ((v << 8) | key[j % klen]) & 0xFFFFFFFF
                j += 1
            self.P[i] ^= v
        l = r = 0
        for i in range(0, 18, 2):
            l, r = self._enc_block(l, r)
            self.P[i], self.P[i + 1] = l, r
        for si in range(4):
            for i in range(0, 256, 2):
                l, r = self._enc_block(l, r)
                self.S[si][i], self.S[si][i + 1] = l, r

    @staticmethod
    def _swap4(b):
        return b"".join(b[i:i + 4][::-1] for i in range(0, len(b), 4))

    def encrypt(self, data):
        out = bytearray()
        for i in range(0, len(data), 8):
            blk = self._swap4(data[i:i + 8])
            l, r = struct.unpack(">II", blk)
            l, r = self._enc_block(l, r)
            out += struct.pack(">II", l, r)
        return bytes(out)

    def decrypt(self, data):
        out = bytearray()
        for i in range(0, len(data), 8):
            l, r = struct.unpack(">II", data[i:i + 8])
            # обратный ход
            for i2 in range(17, 1, -1):
                l ^= self.P[i2]
                r ^= self._f(self.S, l) & 0xFFFFFFFF
                l, r = r, l
            l, r = r, l
            r ^= self.P[1]
            l ^= self.P[0]
            out += self._swap4(struct.pack(">II", l & 0xFFFFFFFF, r & 0xFFFFFFFF))
        return bytes(out)


def bf_selftest():
    bf = Blowfish(bytes(8))
    ct = bf.encrypt(bytes(8))
    ok = ct.hex().upper() == "4EF997456198DD78"
    rt = bf.decrypt(ct) == bytes(8)
    return ok and rt


# =============================================================== шифр Fusion
def _rotl1(x):
    return ((x << 7) | (x >> 1)) & 0xFF


class FusionCipher:
    """Порт CTFAK-Native encryption.cpp — дешифровка чанков exe (build 288)."""

    def __init__(self, title, copyright_, project, magic=54):
        self.key = self._make_key(title, copyright_, project, magic)
        self.table, self.valid = self._decode(self.key, magic)
        self._ks = None

    @staticmethod
    def _make_key(title, copyright_, project, magic=54):
        blob = (title + copyright_ + project).encode("latin1", "replace")
        buf = bytearray(256)
        n = min(len(blob), 256)
        buf[:n] = blob[:n]
        for i in range(128, 256):
            buf[i] = 0
        v33 = 0
        while v33 < 256 and buf[v33]:
            v33 += 1
        v35 = v34 = magic & 0xFF
        for i in range(v33 + 1):
            v34 = _rotl1(v34)
            buf[i] ^= v34
            v35 = (v35 + buf[i] * ((v34 & 1) + 2)) & 0xFF
        buf[v33 + 1] = v35
        return bytes(buf)

    @staticmethod
    def _decode(key, magic=54):
        buf = list(range(256))
        mc2 = mc3 = magic & 0xFF
        pos = 0
        v17 = 0
        v15 = True
        rtn = False
        for i in range(256):
            mc3 = _rotl1(mc3)
            if v15:
                mc2 = (mc2 + ((mc3 & 1) + 2) * key[pos]) & 0xFF
            temp = mc3 ^ key[pos]
            if mc3 == key[pos]:
                if v15:
                    rtn = (mc2 == key[pos + 1])
                mc3 = _rotl1(magic & 0xFF)
                pos = 0
                v15 = False
                temp = mc3 ^ key[0]
            v13 = buf[i]
            v17 = (v17 + ((temp + v13) & 0xFF)) & 0xFF
            buf[i] = buf[v17]
            pos += 1
            buf[v17] = v13
        return buf, rtn

    def keystream(self, n):
        if self._ks is None or len(self._ks) < n:
            b = list(self.table)
            i1 = i2 = 0
            out = bytearray()
            for _ in range(max(n, 8192)):
                i1 = (i1 + 1) & 0xFF
                v7 = b[i1]
                i2 = (i2 + v7) & 0xFF
                v9 = b[i2]
                b[i1] = v9
                b[i2] = v7
                out.append(b[(v7 + v9) & 0xFF])
            self._ks = bytes(out)
        return self._ks[:n]

    def transform(self, data):
        ks = self.keystream(len(data))
        return bytes(a ^ b for a, b in zip(data, ks))


# =============================================================== .dat файлы
def sniff_encoding(b: bytes) -> str:
    if b.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if b.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if b.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    head = b[:800]
    if head and head.count(b"\x00") > len(head) * 0.15:
        return "utf-16-le"
    for enc in ("utf-8", "cp1251"):
        try:
            b.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detect_plain(raw: bytes):
    """Определяет, открытый ли это текст, и в какой кодировке.
    → (True, enc) | (False, None).  Важно: UTF-16 содержит нули,
    поэтому обычная проверка «много ли печатных байтов» его отвергает."""
    if not raw:
        return False, None
    # явные BOM
    if raw.startswith(b"\xff\xfe"):
        return True, "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return True, "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return True, "utf-8-sig"

    head = raw[:2048]
    nulls = head.count(b"\x00")

    # признак UTF-16: много нулей, и они стоят через байт
    if nulls > len(head) * 0.15:
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                t = head.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
            printable = sum(1 for c in t if c.isprintable() or c in "\r\n\t")
            if t and printable / len(t) > 0.85:
                return True, enc
        return False, None            # нули есть, но текст не читается → шифр

    # обычный однобайтовый текст
    textish = sum(1 for c in head if 32 <= c < 127 or c in (9, 10, 13))
    if textish / len(head) > 0.85:
        for enc in ("utf-8", "cp1251"):
            try:
                raw.decode(enc)
                return True, enc
            except UnicodeDecodeError:
                continue
        return True, "latin-1"

    # кириллица без BOM: много байтов 0x80..0xFF.
    # Сначала строго пробуем UTF-8 (у кириллицы там пары 0xD0/0xD1),
    # и только если он не подошёл — cp1251 по структуре INI.
    high = sum(1 for c in head if c >= 0x80)
    if high > len(head) * 0.10:
        try:
            raw.decode("utf-8")
            return True, "utf-8"
        except UnicodeDecodeError:
            pass
        try:
            t = head.decode("cp1251")
        except UnicodeDecodeError:
            return False, None
        marks = t.count("[") + t.count("=") + t.count("\n")
        if marks >= 8:
            return True, "cp1251"
    return False, None


def looks_plaintext(b: bytes) -> bool:
    return detect_plain(b)[0]


def read_text_file(path: Path):
    """→ (текст, кодировка, был_зашифрован)"""
    raw = path.read_bytes()
    plain, enc = detect_plain(raw)
    if plain:
        return raw.decode(enc, "replace"), enc, False
    bf = Blowfish(b"mothking")
    dec = bf.decrypt(raw[:len(raw) - len(raw) % 8]).rstrip(b"\0")
    _, enc2 = detect_plain(dec)
    enc2 = enc2 or "utf-8"
    return dec.decode(enc2, "replace"), enc2, True


def write_text_file(path: Path, text: str, enc: str, encrypt: bool):
    data = text.encode(enc, "replace")
    if encrypt:
        pad = (8 - len(data) % 8) % 8
        data = bf_encrypt_to_bytes(data + b"\0" * pad)
    path.write_bytes(data)


def bf_encrypt_to_bytes(data: bytes) -> bytes:
    return Blowfish(b"mothking").encrypt(data)


# ------------------------------------------------------------------ val.dat
def md5_size(size: int) -> str:
    return hashlib.md5(("l0l_%d" % size).encode()).hexdigest()


def rebuild_val(data_dir: Path, force_langs=None):
    vpath = data_dir / "val.dat"
    if not vpath.exists():
        say("  ! val.dat не найден — пропускаю")
        return 0
    raw = vpath.read_bytes()
    txt = raw.decode("utf-16-le", "replace")
    bom = txt.startswith("\ufeff")
    if bom:
        txt = txt[1:]
    import re
    langs = {"e": "eng", "f": "fre", "g": "ger", "s": "spa", "r": "rus", "p": "pol", "i": "ita"}
    kinds = ["data", "items", "speech"]
    changed = 0
    for letter, lang in langs.items():
        m = re.search(r"(^|\n)(%s=)([0-9a-f]{32})_([0-9a-f]{32})_([0-9a-f]{32})" % letter, txt)
        if not m:
            continue
        toks = [m.group(3), m.group(4), m.group(5)]
        for i, kind in enumerate(kinds):
            fp = data_dir / f"{kind}_{lang}.dat"
            if fp.exists():
                toks[i] = md5_size(fp.stat().st_size)
        new = m.group(1) + m.group(2) + "_".join(toks)
        txt = txt[:m.start()] + new + txt[m.end():]
        changed += 1
    out = ("\ufeff" if bom else "") + txt
    vpath.write_bytes(out.encode("utf-16-le"))
    return changed


# ------------------------------------------------------------------ items INI
def parse_items(text: str):
    """→ ({id: {key: val}}, [порядок])"""
    import re
    items, order, cur, cur_id = {}, [], None, None
    for line in text.splitlines():
        m = re.match(r"^\s*\[(\d+)\]\s*$", line)
        if m:
            cur_id = int(m.group(1))
            cur = {}
            items[cur_id] = cur
            order.append(cur_id)
            continue
        m = re.match(r"^\s*([A-Za-z_]+)\s*=\s*(.*)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    return items, order


def build_items_text(header: str, items: dict, order: list, newline="\r\n") -> str:
    out = [header.rstrip("\r\n")] if header.strip() else []
    for iid in order:
        out.append("")
        out.append(f"[{iid}]")
        for k, v in items[iid].items():
            out.append(f"{k}={v}")
    return newline.join(out) + newline


# =============================================================== RU перевод
# Полная таблица корректных русских названий (ID -> Name).
# Составлена по английскому оригиналу всех 279 предметов.
RU_NAMES = {
    0: "Ключ от камеры", 1: "Ключ персонала", 2: "Мятные конфеты",
    3: "Форма охранника", 4: "Роба заключённого", 5: "Крепкая лопата",
    6: "Ключ от входа", 7: "Ключ от подсобки", 8: "Зажигалка", 9: "Часы",
    10: "Бутылка лекарства", 11: "Электрошокер", 12: "Доска",
    13: "Рулон скотча", 14: "Крем для бритья", 15: "Журнал",
    16: "Снотворное", 17: "Расчёска", 18: "Осколок стекла",
    19: "Стеклянная заточка", 20: "Мёртвая крыса", 21: "Огнетушитель",
    22: "Радиоприёмник", 23: "Пластиковая ложка", 24: "Отвёртка",
    25: "Лом", 26: "Земля", 27: "Пластиковый нож", 28: "Пластиковая вилка",
    29: "Дубинка", 30: "Лопатка", 31: "Мотыга", 32: "Метла",
    33: "Садовые ножницы", 34: "Молоток", 35: "Швабра", 36: "Банка чернил",
    37: "Отбеливатель", 38: "Форма медика", 39: "Крепкая кирка",
    40: "Мастерок", 41: "Блок стены", 42: "Бетон", 43: "Рабочий ключ",
    44: "Кусок верёвки", 45: "Зубная паста", 46: "Плитка шоколада",
    47: "Туалетная бумага", 48: "Мыло", 49: "Колода карт", 50: "Книга",
    51: "Суперклей", 52: "Тальк", 53: "Кусок замазки", 54: "Свеча",
    56: "Бальсовое дерево", 57: "Парус", 58: "Пластиковый рабочий ключ",
    59: "Форма для рабочего ключа", 60: "Фонарик", 61: "Крепкие кусачки",
    62: "Напильник", 63: "Грязная форма охранника", 64: "Грязная роба",
    65: "Сырая еда", 66: "Готовая еда", 67: "Крышка вентиляции",
    68: "Стремянка", 69: "Простыня", 70: "Ключ от столярки",
    71: "Форма для ключа персонала", 72: "Деревянная подпорка",
    73: "Батарейка", 74: "Носок", 75: "Неокрашенный стул",
    76: "Лист металла", 77: "Номерной знак", 78: "Ключ от металлоцеха",
    79: "Мешок цемента", 80: "Вантуз", 81: "Верёвка из простыней",
    82: "Форма для ключа подсобки", 83: "Форма для ключа камеры",
    84: "Расплавленный пластик", 85: "Пластиковый ключ подсобки",
    86: "Пластиковый ключ персонала", 87: "Пластиковый ключ камеры",
    88: "Пластиковый ключ входа", 89: "Форма для ключа входа", 90: "Кружка",
    91: "Маленький динамик", 92: "Плата", 93: "Скрепка", 94: "Лезвие",
    95: "Подушка", 96: "Зубная щётка", 97: "Заточка из щётки",
    98: "Проволока", 99: "Плакат", 100: "Фольга", 101: "Папье-маше",
    102: "Набор для татуировок", 103: "Кистень из носка",
    104: "Супер-кистень из носка", 105: "Кружка растопленного шоколада",
    106: "Игровой набор", 107: "Игральный кубик", 108: "Нунчаки",
    109: "Заточка из расчёски", 110: "Кнут", 111: "Кастет",
    112: "Голова кошки", 113: "Крюк-кошка", 114: "Облегчённая лопата",
    115: "Хлипкая лопата", 116: "Фальшивый блок стены",
    117: "Фальшивая крышка вентиляции", 118: "Хлипкая кирка",
    119: "Облегчённая кирка", 120: "Хлипкие кусачки",
    121: "Облегчённые кусачки", 122: "Рукоятка инструмента",
    123: "Заметка о крафте", 124: "Лезвие из расчёски",
    125: "Тайник для контрабанды", 126: "Манекен в кровати",
    127: "Форма военнопленного", 128: "Мягкая роба", 129: "Стёганая роба",
    130: "Укреплённая роба", 131: "Аптечка", 132: "Шляпа", 133: "Жилет",
    134: "Трусы", 135: "Шорты", 136: "Иголка с ниткой", 137: "Ткань",
    138: "Посылка", 139: "Посылка", 140: "Посылка", 141: "Письмо",
    142: "Мягкая форма военнопленного", 143: "Стёганая форма военнопленного",
    144: "Укреплённая форма военнопленного", 145: "Пульт от телевизора",
    146: "Губка", 147: "DVD-диск", 148: "Печенье", 149: "Маффин",
    150: "Экзотическое перо", 151: "Бананы",
    152: "Документы без подписи", 153: "Документы", 154: "Зелёная трава",
    155: "Красная трава", 156: "Шёлковый платок",
    157: "Элитная туалетная бумага", 158: "Зубная нить",
    159: "Плюшевый мишка", 160: "Крем для рук", 161: "Открытка",
    162: "Педикюрный набор", 163: "Веер", 164: "Карманные часы",
    165: "Семейное фото", 166: "Медаль за службу", 167: "Армейский жетон",
    168: "Лианы", 169: "Кокос", 170: "Манго", 171: "Красный перец чили",
    172: "Песок", 173: "Сомбреро", 174: "Фальшивый забор", 175: "Пончо",
    176: "Сырое буррито", 177: "Буррито", 178: "Племенной барабан",
    179: "Гвозди", 180: "Шипованная лента", 181: "Мультитул",
    182: "Деревянная бита", 183: "Бита с шипами",
    184: "Прочный тайник для контрабанды", 185: "Режущая нить",
    186: "Электроотвёртка", 187: "Основа плота", 188: "Самодельный плот",
    189: "Крюк для канатной дороги", 190: "Пончик DoDo",
    191: "Бочка пенария", 192: "Древесный уголь",
    193: "Ёмкость для смешивания", 194: "Гофрированное железо",
    195: "Взрывная смесь", 196: "Удобрение",
    197: "Самодельный взрывной снаряд", 198: "Взрывчатое вещество",
    199: "Самодельный фитиль", 200: "Самодельный ствол танка",
    201: "Самодельная база танка", 202: "Самодельная башня танка",
    203: "Металлический конус", 204: "Металлическая труба", 205: "Калий",
    206: "Перстень-монета", 207: "Лучина", 208: "Мусорный пакет",
    209: "Лосьон после бритья", 210: "Форма заключённого",
    211: "Форма солдата", 212: "Магнитофон", 213: "Запись голоса",
    214: "Мемуары на плёнке", 215: "Смокинг", 216: "Грязный смокинг",
    217: "Синяя замазка", 218: "Липкая лента", 219: "Грязное стекло",
    220: "Ключ-карта", 221: "Поддельный отпечаток пальца",
    222: "Бомба-сюрприз", 224: "Фальшивое расписное яйцо",
    225: "Огнемёт", 226: "Лак для волос", 227: "Фальшивая обувь",
    228: "Форма приспешника", 229: "Грязная форма приспешника",
    230: "Нож в ботинке", 231: "Часы с режущим лазером",
    232: "Шляпа с металлическими полями", 233: "Шляпа порк-пай",
    234: "Шокер-ручка", 235: "Часы с удавкой",
    236: "Слабый отпечаток пальца", 237: "Острый поднос",
    238: "Костюм эльфа", 239: "Костюм эльфа-охранника", 240: "Лампочки",
    241: "Хлопушка", 242: "Гирлянда", 243: "Блёстки",
    244: "Рычаг-леденец", 245: "Гигантский леденец",
    246: "Пирог с начинкой", 247: "Подарки", 248: "Рождественский чулок",
    249: "Мишура", 250: "Деревянный шарик", 251: "Деревянный кубик",
    252: "Деревянная кукла", 253: "Деревянный самокат",
    254: "Упаковочная бумага", 255: "Письмо непослушному",
    256: "Письмо послушному", 257: "Стамеска", 258: "Деревянный джойстик",
    259: "Игра Worms", 260: "Бейсбольная бита", 261: "Магнит",
    262: "Пробка", 263: "Пустая бутылка", 264: "Рабочая каска",
    265: "Игла", 266: "Намагниченная игла", 267: "Топливо",
    268: "Мощный фонарь", 269: "Галогенная лампа",
    270: "Навигационный фонарь", 271: "Миска оленя", 272: "Бутылка воды",
    273: "Миска воды", 274: "Сырая противная морковь",
    275: "Сочная варёная морковь", 276: "Самодельный компас",
    277: "Красная сельдь", 278: "Ускоритель",
}

# Особо частые ошибки локализации: неправильный вариант -> правильный.
# (Сюда можно дописывать найденные ошибки — применяется к Name и к рецептам.)
RU_FIXUPS = {
    "ключ от каморки": "Ключ от камеры",
    "охранник форма": "Форма охранника",
    "форма охранник": "Форма охранника",
    "лопата крепкая": "Крепкая лопата",
    "скочь": "Рулон скотча",
    "скотч рулон": "Рулон скотча",
    "отвертка": "Отвёртка",
    "зубная щетка": "Зубная щётка",
    "щётка зубная": "Зубная щётка",
    "расческа": "Расчёска",
    "ведёрко краски": "Ведро краски",
    "подушка ": "Подушка",
}


# =============================================================== EXE (Fusion)
CH_END = 32639


def find_stream(d: bytes) -> int:
    def walk(off):
        r = off
        while r + 8 <= len(d):
            cid, flag, size = struct.unpack_from("<hhi", d, r)
            if not (0 <= flag <= 3) or not (0 <= size < 20_000_000):
                return None
            r += 8 + size
            if cid == CH_END:
                return r
        return None
    for off in range(0x1000, min(len(d), 0x500000)):
        cid, flag, size = struct.unpack_from("<hhi", d, off)
        if cid in (8738, 8739) and 0 <= flag <= 3 and 0 < size < 100000:
            if walk(off):
                return off
    raise RuntimeError("поток чанков Fusion не найден — это точно exe The Escapists?")


def read_chunks(d: bytes, start: int):
    out, r = [], start
    while r + 8 <= len(d):
        cid, flag, size = struct.unpack_from("<hhi", d, r)
        out.append((cid, flag, d[r + 8:r + 8 + size]))
        r += 8 + size
        if cid == CH_END:
            break
    return out


def dechunk(raw: bytes):
    out, r = [], 0
    while r + 8 <= len(raw):
        cid, flag, size = struct.unpack_from("<hhi", raw, r)
        if size < 0 or r + 8 + size > len(raw):
            break
        out.append((cid, flag, raw[r + 8:r + 8 + size]))
        r += 8 + size
        if cid == CH_END:
            break
    return out


def uni(b: bytes) -> str:
    try:
        return b.decode("utf-16-le")
    except Exception:
        return b.decode("latin1", "replace")


class Exe:
    """Работа с TheEscapists.exe: чанки, события фрейма, пересборка."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.stream_off = find_stream(self.data)
        self.chunks = read_chunks(self.data, self.stream_off)
        by = {}
        for c in self.chunks:
            by.setdefault(c[0], []).append(c)
        zdec = lambda raw: zlib.decompress(raw[8:8 + struct.unpack_from("<I", raw, 4)[0]])
        title = uni(zdec(by[8740][0][2])).strip("\0")
        copyr = uni(zdec(by[8763][0][2])).strip("\0")
        editor = uni(zdec(by[8750][0][2])).strip("\0")
        self.cipher = FusionCipher(title, copyr, editor)
        self.frames = [i for i, c in enumerate(self.chunks) if c[0] == 13107]

    # -- чанки flag=3 ------------------------------------------------
    def decode3(self, cid, raw):
        body = bytearray(raw[4:])
        if cid & 1:
            body[0] ^= (cid & 0xFF) ^ (cid >> 8)
        t = self.cipher.transform(bytes(body))
        cs, = struct.unpack_from("<I", t, 0)
        return zlib.decompress(t[4:4 + cs])

    def encode3(self, cid, plain):
        comp = zlib.compress(plain, 9)
        t = struct.pack("<I", len(comp)) + comp
        body = bytearray(self.cipher.transform(t))
        if cid & 1:
            body[0] ^= (cid & 0xFF) ^ (cid >> 8)
        return struct.pack("<I", len(plain)) + bytes(body)

    # -- фреймы ------------------------------------------------------
    def frame_name(self, idx):
        subs = dechunk(self.chunks[idx][2])
        for scid, sflag, sraw in subs:
            if scid == 13109:
                body = sraw
                if sflag == 1:                      # сжатый подчанк
                    cs, = struct.unpack_from("<I", sraw, 4)
                    body = zlib.decompress(sraw[8:8 + cs])
                elif sflag == 3:
                    body = self.decode3(scid, sraw)
                return uni(body).strip("\0")
        return "?"

    def find_frame(self, name="game"):
        for idx in self.frames:
            if self.frame_name(idx) == name:
                return idx
        raise RuntimeError(f"фрейм {name!r} не найден")

    def get_events(self, frame="game"):
        idx = self.find_frame(frame)
        subs = dechunk(self.chunks[idx][2])
        for scid, sflag, sraw in subs:
            if scid == 13117:
                return idx, self.decode3(scid, sraw)
        raise RuntimeError("в фрейме нет чанка событий 13117")

    def set_events(self, idx, events):
        cid, flag, data = self.chunks[idx]
        subs = dechunk(data)
        out = []
        for scid, sflag, sraw in subs:
            body = self.encode3(scid, events) if scid == 13117 else sraw
            out.append(struct.pack("<hhi", scid, sflag, len(body)) + body)
        self.chunks[idx] = (cid, flag, b"".join(out))

    def save(self, out_path):
        buf = [self.data[:self.stream_off]]
        for cid, flag, data in self.chunks:
            buf.append(struct.pack("<hhi", cid, flag, len(data)) + data)
        Path(out_path).write_bytes(b"".join(buf))
        return Path(out_path).stat().st_size


# =============================================================== конструктор событий
def _u16(v): return struct.pack("<H", v & 0xFFFF)
def _i16(v): return struct.pack("<h", v)
def _i32(v): return struct.pack("<i", v)


def ev_str(s: str) -> bytes:
    """Выражение-строка (system, num=3)."""
    b = s.encode("utf-16-le") + b"\0\0"
    return _i16(-1) + _u16(3) + _u16(6 + len(b)) + b


def ev_long(v: int) -> bytes:
    """Выражение-число (system, num=0)."""
    return _i16(-1) + _u16(0) + _u16(10) + _i32(v)


def ev_marker() -> bytes:
    """sys-2 маркер (otype=-1, num=-2)."""
    return _i16(-1) + struct.pack("<h", -2) + _u16(6)


def ev_named_var(name: str, getter=True) -> bytes:
    """Выражение «Named variable object:<80|81> имя sys-2».
    getter=True → чтение (81), иначе запись-ссылка (80)."""
    head = struct.pack("<hhh", 36, 81 if getter else 80, 10) + _u16(180) + _i16(0)
    return head + ev_str(name) + ev_marker()


def ev_gstr(index: int) -> bytes:
    """Выражение «глобальная строка №index»."""
    return _i16(-1) + _u16(50) + _u16(10) + _i32(index)


TERM = b"\0\0\0\0"


def param(code: int, payload: bytes) -> bytes:
    return _u16(4 + len(payload)) + _u16(code) + payload


def p_str(s: str) -> bytes:
    """Параметр-строка (code 45)."""
    return param(45, _u16(0) + ev_str(s) + TERM)


def p_long(v: int) -> bytes:
    """Параметр-число (code 22)."""
    return param(22, _u16(0) + ev_long(v) + TERM)


def p_cmp_str(expr: bytes, s: str) -> bytes:
    """Параметр сравнения со строкой (code 23)."""
    return param(23, _u16(0) + expr + TERM)


def p_expr(expr: bytes) -> bytes:
    return param(22, _u16(0) + expr + TERM)


def condition(num, params, obj_type=-1, obj_info=0, flags=0x20, ident=0):
    n = len(params)
    head = (_i16(obj_type) + _i16(num) + _u16(obj_info) + _i16(0) +
            bytes([flags, 0, n, 0]) + _i16(ident))
    body = head + b"".join(params)
    return _u16(2 + len(body)) + body


def action(num, params, obj_type=-1, obj_info=0, flags=0):
    n = len(params)
    head = (_i16(obj_type) + _i16(num) + _u16(obj_info) + _i16(0) +
            bytes([flags, 0, n, 0]))
    body = head + b"".join(params)
    return _u16(2 + len(body)) + body


def group(conds, acts, flags=0x2000):
    body = (bytes([len(conds), len(acts)]) + _u16(flags) + _i16(0) +
            _i32(0) + _i32(0) + b"".join(conds) + b"".join(acts))
    return _i16(-(2 + len(body))) + body


def append_groups(events: bytes, new_groups) -> bytes:
    """Дописывает группы в конец блока ERev, правит размеры ERes/ERev."""
    end = events.rindex(b"<<ER")
    erev = events.rindex(b"ERev", 0, end)
    add = b"".join(new_groups)
    out = bytearray(events[:end] + add + events[end:])
    struct.pack_into("<i", out, erev + 4, (end - (erev + 8)) + len(add))
    eres = events.rindex(b"ERes", 0, erev)
    struct.pack_into("<i", out, eres + 4, struct.unpack_from("<i", out, eres + 4)[0] + len(add))
    return bytes(out)


# --- конкретные группы ------------------------------------------------
NVO = 180   # handle объекта Named variable object


def grp_recipe(combo: str, out_id: int, give_back: int) -> bytes:
    """Рецепт: ЕСЛИ CraftSum И CraftString==combo ТО CraftOutput=out_id ...
    Точная копия структуры оригинальной группы #2916."""
    c1 = condition(-16, [p_str("CraftSum")], flags=0, ident=-32010)
    c2 = condition(-3, [p_expr(ev_named_var("CraftString")), p_cmp_str(ev_str(combo), combo)],
                   flags=0x20, ident=-32011)
    a1 = action(88, [p_str("CraftString"), p_str("")], obj_type=36, obj_info=NVO)
    a2 = action(80, [p_str("CraftOutput"), p_long(out_id)], obj_type=36, obj_info=NVO)
    a3 = action(80, [p_str("Craft_GiveBack"), p_long(give_back)], obj_type=36, obj_info=NVO)
    a4 = action(14, [p_str("Craft_Output"), p_long(1)])
    return group([c1, c2], [a1, a2, a3, a4])


def grp_spawn_door(map_name: str, x: int, y: int) -> bytes:
    """Создать Door - outfit (handle 501) на (x,y) в тюрьме map_name."""
    c1 = condition(-16, [p_str("grab_map_data")], flags=0, ident=-32020)
    c2 = condition(-3, [p_expr(ev_gstr(0)), p_cmp_str(ev_str(map_name), map_name)],
                   flags=0x20, ident=-32021)
    # параметр Create (code 9): position + instance + objinfo
    pos = (_u16(0xFFFF) + _u16(8) + _i16(x) + _i16(y) + _i16(0) + _i16(0) +
           _i32(0) + _i16(0) + _i16(0) + _i16(1))
    p_create = param(9, pos + _u16(6100) + _u16(501) + b"\0\0\0\0")
    a1 = action(0, [p_create], obj_type=-5)
    return group([c1, c2], [a1], flags=0x2080)


def grp_outfit_check(map_name: str, outfit_id: int) -> bytes:
    """Заблокировать шаг, если игрок НЕ в нужной форме у двери по форме."""
    lit = f"{outfit_id}_"
    left = ev_marker2_substring(outfit_len=len(lit))
    c1 = condition(-16, [p_str("move_check")], flags=0, ident=-32030)
    c2 = condition(-3, [p_expr(ev_gstr(0)), p_cmp_str(ev_str(map_name), map_name)],
                   flags=0x20, ident=-32031)
    # коллизия: BASE - You (handle 172) cond -4 с объектом 501
    p_obj = param(1, _i16(0) + _u16(501) + _i16(2))
    c3 = condition(-4, [p_obj], obj_type=2, obj_info=172, flags=0x20, ident=-32032)
    # Outfit не содержит "<id>_"
    p_outfit = param(22, _u16(0) + left + TERM)
    p_lit = param(23, _u16(1) + ev_str(lit) + TERM)
    c4 = condition(-3, [p_outfit, p_lit], flags=0x20, ident=-32033)
    a1 = action(80, [p_str("Blocked"), p_long(1)], obj_type=36, obj_info=NVO)
    return group([c1, c2, c3, c4], [a1])


def ev_marker2_substring(outfit_len: int) -> bytes:
    """Выражение «подстрока Outfit длиной N»: sys19 + NVO:81 'Outfit' + sys-2 + sys-3 + N + sys-2."""
    return (_i16(-1) + _u16(19) + _u16(6) +
            ev_named_var("Outfit") +
            _i16(-1) + struct.pack("<h", -3) + _u16(6) +
            ev_long(outfit_len) +
            ev_marker())


# =============================================================== патч лимита крафта
CRAFT_NEEDLE_OLD = None


def craft_needle(limit: int) -> bytes:
    """Байты действия «activate craft_poss <limit> раз» (уникальная иголка)."""
    p1 = param(45, _u16(0) + ev_str("craft_poss") + TERM)
    p2 = param(22, _u16(0) + ev_long(limit) + TERM)
    return p1 + p2


# =============================================================== моды
def backup(path: Path):
    bak = path.with_suffix(path.suffix + ".bak_mod")
    if not bak.exists():
        shutil.copy2(path, bak)
        return bak
    return None


def mod_translation(data_dir: Path, apply: bool, lang="rus"):
    say(f"\n=== Мод «Русский перевод» ({lang}) ===")
    f = data_dir / f"items_{lang}.dat"
    if not f.exists():
        say(f"  ! не найден {f}")
        return
    text, enc, encrypted = read_text_file(f)
    say(f"  файл: {f.name}, кодировка {enc}" + (", ЗАШИФРОВАН" if encrypted else ", открытый текст"))
    items, order = parse_items(text)
    say(f"  предметов: {len(items)} (ID {min(order)}..{max(order)})")

    # 1) собираем таблицу текущих имён
    cur_names = {i: items[i].get("Name", "") for i in order}

    # 2) что меняем
    changes = []
    rename_map = {}
    for iid, nm in cur_names.items():
        target = RU_NAMES.get(iid)
        if target is None or nm.strip().lower() == "empty":
            continue
        fixed = nm
        low = nm.strip().lower()
        if low in RU_FIXUPS:
            fixed = RU_FIXUPS[low]
        elif nm.strip() != target and not _is_cyrillic(nm):
            fixed = target          # не переведено вовсе
        if fixed != nm:
            changes.append((iid, nm, fixed))
            rename_map[nm] = fixed

    say(f"\n  найдено расхождений: {len(changes)}")
    for iid, old, new in changes[:25]:
        say(f"    [{iid}] {old!r} -> {new!r}")
    if len(changes) > 25:
        say(f"    ... и ещё {len(changes) - 25}")

    if not changes:
        say("  менять нечего — перевод уже в порядке.")
        return
    if not apply:
        say("\n  (режим просмотра; выбери «применить», чтобы записать)")
        return

    bak = backup(f)
    if bak:
        say(f"  бэкап: {bak.name}")

    for iid, old, new in changes:
        items[iid]["Name"] = new

    # 3) рецепты ссылаются на ИМЕНА текстом — правим их синхронно
    fixed_recipes = 0
    for iid in order:
        cr = items[iid].get("Craft")
        if not cr:
            continue
        new_cr = cr
        for old, new in rename_map.items():
            new_cr = new_cr.replace(old, new)
        if new_cr != cr:
            items[iid]["Craft"] = new_cr
            fixed_recipes += 1

    nl = "\r\n" if "\r\n" in text else "\n"
    head = text.split("[", 1)[0]
    write_text_file(f, build_items_text(head, items, order, nl), enc, encrypted)
    say(f"  записано: {f.name} ({f.stat().st_size} байт)")
    say(f"  рецептов синхронизировано: {fixed_recipes}")
    rebuild_val(data_dir)
    say("  val.dat пересобран")


def _is_cyrillic(s: str) -> bool:
    return any("\u0400" <= c <= "\u04ff" for c in s)


def mod_randomizer(data_dir: Path, apply: bool, seed=None, lang="rus", chaos=2):
    say(f"\n=== Мод «Рандомайзер предметов» (chaos={chaos}) ===")
    f = data_dir / f"items_{lang}.dat"
    if not f.exists():
        say(f"  ! не найден {f}")
        return
    text, enc, encrypted = read_text_file(f)
    items, order = parse_items(text)
    rnd = random.Random(seed)
    say(f"  сид: {seed if seed is not None else 'случайный'}")

    STAT_POOLS = {
        "Weapon":     [0, 1, 2, 3, 4, 5],
        "Digging":    [0, 0, 1, 2, 3, 5],
        "Chipping":   [0, 0, 1, 2, 3, 5],
        "Cutting":    [0, 0, 1, 2, 3, 5],
        "Unscrewing": [0, 0, 1, 2, 3],
        "HP":         [0, 0, 5, 10, 15, 25],
        "FAT":        [0, 0, 5, 10, 20],
        "Gift":       [0, 1, 2, 3, 5],
        "Decay":      [0, 1, 2, 5, 10],
    }
    touched = 0
    examples = []
    for iid in order:
        it = items[iid]
        nm = it.get("Name", "").strip().lower()
        if nm in ("", "empty", "none"):
            continue
        n_stats = rnd.randint(1, chaos + 1)
        picks = rnd.sample(list(STAT_POOLS), min(n_stats, len(STAT_POOLS)))
        changed = []
        for k in picks:
            v = rnd.choice(STAT_POOLS[k])
            if v == 0:
                it.pop(k, None)
                changed.append(f"{k}—")
            else:
                it[k] = str(v)
                changed.append(f"{k}={v}")
        if chaos >= 3 and rnd.random() < 0.3:
            it["Illegal"] = "1" if rnd.random() < 0.5 else "0"
        touched += 1
        if len(examples) < 12:
            examples.append(f"    [{iid}] {it.get('Name','?'):32} {', '.join(changed)}")

    say(f"  изменено предметов: {touched}")
    say("  примеры:")
    say("\n".join(examples))
    if not apply:
        say("\n  (режим просмотра)")
        return

    bak = backup(f)
    if bak:
        say(f"  бэкап: {bak.name}")
    nl = "\r\n" if "\r\n" in text else "\n"
    head = text.split("[", 1)[0]
    write_text_file(f, build_items_text(head, items, order, nl), enc, encrypted)
    say(f"  записано: {f.name}")
    rebuild_val(data_dir)
    say("  val.dat пересобран")


def mod_craft_limit(exe_path: Path, out_path: Path, new_limit=281):
    say(f"\n=== Мод «Фикс крафта»: лимит {new_limit} ===")
    say("  Причина бага: крафт-сканер в игре активирует группу craft_poss")
    say("  ровно 200 раз, поэтому предметы с ID >= 200 никогда не крафтятся.")
    ex = Exe(exe_path)
    idx, events = ex.get_events("game")
    old = craft_needle(200)
    n = events.count(old)
    say(f"  иголка «craft_poss, 200»: найдено {n} шт.")
    if n == 0:
        if events.count(craft_needle(new_limit)):
            say("  уже пропатчен — ничего не делаю")
            return None
        say("  ! не нашёл — возможно, другая сборка exe")
        return None
    patched = events.replace(old, craft_needle(new_limit), 1)
    ex.set_events(idx, patched)
    size = ex.save(out_path)
    say(f"  готово: {out_path} ({size} байт)")
    say("  Теперь крафтятся предметы с ID до %d." % (new_limit - 1))
    return out_path


def mod_add_recipe(exe_path: Path, out_path: Path, combo, out_id, give_back):
    say(f"\n=== Мод «Свой рецепт» ===")
    ex = Exe(exe_path)
    idx, events = ex.get_events("game")
    g = grp_recipe(combo, out_id, give_back)
    new_events = append_groups(events, [g])
    ex.set_events(idx, new_events)
    size = ex.save(out_path)
    say(f"  рецепт {combo} -> предмет {out_id} добавлен")
    say(f"  готово: {out_path} ({size} байт)")
    return out_path


def mod_outfit_door(exe_path: Path, out_path: Path, map_name, outfit_id, x, y):
    say(f"\n=== Мод «Дверь по форме» ===")
    ex = Exe(exe_path)
    idx, events = ex.get_events("game")
    gs = [grp_spawn_door(map_name, x, y), grp_outfit_check(map_name, outfit_id)]
    new_events = append_groups(events, gs)
    ex.set_events(idx, new_events)
    size = ex.save(out_path)
    say(f"  дверь Door-outfit в «{map_name}» на ({x},{y}); проход только в форме ID {outfit_id}")
    say(f"  готово: {out_path} ({size} байт)")
    return out_path


# =============================================================== mods/ + лаунчер
def setup_mods_folder(game_dir: Path):
    say("\n=== Установка папки mods/ и лаунчера ===")
    data = game_dir / "Data"
    if not data.is_dir():
        say(f"  ! в {game_dir} нет папки Data — это точно папка игры?")
        return
    mods = game_dir / "mods"
    bak = mods / "_backup"
    bak.mkdir(parents=True, exist_ok=True)
    (mods / "README.txt").write_text(
        "Клади сюда свои .dat (items_rus.dat, data_eng.dat, speech_*.dat ...).\n"
        "Запускай игру через «Запустить_с_модами.bat».\n"
        "Оригиналы хранятся в _backup/ — откат кнопкой в te1_mod.py.\n",
        encoding="utf-8")

    # копия этого скрипта рядом, чтобы bat работал автономно
    try:
        shutil.copy2(Path(__file__).resolve(), game_dir / Path(__file__).name)
    except Exception as e:
        say(f"  ! не смог скопировать скрипт: {e}")

    bat = game_dir / "Запустить_с_модами.bat"
    if not bat.exists():
        script = Path(__file__).name
        bat.write_text(
            "@echo off\r\n"
            "cd /d \"%~dp0\"\r\n"
            "py -3 \"%~dp0" + script + "\" apply \"%~dp0\"\r\n"
            "if errorlevel 1 python \"%~dp0" + script + "\" apply \"%~dp0\"\r\n"
            "start \"\" \"%~dp0TheEscapists.exe\"\r\n",
            encoding="ascii", errors="replace")
    say(f"  создано: {mods}")
    say(f"           {bak}")
    say(f"           {bat.name}")
    say("  Оригиналы НЕ тронуты. Запускай игру через bat-файл.")


def apply_mods(game_dir: Path):
    say("\n=== Применение модов ===")
    mods = game_dir / "mods"
    data = game_dir / "Data"
    bak = mods / "_backup"
    if not mods.is_dir():
        say("  ! папки mods нет — сначала пункт «создать mods/»")
        return
    bak.mkdir(parents=True, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(mods)):
        if not fn.lower().endswith(".dat"):
            continue
        src, dst = mods / fn, data / fn
        if dst.exists() and not (bak / fn).exists():
            shutil.copy2(dst, bak / fn)
        shutil.copy2(src, dst)
        say(f"  {fn} ({src.stat().st_size} байт)")
        n += 1
    say(f"  применено файлов: {n}")
    ch = rebuild_val(data)
    say(f"  val.dat пересобран ({ch} языков)")


def restore_mods(game_dir: Path):
    say("\n=== Откат ===")
    bak = game_dir / "mods" / "_backup"
    data = game_dir / "Data"
    if not bak.is_dir():
        say("  ! бэкапов нет")
        return
    n = 0
    for fn in os.listdir(bak):
        shutil.copy2(bak / fn, data / fn)
        say(f"  восстановлен {fn}")
        n += 1
    rebuild_val(data)
    say(f"  восстановлено: {n}")


# =============================================================== аудит
def audit(game_dir: Path):
    say("\n=== Аудит файлов игры ===")
    data = game_dir / "Data"
    if not data.is_dir():
        say(f"  ! нет {data}")
        return
    expected = {
        "data_eng.dat": 47020, "items_eng.dat": 16925, "speech_eng.dat": 54688,
        "data_rus.dat": 47020, "items_rus.dat": 35234, "speech_rus.dat": 107050,
    }
    for f in sorted(data.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".dat",):
            continue
        sz = f.stat().st_size
        note = ""
        if f.name in expected:
            note = "OK" if sz == expected[f.name] else f"ожидалось {expected[f.name]}"
        say(f"  {f.name:22} {sz:>8}  {note}")

    for lang in ("rus", "eng"):
        f = data / f"items_{lang}.dat"
        if f.exists():
            text, enc, encrypted = read_text_file(f)
            items, order = parse_items(text)
            craft_hi = [i for i in order if items[i].get("Craft") and i >= 200]
            say(f"\n  items_{lang}.dat: {len(items)} предметов, кодировка {enc}"
                + (", ЗАШИФРОВАН" if encrypted else ""))
            if craft_hi:
                say(f"  !! предметов с рецептом и ID>=200: {craft_hi}")
                say("     -> они НЕ скрафтятся, пока не применён «Фикс крафта» (патч exe)")


# =============================================================== поиск игры
DEFAULT_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\The Escapists",
    r"C:\Program Files\Steam\steamapps\common\The Escapists",
    r"D:\Steam\steamapps\common\The Escapists",
    r"D:\SteamLibrary\steamapps\common\The Escapists",
    r"E:\SteamLibrary\steamapps\common\The Escapists",
]


def find_game_dir(arg=None):
    cands = ([arg] if arg else []) + DEFAULT_PATHS + [os.getcwd()]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "Data")):
            return Path(c)
    return None


# =============================================================== меню
BANNER = r"""
  ==========================================================
    THE ESCAPISTS 1  —  MOD TOOLKIT  v{v}
  ==========================================================
""".format(v=VERSION)

MENU = """
  Папка игры: {gd}

   1. Создать папку mods/ + лаунчер (.bat)
   2. Применить моды из mods/ (и запустить игру вручную)
   3. Откатить (восстановить оригиналы)
   4. Аудит файлов (диагностика)
   -----------------------------------------------
   5. Мод: Русский перевод          (items_rus.dat)
   6. Мод: Рандомайзер предметов
   7. Мод: Фикс крафта (лимит 200 -> 281)   [патч exe]
   8. Мод: Добавить свой рецепт             [патч exe]
   9. Мод: Дверь по форме                   [патч exe]
  -----------------------------------------------
  10. Самопроверка (Blowfish + round-trip exe)
   0. Выход
"""


def selftest(exe_path=None):
    say("\n=== Самопроверка ===")
    say(f"  Blowfish (тест-вектор 4EF997456198DD78): {'OK' if bf_selftest() else 'ОШИБКА'}")
    if exe_path and Path(exe_path).exists() and Path(exe_path).stat().st_size > 1_000_000:
        ex = Exe(exe_path)
        idx, events = ex.get_events("game")
        ex.set_events(idx, events)
        tmp = Path("_selftest_out.exe")
        ex.save(tmp)
        same = tmp.read_bytes() == ex.data
        say(f"  Round-trip exe (пересборка без правок): {'ИДЕНТИЧЕН OK' if same else 'ОТЛИЧАЕТСЯ!'}")
        tmp.unlink(missing_ok=True)
        say(f"  Событий фрейма game: {len(events)} байт")
    else:
        say("  (exe не найден — round-trip пропущен)")


def pick_exe(game_dir):
    if game_dir:
        p = game_dir / "TheEscapists.exe"
        if p.exists():
            return p
    p = ask("Путь к TheEscapists.exe (или пусто — отмена)")
    return Path(p) if p else None


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]

    # непоследовательный режим: apply/restore из bat
    if argv and argv[0] in ("apply", "restore"):
        gd = find_game_dir(argv[1] if len(argv) > 1 else None)
        if not gd:
            say("Папка игры не найдена"); return 1
        (apply_mods if argv[0] == "apply" else restore_mods)(gd)
        return 0

    say(BANNER)
    say(f"  Blowfish (тест-вектор): {'OK' if bf_selftest() else 'ОШИБКА'}")
    gd = find_game_dir()
    if gd:
        say(f"  Найдена папка игры: {gd}")
    else:
        say("  Папка игры не найдена автоматически.")
        p = ask("  Введи путь к папке The Escapists (где лежит Data\\)")
        gd = find_game_dir(p)
        if not gd:
            say("  ! папка с Data\\ не найдена — часть функций будет недоступна")

    while True:
        say(MENU.format(gd=gd or "не задана"))
        try:
            ch = ask("Выбор").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if ch == "0":
            break
        elif ch == "1":
            if gd:
                setup_mods_folder(gd)
            else:
                say("  ! сначала укажи папку игры")
        elif ch == "2":
            if gd:
                apply_mods(gd)
                exe = gd / "TheEscapists.exe"
                if exe.exists():
                    if ask("Запустить игру? (y/n)", "y").lower() == "y":
                        os.startfile(exe) if hasattr(os, "startfile") else os.system(f'"{exe}"')
            else:
                say("  ! нет папки игры")
        elif ch == "3":
            if gd:
                restore_mods(gd)
        elif ch == "4":
            if gd:
                audit(gd)
            else:
                say("  ! нет папки игры")
        elif ch == "5":
            if not gd:
                say("  ! нет папки игры"); continue
            mode = ask("Применить изменения? (y = записать, n = только показать)", "n")
            mod_translation(gd / "Data", apply=mode.lower() == "y")
        elif ch == "6":
            if not gd:
                say("  ! нет папки игры"); continue
            seed = ask("Сид (число или пусто = случайный)")
            seed = int(seed) if seed.isdigit() else None
            chaos = ask_int("Уровень хаоса 1..4", 2, 1, 4)
            mode = ask("Применить? (y/n)", "n")
            mod_randomizer(gd / "Data", apply=mode.lower() == "y", seed=seed, chaos=chaos)
        elif ch == "7":
            exe = pick_exe(gd)
            if exe:
                try:
                    out = exe.with_name(exe.stem + "_craftfix.exe")
                    mod_craft_limit(exe, out, ask_int("Новый лимит ID", 281, 201, 400))
                    say(f"\n  Переименуй {out.name} в TheEscapists.exe (с бэкапом!) и замени в папке игры.")
                except Exception as e:
                    say(f"  ! не вышло: {e}")
        elif ch == "8":
            exe = pick_exe(gd)
            if exe:
                say("  Формат рецепта: три ID через «_», пустой слот = -1, игра их сортирует.")
                say("  Пример: 13_4_95 = Скотч(13) + Роба(4) + Подушка(95)")
                combo = ask("Комбинация ID", "13_4_95")
                out_id = ask_int("ID результата", 128)
                gb = ask_int("ID возвращаемого предмета (или -1)", -1)
                try:
                    out = exe.with_name(exe.stem + "_recipe.exe")
                    mod_add_recipe(exe, out, combo, out_id, gb)
                except Exception as e:
                    say(f"  ! не вышло: {e}")
        elif ch == "9":
            exe = pick_exe(gd)
            if exe:
                say("  Имена тюрем: perks, stalagflucht, shanktonstatepen, irongate, TOL, CCL...")
                mp = ask("Тюрьма", "perks")
                oid = ask_int("ID формы, открывающей дверь", 3)
                x = ask_int("X (кратно 16)", 512)
                y = ask_int("Y (кратно 16)", 320)
                try:
                    out = exe.with_name(exe.stem + "_door.exe")
                    mod_outfit_door(exe, out, mp, oid, x, y)
                except Exception as e:
                    say(f"  ! не вышло: {e}")
        elif ch == "10":
            try:
                selftest(pick_exe(gd) if gd else None)
            except Exception as e:
                say(f"  ! не вышло: {e}")
        else:
            say("  ? нет такого пункта")
        pause()

    say("Пока!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
