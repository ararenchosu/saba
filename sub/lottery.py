# -*- coding: utf-8 -*-
"""
sub/lottery.py — 宝くじ（サブBOT専用）【専用パネル版】

仕様（2026-11-10）:
- カジノのゲームメニューとは別に、宝くじ専用パネルを /setup_lottery で設置する。
  パネルの設置場所は cfg["panels"]["lottery"] に保存し、起動時に最新内容へ
  自動更新する（カジノパネルと同じ仕組み）。
- 通貨はカジノと同じ $（users.json の money を共用）。
- 2形式:
  ① 抽選形式 … 1口の料金 / 1等〜5等の賞金と当選口数 / 終了時期 を設定でき、
     締切になると自動抽選（管理者の手動抽選・キャンセル返金も可）。当選金は
     自動で残高に加算し、当選者へ DM でも知らせる。
  ② スクラッチ形式 … 1口の料金 / 絵柄ごとの賞金 / 1人の口数上限 / 全体上限
     枚数（在庫）を設定できる。3×3 のマスをめくり、1列そろえばその絵柄の
     賞金。当たりやすさは内部確率で固定し、ルール内に明示する。
     盤面は「結果を先に決めてから生成」するので還元率を制御できる。
- 設定の変更はパネルの「⚙️ 設定」ボタンから（サーバーオーナーと管理者のみ。
  許可ユーザーは含まない）。カジノの倍率設定と同じ権限ルール。
- 開催状態: 初期は両形式とも「未開催」で買えない。管理者が設定後に
  「開催する」で販売開始。抽選くじは抽選・キャンセルで自動的に未開催へ戻る。
"""

import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from sub.core import bot, store, is_home, requires
from sub.userdata import users

JST = timezone(timedelta(hours=9))

# ---------------- 既定値 ----------------
DRAW_DEFAULT_PRICE = 100
DRAW_DEFAULT_TIERS = [[10000, 1], [5000, 2], [1000, 5], [500, 10], [100, 20]]  # [賞金, 当選口数] × 5等
SCRATCH_DEFAULT_PRICE = 100
SCRATCH_SYMBOLS = ["💎", "⭐", "🔔", "🍋", "🍒"]
SCRATCH_DEFAULT_PRIZES = {"💎": 10000, "⭐": 2500, "🔔": 800, "🍋": 300, "🍒": 150}
# 当たりやすさ（1000口あたりの口数）。残りはハズレ。ルール表示にも明示する。
SCRATCH_WEIGHTS = {"💎": 3, "⭐": 10, "🔔": 25, "🍋": 50, "🍒": 100}
SCRATCH_DEFAULT_PER_USER = 10
SCRATCH_DEFAULT_CAP = 100
SCRATCH_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # 横
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # 縦
    (0, 4, 8), (2, 4, 6),             # 斜め
]


def fmt(amount: int) -> str:
    return f"${amount:,}"


def _wallet(guild_id: int, user_id: int) -> dict:
    u = users.get(guild_id, user_id)
    u.setdefault("money", 0)
    return u


def _add_money(guild_id: int, user_id: int, amount: int):
    u = _wallet(guild_id, user_id)
    u["money"] += amount
    users.save()


async def _guard(interaction) -> bool:
    if interaction.guild is None or not is_home(interaction.guild.id):
        await interaction.response.send_message("このBOTの担当サーバーではありません。", ephemeral=True)
        return False
    return True


def _can_admin(interaction) -> bool:
    """設定変更できる人: サーバーオーナー or 管理者（許可ユーザーは含まない）"""
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


# ---------------- 設定の読み書き ----------------
def _lot(guild_id: int) -> dict:
    cfg = store.cfg(guild_id)
    lot = cfg.setdefault("lottery", {})
    d = lot.setdefault("draw", {})
    d.setdefault("price", DRAW_DEFAULT_PRICE)
    tiers = d.setdefault("tiers", [list(t) for t in DRAW_DEFAULT_TIERS])
    while len(tiers) < 5:
        tiers.append([0, 0])
    d.setdefault("open", False)  # 開催中かどうか（初期は未開催。管理者が設定後に開催する）
    d.setdefault("end", "")
    d.setdefault("round", 1)
    d.setdefault("tickets", [])
    d.setdefault("last_result", "")
    s = lot.setdefault("scratch", {})
    s.setdefault("price", SCRATCH_DEFAULT_PRICE)
    prizes = s.setdefault("prizes", dict(SCRATCH_DEFAULT_PRIZES))
    for sym, p in SCRATCH_DEFAULT_PRIZES.items():
        prizes.setdefault(sym, p)
    s.setdefault("open", False)  # 開催中かどうか（初期は未開催）
    s.setdefault("per_user", SCRATCH_DEFAULT_PER_USER)
    s.setdefault("cap", SCRATCH_DEFAULT_CAP)
    s.setdefault("sold", 0)
    s.setdefault("batch", 1)
    s.setdefault("user_counts", {})
    return lot


