# -*- coding: utf-8 -*-
"""
sub/casino.py — カジノ（サブBOT専用）【メニュー式パネル版】

仕様（2026-11-10 刷新）:
- パネルはボタンではなく「セレクトメニュー」で操作する。
  - 機能メニュー: ログインボーナス / 所持金確認 / ルール説明 / 全体ランキング
  - ゲームメニュー: GAMES レジストリに登録されたゲームだけが並ぶ。
  - 倍率設定メニュー: ゲームごと・当たり方ごとに配当倍率を細かく変更する。
    選べるのはサーバーオーナーと管理者だけ（他は選んでも弾かれる）。
- 旧ゲーム（スロット / バカラ / ハイアンドロー / マインズ）は全廃止。
  現在 GAMES に登録されているのは①系（ルーレット / サイコロ / スロット /
  コイントス / 数字当て）。各ゲームは選択後に「🎮 ゲームを始める（実コイン）」
  と「🖋 練習モード（コインの増減は一切なし）」の2ボタンから始まる。
- パネルの設置場所は cfg["panels"]["casino"] に保存し、BOT起動時に
  最新のメニュー内容で自動編集する。そのため、新しいゲーム（メニュー項目でも
  ボタンでも）を追加して再デプロイすると、設置済みパネルにも自動で反映される。
  （/setup_casino の再実行は不要）
- 通貨は $ 。所持金は users.json に保存（money）。コイン経済とは別。
- お金の増減はサーバーオーナー専用コマンド /money_add /money_remove のみ。
"""

import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from sub.core import bot, store, is_home, requires
from sub.userdata import users

JST = timezone(timedelta(hours=9))
LOGIN_BONUS = 5000


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


# ---------------- ゲームレジストリ ----------------
# ゲームを追加するときは、ここに register_game(...) を書く（または他モジュールから呼ぶ）。
# start には async def start(interaction) を渡す。登録したゲームは次回起動時に
# 設置済みパネルのゲームメニューへ自動で追加される。
GAMES = []


def register_game(game_id: str, label: str, start, emoji: str = "🎮", description: str = "", rules: str = ""):
    GAMES.append(
        {
            "id": game_id,
            "label": label,
            "emoji": emoji,
            "description": description,
            "rules": rules,
            "start": start,
        }
    )


def _find_game(game_id: str):
    for g in GAMES:
        if g["id"] == game_id:
            return g
    return None

# ---------------- 倍率設定（オーナー・管理者専用） ----------------
# ゲームごと・当たり方ごとに配当倍率を細かく設定できる。
# 設定はサーバーごとに cfg["casino_payouts"] = {game_id: {case_key: 倍率}} へ保存され、
# 未設定の項目は PAYOUT_DEFAULTS の値が使われる。
PAYOUT_DEFAULTS = {
    "roulette": {"red": 2.0, "black": 2.0, "even": 2.0, "odd": 2.0, "green": 36.0},
    "dice": {"small": 2.0, "big": 2.0, "pair": 6.0},
    "slot": {"cherry": 4.0, "lemon": 6.0, "bell": 10.0, "star": 15.0, "gem": 25.0, "seven": 50.0, "pair": 1.2},
    "coin": {"win": 1.95},
    "number": {"win": 9.0},
}
PAYOUT_LABELS = {
    "roulette": {"red": "🔴 赤", "black": "⚫ 黒", "even": "偶数", "odd": "奇数", "green": "🟢 緑（0）"},
    "dice": {"small": "🎲 小（2〜6）", "big": "🎲 大（8〜12）", "pair": "🎲 ゾロ目"},
    "slot": {"cherry": "🍒 3つ揃い", "lemon": "🍋 3つ揃い", "bell": "🔔 3つ揃い", "star": "⭐ 3つ揃い", "gem": "💎 3つ揃い", "seven": "7️⃣ 3つ揃い", "pair": "ペア（2つ一致）"},
    "coin": {"win": "的中"},
    "number": {"win": "的中"},
}
SLOT_SYMBOL_KEYS = {"🍒": "cherry", "🍋": "lemon", "🔔": "bell", "⭐": "star", "💎": "gem", "7️⃣": "seven"}


def _fmt_mult(v) -> str:
    return f"×{float(v):g}"


def _payout_table(guild_id, game_id: str) -> dict:
    """そのサーバーの配当テーブル（デフォルト＋保存済みの上書き）"""
    table = dict(PAYOUT_DEFAULTS.get(game_id, {}))
    if guild_id is None:
        return table
    cfg = store.cfg(guild_id)
    saved = cfg.get("casino_payouts", {}).get(game_id, {})
    for k, v in saved.items():
        if k in table:
            try:
                table[k] = float(v)
            except Exception:
                pass
    return table


