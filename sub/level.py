# -*- coding: utf-8 -*-
"""
sub/level.py — レベル / XP システム（サブBOT高機能）

- 発言でXP（60秒クールダウン）。レベル = 累計XPから算出（レベルn到達に 100*n^2 XP）
- レベルアップ時に通知＆設定された報酬ロールを付与
- /rank … 自分 or 指定ユーザーのランク表示
- /leaderboard … サーバーのXPランキング
- ON/OFF は /settings → 高度な設定 の「レベル/XP」トグル、または /leveltoggle コマンド（xp_enabled）。
  オフの間は XP加算・レベルアップ通知・報酬ロールが止まり、/rank・/leaderboard もオフ案内になる（データは消えない）。
"""

import time

import discord
from discord import app_commands

from sub.core import bot, store, get_or_create_role, is_home, requires
from sub.userdata import users

XP_COOLDOWN = 60


def _enabled(interaction) -> bool:
    """レベル/XP機能がオンか（/settings → 高度な設定 の「レベル/XP」トグル）"""
    return store.cfg(interaction.guild.id).get("xp_enabled", True)


def xp_for_level(level: int) -> int:
    """そのレベルに到達するのに必要な累計XP"""
    return 100 * level * level


def level_from_xp(xp: int) -> int:
    lvl = 0
    while xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return lvl


def progress(xp: int):
    """(現在レベル, 現レベル内XP, 次レベルまでの必要XP)"""
    lvl = level_from_xp(xp)
    cur = xp - xp_for_level(lvl)
    need = xp_for_level(lvl + 1) - xp_for_level(lvl)
    return lvl, cur, need


def bar(cur: int, need: int, width: int = 12) -> str:
    filled = int(width * cur / need) if need else width
    return "█" * filled + "░" * (width - filled)


@bot.listen("on_message")
async def xp_on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if not is_home(message.guild.id):
        return
    cfg = store.cfg(message.guild.id)
    if not cfg.get("xp_enabled", True):
        return
    u = users.get(message.guild.id, message.author.id)
    now = time.time()
    if now - u.get("last_xp_at", 0) < XP_COOLDOWN:
        return
    old_level = level_from_xp(u["xp"])
    u["xp"] += int(cfg.get("xp_per_message", 15))
    u["last_xp_at"] = now
    users.save()
    new_level = level_from_xp(u["xp"])
    if new_level > old_level:
        # 報酬ロール
        rewards = cfg.get("level_rewards", {})
        role_name = rewards.get(str(new_level))
        reward_text = ""
        if role_name:
            role = await get_or_create_role(message.guild, role_name)
            if role is not None:
                try:
                    await message.author.add_roles(role)
                    reward_text = f" 報酬ロール「{role_name}」をゲット！"
                except discord.Forbidden:
                    pass
        if cfg.get("levelup_announce", True):
            try:
                await message.channel.send(f"🎉 {message.author.mention} が **レベル {new_level}** にアップ！{reward_text}")
            except discord.Forbidden:
                pass


@bot.tree.command(name="rank", description="レベルとXPを表示する")
@app_commands.describe(user="見たい人（省略で自分）")
async def cmd_rank(interaction: discord.Interaction, user: discord.Member = None):
    if not _enabled(interaction):
        await interaction.response.send_message("レベル/XP機能は今オフだよ。（オンにするには /settings → 高度な設定 →「レベル/XP」）", ephemeral=True)
        return
    target = user or interaction.user
    u = users.get(interaction.guild.id, target.id)
    lvl, cur, need = progress(u["xp"])
    # 順位
    all_users = users.guild_users(interaction.guild.id)
    ranking = sorted(all_users.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)
    rank_pos = next((i + 1 for i, (uid, _) in enumerate(ranking) if uid == str(target.id)), None)
    embed = discord.Embed(title=f"📊 {target.display_name} のランク", color=discord.Color.gold())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="レベル", value=f"**{lvl}**", inline=True)
    embed.add_field(name="サーバー順位", value=f"**{rank_pos}位** / {len(ranking)}人" if rank_pos else "-", inline=True)
    embed.add_field(name="XP", value=f"{cur} / {need}\n{bar(cur, need)}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="leaderboard", description="XPランキング（上位10人）を表示する")
async def cmd_leaderboard(interaction: discord.Interaction):
    if not _enabled(interaction):
        await interaction.response.send_message("レベル/XP機能は今オフだよ。（オンにするには /settings → 高度な設定 →「レベル/XP」）", ephemeral=True)
        return
    all_users = users.guild_users(interaction.guild.id)
    ranking = sorted(all_users.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:10]
    if not ranking:
        await interaction.response.send_message("まだXPデータがないよ。", ephemeral=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, data) in enumerate(ranking):
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ユーザー({uid})"
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} **{name}** — Lv.{level_from_xp(data.get('xp', 0))}（{data.get('xp', 0)} XP）")
    embed = discord.Embed(title="🏆 XPランキング", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leveltoggle", description="レベル/XP機能をオン・オフする（管理者用）")
@requires(administrator=True)
@app_commands.describe(mode="オンかオフか")
@app_commands.choices(mode=[
    app_commands.Choice(name="オン", value="on"),
    app_commands.Choice(name="オフ", value="off"),
])
async def cmd_leveltoggle(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    cfg = store.cfg(interaction.guild.id)
    new_state = mode.value == "on"
    was = bool(cfg.get("xp_enabled", True))
    cfg["xp_enabled"] = new_state
    store.save_config()
    if new_state:
        msg = "🎚️ レベル/XP機能はすでにオンだよ。" if was else "🎚️ レベル/XP機能を **オン** にしたよ。発言でXPが貯まって、/rank や /leaderboard も使えるよ。"
    else:
        msg = "🎚️ レベル/XP機能はすでにオフだよ。" if not was else "🎚️ レベル/XP機能を **オフ** にしたよ。XPは貯まらず、/rank や /leaderboard はオフ案内になるよ（データは消えない）。"
    await interaction.response.send_message(msg, ephemeral=True)
