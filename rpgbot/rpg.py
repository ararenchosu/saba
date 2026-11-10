# -*- coding: utf-8 -*-
"""
rpgbot/rpg.py — 簡易RPG（専用BOT）【カジノ$連動・専用パネル版】

仕様（2026-11-11）:
- /setup_rpg で専用パネルを設置。パネルから「冒険（ステージ戦闘）」「チーム編成」
  「仲間ガチャ」「ステータス」をすべて操作するターン制RPG。
- 通貨はカジノと同じ $（users.json の money 共用）。仲間はガチャで集める
  （1回 $500 / 10連 $5,000、10連はSR以上1人確定）。被りは必殺技Lv（上限5）が
  先に上がり、技LvMAX後の被りは凸（+10%/凸、上限10）。全部MAXの被りは $ 変換。
- 編成: 手動（属性で絞り込み可）＋自動編成（バランス/ステージ相性/属性優先）。
  ステージ開始前にも「今の編成で出発 / 自動編成して出発」を選べる。
- 初回はスターター3人（剣士/ヒーラー/タンク）を自動で配布する。
- 戦闘: 味方3人と敵が順番に行動するターン制。ボタンで 攻撃/スキル/防御/回復薬。
  属性相性（火>木>水>火、光と闇は相互に強い）と役割（アタッカー/魔法使い/
  ヒーラー/タンク/サポーター）で編成を考える。ボスは溜め攻撃と怒りモード持ち。
- 進行・所持ユニット・レベルは users.json の rpg 欄に保存（サーバーごと）。
- 戦闘の途中状態はメモリ上のみ（BOT再起動で戦闘は消える。ペナルティなし）。
"""

import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from rpgbot.core import bot, store, is_home, requires
from sub.userdata import users

JST = timezone(timedelta(hours=9))

GACHA_COST = 500
GACHA10_COST = 5000
MAX_SKILL = 5
MAX_DUP = 10
POTIONS_PER_BATTLE = 3

ELEMENT_EMOJI = {"火": "🔥", "水": "💧", "木": "🌿", "光": "⚡", "闇": "🌑"}
ROLE_NAME = {"attacker": "アタッカー", "mage": "魔法使い", "healer": "ヒーラー", "tank": "タンク", "support": "サポーター"}
SKILL_NAME = {
    "attacker": "強撃（200%ダメージ）",
    "mage": "大魔法（180%ダメージ）",
    "healer": "癒しの光（全体回復）",
    "tank": "鉄壁の挑発（敵の攻撃を集めて半減）",
    "support": "鼓舞の歌（全体の攻撃+30%）",
}
SKILL_CD = {"attacker": 3, "mage": 3, "healer": 4, "tank": 4, "support": 4}

# id: (名前, 絵文字, 属性, 役割, レア, HP, ATK, DEF)
UNITS = {
    # ===== SSR =====
    "nobunaga":   ("織田信長", "🏯", "火", "attacker", "SSR", 178, 67, 13),
    "poseidon":   ("ポセイドン", "🔱", "水", "mage", "SSR", 158, 74, 10),
    "heracles":   ("ヘラクレス", "💪", "木", "tank", "SSR", 335, 37, 27),
    "amaterasu":  ("アマテラス", "☀️", "光", "support", "SSR", 168, 43, 13),
    "persephone": ("ペルセポネ", "🌹", "闇", "healer", "SSR", 176, 50, 14),
    # ===== SR =====
    "agni":        ("アグニ", "🔥", "火", "mage", "SR", 146, 56, 10),
    "hephaestus":  ("ヘパイストス", "🔨", "火", "tank", "SR", 298, 33, 24),
    "musashi":     ("宮本武蔵", "⚔️", "水", "attacker", "SR", 170, 51, 12),
    "genbu":       ("玄武", "🐢", "水", "tank", "SR", 305, 31, 25),
    "titania":     ("ティターニア", "🧚", "木", "mage", "SR", 144, 55, 10),
    "pan":         ("パン", "🐐", "木", "support", "SR", 152, 38, 12),
    "arthur":      ("アーサー王", "⚜️", "光", "attacker", "SR", 172, 52, 12),
    "nightingale": ("ナイチンゲール", "🩺", "光", "healer", "SR", 152, 41, 12),
    "lucifer":     ("ルシファー", "😈", "闇", "attacker", "SR", 166, 54, 11),
    "hades":       ("ハデス", "💀", "闇", "mage", "SR", 148, 57, 10),
    # ===== R =====
    "phoenix":    ("フェニックス", "🐦", "火", "healer", "R", 128, 29, 9),
    "salamander": ("サラマンダー", "🦎", "火", "support", "R", 136, 30, 10),
    "otohime":    ("乙姫", "🐚", "水", "healer", "R", 126, 28, 9),
    "seiren":     ("セイレーン", "🎵", "水", "support", "R", 134, 31, 10),
    "robin":      ("ロビン・フッド", "🏹", "木", "attacker", "R", 148, 37, 10),
    "flora":      ("フローラ", "🌸", "木", "healer", "R", 124, 28, 9),
    "gabriel":    ("ガブリエル", "🎺", "光", "mage", "R", 132, 43, 9),
    "lancelot":   ("ランスロット", "🛡️", "光", "tank", "R", 242, 27, 17),
    "anubis":     ("アヌビス", "🐺", "闇", "tank", "R", 238, 26, 18),
    "dakki":      ("妲己", "🦊", "闇", "support", "R", 136, 32, 10),
    # ===== スターター（配布専用も兼ねるR） =====
    "taro":    ("村の剣士タロウ", "⚔️", "火", "attacker", "R", 150, 34, 10),
    "mint":    ("見習いヒーラーミント", "🌱", "水", "healer", "R", 120, 26, 8),
    "gonta":   ("木こりゴンタ", "🪓", "木", "tank", "R", 230, 24, 16),
}
STARTERS = ["taro", "mint", "gonta"]
GACHA_RATES = {"SSR": 3, "SR": 17, "R": 80}  # %

