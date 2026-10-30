# -*- coding: utf-8 -*-
"""
sub/economy.py — サーバー内コイン経済（サブBOT高機能）

- /balance … 残高表示
- /daily … 1日1回のボーナス（連続日数で少し増える）
- /pay … 他の人へ送金
- /coinrank … コイン所持ランキング
"""

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from sub.core import bot, store
from sub.userdata import users

JST = timezone(timedelta(hours=9))


def _enabled(interaction) -> bool:
    return store.cfg(interaction.guild.id).get("economy_enabled", True)


@bot.tree.command(name="balance", description="コイン残高を表示する")
@app_commands.describe(user="見たい人（省略で自分）")
async def cmd_balance(interaction: discord.Interaction, user: discord.Member = None):
    if not _enabled(interaction):
        await interaction.response.send_message("コイン機能は今オフだよ。", ephemeral=True)
        return
    target = user or interaction.user
    u = users.get(interaction.guild.id, target.id)
    await interaction.response.send_message(f"💰 {target.display_name} の残高は **{u['coins']} コイン** だよ。", ephemeral=True)


@bot.tree.command(name="daily", description="デイリーボーナスを受け取る（1日1回）")
async def cmd_daily(interaction: discord.Interaction):
    if not _enabled(interaction):
        await interaction.response.send_message("コイン機能は今オフだよ。", ephemeral=True)
        return
    cfg = store.cfg(interaction.guild.id)
    u = users.get(interaction.guild.id, interaction.user.id)
    today = datetime.now(JST).date()
    today_s = today.isoformat()
    if u.get("last_daily") == today_s:
        await interaction.response.send_message("今日のボーナスはもう受け取り済みだよ。また明日ね。", ephemeral=True)
        return
    yesterday_s = (today - timedelta(days=1)).isoformat()
    streak = u.get("daily_streak", 0) + 1 if u.get("last_daily") == yesterday_s else 1
    base = int(cfg.get("daily_coins", 300))
    bonus = min(streak - 1, 10) * 20  # 連続ボーナス（最大+200）
    total = base + bonus
    u["coins"] += total
    u["last_daily"] = today_s
    u["daily_streak"] = streak
    users.save()
    await interaction.response.send_message(f"🎁 デイリーボーナス **{total} コイン** を受け取ったよ！（連続 {streak} 日目）残高は {u['coins']} コイン。")


@bot.tree.command(name="pay", description="他の人にコインを送る")
@app_commands.describe(user="送る相手", amount="送る量")
async def cmd_pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not _enabled(interaction):
        await interaction.response.send_message("コイン機能は今オフだよ。", ephemeral=True)
        return
    if user.bot or user.id == interaction.user.id:
        await interaction.response.send_message("その相手には送れないよ。", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("1以上の数を指定してね。", ephemeral=True)
        return
    me = users.get(interaction.guild.id, interaction.user.id)
    if me["coins"] < amount:
        await interaction.response.send_message(f"残高が足りないよ（今 {me['coins']} コイン）。", ephemeral=True)
        return
    target = users.get(interaction.guild.id, user.id)
    me["coins"] -= amount
    target["coins"] += amount
    users.save()
    await interaction.response.send_message(f"💸 {user.mention} に **{amount} コイン** を送ったよ。あなたの残高は {me['coins']} コイン。")


@bot.tree.command(name="coinrank", description="コイン所持ランキング（上位10人）を表示する")
async def cmd_coinrank(interaction: discord.Interaction):
    if not _enabled(interaction):
        await interaction.response.send_message("コイン機能は今オフだよ。", ephemeral=True)
        return
    all_users = users.guild_users(interaction.guild.id)
    ranking = sorted(all_users.items(), key=lambda kv: kv[1].get("coins", 0), reverse=True)[:10]
    ranking = [r for r in ranking if r[1].get("coins", 0) > 0]
    if not ranking:
        await interaction.response.send_message("まだコインを持っている人がいないよ。/daily で受け取ってね。", ephemeral=True)
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, data) in enumerate(ranking):
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ユーザー({uid})"
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} **{name}** — {data.get('coins', 0)} コイン")
    embed = discord.Embed(title="💰 コインランキング", description="\n".join(lines), color=discord.Color.green())
    await interaction.response.send_message(embed=embed)