def _set_payout(guild_id: int, game_id: str, case_key: str, value: float):
    cfg = store.cfg(guild_id)
    all_payouts = cfg.setdefault("casino_payouts", {})
    all_payouts.setdefault(game_id, {})[case_key] = float(value)
    store.save_config()


def _payout_summary(guild_id: int, game_id: str) -> str:
    """現在の配当を1行で表示する（例: 🔴 赤 ×2 ／ ⚫ 黒 ×2 ／ …）"""
    table = _payout_table(guild_id, game_id)
    labels = PAYOUT_LABELS.get(game_id, {})
    return " ／ ".join(f"{labels.get(k, k)} {_fmt_mult(v)}" for k, v in table.items())


def _can_change_payout(interaction) -> bool:
    """倍率変更できるのはサーバーオーナーと管理者だけ（許可ユーザーの抜け道なし）"""
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


# ---------------- 機能メニューの中身 ----------------
async def _feat_bonus(interaction: discord.Interaction):
    u = _wallet(interaction.guild.id, interaction.user.id)
    if u["login_bonus_date"] == _today():
        await interaction.response.send_message(
            "今日のログインボーナスはもう受け取り済みだよ。明日（日本時間0時〜）また選んでね。",
            ephemeral=True,
        )
        return
    u["login_bonus_date"] = _today()
    u["money"] += LOGIN_BONUS
    users.save()
    await interaction.response.send_message(
        f"💰 ログインボーナス **{fmt(LOGIN_BONUS)}** を受け取りました！ 残高: {fmt(u['money'])}",
        ephemeral=True,
    )


async def _feat_balance(interaction: discord.Interaction):
    u = _wallet(interaction.guild.id, interaction.user.id)
    bonus = "受け取り済み" if u["login_bonus_date"] == _today() else "まだ受け取れます"
    await interaction.response.send_message(
        f"👛 {interaction.user.display_name} の所持金は **{fmt(u['money'])}** です。\n今日のログインボーナス: {bonus}",
        ephemeral=True,
    )


def _rules_text(guild_id: int = None) -> str:
    lines = [
        f"・通貨は **$**（所持金）。サーバーごとに別々に管理されます",
        f"・💰 ログインボーナスは1日1回 **{fmt(LOGIN_BONUS)}**（日本時間 0:00 リセット）。機能メニューから受け取ってね",
        "・遊び方は、パネルのメニューから項目を選ぶだけ",
        "・お金の追加・没収はサーバーオーナーだけができます",
        "・配当倍率はサーバーごとに設定されています（オーナー・管理者が変更可）",
    ]
    if GAMES:
        lines.append("")
        lines.append("**🎮 ゲームのルール**")
        for g in GAMES:
            if g["rules"]:
                line = f"・{g['emoji']} {g['label']}: {g['rules']}"
                if guild_id is not None and g["id"] in PAYOUT_DEFAULTS:
                    line += f"\n　現在の配当: {_payout_summary(guild_id, g['id'])}"
                lines.append(line)
    else:
        lines.append("・ゲームは今後追加予定です。追加されたら、このパネルにも自動で表示されます")
    return "\n".join(lines)