# ステージ: (名前, 絵文字, 属性, HP, ATK, DEF, ボスか, 怒りか)
STAGES = [
    ("スライム", "🫧", "水", 260, 22, 5, False, False),
    ("ゴブリン", "👺", "木", 340, 30, 8, False, False),
    ("ファイアインプ", "👿", "火", 420, 38, 10, False, False),
    ("石ゴーレム", "🗿", "木", 650, 34, 30, False, False),
    ("炎の魔獣", "🦁", "火", 1700, 55, 18, True, False),
    ("ダークナイト", "♞", "闇", 1000, 58, 22, False, False),
    ("氷の女王", "👸", "水", 1150, 62, 20, False, False),
    ("サンダーバード", "🦅", "光", 1200, 68, 18, False, False),
    ("影の暗殺者", "🥷", "闇", 1000, 80, 14, False, False),
    ("混沌の魔王", "👑", "闇", 2800, 74, 28, True, True),
]

_ADV = {("火", "木"), ("木", "水"), ("水", "火"), ("光", "闇"), ("闇", "光")}


def elem_mult(atk_elem: str, def_elem: str) -> float:
    if (atk_elem, def_elem) in _ADV:
        return 1.3
    if (def_elem, atk_elem) in _ADV and (atk_elem, def_elem) not in _ADV:
        return 0.75
    return 1.0


def fmt(amount: int) -> str:
    return f"${amount:,}"


async def _guard(interaction) -> bool:
    if interaction.guild is None or not is_home(interaction.guild.id):
        await interaction.response.send_message("このBOTの担当サーバーではありません。", ephemeral=True)
        return False
    return True


def _rpg(gid: int, uid: int) -> dict:
    """ユーザーのRPGデータ（初回はスターター配布）"""
    u = users.get(gid, uid)
    u.setdefault("money", 0)
    r = u.setdefault("rpg", {})
    r.setdefault("units", {})
    r.setdefault("party", [])
    r.setdefault("cleared", 0)
    if not r["units"]:
        for sid in STARTERS:
            r["units"][sid] = {"lv": 1, "exp": 0, "dup": 0, "skill": 1}
        r["party"] = list(STARTERS)
        users.save()
    # ロスター変更で消えたユニットを掃除し、技Lvの初期値を補う
    for _uid in list(r["units"]):
        if _uid not in UNITS:
            del r["units"][_uid]
    r["party"] = [p for p in r["party"] if p in r["units"]]
    for _rec in r["units"].values():
        _rec.setdefault("skill", 1)
        _rec.setdefault("dup", 0)
    return r


def unit_stats(unit_id: str, rec: dict):
    """(HP, ATK, DEF) をレベルと凸で計算"""
    _, _, _, _, _, hp, atk, dfn = UNITS[unit_id]
    mult = (1 + 0.08 * (rec["lv"] - 1)) * (1 + 0.10 * rec.get("dup", 0))
    return int(hp * mult), int(atk * mult), int(dfn * mult)


def skill_mult(rec: dict) -> float:
    """必殺技Lvによる技の効果倍率（Lv1=1.0 → Lv5=2.0）"""
    return 1 + 0.25 * (rec.get("skill", 1) - 1)


def unit_power(unit_id: str, rec: dict) -> int:
    """編成の目安になる戦力スコア（自動編成の評価にも使う）"""
    hp, atk, dfn = unit_stats(unit_id, rec)
    return hp // 5 + atk + dfn


def unit_line(unit_id: str, rec: dict) -> str:
    name, emoji, elem, role, rarity, *_ = UNITS[unit_id]
    hp, atk, dfn = unit_stats(unit_id, rec)
    dup = rec.get("dup", 0)
    return (f"{emoji} **{name}** [{rarity}] {ELEMENT_EMOJI[elem]}{elem}・{ROLE_NAME[role]} "
            f"Lv{rec['lv']} 技Lv{rec.get('skill', 1)}" + (f" 凸{dup}" if dup else "") +
            f"（HP{hp} 攻{atk} 防{dfn}）")


# ---------------- ガチャ ----------------
def _roll_rarity(force_sr: bool = False) -> str:
    if force_sr:
        return "SSR" if random.random() < 3 / 20 else "SR"
    r = random.random() * 100
    if r < GACHA_RATES["SSR"]:
        return "SSR"
    if r < GACHA_RATES["SSR"] + GACHA_RATES["SR"]:
        return "SR"
    return "R"


def _apply_pull(r: dict, unit_id: str) -> str:
    """1体入手をデータに反映して結果行を返す。被りは 技Lv→凸→$変換 の順に回る。"""
    rec = r["units"].get(unit_id)
    if rec is None:
        r["units"][unit_id] = {"lv": 1, "exp": 0, "dup": 0, "skill": 1}
        return f"🆕 {unit_line(unit_id, r['units'][unit_id])}"
    if rec.get("skill", 1) < MAX_SKILL:
        rec["skill"] = rec.get("skill", 1) + 1
        return f"🎯 必殺技Lv+1！ {unit_line(unit_id, rec)}"
    if rec.get("dup", 0) < MAX_DUP:
        rec["dup"] = rec.get("dup", 0) + 1
        return f"🔼 凸+1！ {unit_line(unit_id, rec)}"
    # 全部MAXの被りは $200 に変換
    return f"💰 全部MAXの被り → {fmt(200)} に変換 {UNITS[unit_id][1]} {UNITS[unit_id][0]}"


