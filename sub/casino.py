# -*- coding: utf-8 -*-
"""
sub/casino.py — カジノ（サブBOT専用）

通貨は $ 。所持金は users.json に保存（money）。
- パネル（/setup_casino で設置）: ログインボーナス（ボタン式・1日1回 $5000）/ 残高 / ランキング / 4ゲーム
- ゲーム: スロット / バカラ / ハイアンドロー / マインズ（掛け金はモーダル入力式）
- お金の増減はサーバーオーナー専用コマンド /money_add /money_remove のみ
- ゲームの結果はすべて自分だけ見える（ephemeral）表示
"""

import random
from datetime import datetime, timedelta, timezone
from math import comb

import discord
from discord import app_commands

from sub.core import bot, store, is_home
from sub.userdata import users

JST = timezone(timedelta(hours=9))
LOGIN_BONUS = 5000
MIN_BET = 10


def _wallet(guild_id: int, user_id: int) -> dict:
    u = users.get(guild_id, user_id)
    u.setdefault("money", 0)
    u.setdefault("login_bonus_date", "")
    return u


def _today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def fmt(amount: int) -> str:
    return f"${amount:,}"


async def _guard(interaction) -> bool:
    if interaction.guild is None or not is_home(interaction.guild.id):
        await interaction.response.send_message("このBOTの担当サーバーではありません。", ephemeral=True)
        return False
    return True


def _parse_bet(raw: str):
    try:
        return int(raw.strip().replace(",", "").replace("$", "").replace("＄", ""))
    except Exception:
        return None


# ---------------- スロット ----------------
SLOT_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 26, 20, 12, 8, 4]
SLOT_TRIPLE = {"🍒": 4, "🍋": 6, "🔔": 10, "⭐": 15, "💎": 25, "7️⃣": 50}


def slot_spin():
    return [random.choices(SLOT_SYMBOLS, SLOT_WEIGHTS)[0] for _ in range(3)]


def slot_payout(bet: int, reels) -> int:
    if reels[0] == reels[1] == reels[2]:
        return bet * SLOT_TRIPLE[reels[0]]
    if len(set(reels)) == 2:
        return int(bet * 1.2)
    return 0