async def _feat_rules(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 カジノのルール", description=_rules_text(interaction.guild.id), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _feat_ranking(interaction: discord.Interaction):
    rows = []
    for uid, rec in users.guild_users(interaction.guild.id).items():
        rows.append((int(uid), rec.get("money", 0)))
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = ["**🏆 所持金ランキング**"]
    if not rows:
        lines.append("まだデータがありません。")
    for i, (uid, money) in enumerate(rows[:10], 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"ユーザー {uid}"
        lines.append(f"{i}. {name} … **{fmt(money)}**")
    for i, (uid, money) in enumerate(rows, 1):
        if uid == interaction.user.id:
            if i > 10:
                lines.append(f"— あなたの順位: {i}位（{fmt(money)}）")
            break
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


_FEATURE_HANDLERS = {
    "bonus": _feat_bonus,
    "balance": _feat_balance,
    "rules": _feat_rules,
    "ranking": _feat_ranking,
}


# ---------------- パネル（セレクトメニュー×2） ----------------
class FeatureSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="ログインボーナス", value="bonus", emoji="💰", description=f"1日1回 {fmt(LOGIN_BONUS)} を受け取る"),
            discord.SelectOption(label="所持金確認", value="balance", emoji="👛", description="自分の残高とボーナス状況を見る"),
            discord.SelectOption(label="ルール説明", value="rules", emoji="📖", description="カジノのルールとゲームの説明"),
            discord.SelectOption(label="全体ランキング", value="ranking", emoji="🏆", description="所持金ランキング（上位10人＋自分の順位）"),
        ]
        super().__init__(custom_id="casino:feature_menu", placeholder="🎰 機能メニューを開く", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        handler = _FEATURE_HANDLERS.get(self.values[0] if self.values else "")
        if handler is not None:
            await handler(interaction)


class GameSelect(discord.ui.Select):
    def __init__(self):
        if GAMES:
            options = [
                discord.SelectOption(
                    label=g["label"],
                    value=g["id"],
                    emoji=g["emoji"] or None,
                    description=(g["description"] or None),
                )
                for g in GAMES
            ]
            super().__init__(custom_id="casino:game_menu", placeholder="🎮 遊ぶゲームを選ぶ", options=options, row=1)
        else:
            options = [discord.SelectOption(label="ゲームは準備中です", value="__none__")]
            super().__init__(
                custom_id="casino:game_menu",
                placeholder="🎮 ゲームメニュー（準備中）",
                options=options,
                row=1,
                disabled=True,
            )

    async def callback(self, interaction: discord.Interaction):
        if not await _guard(interaction):
            return
        game = _find_game(self.values[0] if self.values else "")
        if game is None:
            await interaction.response.send_message("そのゲームはまだ遊べません。", ephemeral=True)
            return
        await game["start"](interaction)


class PayoutSelect(discord.ui.Select):
    """倍率設定メニュー（パネル常駐）。ゲームを選ぶ入口。
    選べるのはサーバーオーナーと管理者だけ（他は弾かれる）。"""

    def __init__(self):
        options = [
            discord.SelectOption(
                label=f"{g['emoji']} {g['label']} の倍率",
                value=g["id"],
                description="このゲームの配当を項目ごとに設定",
            )
            for g in GAMES
            if g["id"] in PAYOUT_DEFAULTS
        ]
        if not options:
            options = [discord.SelectOption(label="設定できるゲームがありません", value="__none__")]
        super().__init__(
            custom_id="casino:payout_menu",
            placeholder="⚙️ 倍率設定（オーナー・管理者専用）",
            options=options,
            row=2,
            disabled=not options or options[0].value == "__none__",
        )

    async def callback(self, interaction: discord.Interaction):
        if not _can_change_payout(interaction):
            await interaction.response.send_message(
                "⚙️ このメニューはサーバーのオーナーと管理者専用だよ。",
                ephemeral=True,
            )
            return
        game = _find_game(self.values[0] if self.values else "")
        if game is None or game["id"] not in PAYOUT_DEFAULTS:
            await interaction.response.send_message("そのゲームは倍率設定できません。", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_payout_admin_embed(interaction.guild.id, game),
            view=PayoutAdminView(interaction.guild.id, game["id"]),
            ephemeral=True,
        )


def _payout_admin_embed(guild_id: int, game: dict) -> discord.Embed:
    table = _payout_table(guild_id, game["id"])
    labels = PAYOUT_LABELS.get(game["id"], {})
    lines = [f"・{labels.get(k, k)}: **{_fmt_mult(v)}**" for k, v in table.items()]
    return discord.Embed(
        title=f"⚙️ {game['emoji']} {game['label']} の倍率設定",
        description="現在の配当\n" + "\n".join(lines) + "\n\n変更したい項目を下のメニューから選んでね。",
        color=discord.Color.orange(),
    )


class PayoutCaseSelect(discord.ui.Select):
    def __init__(self, guild_id: int, game_id: str):
        self.game_id = game_id
        table = _payout_table(guild_id, game_id)
        labels = PAYOUT_LABELS.get(game_id, {})
        options = [
            discord.SelectOption(label=f"{labels.get(k, k)}（現在 {_fmt_mult(v)}）", value=k)
            for k, v in table.items()
        ]
        super().__init__(placeholder="変更する項目を選ぶ", options=options)

    async def callback(self, interaction: discord.Interaction):
        if not _can_change_payout(interaction):
            await interaction.response.send_message("⚙️ この操作はサーバーのオーナーと管理者専用だよ。", ephemeral=True)
            return
        case_key = self.values[0] if self.values else ""
        game = _find_game(self.game_id)
        label = PAYOUT_LABELS.get(self.game_id, {}).get(case_key, case_key)
        current = _payout_table(interaction.guild.id, self.game_id)[case_key]
        embed = discord.Embed(
            title=f"⚙️ {game['emoji']} {game['label']}：{label}",
            description=(
                f"現在の倍率: **{_fmt_mult(current)}**\n"
                "新しい倍率を下のメニューから選ぶか、「✏️ 自由入力」ボタンで好きな値を入力してね。"
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, view=PayoutValueView(self.game_id, case_key), ephemeral=True)


class PayoutAdminView(discord.ui.View):
    def __init__(self, guild_id: int, game_id: str):
        super().__init__(timeout=300)
        self.add_item(PayoutCaseSelect(guild_id, game_id))


PAYOUT_VALUE_CHOICES = [0, 0.5, 0.8, 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 9, 10, 12, 15, 20, 25, 36, 50]


class PayoutValueSelect(discord.ui.Select):
    def __init__(self, game_id: str, case_key: str):
        self.game_id = game_id
        self.case_key = case_key
        options = [discord.SelectOption(label=_fmt_mult(v), value=str(v)) for v in PAYOUT_VALUE_CHOICES]
        super().__init__(placeholder="新しい倍率を選ぶ", options=options)

    async def callback(self, interaction: discord.Interaction):
        if not _can_change_payout(interaction):
            await interaction.response.send_message("⚙️ この操作はサーバーのオーナーと管理者専用だよ。", ephemeral=True)
            return
        await _apply_payout_change(interaction, self.game_id, self.case_key, float(self.values[0]))


class PayoutValueView(discord.ui.View):
    def __init__(self, game_id: str, case_key: str):
        super().__init__(timeout=300)
        self.game_id = game_id
        self.case_key = case_key
        self.add_item(PayoutValueSelect(game_id, case_key))

    @discord.ui.button(label="✏️ 自由入力", style=discord.ButtonStyle.secondary)
    async def btn_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _can_change_payout(interaction):
            await interaction.response.send_message("⚙️ この操作はサーバーのオーナーと管理者専用だよ。", ephemeral=True)
            return
        await interaction.response.send_modal(PayoutCustomModal(self.game_id, self.case_key))


class PayoutCustomModal(discord.ui.Modal, title="倍率を入力"):
    def __init__(self, game_id: str, case_key: str):
        super().__init__()
        self.game_id = game_id
        self.case_key = case_key
        self.value_input = discord.ui.TextInput(label="倍率（0〜1000、小数OK）", placeholder="例: 2.5", max_length=10)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not _can_change_payout(interaction):
            await interaction.response.send_message("⚙️ この操作はサーバーのオーナーと管理者専用だよ。", ephemeral=True)
            return
        try:
            value = float(str(self.value_input.value).strip().replace("×", "").replace("x", ""))
        except Exception:
            await interaction.response.send_message("倍率は数字で入力してね（例: 2.5）。", ephemeral=True)
            return
        if value < 0 or value > 1000:
            await interaction.response.send_message("倍率は0〜1000の範囲で入力してね。", ephemeral=True)
            return
        await _apply_payout_change(interaction, self.game_id, self.case_key, value)


async def _apply_payout_change(interaction: discord.Interaction, game_id: str, case_key: str, value: float):
    _set_payout(interaction.guild.id, game_id, case_key, value)
    game = _find_game(game_id)
    label = PAYOUT_LABELS.get(game_id, {}).get(case_key, case_key)
    await interaction.response.send_message(
        f"✅ {game['emoji']} {game['label']} の「{label}」を **{_fmt_mult(value)}** に変更しました。このあとのゲームから適用されます。",
        embed=_payout_admin_embed(interaction.guild.id, game),
        view=PayoutAdminView(interaction.guild.id, game_id),
        ephemeral=True,
    )


class CasinoPanelView(discord.ui.View):
    """永続ビュー（カスタムID固定）。中身は GAMES の内容から組み立てる。"""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FeatureSelect())
        self.add_item(GameSelect())
        self.add_item(PayoutSelect())


def build_panel_embed(guild_id: int = None) -> discord.Embed:
    embed = discord.Embed(
        title="🎰 カジノ",
        description=(
            "下のメニューから選んで遊べます。通貨は **$** です。\n"
            f"まずは機能メニューから 💰 ログインボーナス（1日1回 **{fmt(LOGIN_BONUS)}**）を受け取ってね。"
        ),
        color=discord.Color.gold(),
    )
    if GAMES:
        game_lines = [f"{g['emoji']} {g['label']}" + (f" — {g['description']}" if g["description"] else "") for g in GAMES]
        embed.add_field(name="🎮 遊べるゲーム", value="\n".join(game_lines), inline=False)
    else:
        embed.add_field(name="🎮 遊べるゲーム", value="準備中です。ゲームが追加されると、ここに自動で表示されます。", inline=False)
    embed.add_field(
        name="⚙️ 倍率設定",
        value="配当倍率はゲームごと・当たり方ごとに設定できます。変更は下の「倍率設定」メニューから（オーナー・管理者専用）。",
        inline=False,
    )
    return embed


# ---------------- 設置済みパネルの自動更新 ----------------
_panels_refreshed = False


@bot.listen("on_ready")
async def _refresh_casino_panels():
    """起動時に、設置済みパネルを最新メニューで編集し直す。
    新しいゲーム等を追加して再デプロイしたとき、既存パネルへ自動反映するための処理。"""
    global _panels_refreshed
    if _panels_refreshed:
        return
    _panels_refreshed = True
    for gid_str in list(store.configs.keys()):
        try:
            cfg = store.cfg(int(gid_str))
            panel = cfg.get("panels", {}).get("casino")
            if not panel:
                continue
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=build_panel_embed(int(gid_str)), view=CasinoPanelView())
        except Exception:
            pass  # パネルが消えている・権限がない等は無視（/setup_casino で再設置できる）