def _pull_one(r: dict, force_sr: bool = False) -> str:
    rarity = _roll_rarity(force_sr)
    pool = [uid for uid, u in UNITS.items() if u[4] == rarity]
    return _apply_pull(r, random.choice(pool))


def _gacha_result_embed(gid: int, uid: int, lines: list, cost: int) -> discord.Embed:
    bal = users.get(gid, uid).get("money", 0)
    embed = discord.Embed(title="🎰 仲間ガチャ結果", description="\n".join(lines), color=discord.Color.purple())
    embed.set_footer(text=f"消費 {fmt(cost)} ／ 残高 {fmt(bal)}")
    return embed


class GachaView(discord.ui.View):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid

    async def _do(self, interaction: discord.Interaction, n: int):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのガチャではありません。", ephemeral=True)
            return
        cost = GACHA_COST if n == 1 else GACHA10_COST
        u = users.get(self.gid, self.uid)
        if u.get("money", 0) < cost:
            await interaction.response.send_message(
                f"残高が足りません（必要 {fmt(cost)} ／ 残高 {fmt(u.get('money', 0))}）。カジノで貯めてください。",
                ephemeral=True)
            return
        u["money"] -= cost
        r = _rpg(self.gid, self.uid)
        lines = []
        refund = 0
        if n == 1:
            line = _pull_one(r)
            if "変換" in line:
                refund += 200
            lines.append(line)
        else:
            rarities = []
            for _ in range(10):
                line = _pull_one(r)
                if "変換" in line:
                    refund += 200
                lines.append(line)
                rarities.append(line)
            # 10連はSR以上1人確定: 全部Rなら最後をSR以上に引き直す
            has_sr = any(f"[{x}]" in ln for ln in lines for x in ("SR", "SSR"))
            if not has_sr:
                lines[-1] = "（確定枠）" + _pull_one(r, force_sr=True)
        if refund:
            u["money"] += refund
        users.save()
        await interaction.response.send_message(embed=_gacha_result_embed(self.gid, self.uid, lines, cost), ephemeral=True)

    @discord.ui.button(label="1回引く（$500）", emoji="🎰", style=discord.ButtonStyle.primary)
    async def one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do(interaction, 1)

    @discord.ui.button(label="10連（$5,000・SR以上1人確定）", emoji="🎰", style=discord.ButtonStyle.success)
    async def ten(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do(interaction, 10)


# ---------------- 戦闘 ----------------
def _bar(cur: int, mx: int, n: int = 12) -> str:
    if mx <= 0:
        return "▱" * n
    filled = max(0, min(n, round(cur / mx * n)))
    return "▰" * filled + "▱" * (n - filled)


class BattleView(discord.ui.View):
    def __init__(self, gid: int, uid: int, stage_no: int):
        super().__init__(timeout=900)
        self.gid = gid
        self.uid = uid
        self.stage_no = stage_no
        r = _rpg(gid, uid)
        party_ids = [p for p in r["party"] if p in r["units"]][:3] or list(r["units"].keys())[:3]
        self.party = []
        for pid in party_ids:
            hp, atk, dfn = unit_stats(pid, r["units"][pid])
            self.party.append({"id": pid, "hp": hp, "max": hp, "atk": atk, "def": dfn, "cd": 0, "guard": False,
                               "skill": r["units"][pid].get("skill", 1)})
        name, emoji, elem, hp, atk, dfn, boss, enrage = STAGES[stage_no - 1]
        self.enemy = {"name": name, "emoji": emoji, "elem": elem, "hp": hp, "max": hp,
                      "atk": atk, "def": dfn, "boss": boss, "enrage": enrage,
                      "enraged": False, "charged": False, "eturns": 0}
        self.queue = []
        self.actor = None
        self.buff_turns = 0
        self.buff_pct = 0.0
        self.taunt_turns = 0
        self.taunt_by = None
        self._taunt_now = False
        self.potions = POTIONS_PER_BATTLE
        self.log = [f"ステージ{stage_no}：{emoji} {name} が現れた！"]
        self.over = False
        self.message = None

    # ---------- 表示 ----------
    def _embed(self) -> discord.Embed:
        e = self.enemy
        title = f"⚔️ ステージ{self.stage_no}：{e['emoji']} {e['name']}" + ("【ボス】" if e["boss"] else "")
        embed = discord.Embed(title=title, color=discord.Color.red() if e["boss"] else discord.Color.orange())
        embed.add_field(
            name=f"敵 {ELEMENT_EMOJI[e['elem']]}{e['elem']}属性",
            value=f"HP {e['hp']}/{e['max']}\n{_bar(e['hp'], e['max'])}" + ("\n⚠️ 大技を溜めている…！" if e["charged"] else ""),
            inline=False)
        lines = []
        for i, f in enumerate(self.party):
            name = UNITS[f["id"]][0]
            mark = "▶" if self.actor == i and not self.over else "・"
            state = "💀" if f["hp"] <= 0 else _bar(f["hp"], f["max"], 8)
            lines.append(f"{mark} {UNITS[f['id']][1]} {name} HP {max(0, f['hp'])}/{f['max']} {state}")
        embed.add_field(name="パーティ", value="\n".join(lines), inline=False)
        if self.log:
            embed.add_field(name="戦況", value="\n".join(self.log[-6:]), inline=False)
        if self.buff_turns > 0:
            embed.set_footer(text=f"鼓舞の効果中（攻撃+30%・残り{self.buff_turns}手番）／ 回復薬 残り{self.potions}")
        else:
            embed.set_footer(text=f"回復薬 残り{self.potions}")
        return embed

    # ---------- ターン制御 ----------
    def _next_actor(self):
        while True:
            while self.queue:
                a = self.queue.pop(0)
                if a == "E" or self.party[a]["hp"] > 0:
                    return a
            self.queue = [i for i, f in enumerate(self.party) if f["hp"] > 0] + ["E"]

    def _party_dead(self) -> bool:
        return all(f["hp"] <= 0 for f in self.party)

    def _damage(self, atk: int, atk_elem: str, target: dict, mult: float = 1.0) -> int:
        dmg = atk * elem_mult(atk_elem, target.get("elem", "")) * mult if "elem" in target else atk * mult
        dfn = target["def"]
        dmg = dmg * 100 / (100 + dfn) * random.uniform(0.9, 1.1)
        return max(1, int(dmg))

    def _hit_enemy(self, f: dict, mult: float, label: str):
        elem = UNITS[f["id"]][2]
        atk = f["atk"] * (1 + self.buff_pct if self.buff_turns > 0 else 1.0)
        dmg = self._damage(int(atk), elem, self.enemy, mult)
        self.enemy["hp"] -= dmg
        adv = elem_mult(elem, self.enemy["elem"])
        note = "（効果抜群！）" if adv > 1 else "（いまひとつ…）" if adv < 1 else ""
        self.log.append(f"{UNITS[f['id']][1]} {label} → {dmg} ダメージ{note}")

    def _enemy_act(self):
        e = self.enemy
        e["eturns"] += 1
        if e["enrage"] and not e["enraged"] and e["hp"] <= e["max"] * 0.3:
            e["enraged"] = True
            e["atk"] = int(e["atk"] * 1.35)
            self.log.append(f"💢 {e['name']} が怒りモードに！攻撃力が上がった！")
        self._taunt_now = self.taunt_turns > 0
        if self.taunt_turns > 0:
            self.taunt_turns -= 1
        if e["boss"] and not e["charged"] and e["eturns"] % 4 == 0:
            e["charged"] = True
            self.log.append(f"⚠️ {e['name']} が大きな技を溜め始めた…次の攻撃は全体に大ダメージ！（防御で軽減できる）")
            return
        if e["charged"]:
            e["charged"] = False
            for f in self.party:
                if f["hp"] <= 0:
                    continue
                dmg = self._damage(e["atk"], e["elem"], {"def": f["def"], "elem": UNITS[f["id"]][2]}, 2.2)
                if f["guard"]:
                    dmg //= 2
                f["hp"] -= dmg
                self.log.append(f"💥 {e['name']} の大技！ {UNITS[f['id']][1]} に {dmg} ダメージ")
            return
        # 通常攻撃: 挑発中はタンクを狙う
        if self._taunt_now and self.taunt_by is not None and self.party[self.taunt_by]["hp"] > 0:
            target = self.party[self.taunt_by]
        else:
            alive = [f for f in self.party if f["hp"] > 0]
            target = random.choice(alive)
        dmg = self._damage(e["atk"], e["elem"], {"def": target["def"], "elem": UNITS[target["id"]][2]}, 1.0)
        if target["guard"]:
            dmg //= 2
        if self._taunt_now and self.taunt_by is not None and target is self.party[self.taunt_by]:
            dmg //= 2  # 鉄壁中はタンクの被ダメ半減
        target["hp"] -= dmg
        self.log.append(f"{e['emoji']} {e['name']} の攻撃 → {UNITS[target['id']][1]} に {dmg} ダメージ")

    # ---------- 進行 ----------
    async def _advance(self, interaction: discord.Interaction):
        while True:
            if self.enemy["hp"] <= 0:
                await self._victory(interaction)
                return
            if self._party_dead():
                await self._defeat(interaction)
                return
            actor = self._next_actor()
            if actor == "E":
                self._enemy_act()
                continue
            self.actor = actor
            f = self.party[actor]
            if f["cd"] > 0:
                f["cd"] -= 1
            f["guard"] = False
            self._build_buttons()
            await interaction.response.edit_message(embed=self._embed(), view=self)
            return

    async def start(self, interaction: discord.Interaction):
        """戦闘開始（最初の手番まで進める）"""
        while True:
            actor = self._next_actor()
            if actor == "E":
                self._enemy_act()
                if self._party_dead():
                    await self._defeat(interaction, first=True)
                    return
                continue
            self.actor = actor
            self._build_buttons()
            await interaction.response.send_message(embed=self._embed(), view=self, ephemeral=True)
            self.message = await interaction.original_response()
            return

    def _build_buttons(self):
        self.clear_items()
        f = self.party[self.actor]
        role = UNITS[f["id"]][3]
        b1 = discord.ui.Button(label=f"{UNITS[f['id']][1]} 通常攻撃", style=discord.ButtonStyle.primary, row=0)
        b1.callback = lambda i: self._act(i, "attack")
        self.add_item(b1)
        cd = f["cd"]
        b2 = discord.ui.Button(
            label=f"スキル：{SKILL_NAME[role].split('（')[0]} Lv{f['skill']}" + (f"（あと{cd}）" if cd > 0 else ""),
            style=discord.ButtonStyle.success, row=0, disabled=cd > 0)
        b2.callback = lambda i: self._act(i, "skill")
        self.add_item(b2)
        b3 = discord.ui.Button(label="防御（被ダメ半減）", style=discord.ButtonStyle.secondary, row=1)
        b3.callback = lambda i: self._act(i, "guard")
        self.add_item(b3)
        b4 = discord.ui.Button(label=f"回復薬（残り{self.potions}・全体30%）", style=discord.ButtonStyle.secondary,
                               row=1, disabled=self.potions <= 0)
        b4.callback = lambda i: self._act(i, "potion")
        self.add_item(b4)
        b5 = discord.ui.Button(label="逃げる", style=discord.ButtonStyle.danger, row=1)
        b5.callback = lambda i: self._act(i, "flee")
        self.add_item(b5)

    async def _act(self, interaction: discord.Interaction, kind: str):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたの戦闘ではありません。", ephemeral=True)
            return
        if self.over:
            return
        f = self.party[self.actor]
        role = UNITS[f["id"]][3]
        if kind == "flee":
            self.over = True
            self.clear_items()
            await interaction.response.edit_message(
                content="🏃 逃げ出した…（ペナルティなし）", embed=None, view=self)
            return
        if kind == "attack":
            self._hit_enemy(f, 1.0, "通常攻撃")
        elif kind == "skill":
            f["cd"] = SKILL_CD[role]
            m = skill_mult(f)
            if role == "attacker":
                self._hit_enemy(f, 2.0 * m, "強撃")
            elif role == "mage":
                self._hit_enemy(f, 1.8 * m, "大魔法")
            elif role == "healer":
                heal = int(f["atk"] * 1.2 * m * random.uniform(0.9, 1.1))
                for t in self.party:
                    if t["hp"] > 0:
                        t["hp"] = min(t["max"], t["hp"] + heal)
                self.log.append(f"{UNITS[f['id']][1]} 癒しの光 → 味方全体を {heal} 回復")
            elif role == "tank":
                self.taunt_turns = 3
                self.taunt_by = self.actor
                heal_self = int(f["max"] * 0.10 * m)
                f["hp"] = min(f["max"], f["hp"] + heal_self)
                self.log.append(f"{UNITS[f['id']][1]} 鉄壁の挑発 → 敵の攻撃を自分に集める（被ダメ半減）＋自分を {heal_self} 回復")
            elif role == "support":
                self.buff_turns = 4
                self.buff_pct = 0.30 * m
                self.log.append(f"{UNITS[f['id']][1]} 鼓舞の歌 → 味方全体の攻撃+{int(self.buff_pct * 100)}%")
        elif kind == "guard":
            f["guard"] = True
            self.log.append(f"{UNITS[f['id']][1]} は防御の構え（被ダメ半減）")
        elif kind == "potion":
            if self.potions > 0:
                self.potions -= 1
                for t in self.party:
                    if t["hp"] > 0:
                        t["hp"] = min(t["max"], t["hp"] + int(t["max"] * 0.3))
                self.log.append("🧪 回復薬 → 味方全体を30%回復")
        if self.buff_turns > 0 and not (kind == "skill" and role == "support"):
            self.buff_turns -= 1
        self.actor = None
        await self._advance(interaction)

    # ---------- 終了 ----------
    def _apply_rewards(self):
        stage = self.stage_no
        r = _rpg(self.gid, self.uid)
        first = stage > r["cleared"]
        money = 150 * stage + (300 if first else 0)
        exp = 50 + 30 * stage
        u = users.get(self.gid, self.uid)
        u["money"] = u.get("money", 0) + money
        levelups = []
        for f in self.party:
            rec = r["units"][f["id"]]
            rec["exp"] = rec.get("exp", 0) + exp
            while rec["exp"] >= rec["lv"] * 100:
                rec["exp"] -= rec["lv"] * 100
                rec["lv"] += 1
                levelups.append(f"{UNITS[f['id']][1]} {UNITS[f['id']][0]} → Lv{rec['lv']}")
        if first:
            r["cleared"] = stage
        users.save()
        return money, exp, levelups, first

    async def _victory(self, interaction: discord.Interaction):
        self.over = True
        money, exp, levelups, first = self._apply_rewards()
        self.clear_items()
        for label, cb, style in self._end_buttons(win=True):
            b = discord.ui.Button(label=label, style=style)
            b.callback = cb
            self.add_item(b)
        lines = [f"🎉 **ステージ{self.stage_no} クリア！**", f"報酬: {fmt(money)}" + ("（初クリアボーナス込み）" if first else ""),
                 f"パーティ全員に EXP +{exp}"]
        lines += [f"🆙 {x}" for x in levelups]
        await interaction.response.edit_message(content="\n".join(lines), embed=self._embed(), view=self)

    async def _defeat(self, interaction: discord.Interaction, first: bool = False):
        self.over = True
        self.clear_items()
        for label, cb, style in self._end_buttons(win=False):
            b = discord.ui.Button(label=label, style=style)
            b.callback = cb
            self.add_item(b)
        msg = "💀 全滅した… レベルを上げるか、編成（属性・ヒーラー）を見直してみて。"
        if first:
            await interaction.response.send_message(content=msg, embed=self._embed(), view=self, ephemeral=True)
            self.message = await interaction.original_response()
        else:
            await interaction.response.edit_message(content=msg, embed=self._embed(), view=self)

    def _end_buttons(self, win: bool):
        async def retry(i: discord.Interaction):
            if i.user.id != self.uid:
                await i.response.send_message("これはあなたの戦闘ではありません。", ephemeral=True)
                return
            nb = BattleView(self.gid, self.uid, self.stage_no)
            await nb.start(i)
        out = [("もう一度挑戦" if not win else "もう一度戦う", retry, discord.ButtonStyle.primary)]
        if win and self.stage_no < len(STAGES):
            nxt = self.stage_no + 1
            async def go_next(i: discord.Interaction):
                if i.user.id != self.uid:
                    await i.response.send_message("これはあなたの戦闘ではありません。", ephemeral=True)
                    return
                nb = BattleView(self.gid, self.uid, nxt)
                await nb.start(i)
            out.append((f"次のステージ{nxt}へ", go_next, discord.ButtonStyle.success))
        return out

    async def on_timeout(self):
        self.clear_items()
        if self.message is not None:
            try:
                await self.message.edit(content="⏰ 戦闘は時間切れで終了しました（ペナルティなし）。", embed=None, view=self)
            except Exception:
                pass


# ---------------- パネルまわり ----------------
def _rules_text() -> str:
    return (
        "**⚔️ 遊び方**\n"
        "・3人チームでステージに挑戦。勝つと次のステージが開き、EXPと $ がもらえます。\n"
        "・戦闘は順番制：自分の手番に 攻撃／スキル／防御／回復薬（1戦闘3個）から選ぶ。\n"
        "・スキルは使ったあと数手番は使えません。ボスの「溜め」を見たら防御か回復の準備を。\n\n"
        "**🧩 編成のコツ**\n"
        "・属性相性：火は木に強い／木は水に強い／水は火に強い／光と闇はお互いに強い（1.3倍）。逆は0.75倍。\n"
        "・役割：アタッカー=単体火力、魔法使い=大ダメージ、ヒーラー=全体回復、"
        "タンク=敵の攻撃を集めて耐える、サポーター=全体の攻撃アップ。\n"
        "・ボスは4手番ごとに全体大技を溜めます。HP3割以下で怒るボスもいます。\n"
        "・編成に迷ったら自動編成（バランス型／ステージ相性／属性優先）がおすすめ。\n\n"
        "**🎰 仲間ガチャ**\n"
        f"・1回 {fmt(GACHA_COST)} ／ 10連 {fmt(GACHA10_COST)}（SR以上1人確定）。レア度: SSR 3% / SR 17% / R 80%。\n"
        f"・被りは必殺技Lvが上がります（最大{MAX_SKILL}、技の効果が最大2倍）。技LvMAX後の被りは凸\n"
        f"（全ステータス+10%、最大{MAX_DUP}凸）。全部MAXの被りは {fmt(200)} に変換されます。\n"
        "・$ はカジノと共通です。カジノのログインボーナスやゲームで貯めてください。"
    )


def build_rpg_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ 簡易RPGパネル",
        description=(
            "3人チームでステージを進み、ボスを倒すターン制RPG。\n"
            "仲間はガチャ（カジノの $）で集めて、属性と役割で編成を考えるゲームです。"
        ),
        color=discord.Color.dark_teal(),
    )
    embed.add_field(name="遊び方", value=(
        "⚔️ 冒険に出る → ステージを選んで戦闘\n"
        "🧩 チーム編成 → 3人を選ぶ（自動編成あり）\n"
        "🎰 仲間ガチャ → 新しい仲間を集める\n"
        "📊 ステータス → 進行度と所持ユニット"
    ), inline=False)
    embed.add_field(name="ステージ", value=f"全{len(STAGES)}面（5面と10面がボス）", inline=False)
    return embed


