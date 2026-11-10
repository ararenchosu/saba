# -*- coding: utf-8 -*-
"""
sub/casino.py — カジノ（サブBOT専用）【メニュー式パネル版】

仕様（2026-11-10 刷新）:
- パネルはボタンではなく「セレクトメニュー×2」で操作する。
  - 機能メニュー: ログインボーナス / 所持金確認 / ルール説明 / 全体ランキング
  - ゲームメニュー: GAMES レジストリに登録されたゲームだけが並ぶ。
- 旧ゲーム（スロット / バカラ / ハイアンドロー / マインズ）は全廃止。
  ゲームは今後 GAMES へ追加していく。
- パネルの設置場所は cfg["panels"]["casino"] に保存し、BOT起動時に
  最新のメニュー内容で自動編集する。そのため、新しいゲーム（メニュー項目でも
  ボタンでも）を追加して再デプロイすると、設置済みパネルにも自動で反映される。
  （/setup_casino の再実行は不要）
- 通貨は $ 。所持金は users.json に保存（money）。コイン経済とは別。
- お金の増減はサーバーオーナー専用コマンド /money_add /money_remove のみ。
"""

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


def _rules_text() -> str:
    lines = [
        f"・通貨は **$**（所持金）。サーバーごとに別々に管理されます",
        f"・💰 ログインボーナスは1日1回 **{fmt(LOGIN_BONUS)}**（日本時間 0:00 リセット）。機能メニューから受け取ってね",
        "・遊び方は、パネルのメニューから項目を選ぶだけ",
        "・お金の追加・没収はサーバーオーナーだけができます",
    ]
    if GAMES:
        lines.append("")
        lines.append("**🎮 ゲームのルール**")
        for g in GAMES:
            if g["rules"]:
                lines.append(f"・{g['emoji']} {g['label']}: {g['rules']}")
    else:
        lines.append("・ゲームは今後追加予定です。追加されたら、このパネルにも自動で表示されます")
    return "\n".join(lines)


async def _feat_rules(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 カジノのルール", description=_rules_text(), color=discord.Color.gold())
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


class CasinoPanelView(discord.ui.View):
    """永続ビュー（カスタムID固定）。中身は GAMES の内容から組み立てる。"""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FeatureSelect())
        self.add_item(GameSelect())


def build_panel_embed() -> discord.Embed:
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
            await message.edit(embed=build_panel_embed(), view=CasinoPanelView())
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
    msg = await interaction.channel.send(embed=build_panel_embed(), view=CasinoPanelView())
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