# ---------------- バカラ ----------------
RANKS = [(1, "A"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6"), (7, "7"), (8, "8"), (9, "9"), (10, "10"), (11, "J"), (12, "Q"), (13, "K")]
SUITS = ["♠️", "♥️", "♦️", "♣️"]


def _new_shoe():
    deck = [(r, s) for r, _ in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def _card_text(card) -> str:
    rank, suit = card
    label = dict(RANKS)[rank]
    return f"{suit}{label}"


def _hand_value(cards) -> int:
    return sum(min(r, 10) if r > 10 else (0 if r == 10 else r) for r, _ in cards) % 10


def deal_baccarat():
    """(player_cards, banker_cards) を正式ルールで配る"""
    deck = _new_shoe()
    player = [deck.pop(), deck.pop()]
    banker = [deck.pop(), deck.pop()]
    pv, bv = _hand_value(player), _hand_value(banker)
    if pv < 8 and bv < 8:  # ナチュラルでなければ続行
        p_third = None
        if pv <= 5:
            p_third = deck.pop()
            player.append(p_third)
        if p_third is None:
            if bv <= 5:
                banker.append(deck.pop())
        else:
            t = _hand_value([p_third])
            if bv <= 2:
                banker.append(deck.pop())
            elif bv == 3 and t != 8:
                banker.append(deck.pop())
            elif bv == 4 and t in (2, 3, 4, 5, 6, 7):
                banker.append(deck.pop())
            elif bv == 5 and t in (4, 5, 6, 7):
                banker.append(deck.pop())
            elif bv == 6 and t in (6, 7):
                banker.append(deck.pop())
    return player, banker


def baccarat_winner(player, banker) -> str:
    pv, bv = _hand_value(player), _hand_value(banker)
    if pv > bv:
        return "player"
    if bv > pv:
        return "banker"
    return "tie"


def baccarat_payout(bet: int, side: str, winner: str) -> int:
    """払い戻し総額（掛け金含む）。負けは0、タイ結果でプレイヤー/バンカー賭けは返金"""
    if winner == "tie":
        if side == "tie":
            return bet * 8
        return bet  # プッシュ（返金）
    if side == winner == "player":
        return bet * 2
    if side == winner == "banker":
        return int(bet * 1.95)
    return 0


# ---------------- ハイアンドロー ----------------
def hl_payout(bet: int) -> int:
    return int(bet * 1.9)


# ---------------- マインズ ----------------
MINES_TILES = 20


def mines_multiplier(tiles: int, mines: int, revealed: int) -> float:
    if revealed <= 0:
        return 1.0
    return comb(tiles, revealed) / comb(tiles - mines, revealed) * 0.97


# ---------------- 掛け金モーダル ----------------
class BetModal(discord.ui.Modal, title="掛け金を入力"):
    bet = discord.ui.TextInput(label="掛け金（$）", placeholder="例: 1000", max_length=10)

    def __init__(self, game: str):
        super().__init__()
        self.game = game

    async def on_submit(self, interaction: discord.Interaction):
        amount = _parse_bet(self.bet.value)
        if amount is None:
            await interaction.response.send_message("掛け金は数字で入力してね。", ephemeral=True)
            return
        u = _wallet(interaction.guild.id, interaction.user.id)
        if amount < MIN_BET:
            await interaction.response.send_message(f"最小掛け金は {fmt(MIN_BET)} だよ。", ephemeral=True)
            return
        if amount > u["money"]:
            await interaction.response.send_message(f"残高が足りません（残高: {fmt(u['money'])}）。ログインボーナスで受け取ってね。", ephemeral=True)
            return
        if self.game == "slot":
            u["money"] -= amount
            reels = slot_spin()
            pay = slot_payout(amount, reels)
            u["money"] += pay
            users.save()
            embed = discord.Embed(title="🎰 スロット", color=discord.Color.gold() if pay > amount else discord.Color.greyple())
            embed.description = f"## {' '.join(reels)}"
            if pay > amount:
                embed.add_field(name="結果", value=f"🎉 当たり！ **{fmt(pay)}** 獲得（+{fmt(pay - amount)}）", inline=False)
            elif pay > 0:
                embed.add_field(name="結果", value=f"ペアで **{fmt(pay)}** 戻ってきました（-{fmt(amount - pay)}）", inline=False)
            else:
                embed.add_field(name="結果", value=f"ハズレ… **{fmt(amount)}** を失いました", inline=False)
            embed.add_field(name="残高", value=fmt(u["money"]), inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif self.game == "baccarat":
            await interaction.response.send_message(
                f"掛け金 {fmt(amount)}。どっちに賭ける？",
                view=BaccaratSideView(amount),
                ephemeral=True,
            )
        elif self.game == "highlow":
            u["money"] -= amount
            users.save()
            view = HighLowView(amount)
            await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


class MinesBetModal(discord.ui.Modal, title="マインズ: 掛け金と地雷の数"):
    bet = discord.ui.TextInput(label="掛け金（$）", placeholder="例: 1000", max_length=10)
    mines = discord.ui.TextInput(label="地雷の数（1〜19）", default="4", max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        amount = _parse_bet(self.bet.value)
        m = _parse_bet(self.mines.value)
        if amount is None or m is None:
            await interaction.response.send_message("数字で入力してね。", ephemeral=True)
            return
        if m < 1 or m > MINES_TILES - 1:
            await interaction.response.send_message(f"地雷の数は1〜{MINES_TILES - 1}で指定してね。", ephemeral=True)
            return
        u = _wallet(interaction.guild.id, interaction.user.id)
        if amount < MIN_BET:
            await interaction.response.send_message(f"最小掛け金は {fmt(MIN_BET)} だよ。", ephemeral=True)
            return
        if amount > u["money"]:
            await interaction.response.send_message(f"残高が足りません（残高: {fmt(u['money'])}）。ログインボーナスで受け取ってね。", ephemeral=True)
            return
        u["money"] -= amount
        users.save()
        view = MinesView(amount, m)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


# ---------------- バカラ: サイド選択 ----------------
class BaccaratSideView(discord.ui.View):
    def __init__(self, bet: int):
        super().__init__(timeout=180)
        self.bet = bet

    async def _play(self, interaction: discord.Interaction, side: str, side_label: str):
        for child in self.children:
            child.disabled = True
        u = _wallet(interaction.guild.id, interaction.user.id)
        if self.bet > u["money"]:
            await interaction.response.edit_message(content="残高が足りなくなっています。", view=self)
            return
        u["money"] -= self.bet
        player, banker = deal_baccarat()
        winner = baccarat_winner(player, banker)
        pay = baccarat_payout(self.bet, side, winner)
        u["money"] += pay
        users.save()
        winner_label = {"player": "プレイヤー", "banker": "バンカー", "tie": "タイ"}[winner]
        embed = discord.Embed(title="🃏 バカラ", color=discord.Color.green() if pay > self.bet else discord.Color.greyple())
        embed.add_field(name=f"プレイヤー（{_hand_value(player)}）", value=" ".join(_card_text(c) for c in player), inline=False)
        embed.add_field(name=f"バンカー（{_hand_value(banker)}）", value=" ".join(_card_text(c) for c in banker), inline=False)
        if pay > self.bet:
            result = f"🎉 **{winner_label}** の勝ち！ あなたは {side_label} に賭けて **{fmt(pay)}** 獲得（+{fmt(pay - self.bet)}）"
        elif pay == self.bet and pay > 0:
            result = f"**{winner_label}** で引き分け。掛け金 **{fmt(pay)}** が返金されました"
        else:
            result = f"**{winner_label}** の勝ち。あなたは {side_label} に賭けて **{fmt(self.bet)}** を失いました"
        embed.add_field(name="結果", value=result, inline=False)
        embed.add_field(name="残高", value=fmt(u["money"]), inline=False)
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="プレイヤー（×2.0）", style=discord.ButtonStyle.primary)
    async def btn_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._play(interaction, "player", "プレイヤー")

    @discord.ui.button(label="バンカー（×1.95）", style=discord.ButtonStyle.danger)
    async def btn_banker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._play(interaction, "banker", "バンカー")

    @discord.ui.button(label="タイ（×8）", style=discord.ButtonStyle.success)
    async def btn_tie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._play(interaction, "tie", "タイ")


# ---------------- ハイアンドロー ----------------
class HighLowView(discord.ui.View):
    def __init__(self, bet: int):
        super().__init__(timeout=180)
        self.bet = bet
        deck = _new_shoe()
        self.current = deck.pop()
        self.next = deck.pop()

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🔼 ハイアンドロー", color=discord.Color.blurple())
        embed.description = f"現在のカード: **{_card_text(self.current)}**\n次のカードはこれより高い？低い？（勝てば×1.9、同数は返金）"
        embed.add_field(name="掛け金", value=fmt(self.bet), inline=False)
        return embed

    async def _guess(self, interaction: discord.Interaction, high: bool):
        for child in self.children:
            child.disabled = True
        cur = self.current[0]
        nxt = self.next[0]
        u = _wallet(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(title="🔼 ハイアンドロー")
        embed.description = f"{_card_text(self.current)} → {_card_text(self.next)}"
        if nxt == cur:
            u["money"] += self.bet
            embed.color = discord.Color.greyple()
            embed.add_field(name="結果", value=f"同数で引き分け。掛け金 **{fmt(self.bet)}** が返金されました", inline=False)
        elif (nxt > cur) == high:
            pay = hl_payout(self.bet)
            u["money"] += pay
            embed.color = discord.Color.green()
            embed.add_field(name="結果", value=f"🎉 当たり！ **{fmt(pay)}** 獲得（+{fmt(pay - self.bet)}）", inline=False)
        else:
            embed.color = discord.Color.red()
            embed.add_field(name="結果", value=f"ハズレ… **{fmt(self.bet)}** を失いました", inline=False)
        users.save()
        embed.add_field(name="残高", value=fmt(u["money"]), inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬆️ ハイ（高い）", style=discord.ButtonStyle.primary)
    async def btn_high(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._guess(interaction, True)

    @discord.ui.button(label="⬇️ ロー（低い）", style=discord.ButtonStyle.primary)
    async def btn_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._guess(interaction, False)


# ---------------- マインズ ----------------
class MinesView(discord.ui.View):
    def __init__(self, bet: int, mines: int):
        super().__init__(timeout=600)
        self.bet = bet
        self.mines = mines
        self.mine_set = set(random.sample(range(MINES_TILES), mines))
        self.revealed = set()
        self.finished = False
        self.tile_buttons = []
        for idx in range(MINES_TILES):
            b = discord.ui.Button(label="❔", style=discord.ButtonStyle.secondary, row=idx // 5)
            b.callback = self._make_tile_cb(idx)
            self.tile_buttons.append(b)
            self.add_item(b)
        self.cash_btn = discord.ui.Button(label="💰 キャッシュアウト（返金）", style=discord.ButtonStyle.success, row=4)
        self.cash_btn.callback = self._cashout
        self.add_item(self.cash_btn)

    def _cashout_amount(self) -> int:
        return int(self.bet * mines_multiplier(MINES_TILES, self.mines, len(self.revealed)))

    def build_embed(self, end_text: str = None) -> discord.Embed:
        embed = discord.Embed(title="💣 マインズ", color=discord.Color.orange())
        mult = mines_multiplier(MINES_TILES, self.mines, len(self.revealed))
        embed.description = (
            f"地雷 {self.mines} 個 / 全 {MINES_TILES} マス。マスを開けるたび倍率アップ、地雷で全没収。\n"
            f"開けたマス: {len(self.revealed)} / 現在の倍率: ×{mult:.2f} / キャッシュアウト額: **{fmt(self._cashout_amount())}**"
        )
        embed.add_field(name="掛け金", value=fmt(self.bet), inline=False)
        if end_text:
            embed.add_field(name="結果", value=end_text, inline=False)
        return embed

    def _reveal_all(self):
        for idx, b in enumerate(self.tile_buttons):
            b.disabled = True
            if idx in self.mine_set:
                b.label = "💣"
                b.style = discord.ButtonStyle.danger
            elif idx in self.revealed:
                b.label = "💎"
            else:
                b.label = "・"
        self.cash_btn.disabled = True

    def _make_tile_cb(self, idx: int):
        async def _cb(interaction: discord.Interaction):
            if self.finished:
                await interaction.response.defer()
                return
            if idx in self.mine_set:
                self.finished = True
                self._reveal_all()
                u = _wallet(interaction.guild.id, interaction.user.id)
                embed = self.build_embed(f"💥 地雷を踏みました… **{fmt(self.bet)}** 没収。残高: {fmt(u['money'])}")
                embed.color = discord.Color.red()
                await interaction.response.edit_message(embed=embed, view=self)
                return
            self.revealed.add(idx)
            b = self.tile_buttons[idx]
            b.label = "💎"
            b.style = discord.ButtonStyle.primary
            b.disabled = True
            amount = self._cashout_amount()
            self.cash_btn.label = f"💰 キャッシュアウト {fmt(amount)}"
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return _cb

    async def _cashout(self, interaction: discord.Interaction):
        if self.finished:
            await interaction.response.defer()
            return
        self.finished = True
        amount = self._cashout_amount()
        u = _wallet(interaction.guild.id, interaction.user.id)
        u["money"] += amount
        users.save()
        self._reveal_all()
        profit = amount - self.bet
        if profit > 0:
            text = f"🎉 **{fmt(amount)}** をキャッシュアウト（+{fmt(profit)}）！ 残高: {fmt(u['money'])}"
        else:
            text = f"掛け金 **{fmt(amount)}** をそのまま回収しました。残高: {fmt(u['money'])}"
        embed = self.build_embed(text)
        embed.color = discord.Color.green()
        await interaction.response.edit_message(embed=embed, view=self)


# ---------------- カジノパネル ----------------
class CasinoPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 ログインボーナス $5,000", style=discord.ButtonStyle.success, custom_id="casino_bonus", row=0)
    async def btn_bonus(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        u = _wallet(interaction.guild.id, interaction.user.id)
        if u["login_bonus_date"] == _today():
            await interaction.response.send_message("今日のログインボーナスはもう受け取り済みだよ。明日（日本時間0時〜）また押してね。", ephemeral=True)
            return
        u["login_bonus_date"] = _today()
        u["money"] += LOGIN_BONUS
        users.save()
        await interaction.response.send_message(f"💰 ログインボーナス **{fmt(LOGIN_BONUS)}** を受け取りました！ 残高: {fmt(u['money'])}", ephemeral=True)

    @discord.ui.button(label="👛 残高", style=discord.ButtonStyle.secondary, custom_id="casino_balance", row=0)
    async def btn_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        u = _wallet(interaction.guild.id, interaction.user.id)
        bonus = "受け取り済み" if u["login_bonus_date"] == _today() else "まだ受け取れます"
        await interaction.response.send_message(f"👛 {interaction.user.display_name} の残高は **{fmt(u['money'])}** です。\n今日のログインボーナス: {bonus}", ephemeral=True)

    @discord.ui.button(label="🏆 ランキング", style=discord.ButtonStyle.secondary, custom_id="casino_rank", row=0)
    async def btn_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        rows = []
        for uid, rec in users.guild_users(interaction.guild.id).items():
            rows.append((int(uid), rec.get("money", 0)))
        rows.sort(key=lambda x: x[1], reverse=True)
        lines = ["**🏆 ポイント（$）ランキング**"]
        if not rows:
            lines.append("まだデータがありません。")
        for i, (uid, money) in enumerate(rows[:10], 1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"ユーザー {uid}"
            lines.append(f"{i}. {name} … **{fmt(money)}**")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @discord.ui.button(label="🎰 スロット", style=discord.ButtonStyle.primary, custom_id="casino_slot", row=1)
    async def btn_slot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_modal(BetModal("slot"))

    @discord.ui.button(label="🃏 バカラ", style=discord.ButtonStyle.primary, custom_id="casino_baccarat", row=1)
    async def btn_baccarat(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_modal(BetModal("baccarat"))

    @discord.ui.button(label="🔼 ハイアンドロー", style=discord.ButtonStyle.primary, custom_id="casino_highlow", row=2)
    async def btn_highlow(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_modal(BetModal("highlow"))

    @discord.ui.button(label="💣 マインズ", style=discord.ButtonStyle.primary, custom_id="casino_mines", row=2)
    async def btn_mines(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _guard(interaction):
            return
        await interaction.response.send_modal(MinesBetModal())


@bot.tree.command(name="setup_casino", description="このチャンネルにカジノパネルを設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_casino(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎰 カジノ",
        description=(
            "ボタンから遊べます。通貨は **$**、掛け金は押した後の入力式です。\n"
            "💰 ログインボーナスは1日1回 **$5,000**。まずはこれを受け取ってから遊んでね。\n"
            "🎰 スロット / 🃏 バカラ / 🔼 ハイアンドロー / 💣 マインズ"
        ),
        color=discord.Color.gold(),
    )
    await interaction.channel.send(embed=embed, view=CasinoPanelView())
    await interaction.response.send_message("✅ カジノパネルを設置しました。", ephemeral=True)


# ---------------- オーナー専用: お金の増減 ----------------
def _owner_only(interaction) -> bool:
    return interaction.guild is not None and interaction.user.id == interaction.guild.owner_id


@bot.tree.command(name="money_add", description="お金を増やす（サーバーオーナー専用）")
@app_commands.describe(user="対象のユーザー", amount="増やす額（$）")
async def cmd_money_add(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not _owner_only(interaction):
        await interaction.response.send_message("このコマンドはサーバーオーナー専用です。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("額は1以上で指定してね。", ephemeral=True)
        return
    u = _wallet(interaction.guild.id, user.id)
    u["money"] += amount
    users.save()
    await interaction.response.send_message(f"💰 {user.mention} に **{fmt(amount)}** を追加しました（残高: {fmt(u['money'])}）。", ephemeral=True)


@bot.tree.command(name="money_remove", description="お金を減らす（サーバーオーナー専用）")
@app_commands.describe(user="対象のユーザー", amount="減らす額（$）")
async def cmd_money_remove(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not _owner_only(interaction):
        await interaction.response.send_message("このコマンドはサーバーオーナー専用です。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("額は1以上で指定してね。", ephemeral=True)
        return
    u = _wallet(interaction.guild.id, user.id)
    u["money"] = max(0, u["money"] - amount)
    users.save()
    await interaction.response.send_message(f"💸 {user.mention} から **{fmt(amount)}** を減らしました（残高: {fmt(u['money'])}）。", ephemeral=True)