# ---------------- 自動編成 ----------------
def auto_party(r: dict, mode: str, elem: str = None, enemy_elem: str = None) -> list:
    """方針に沿って所持ユニットから3人を選ぶ。
    mode: "balance"（役割バランス）/ "stage"（敵に有利な属性）/ "elem"（指定属性を優先）。
    どの方針でもタンクとヒーラーを1人ずつ優先して確保する。"""
    def score(item):
        uid, rec = item
        s = unit_power(uid, rec)
        e = UNITS[uid][2]
        if mode == "elem" and elem:
            if e == elem:
                s += 1000
        elif mode == "stage" and enemy_elem:
            m = elem_mult(e, enemy_elem)
            if m > 1:
                s += 1000
            elif m < 1:
                s -= 500
        return s

    ranked = [uid for uid, _ in sorted(r["units"].items(), key=score, reverse=True)]
    party = []
    for want in ("tank", "healer"):
        for uid in ranked:
            if uid not in party and UNITS[uid][3] == want:
                party.append(uid)
                break
    for uid in ranked:
        if len(party) >= 3:
            break
        if uid not in party:
            party.append(uid)
    return party[:3]


def _auto_mode_options(with_stage: bool):
    opts = [discord.SelectOption(label="バランス型（タンク＋ヒーラー＋火力）", value="balance", emoji="⚖️",
                                 description="役割をそろえて安定重視")]
    if with_stage:
        opts.append(discord.SelectOption(label="ステージ相性（敵に有利な属性を優先）", value="stage", emoji="🎯",
                                         description="そのステージの敵に強い属性で組む"))
    for e in ("火", "水", "木", "光", "闇"):
        opts.append(discord.SelectOption(label=f"{e}属性を優先", value=f"elem:{e}", emoji=ELEMENT_EMOJI[e],
                                         description=f"{e}属性の仲間を中心に組む"))
    return opts