@bot.tree.command(name="setup_casino", description="このチャンネルにカジノパネルを設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_casino(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    # 以前の設置があれば消してから設置し直す（パネルの二重残りを防ぐ）
    old = cfg.get("panels", {}).get("casino")
    if old:
        try:
            old_ch = interaction.guild.get_channel(old["channel_id"])
            if old_ch is not None:
                old_msg = await old_ch.fetch_message(old["message_id"])
                await old_msg.delete()
        except Exception:
            pass
    msg = await interaction.channel.send(embed=build_panel_embed(interaction.guild.id), view=CasinoPanelView())
    cfg.setdefault("panels", {})["casino"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.response.send_message(
        "✅ カジノパネルを設置しました。今後ゲームが追加されたときは、このパネルにも自動で反映されます。",
        ephemeral=True,
    )


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


# ============================================================
# ①系ゲーム（選んで即結果）+ モード選択（本番 / 練習）
# ============================================================
MIN_BET = 10
VIRTUAL_BET = 100  # 練習モードの仮想ベット（実際のコインは動かない）


def _parse_bet(raw: str):
    try:
        return int(str(raw).strip().replace(",", "").replace("$", "").replace("＄", ""))
    except Exception:
        return None


def _apply_result(guild_id: int, user_id: int, bet: int, pay: int, practice: bool):
    """結果を残高へ反映する（練習モードでは一切動かさない）。戻り値は新しい残高（練習時は None）。"""
    if practice:
        return None
    u = _wallet(guild_id, user_id)
    u["money"] += pay - bet
    users.save()
    return u["money"]


def _money_text(bet: int, pay: int, balance, practice: bool) -> str:
    if practice:
        diff = pay - bet
        sign = f"+{fmt(diff)}" if diff > 0 else (f"-{fmt(-diff)}" if diff < 0 else "±$0")
        return f"🖋 練習モード（仮想ベット {fmt(bet)}）: 結果は {sign} 相当\n※ コインの増減は一切ありません"
    if pay > bet:
        return f"🎉 **{fmt(pay)}** 獲得（+{fmt(pay - bet)}）"
    if pay == bet and pay > 0:
        return f"掛け金 **{fmt(pay)}** が戻ってきました"
    if pay > 0:
        return f"**{fmt(pay)}** 戻ってきました（-{fmt(bet - pay)}）"
    return f"**{fmt(bet)}** を失いました"


def _result_embed(title: str, color: discord.Color, description: str, bet: int, pay: int, balance, practice: bool) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name="結果", value=_money_text(bet, pay, balance, practice), inline=False)
    if not practice:
        embed.add_field(name="残高", value=fmt(balance), inline=False)
    return embed


# ---------------- モード選択（全ゲーム共通） ----------------
class ModeSelectView(discord.ui.View):
    """ゲーム選択直後の画面: 🎮 ゲームを始める（実コイン） / 🖋 練習モード（増減なし）"""

    def __init__(self, game_id: str):
        super().__init__(timeout=300)
        self.game_id = game_id

    @discord.ui.button(label="🎮 ゲームを始める", style=discord.ButtonStyle.success)
    async def btn_real(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _begin_game(interaction, self.game_id, practice=False)

    @discord.ui.button(label="🖋 練習モード", style=discord.ButtonStyle.secondary)
    async def btn_practice(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _begin_game(interaction, self.game_id, practice=True)


def _mode_select_embed(game: dict, guild_id: int = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"{game['emoji']} {game['label']}",
        description=(
            f"{game['rules']}\n\n"
            "🎮 **ゲームを始める** … 実際のコインを使って遊びます\n"
            f"🖋 **練習モード** … **コインの増減は一切ありません**（仮想ベット {fmt(VIRTUAL_BET)} で遊べます）"
        ),
        color=discord.Color.blurple(),
    )
    if guild_id is not None and game["id"] in PAYOUT_DEFAULTS:
        embed.add_field(name="現在の配当", value=_payout_summary(guild_id, game["id"]), inline=False)
    return embed


def _make_mode_start(game_id: str):
    async def _start(interaction: discord.Interaction):
        game = _find_game(game_id)
        await interaction.response.send_message(embed=_mode_select_embed(game, interaction.guild.id), view=ModeSelectView(game_id), ephemeral=True)

    return _start


async def _begin_game(interaction: discord.Interaction, game_id: str, practice: bool):
    if game_id == "slot":
        if practice:
            embed = _slot_embed_for(interaction, VIRTUAL_BET, practice=True)
            await interaction.response.edit_message(embed=embed, view=SlotAgainView(VIRTUAL_BET, practice=True))
        else:
            await interaction.response.send_modal(GameBetModal("slot"))
    elif game_id in ("roulette", "dice", "coin"):
        if practice:
            view = ChoiceView(game_id, VIRTUAL_BET, practice=True, guild_id=interaction.guild.id)
            await interaction.response.edit_message(embed=view.intro_embed(), view=view)
        else:
            await interaction.response.send_modal(GameBetModal(game_id))
    elif game_id == "number":
        await interaction.response.send_modal(NumberModal(practice))


# ---------------- 掛け金モーダル（本番用） ----------------
class GameBetModal(discord.ui.Modal, title="掛け金を入力"):
    bet = discord.ui.TextInput(label="掛け金（$）", placeholder="例: 1000", max_length=10)

    def __init__(self, game_id: str):
        super().__init__()
        self.game_id = game_id

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
        if self.game_id == "slot":
            embed = _slot_embed_for(interaction, amount, practice=False)
            await interaction.response.send_message(embed=embed, view=SlotAgainView(amount, practice=False), ephemeral=True)
        else:
            view = ChoiceView(self.game_id, amount, practice=False, guild_id=interaction.guild.id)
            await interaction.response.send_message(embed=view.intro_embed(), view=view, ephemeral=True)


# ---------------- スロット ----------------
SLOT_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 26, 20, 12, 8, 4]


def slot_spin():
    return [random.choices(SLOT_SYMBOLS, SLOT_WEIGHTS)[0] for _ in range(3)]


def slot_payout(bet: int, reels, table: dict) -> int:
    if reels[0] == reels[1] == reels[2]:
        return int(bet * table[SLOT_SYMBOL_KEYS[reels[0]]])
    if len(set(reels)) == 2:
        return int(bet * table["pair"])
    return 0


def _slot_embed_for(interaction, bet: int, practice: bool) -> discord.Embed:
    """スロットを1回回し、残高へ反映して結果Embedを返す。"""
    reels = slot_spin()
    pay = slot_payout(bet, reels, _payout_table(interaction.guild.id, "slot"))
    balance = _apply_result(interaction.guild.id, interaction.user.id, bet, pay, practice)
    return _result_embed(
        "🎰 スロット",
        discord.Color.gold() if pay > bet else discord.Color.greyple(),
        f"## {' '.join(reels)}",
        bet, pay, balance, practice,
    )


class SlotAgainView(discord.ui.View):
    def __init__(self, bet: int, practice: bool):
        super().__init__(timeout=600)
        self.bet = bet
        self.practice = practice
        if practice:
            self.btn_change.disabled = True
            self.btn_change.label = "🖋 練習モード（掛け金は固定）"

    async def _spin_and_show(self, interaction: discord.Interaction):
        embed = _slot_embed_for(interaction, self.bet, self.practice)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🔁 もう一度回す（同じ掛け金）", style=discord.ButtonStyle.primary)
    async def btn_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.practice:
            u = _wallet(interaction.guild.id, interaction.user.id)
            if self.bet > u["money"]:
                await interaction.response.send_message(f"残高が足りません（残高: {fmt(u['money'])}）。", ephemeral=True)
                return
        await self._spin_and_show(interaction)

    @discord.ui.button(label="✏️ 掛け金を変える", style=discord.ButtonStyle.secondary)
    async def btn_change(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GameBetModal("slot"))


# ---------------- ルーレット ----------------
ROULETTE_RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_spin() -> int:
    return random.randint(0, 36)


def roulette_color(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in ROULETTE_RED else "black"


def roulette_multiplier(choice: str, n: int, table: dict) -> float:
    color = roulette_color(n)
    if choice == "green":
        return table["green"] if n == 0 else 0.0
    if choice in ("red", "black"):
        return table[choice] if color == choice else 0.0
    if choice == "even":
        return table["even"] if (n != 0 and n % 2 == 0) else 0.0
    if choice == "odd":
        return table["odd"] if (n % 2 == 1) else 0.0
    return 0.0


# ---------------- サイコロ ----------------
DICE_FACES = "⚀⚁⚂⚃⚄⚅"


def dice_roll():
    return random.randint(1, 6), random.randint(1, 6)


def dice_multiplier(choice: str, total: int, is_pair: bool, table: dict) -> float:
    if choice == "pair":
        return table["pair"] if is_pair else 0.0
    if choice == "small":
        return table["small"] if 2 <= total <= 6 else 0.0
    if choice == "big":
        return table["big"] if 8 <= total <= 12 else 0.0
    return 0.0


# ---------------- コイントス ----------------
def coin_flip() -> str:
    return random.choice(["heads", "tails"])


# ---------------- 選択式ゲーム共通ビュー（ルーレット/サイコロ/コイントス） ----------------
CHOICE_DEFS = {
    "roulette": {
        "title": "🎡 ルーレット",
        "choices": [
            ("red", "red", "🔴 赤", discord.ButtonStyle.danger),
            ("black", "black", "⚫ 黒", discord.ButtonStyle.secondary),
            ("even", "even", "偶数", discord.ButtonStyle.primary),
            ("odd", "odd", "奇数", discord.ButtonStyle.primary),
            ("green", "green", "🟢 緑(0)", discord.ButtonStyle.success),
        ],
    },
    "dice": {
        "title": "🎲 サイコロ",
        "choices": [
            ("small", "small", "🎲 小（2〜6）", discord.ButtonStyle.primary),
            ("big", "big", "🎲 大（8〜12）", discord.ButtonStyle.primary),
            ("pair", "pair", "🎲 ゾロ目", discord.ButtonStyle.success),
        ],
    },
    "coin": {
        "title": "🪙 コイントス",
        "choices": [
            ("heads", "win", "🪙 表", discord.ButtonStyle.primary),
            ("tails", "win", "🪙 裏", discord.ButtonStyle.primary),
        ],
    },
}


def _resolve_choice(guild_id, game_id: str, choice: str, bet: int):
    """(結果の説明文, 払戻額) を返す。配当はそのサーバーの設定テーブルを使う。"""
    table = _payout_table(guild_id, game_id)
    if game_id == "roulette":
        n = roulette_spin()
        color = roulette_color(n)
        emoji = {"red": "🔴", "black": "⚫", "green": "🟢"}[color]
        mult = roulette_multiplier(choice, n, table)
        return f"ボールは {emoji} **{n}** に止まりました", int(bet * mult) if mult else 0
    if game_id == "dice":
        d1, d2 = dice_roll()
        total = d1 + d2
        mult = dice_multiplier(choice, total, d1 == d2, table)
        pair_text = "（ゾロ目！）" if d1 == d2 else ""
        return f"{DICE_FACES[d1 - 1]} {DICE_FACES[d2 - 1]} 合計 **{total}**{pair_text}", int(bet * mult) if mult else 0
    if game_id == "coin":
        result = coin_flip()
        win = result == choice
        label = "表" if result == "heads" else "裏"
        pay = int(bet * table["win"]) if win else 0
        return f"コインは **{label}** でした", pay
    return "", 0


class ChoiceView(discord.ui.View):
    def __init__(self, game_id: str, bet: int, practice: bool, guild_id: int = None):
        super().__init__(timeout=600)
        self.game_id = game_id
        self.bet = bet
        self.practice = practice
        self.finished = False
        self.choice_buttons = []
        table = _payout_table(guild_id, game_id)
        for value, mult_key, label_base, style in CHOICE_DEFS[game_id]["choices"]:
            label = f"{label_base} {_fmt_mult(table[mult_key])}"
            b = discord.ui.Button(label=label, style=style, row=0 if len(self.choice_buttons) < 5 else 1)
            b.callback = self._make_choice_cb(value)
            self.choice_buttons.append(b)
            self.add_item(b)
        self.again_btn = discord.ui.Button(label="🔁 もう一度（同じ掛け金）", style=discord.ButtonStyle.success, row=2, disabled=True)
        self.again_btn.callback = self._again
        self.add_item(self.again_btn)

    def intro_embed(self) -> discord.Embed:
        mode = "🖋 練習モード（コインの増減は一切ありません）" if self.practice else "🎮 本番"
        embed = discord.Embed(
            title=CHOICE_DEFS[self.game_id]["title"],
            description=f"掛け金: **{fmt(self.bet)}**（{mode}）\nどれに賭ける？",
            color=discord.Color.blurple(),
        )
        return embed

    def _make_choice_cb(self, value: str):
        async def _cb(interaction: discord.Interaction):
            if self.finished:
                await interaction.response.defer()
                return
            self.finished = True
            desc, pay = _resolve_choice(interaction.guild.id, self.game_id, value, self.bet)
            balance = _apply_result(interaction.guild.id, interaction.user.id, self.bet, pay, self.practice)
            for b in self.choice_buttons:
                b.disabled = True
            self.again_btn.disabled = False
            embed = _result_embed(
                CHOICE_DEFS[self.game_id]["title"],
                discord.Color.green() if pay > self.bet else discord.Color.greyple(),
                desc,
                self.bet, pay, balance, self.practice,
            )
            await interaction.response.edit_message(embed=embed, view=self)

        return _cb

    async def _again(self, interaction: discord.Interaction):
        if not self.practice:
            u = _wallet(interaction.guild.id, interaction.user.id)
            if self.bet > u["money"]:
                await interaction.response.send_message(f"残高が足りません（残高: {fmt(u['money'])}）。", ephemeral=True)
                return
        self.finished = False
        for b in self.choice_buttons:
            b.disabled = False
        self.again_btn.disabled = True
        await interaction.response.edit_message(embed=self.intro_embed(), view=self)


# ---------------- 数字当て ----------------
def _draw_number() -> int:
    return random.randint(1, 10)


class NumberModal(discord.ui.Modal, title="数字当て（1〜10）"):
    def __init__(self, practice: bool):
        super().__init__()
        self.practice = practice
        self.bet_input = None
        if not practice:
            self.bet_input = discord.ui.TextInput(label="掛け金（$）", placeholder="例: 1000", max_length=10)
            self.add_item(self.bet_input)
        self.guess_input = discord.ui.TextInput(label="予想する数字（1〜10）", placeholder="例: 7", max_length=2)
        self.add_item(self.guess_input)

    async def on_submit(self, interaction: discord.Interaction):
        guess = _parse_bet(self.guess_input.value)
        if guess is None or not (1 <= guess <= 10):
            await interaction.response.send_message("数字は1〜10で入力してね。", ephemeral=True)
            return
        if self.practice:
            bet = VIRTUAL_BET
        else:
            bet = _parse_bet(self.bet_input.value)
            if bet is None:
                await interaction.response.send_message("掛け金は数字で入力してね。", ephemeral=True)
                return
            u = _wallet(interaction.guild.id, interaction.user.id)
            if bet < MIN_BET:
                await interaction.response.send_message(f"最小掛け金は {fmt(MIN_BET)} だよ。", ephemeral=True)
                return
            if bet > u["money"]:
                await interaction.response.send_message(f"残高が足りません（残高: {fmt(u['money'])}）。", ephemeral=True)
                return
        drawn = _draw_number()
        pay = int(bet * _payout_table(interaction.guild.id, "number")["win"]) if guess == drawn else 0
        balance = _apply_result(interaction.guild.id, interaction.user.id, bet, pay, self.practice)
        embed = _result_embed(
            "🔢 数字当て",
            discord.Color.green() if pay > 0 else discord.Color.greyple(),
            f"あなたの予想: **{guess}** ／ 出た数字: **{drawn}**",
            bet, pay, balance, self.practice,
        )
        await interaction.response.send_message(embed=embed, view=NumberAgainView(self.practice), ephemeral=True)


class NumberAgainView(discord.ui.View):
    def __init__(self, practice: bool):
        super().__init__(timeout=600)
        self.practice = practice

    @discord.ui.button(label="🔁 もう一度", style=discord.ButtonStyle.primary)
    async def btn_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NumberModal(self.practice))


# ---------------- ゲーム登録（ゲームメニューの並び順） ----------------
register_game(
    "roulette", "ルーレット", _make_mode_start("roulette"),
    emoji="🎡", description="赤・黒・偶数・奇数・緑に賭ける",
    rules="0〜36のどこにボールが止まるかを当てます。赤・黒・偶数・奇数・緑（0）から賭け先を選びます。",
)
register_game(
    "dice", "サイコロ", _make_mode_start("dice"),
    emoji="🎲", description="2個の合計を予想する",
    rules="サイコロ2個の合計を予想します。小（2〜6）/大（8〜12）/ゾロ目から賭け先を選びます。合計7はハズレです。",
)
register_game(
    "slot", "スロット", _make_mode_start("slot"),
    emoji="🎰", description="リール3つを回す",
    rules="リール3つを回します。3つ揃いと、どれか2つ一致（ペア）で配当があります。",
)
register_game(
    "coin", "コイントス", _make_mode_start("coin"),
    emoji="🪙", description="表か裏を当てる",
    rules="コインの表か裏を当てます。",
)
register_game(
    "number", "数字当て", _make_mode_start("number"),
    emoji="🔢", description="1〜10の数字を当てる",
    rules="1〜10の数字を1つ予想します。",
)