def _end_dt(d: dict):
    raw = (d.get("end") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _parse_end(text: str):
    """終了時期の入力を datetime(JST) にする。空/なし なら None（=解除）。
    対応形式: 2026-11-20 21:00 / 2026/11/20 21:00 / 2026-11-20 / 11/20 21:00 / 11/20"""
    t = (text or "").strip()
    if t in ("", "なし", "未定", "なし（解除）"):
        return None
    now = datetime.now(JST)
    fmts_full = ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]
    for f in fmts_full:
        try:
            return datetime.strptime(t, f).replace(tzinfo=JST)
        except ValueError:
            pass
    for f in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(t, f).replace(hour=23, minute=59, tzinfo=JST)
        except ValueError:
            pass
    for f in ("%m/%d %H:%M", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(t, f).replace(year=now.year, tzinfo=JST)
            if dt <= now:
                dt = dt.replace(year=now.year + 1)
            return dt
        except ValueError:
            pass
    try:
        dt = datetime.strptime(t, "%m/%d").replace(year=now.year, hour=23, minute=59, tzinfo=JST)
        if dt <= now:
            dt = dt.replace(year=now.year + 1)
        return dt
    except ValueError:
        pass
    raise ValueError("format")


# ---------------- パネル表示 ----------------
def _hit_rate_text(sym: str) -> str:
    w = SCRATCH_WEIGHTS.get(sym, 0)
    return f"約{w / 10:g}%"


def build_lottery_embed(guild_id: int) -> discord.Embed:
    lot = _lot(guild_id)
    d, s = lot["draw"], lot["scratch"]
    embed = discord.Embed(
        title="🎟 宝くじパネル",
        description="カジノと同じ **$** で買えます。下のボタンからどうぞ。",
        color=discord.Color.gold(),
    )
    # 抽選形式
    tickets = d["tickets"]
    people = len(set(tickets))
    end = _end_dt(d)
    if end is not None:
        end_line = f"<t:{int(end.timestamp())}:F>（あと {(end - datetime.now(JST)).days} 日以内）" if end > datetime.now(JST) else "終了時刻を過ぎています（抽選処理中）"
    else:
        end_line = "未設定（管理者が設定するまで締切なし）"
    tier_lines = []
    for i, (prize, winners) in enumerate(d["tiers"][:5], 1):
        if prize > 0 and winners > 0:
            tier_lines.append(f"{i}等 {fmt(prize)} × {winners}口")
    if d["open"]:
        draw_value = (
            f"1口 **{fmt(d['price'])}** ／ 販売 {len(tickets)}口（参加 {people}人）\n"
            f"締切: {end_line}\n"
            f"賞金: {' ／ '.join(tier_lines) if tier_lines else '未設定'}"
        )
    else:
        draw_value = "⏸ **現在は未開催です**（次回の開催をお待ちください）"
    embed.add_field(
        name=f"🎫 抽選くじ（第{d['round']}回）",
        value=draw_value,
        inline=False,
    )
    if d.get("last_result"):
        embed.add_field(name="🏆 前回の結果", value=d["last_result"][:1000], inline=False)
    # スクラッチ形式
    remain = max(0, s["cap"] - s["sold"])
    prize_lines = [f"{sym} {fmt(s['prizes'].get(sym, 0))}（{_hit_rate_text(sym)}）" for sym in SCRATCH_SYMBOLS]
    if s["open"]:
        scratch_value = (
            f"1口 **{fmt(s['price'])}** ／ 残り {remain}口（全{s['cap']}口・1人{s['per_user']}口まで）\n"
            "3×3をめくって1列そろえば当選！\n"
            f"賞金: {' ／ '.join(prize_lines)}"
        )
    else:
        scratch_value = "⏸ **現在は未開催です**（次回の開催をお待ちください）"
    embed.add_field(
        name=f"✨ スクラッチ（第{s['batch']}弾）",
        value=scratch_value,
        inline=False,
    )
    embed.set_footer(text="設定の変更は「⚙️ 設定」ボタンから（オーナー・管理者専用）")
    return embed


async def _refresh_panel(guild_id: int):
    cfg = store.cfg(guild_id)
    panel = cfg.get("panels", {}).get("lottery")
    if not panel:
        return
    try:
        channel = bot.get_channel(panel["channel_id"]) or await bot.fetch_channel(panel["channel_id"])
        message = await channel.fetch_message(panel["message_id"])
        await message.edit(embed=build_lottery_embed(guild_id), view=LotteryPanelView())
    except Exception:
        pass


# ---------------- 抽選の実行 ----------------
async def _run_draw(guild: discord.Guild, *, manual: bool = False) -> str:
    """現在の回を抽選して当選金を払い、次回へ進める。結果の要約文字列を返す。"""
    lot = _lot(guild.id)
    d = lot["draw"]
    tickets = list(d["tickets"])
    price = d["price"]
    result_lines = []
    if not tickets:
        result_lines.append("参加者がいなかったため当選者なし")
    else:
        shuffled = random.sample(tickets, len(tickets))
        idx = 0
        dm_targets = {}
        for ti, (prize, winners) in enumerate(d["tiers"][:5], 1):
            if prize <= 0 or winners <= 0 or idx >= len(shuffled):
                continue
            take = shuffled[idx:idx + winners]
            idx += len(take)
            agg = {}
            for uid in take:
                agg[uid] = agg.get(uid, 0) + 1
            for uid, cnt in agg.items():
                _add_money(guild.id, uid, prize * cnt)
                dm_targets[uid] = dm_targets.get(uid, 0) + prize * cnt
            names = "、".join(f"<@{uid}>" + (f"×{c}" if c > 1 else "") for uid, c in agg.items())
            result_lines.append(f"{ti}等 {fmt(prize)} … {names}")
        # 当選者へDM
        for uid, total in dm_targets.items():
            try:
                user = await bot.fetch_user(uid)
                await user.send(f"🎉 宝くじ（{guild.name}）第{d['round']}回で **{fmt(total)}** が当たりました！残高に加算済みです。")
            except Exception:
                pass
    summary = "\n".join(result_lines)
    d["last_result"] = (f"第{d['round']}回（{datetime.now(JST).strftime('%Y-%m-%d %H:%M')}）\n" + summary)[:1000]
    d["tickets"] = []
    d["round"] += 1
    d["end"] = ""
    d["open"] = False  # 抽選が終わったら未開催に戻る（次回は管理者が開催する）
    store.save_config()
    # 結果をパネルのチャンネルへ投稿
    cfg = store.cfg(guild.id)
    panel = cfg.get("panels", {}).get("lottery")
    if panel:
        try:
            channel = bot.get_channel(panel["channel_id"]) or await bot.fetch_channel(panel["channel_id"])
            embed = discord.Embed(title=f"🎟 宝くじ抽選結果（第{d['round'] - 1}回）", description=summary, color=discord.Color.gold())
            embed.set_footer(text="当選金は自動で残高に加算されています")
            await channel.send(embed=embed)
        except Exception:
            pass
    await _refresh_panel(guild.id)
    return summary


async def _cancel_draw(guild: discord.Guild) -> int:
    """現在の回をキャンセルし、全員へ返金する。返金総額を返す。"""
    lot = _lot(guild.id)
    d = lot["draw"]
    total = 0
    agg = {}
    for uid in d["tickets"]:
        agg[uid] = agg.get(uid, 0) + 1
    for uid, cnt in agg.items():
        refund = d["price"] * cnt
        _add_money(guild.id, uid, refund)
        total += refund
    d["tickets"] = []
    d["end"] = ""
    d["open"] = False
    d["round"] += 1
    d["last_result"] = f"第{d['round'] - 1}回はキャンセルされました（全員へ返金済み）"
    store.save_config()
    await _refresh_panel(guild.id)
    return total


# ---------------- 購入（抽選） ----------------
class DrawBuyModal(discord.ui.Modal, title="抽選くじを買う"):
    count = discord.ui.TextInput(label="何口買いますか？", placeholder="例: 3", default="1", max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        lot = _lot(interaction.guild.id)
        d = lot["draw"]
        if not d["open"]:
            await interaction.response.send_message("⏸ 抽選くじは現在未開催です。", ephemeral=True)
            return
        try:
            n = int(str(self.count.value).strip())
        except ValueError:
            await interaction.response.send_message("口数は数字で入力してください。", ephemeral=True)
            return
        if n < 1 or n > 1000:
            await interaction.response.send_message("1〜1000口の範囲で入力してください。", ephemeral=True)
            return
        end = _end_dt(d)
        if end is not None and datetime.now(JST) >= end:
            await interaction.response.send_message("この回は締切を過ぎたため買えません（抽選処理中）。", ephemeral=True)
            return
        cost = d["price"] * n
        u = _wallet(interaction.guild.id, interaction.user.id)
        if u["money"] < cost:
            await interaction.response.send_message(
                f"残高が足りません（必要 {fmt(cost)} ／ 残高 {fmt(u['money'])}）。カジノのログインボーナス等で貯めてください。",
                ephemeral=True,
            )
            return
        u["money"] -= cost
        users.save()
        d["tickets"].extend([interaction.user.id] * n)
        store.save_config()
        await interaction.response.send_message(
            f"🎫 第{d['round']}回の抽選くじを **{n}口** 買いました（{fmt(cost)}）。\n"
            f"あなたの現在の口数: {d['tickets'].count(interaction.user.id)}口 ／ 残高: {fmt(u['money'])}",
            ephemeral=True,
        )
        await _refresh_panel(interaction.guild.id)


# ---------------- スクラッチ ----------------
def _roll_scratch():
    """結果を先に決める: 当たり絵柄 or None（ハズレ）"""
    pool = list(SCRATCH_WEIGHTS.keys()) + [None]
    weights = list(SCRATCH_WEIGHTS.values()) + [1000 - sum(SCRATCH_WEIGHTS.values())]
    return random.choices(pool, weights=weights, k=1)[0]


def _board_wins(board) -> list:
    wins = []
    for a, b, c in SCRATCH_LINES:
        if board[a] == board[b] == board[c]:
            wins.append(board[a])
    return wins


def _make_board(win_symbol) -> list:
    """当たり盤面は狙った絵柄の列がちょうど1つだけ、ハズレ盤面は列ゼロになるよう生成"""
    for _ in range(1000):
        board = [random.choice(SCRATCH_SYMBOLS) for _ in range(9)]
        if win_symbol:
            line = random.choice(SCRATCH_LINES)
            for i in line:
                board[i] = win_symbol
            if _board_wins(board) == [win_symbol]:
                return board
        else:
            if _board_wins(board) == []:
                return board
    # フォールバック（ほぼ到達しない）
    board = ["🍒", "🍋", "🔔", "⭐", "💎", "🍒", "🍋", "🔔", "⭐"]
    if win_symbol:
        for i in SCRATCH_LINES[0]:
            board[i] = win_symbol
    return board


class ScratchView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, board: list, win_symbol):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.user_id = user_id
        self.board = board
        self.win_symbol = win_symbol
        self.revealed = [False] * 9
        self.settled = False
        self.message = None
        for i in range(9):
            btn = discord.ui.Button(label="❔", style=discord.ButtonStyle.secondary, row=i // 3, custom_id=f"lottery:cell:{i}")
            btn.callback = self._make_callback(i)
            self.add_item(btn)
        all_btn = discord.ui.Button(label="全部めくる", emoji="👉", style=discord.ButtonStyle.primary, row=3, custom_id="lottery:cell:all")
        all_btn.callback = self._reveal_all
        self.add_item(all_btn)

    def _make_callback(self, idx: int):
        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("これはあなたのスクラッチではありません。", ephemeral=True)
                return
            self.revealed[idx] = True
            await self._update(interaction)
        return _cb

    async def _reveal_all(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("これはあなたのスクラッチではありません。", ephemeral=True)
            return
        self.revealed = [True] * 9
        await self._update(interaction)

    def _win_now(self):
        """そろった当たり列の絵柄（なければ None）。全マス確定 or 当たり列完成で判定"""
        for a, b, c in SCRATCH_LINES:
            if self.revealed[a] and self.revealed[b] and self.revealed[c]:
                if self.board[a] == self.board[b] == self.board[c]:
                    return self.board[a]
        return None

    def _render(self, footer: str) -> str:
        cells = [self.board[i] if self.revealed[i] else "❔" for i in range(9)]
        grid = "\n".join(" ".join(cells[r * 3:(r + 1) * 3]) for r in range(3))
        return f"✨ **スクラッチ**\n{grid}\n{footer}"

    async def _update(self, interaction: discord.Interaction):
        win = self._win_now()
        done = all(self.revealed) or win is not None
        if done and not self.settled:
            self.settled = True
            self.revealed = [True] * 9
            lot = _lot(self.guild_id)
            prize = 0
            if win:
                prize = lot["scratch"]["prizes"].get(win, 0)
            if prize > 0:
                _add_money(self.guild_id, self.user_id, prize)
                bal = _wallet(self.guild_id, self.user_id)["money"]
                footer = f"🎉 **{win} がそろった！ {fmt(prize)} ゲット！** 残高: {fmt(bal)}"
            else:
                footer = "残念、ハズレでした… また挑戦してね！"
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content=self._render(footer), view=self)
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id and child.custom_id.startswith("lottery:cell:") and child.custom_id != "lottery:cell:all":
                i = int(child.custom_id.rsplit(":", 1)[1])
                if self.revealed[i]:
                    child.label = self.board[i]
                    child.disabled = True
        left = self.revealed.count(False)
        await interaction.response.edit_message(content=self._render(f"あと {left} マス。タップでめくれます"), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content=self._render("⏰ 時間切れで無効になりました"), view=self)
            except Exception:
                pass


# ---------------- パネル ----------------
def _rules_text(guild_id: int) -> str:
    lot = _lot(guild_id)
    d, s = lot["draw"], lot["scratch"]
    tiers = " ／ ".join(
        f"{i}等 {fmt(p)}×{w}口" for i, (p, w) in enumerate(d["tiers"][:5], 1) if p > 0 and w > 0
    ) or "未設定"
    sp = " ／ ".join(f"{sym} {fmt(s['prizes'].get(sym, 0))}（{_hit_rate_text(sym)}）" for sym in SCRATCH_SYMBOLS)
    lose = 100 - sum(SCRATCH_WEIGHTS.values()) / 10
    return (
        "**🎫 抽選くじ**\n"
        f"・1口 {fmt(d['price'])}。締切（終了時期）が来ると自動で抽選され、当選金は残高に自動加算＋DMでお知らせします。\n"
        f"・賞金: {tiers}\n"
        "・同じ人が複数口当選することもあります。締切未設定の間は管理者が手動で抽選できます。\n\n"
        "**✨ スクラッチ**\n"
        f"・1口 {fmt(s['price'])}。3×3のマスをめくり、タテ・ヨコ・ナナメのどれか1列が同じ絵柄でそろえば当選。\n"
        f"・賞金: {sp} ／ ハズレ 約{lose:g}%\n"
        f"・1人 {s['per_user']}口まで（第{s['batch']}弾）。在庫がなくなると売り切れです。\n"
        "・途中で閉じたり10分放置すると、そのスクラッチは無効になります。"
    )


class LotteryPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="抽選くじを買う", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="lottery:buy_draw", row=0)
    async def buy_draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        if not _lot(interaction.guild.id)["draw"]["open"]:
            await interaction.response.send_message("⏸ 抽選くじは現在未開催です。開催をお待ちください。", ephemeral=True)
            return
        await interaction.response.send_modal(DrawBuyModal())

    @discord.ui.button(label="スクラッチを買う", emoji="✨", style=discord.ButtonStyle.success, custom_id="lottery:buy_scratch", row=0)
    async def buy_scratch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        gid, uid = interaction.guild.id, interaction.user.id
        lot = _lot(gid)
        s = lot["scratch"]
        if not s["open"]:
            await interaction.response.send_message("⏸ スクラッチは現在未開催です。開催をお待ちください。", ephemeral=True)
            return
        if s["sold"] >= s["cap"]:
            await interaction.response.send_message("この弾は売り切れです。次の弾をお待ちください。", ephemeral=True)
            return
        cnt = s["user_counts"].get(str(uid), 0)
        if cnt >= s["per_user"]:
            await interaction.response.send_message(f"この弾は1人 {s['per_user']}口までです（あなたは {cnt}口購入済み）。", ephemeral=True)
            return
        u = _wallet(gid, uid)
        if u["money"] < s["price"]:
            await interaction.response.send_message(
                f"残高が足りません（必要 {fmt(s['price'])} ／ 残高 {fmt(u['money'])}）。", ephemeral=True)
            return
        u["money"] -= s["price"]
        users.save()
        s["sold"] += 1
        s["user_counts"][str(uid)] = cnt + 1
        store.save_config()
        win = _roll_scratch()
        board = _make_board(win)
        view = ScratchView(gid, uid, board, win)
        await interaction.response.send_message(view._render("タップでめくってね。1列そろえば当選！"), view=view, ephemeral=True)
        view.message = await interaction.original_response()
        await _refresh_panel(gid)

    @discord.ui.button(label="自分のチケット", emoji="🎟", style=discord.ButtonStyle.secondary, custom_id="lottery:my", row=1)
    async def my_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        gid, uid = interaction.guild.id, interaction.user.id
        lot = _lot(gid)
        d, s = lot["draw"], lot["scratch"]
        my_draw = d["tickets"].count(uid)
        my_scratch = s["user_counts"].get(str(uid), 0)
        bal = _wallet(gid, uid)["money"]
        await interaction.response.send_message(
            f"🎟 **{interaction.user.display_name} のチケット**\n"
            f"抽選くじ（第{d['round']}回）: {my_draw}口\n"
            f"スクラッチ（第{s['batch']}弾）: {my_scratch}口購入（上限 {s['per_user']}口）\n"
            f"残高: {fmt(bal)}",
            ephemeral=True,
        )

    @discord.ui.button(label="ルール", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="lottery:rules", row=1)
    async def rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_message(_rules_text(interaction.guild.id), ephemeral=True)

    @discord.ui.button(label="設定（管理者）", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="lottery:admin", row=1)
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        if not _can_admin(interaction):
            await interaction.response.send_message("設定を変更できるのはサーバーオーナーと管理者だけです。", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_admin_embed(interaction.guild.id), view=LotteryAdminView(), ephemeral=True)


# ---------------- 管理者設定 ----------------
def _admin_embed(guild_id: int) -> discord.Embed:
    lot = _lot(guild_id)
    d, s = lot["draw"], lot["scratch"]
    end = _end_dt(d)
    tiers = " ／ ".join(f"{i}等 {fmt(p)}×{w}口" for i, (p, w) in enumerate(d["tiers"][:5], 1))
    sp = " ／ ".join(f"{sym} {fmt(s['prizes'].get(sym, 0))}" for sym in SCRATCH_SYMBOLS)
    embed = discord.Embed(title="⚙️ 宝くじ設定（オーナー・管理者専用）", color=discord.Color.blurple())
    embed.add_field(name="🎫 抽選くじ", value=(
        f"状態: {'🟢 開催中' if d['open'] else '⏸ 未開催'} ／ 1口: {fmt(d['price'])} ／ 第{d['round']}回 ／ 販売 {len(d['tickets'])}口\n"
        f"賞金: {tiers}\n"
        f"終了時期: {end.strftime('%Y-%m-%d %H:%M') if end else '未設定'}"
    ), inline=False)
    embed.add_field(name="✨ スクラッチ", value=(
        f"状態: {'🟢 開催中' if s['open'] else '⏸ 未開催'} ／ 1口: {fmt(s['price'])} ／ 第{s['batch']}弾 ／ 販売 {s['sold']}/{s['cap']}口 ／ 1人上限 {s['per_user']}口\n"
        f"賞金: {sp}"
    ), inline=False)
    embed.set_footer(text="下のメニューから変更する項目を選んでください")
    return embed


class ConfirmView(discord.ui.View):
    def __init__(self, user_id: int, action, label: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.action = action
        self.label = label

    @discord.ui.button(label="実行する", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("実行できるのは操作した本人だけです。", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"⏳ {self.label} を実行中…", view=self)
        msg = await self.action(interaction)
        await interaction.followup.send(msg, ephemeral=True)
        await _refresh_panel(interaction.guild.id)

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("操作した本人だけが押せます。", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="キャンセルしました。", view=self)


class _PriceModal(discord.ui.Modal):
    def __init__(self, kind: str, current: int):
        super().__init__(title=("抽選くじ" if kind == "draw" else "スクラッチ") + "：1口の料金")
        self.kind = kind
        self.price = discord.ui.TextInput(label="料金（$）", default=str(current), max_length=9)
        self.add_item(self.price)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = int(str(self.price.value).replace(",", "").replace("$", "").strip())
        except ValueError:
            await interaction.response.send_message("料金は数字で入力してください。", ephemeral=True)
            return
        if v < 1 or v > 100_000_000:
            await interaction.response.send_message("1〜100,000,000 の範囲で入力してください。", ephemeral=True)
            return
        lot = _lot(interaction.guild.id)
        lot["draw" if self.kind == "draw" else "scratch"]["price"] = v
        store.save_config()
        await interaction.response.send_message(f"✅ 1口の料金を **{fmt(v)}** にしました。", ephemeral=True)
        await _refresh_panel(interaction.guild.id)


class _TierModal(discord.ui.Modal):
    def __init__(self, tier_idx: int, prize: int, winners: int):
        super().__init__(title=f"抽選くじ：{tier_idx + 1}等の設定")
        self.tier_idx = tier_idx
        self.prize = discord.ui.TextInput(label="賞金（$）", default=str(prize), max_length=9)
        self.winners = discord.ui.TextInput(label="当選口数（0で無効）", default=str(winners), max_length=4)
        self.add_item(self.prize)
        self.add_item(self.winners)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            p = int(str(self.prize.value).replace(",", "").strip())
            w = int(str(self.winners.value).strip())
        except ValueError:
            await interaction.response.send_message("賞金と口数は数字で入力してください。", ephemeral=True)
            return
        if p < 0 or w < 0 or p > 100_000_000 or w > 10000:
            await interaction.response.send_message("範囲外です（賞金 0〜100,000,000 / 口数 0〜10,000）。", ephemeral=True)
            return
        lot = _lot(interaction.guild.id)
        lot["draw"]["tiers"][self.tier_idx] = [p, w]
        store.save_config()
        await interaction.response.send_message(
            f"✅ {self.tier_idx + 1}等を **{fmt(p)} × {w}口** にしました。", ephemeral=True)
        await _refresh_panel(interaction.guild.id)


class _EndModal(discord.ui.Modal, title="抽選くじ：終了時期"):
    end = discord.ui.TextInput(
        label="終了時期（JST）", placeholder="2026-11-20 21:00 ／ 11/20 21:00 ／ なし で解除", max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.end.value).strip()
        try:
            dt = _parse_end(raw)
        except ValueError:
            await interaction.response.send_message("形式が読み取れませんでした。例: 2026-11-20 21:00 / 11/20 21:00", ephemeral=True)
            return
        if dt is not None and dt <= datetime.now(JST):
            await interaction.response.send_message("終了時期は未来の日時を指定してください。", ephemeral=True)
            return
        lot = _lot(interaction.guild.id)
        lot["draw"]["end"] = dt.isoformat() if dt else ""
        store.save_config()
        msg = f"✅ 終了時期を **{dt.strftime('%Y-%m-%d %H:%M')}** にしました。この時刻になると自動で抽選されます。" if dt else "✅ 終了時期を解除しました（手動抽選のみ）。"
        await interaction.response.send_message(msg, ephemeral=True)
        await _refresh_panel(interaction.guild.id)


class _SymbolModal(discord.ui.Modal):
    def __init__(self, symbol: str, current: int):
        super().__init__(title=f"スクラッチ：{symbol} の賞金")
        self.symbol = symbol
        self.prize = discord.ui.TextInput(label="賞金（$）", default=str(current), max_length=9)
        self.add_item(self.prize)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = int(str(self.prize.value).replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message("賞金は数字で入力してください。", ephemeral=True)
            return
        if v < 0 or v > 100_000_000:
            await interaction.response.send_message("0〜100,000,000 の範囲で入力してください。", ephemeral=True)
            return
        lot = _lot(interaction.guild.id)
        lot["scratch"]["prizes"][self.symbol] = v
        store.save_config()
        await interaction.response.send_message(f"✅ {self.symbol} の賞金を **{fmt(v)}** にしました。", ephemeral=True)
        await _refresh_panel(interaction.guild.id)


class _LimitsModal(discord.ui.Modal, title="スクラッチ：口数・上限"):
    def __init__(self, per_user: int, cap: int):
        self.per_user_in = discord.ui.TextInput(label="1人の口数上限", default=str(per_user), max_length=5)
        self.cap_in = discord.ui.TextInput(label="全体の上限枚数（在庫）", default=str(cap), max_length=6)
        self.add_item(self.per_user_in)
        self.add_item(self.cap_in)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pu = int(str(self.per_user_in.value).strip())
            cap = int(str(self.cap_in.value).strip())
        except ValueError:
            await interaction.response.send_message("数字で入力してください。", ephemeral=True)
            return
        if pu < 1 or cap < 1 or pu > 10000 or cap > 100000:
            await interaction.response.send_message("範囲外です（1人上限 1〜10,000 / 全体 1〜100,000）。", ephemeral=True)
            return
        lot = _lot(interaction.guild.id)
        lot["scratch"]["per_user"] = pu
        lot["scratch"]["cap"] = cap
        store.save_config()
        await interaction.response.send_message(f"✅ 1人上限 **{pu}口** ／ 全体上限 **{cap}口** にしました。", ephemeral=True)
        await _refresh_panel(interaction.guild.id)


class _TierPickerView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        lot = _lot(guild_id)
        opts = [
            discord.SelectOption(label=f"{i + 1}等", value=str(i), description=f"現在: {fmt(p)} × {w}口")
            for i, (p, w) in enumerate(lot["draw"]["tiers"][:5])
        ]
        sel = discord.ui.Select(placeholder="設定する等級を選んでください", options=opts)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        lot = _lot(interaction.guild.id)
        p, w = lot["draw"]["tiers"][idx]
        await interaction.response.send_modal(_TierModal(idx, p, w))


class _SymbolPickerView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        lot = _lot(guild_id)
        opts = [
            discord.SelectOption(label=f"{sym} の賞金", value=sym, emoji=sym if len(sym) <= 2 else None,
                                 description=f"現在: {fmt(lot['scratch']['prizes'].get(sym, 0))}（当たりやすさ {_hit_rate_text(sym)}）")
            for sym in SCRATCH_SYMBOLS
        ]
        sel = discord.ui.Select(placeholder="設定する絵柄を選んでください", options=opts)
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        sym = interaction.data["values"][0]
        lot = _lot(interaction.guild.id)
        await interaction.response.send_modal(_SymbolModal(sym, lot["scratch"]["prizes"].get(sym, 0)))


class LotteryAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        sel = discord.ui.Select(
            placeholder="変更する項目を選んでください",
            options=[
                discord.SelectOption(label="抽選：開催する／終了する", value="draw_toggle", emoji="🎫"),
                discord.SelectOption(label="抽選：1口の料金", value="draw_price", emoji="🎫"),
                discord.SelectOption(label="抽選：等級の賞金・当選口数", value="draw_tier", emoji="🏆"),
                discord.SelectOption(label="抽選：終了時期", value="draw_end", emoji="⏰"),
                discord.SelectOption(label="抽選：今すぐ抽選する", value="draw_now", emoji="🎲"),
                discord.SelectOption(label="抽選：回をキャンセルして返金", value="draw_cancel", emoji="↩️"),
                discord.SelectOption(label="スクラッチ：開催する／終了する", value="scratch_toggle", emoji="✨"),
                discord.SelectOption(label="スクラッチ：1口の料金", value="scratch_price", emoji="✨"),
                discord.SelectOption(label="スクラッチ：絵柄の賞金", value="scratch_prize", emoji="💎"),
                discord.SelectOption(label="スクラッチ：口数・全体上限", value="scratch_limits", emoji="🔢"),
                discord.SelectOption(label="スクラッチ：在庫リセット（次の弾へ）", value="scratch_restock", emoji="📦"),
            ],
        )
        sel.callback = self._cb
        self.add_item(sel)

    async def _cb(self, interaction: discord.Interaction):
        if not _can_admin(interaction):
            await interaction.response.send_message("設定を変更できるのはサーバーオーナーと管理者だけです。", ephemeral=True)
            return
        v = interaction.data["values"][0]
        gid = interaction.guild.id
        lot = _lot(gid)
        if v == "draw_toggle":
            if lot["draw"]["open"]:
                if lot["draw"]["tickets"]:
                    await interaction.response.send_message(
                        "チケットが販売済みのため、そのまま終了はできません。「今すぐ抽選する」か「キャンセルして返金」で締めてください。",
                        ephemeral=True)
                else:
                    lot["draw"]["open"] = False
                    store.save_config()
                    await interaction.response.send_message("⏸ 抽選くじを未開催にしました。", ephemeral=True)
                    await _refresh_panel(gid)
            else:
                lot["draw"]["open"] = True
                store.save_config()
                await interaction.response.send_message(
                    f"▶️ 第{lot['draw']['round']}回を開催しました。チケット販売中です"
                    + ("。" if not _end_dt(lot["draw"]) else f"（締切: {_end_dt(lot['draw']).strftime('%Y-%m-%d %H:%M')}）"),
                    ephemeral=True)
                await _refresh_panel(gid)
        elif v == "scratch_toggle":
            if lot["scratch"]["open"]:
                lot["scratch"]["open"] = False
                store.save_config()
                await interaction.response.send_message("⏸ スクラッチを未開催にしました。", ephemeral=True)
                await _refresh_panel(gid)
            elif lot["scratch"]["sold"] >= lot["scratch"]["cap"]:
                await interaction.response.send_message(
                    "在庫が売り切れのままです。先に「在庫リセット（次の弾へ）」をしてから開催してください。", ephemeral=True)
            else:
                lot["scratch"]["open"] = True
                store.save_config()
                await interaction.response.send_message(
                    f"▶️ スクラッチ第{lot['scratch']['batch']}弾を開催しました。", ephemeral=True)
                await _refresh_panel(gid)
        elif v == "draw_price":
            await interaction.response.send_modal(_PriceModal("draw", lot["draw"]["price"]))
        elif v == "scratch_price":
            await interaction.response.send_modal(_PriceModal("scratch", lot["scratch"]["price"]))
        elif v == "draw_tier":
            await interaction.response.send_message("等級を選んでください:", view=_TierPickerView(gid), ephemeral=True)
        elif v == "scratch_prize":
            await interaction.response.send_message("絵柄を選んでください:", view=_SymbolPickerView(gid), ephemeral=True)
        elif v == "draw_end":
            await interaction.response.send_modal(_EndModal())
        elif v == "scratch_limits":
            await interaction.response.send_modal(_LimitsModal(lot["scratch"]["per_user"], lot["scratch"]["cap"]))
        elif v == "draw_now":
            async def _do(inter: discord.Interaction) -> str:
                summary = await _run_draw(inter.guild, manual=True)
                return f"🎲 抽選を実行しました。\n{summary}"
            await interaction.response.send_message(
                f"第{lot['draw']['round']}回を今すぐ抽選しますか？（販売 {len(lot['draw']['tickets'])}口）",
                view=ConfirmView(interaction.user.id, _do, "抽選"), ephemeral=True)
        elif v == "draw_cancel":
            async def _do(inter: discord.Interaction) -> str:
                total = await _cancel_draw(inter.guild)
                return f"↩️ 回をキャンセルし、合計 {fmt(total)} を返金しました。"
            await interaction.response.send_message(
                f"第{lot['draw']['round']}回をキャンセルして全員に返金しますか？（販売 {len(lot['draw']['tickets'])}口）",
                view=ConfirmView(interaction.user.id, _do, "キャンセル"), ephemeral=True)
        elif v == "scratch_restock":
            async def _do(inter: discord.Interaction) -> str:
                lot2 = _lot(inter.guild.id)
                lot2["scratch"]["sold"] = 0
                lot2["scratch"]["user_counts"] = {}
                lot2["scratch"]["batch"] += 1
                store.save_config()
                return f"📦 在庫をリセットしました（第{lot2['scratch']['batch']}弾スタート）。"
            await interaction.response.send_message(
                "在庫をリセットして次の弾に進みますか？（販売数と1人あたりの購入数がリセットされます）",
                view=ConfirmView(interaction.user.id, _do, "在庫リセット"), ephemeral=True)


# ---------------- 自動抽選ループ ----------------
@tasks.loop(minutes=1)
async def _lottery_loop():
    now = datetime.now(JST)
    for gid_str in list(store.configs.keys()):
        try:
            lot = _lot(int(gid_str))
            end = _end_dt(lot["draw"])
            if end is not None and now >= end:
                guild = bot.get_guild(int(gid_str))
                if guild is not None:
                    await _run_draw(guild)
        except Exception:
            pass


_lottery_ready = False


@bot.listen("on_ready")
async def _lottery_on_ready():
    global _lottery_ready
    if _lottery_ready:
        return
    _lottery_ready = True
    if not _lottery_loop.is_running():
        _lottery_loop.start()
    for gid_str in list(store.configs.keys()):
        await _refresh_panel(int(gid_str))


# ---------------- 設置コマンド ----------------
@bot.tree.command(name="setup_lottery", description="このチャンネルに宝くじ専用パネルを設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_lottery(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    old = cfg.get("panels", {}).get("lottery")
    if old:
        try:
            old_ch = interaction.guild.get_channel(old["channel_id"])
            if old_ch is not None:
                old_msg = await old_ch.fetch_message(old["message_id"])
                await old_msg.delete()
        except Exception:
            pass
    msg = await interaction.channel.send(embed=build_lottery_embed(interaction.guild.id), view=LotteryPanelView())
    cfg.setdefault("panels", {})["lottery"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.response.send_message(
        "✅ 宝くじパネルを設置しました。料金・賞金・終了時期などの設定は、パネルの「⚙️ 設定（管理者）」ボタンから変更できます。",
        ephemeral=True,
    )