class AutoPartyView(discord.ui.View):
    """自動編成の方針を選ぶ → 編成を保存して結果を表示（stage_no があれば出発ボタン付き）"""

    def __init__(self, gid: int, uid: int, stage_no: int = None):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.stage_no = stage_no
        sel = discord.ui.Select(placeholder="自動編成の方針を選んでください",
                                options=_auto_mode_options(stage_no is not None))
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        value = interaction.data["values"][0]
        r = _rpg(self.gid, self.uid)
        if value == "stage" and self.stage_no is not None:
            party = auto_party(r, "stage", enemy_elem=STAGES[self.stage_no - 1][2])
            mode_label = "ステージ相性"
        elif value.startswith("elem:"):
            elem = value.split(":", 1)[1]
            party = auto_party(r, "elem", elem=elem)
            mode_label = f"{elem}属性優先"
        else:
            party = auto_party(r, "balance")
            mode_label = "バランス型"
        r["party"] = party
        users.save()
        lines = [unit_line(u, r["units"][u]) for u in party]
        text = f"🤖 **自動編成（{mode_label}）でチームを組みました**\n" + "\n".join(lines)
        if self.stage_no is not None:
            await interaction.response.send_message(text, view=DepartView(self.gid, self.uid, self.stage_no), ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


class DepartView(discord.ui.View):
    """自動編成の結果から、そのままステージへ出発する"""

    def __init__(self, gid: int, uid: int, stage_no: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.stage_no = stage_no

    @discord.ui.button(label="この編成で出発", emoji="⚔️", style=discord.ButtonStyle.success)
    async def depart(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたの戦闘ではありません。", ephemeral=True)
            return
        battle = BattleView(self.gid, self.uid, self.stage_no)
        await battle.start(interaction)


class StartChoiceView(discord.ui.View):
    """ステージ決定後: 今の編成で出発 / 自動編成してから出発"""

    def __init__(self, gid: int, uid: int, stage_no: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.stage_no = stage_no

    @discord.ui.button(label="今の編成で出発", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        battle = BattleView(self.gid, self.uid, self.stage_no)
        await battle.start(interaction)

    @discord.ui.button(label="自動編成してから出発", emoji="🤖", style=discord.ButtonStyle.success)
    async def auto(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "自動編成の方針を選んでください:", view=AutoPartyView(self.gid, self.uid, self.stage_no), ephemeral=True)


class StageSelectView(discord.ui.View):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        r = _rpg(gid, uid)
        max_stage = min(len(STAGES), r["cleared"] + 1)
        opts = []
        for i in range(max_stage):
            name, emoji, elem, hp, atk, dfn, boss, enrage = STAGES[i]
            opts.append(discord.SelectOption(
                label=f"ステージ{i + 1}: {name}" + ("【ボス】" if boss else "") + (" ✅" if i + 1 <= r["cleared"] else ""),
                value=str(i + 1),
                emoji=emoji,
                description=f"{elem}属性 HP{hp} 攻{atk} 防{dfn}"))
        sel = discord.ui.Select(placeholder="挑戦するステージを選んでください", options=opts)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        stage = int(interaction.data["values"][0])
        r = _rpg(self.gid, self.uid)
        lines = [unit_line(u, r["units"][u]) for u in r["party"] if u in r["units"]]
        await interaction.response.send_message(
            f"**ステージ{stage}** に挑戦します。今のチーム:\n" + "\n".join(lines),
            view=StartChoiceView(self.gid, self.uid, stage), ephemeral=True)


class PartySelectView(discord.ui.View):
    """手動編成: 属性で絞って3人まで選び「この編成で決定」で保存。自動編成ボタンも併設。
    所持数が増えてもセレクトの上限（25件）を超えないよう、属性フィルタで切り替える。"""

    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        r = _rpg(gid, uid)
        self.chosen = [p for p in r["party"] if p in r["units"]][:3]
        self.filter_elem = None
        self._build()

    def _unit_options(self):
        r = _rpg(self.gid, self.uid)
        opts = []
        for unit_id, rec in r["units"].items():
            if self.filter_elem and UNITS[unit_id][2] != self.filter_elem:
                continue
            name, emoji, elem, role, rarity, *_ = UNITS[unit_id]
            opts.append(discord.SelectOption(
                label=f"{name}（Lv{rec['lv']}）", value=unit_id, emoji=emoji,
                description=f"[{rarity}] {elem}・{ROLE_NAME[role]} 技Lv{rec.get('skill', 1)}" +
                            (f" 凸{rec['dup']}" if rec.get("dup") else "") +
                            ("（選択中）" if unit_id in self.chosen else "")))
        return opts[:25]

    def _build(self):
        self.clear_items()
        r = _rpg(self.gid, self.uid)
        owned_elems = {UNITS[u][2] for u in r["units"]}
        fopts = [discord.SelectOption(label="全ての属性", value="all", emoji="🌈")]
        for e in ("火", "水", "木", "光", "闇"):
            if e in owned_elems:
                fopts.append(discord.SelectOption(label=f"{e}属性だけ表示", value=e, emoji=ELEMENT_EMOJI[e]))
        fsel = discord.ui.Select(placeholder="絞り込み（属性）", options=fopts, row=0)
        fsel.callback = self._on_filter
        self.add_item(fsel)
        usel = discord.ui.Select(placeholder="チームに入れる3人を選んでください", options=self._unit_options(),
                                 min_values=0, max_values=3, row=1)
        usel.callback = self._on_units
        self.add_item(usel)
        abtn = discord.ui.Button(label="自動編成", emoji="🤖", style=discord.ButtonStyle.success, row=2)
        abtn.callback = self._on_auto
        self.add_item(abtn)
        cbtn = discord.ui.Button(label="この編成で決定", emoji="✅", style=discord.ButtonStyle.primary, row=2)
        cbtn.callback = self._on_confirm
        self.add_item(cbtn)

    def _summary(self) -> str:
        r = _rpg(self.gid, self.uid)
        if not self.chosen:
            return "チームに入れる3人を選んでください（属性で絞り込みもできます）:"
        lines = [unit_line(u, r["units"][u]) for u in self.chosen]
        return "現在の選択:\n" + "\n".join(lines) + "\n\nよければ「この編成で決定」を押してください。"

    async def _on_filter(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        v = interaction.data["values"][0]
        self.filter_elem = None if v == "all" else v
        self._build()
        await interaction.response.edit_message(content=self._summary(), view=self)

    async def _on_units(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        shown = {o.value for o in self._unit_options()}
        selected = list(interaction.data["values"])
        merged = [c for c in self.chosen if c not in shown] + selected
        while len(merged) > 3:
            for c in merged:
                if c not in selected:
                    merged.remove(c)
                    break
            else:
                merged.pop(0)
        self.chosen = merged
        self._build()
        await interaction.response.edit_message(content=self._summary(), view=self)

    async def _on_auto(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        await interaction.response.send_message(
            "自動編成の方針を選んでください:", view=AutoPartyView(self.gid, self.uid), ephemeral=True)

    async def _on_confirm(self, interaction: discord.Interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("これはあなたのメニューではありません。", ephemeral=True)
            return
        if not self.chosen:
            await interaction.response.send_message("1人以上選んでください（または自動編成を使ってください）。", ephemeral=True)
            return
        r = _rpg(self.gid, self.uid)
        r["party"] = list(self.chosen)
        users.save()
        lines = [unit_line(u, r["units"][u]) for u in self.chosen]
        await interaction.response.send_message("🧩 **チームを編成しました**\n" + "\n".join(lines), ephemeral=True)


def _status_embed(gid: int, uid: int, display_name: str) -> discord.Embed:
    r = _rpg(gid, uid)
    bal = users.get(gid, uid).get("money", 0)
    embed = discord.Embed(title=f"📊 {display_name} のステータス", color=discord.Color.blurple())
    embed.add_field(name="進行度", value=f"クリア済み: ステージ{r['cleared']} ／ 残高: {fmt(bal)}", inline=False)
    party_lines = [unit_line(u, r["units"][u]) for u in r["party"] if u in r["units"]]
    embed.add_field(name="現在のチーム", value="\n".join(party_lines) or "なし", inline=False)
    others = [unit_line(u, rec) for u, rec in r["units"].items() if u not in r["party"]]
    if others:
        embed.add_field(name="控えの仲間", value="\n".join(others)[:1024], inline=False)
    return embed


class RpgPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="冒険に出る", emoji="⚔️", style=discord.ButtonStyle.primary, custom_id="rpg:adventure", row=0)
    async def adventure(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(
            "挑戦するステージを選んでください:", view=StageSelectView(interaction.guild.id, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="チーム編成", emoji="🧩", style=discord.ButtonStyle.success, custom_id="rpg:party", row=0)
    async def party(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(
            "チームに入れる3人を選んでください:", view=PartySelectView(interaction.guild.id, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="仲間ガチャ", emoji="🎰", style=discord.ButtonStyle.success, custom_id="rpg:gacha", row=0)
    async def gacha(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        bal = users.get(interaction.guild.id, interaction.user.id).get("money", 0)
        await interaction.response.send_message(
            f"🎰 **仲間ガチャ**（残高 {fmt(bal)}）\nSSR 3% / SR 17% / R 80%。被りは必殺技Lv→凸の順に強化されます。",
            view=GachaView(interaction.guild.id, interaction.user.id), ephemeral=True)

    @discord.ui.button(label="ステータス", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="rpg:status", row=1)
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(
            embed=_status_embed(interaction.guild.id, interaction.user.id, interaction.user.display_name), ephemeral=True)

    @discord.ui.button(label="遊び方", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="rpg:rules", row=1)
    async def rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(_rules_text(), ephemeral=True)


# ---------------- 設置済みパネルの自動更新 ----------------
_panels_refreshed = False


@bot.listen("on_ready")
async def _refresh_rpg_panels():
    global _panels_refreshed
    if _panels_refreshed:
        return
    _panels_refreshed = True
    for gid_str in list(store.configs.keys()):
        try:
            cfg = store.cfg(int(gid_str))
            panel = cfg.get("panels", {}).get("rpg")
            if not panel:
                continue
            channel = bot.get_channel(panel["channel_id"]) or await bot.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=build_rpg_embed(), view=RpgPanelView())
        except Exception:
            pass


@bot.tree.command(name="setup_rpg", description="このチャンネルに簡易RPGパネルを設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_rpg(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get("panels", {}).get("rpg")
    if old:
        try:
            old_ch = interaction.guild.get_channel(old["channel_id"])
            if old_ch is not None:
                old_msg = await old_ch.fetch_message(old["message_id"])
                await old_msg.delete()
        except Exception:
            pass
    msg = await interaction.channel.send(embed=build_rpg_embed(), view=RpgPanelView())
    cfg.setdefault("panels", {})["rpg"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.response.send_message(
        "✅ RPGパネルを設置しました。みんなはパネルから冒険・編成・ガチャができます。", ephemeral=True)
