# -*- coding: utf-8 -*-
"""
invites.py — 招待トラッキング＋入退室ログ（メインBOT）

入室・退出を、スクショのような詳細Embedでログチャンネルに記録する。
入室Embedには「どの招待コードから入ったか（作成者つき）」も載せる。
仕組み: 招待ごとの使用回数を控えておき、入室時に増えたコードを突き止める。
- BOTに「サーバーの管理」権限がないと招待一覧を取得できず、招待元は「取得不可」になる
- バニティURL・ウィジェット・サーバー発見からの入室は「特定できませんでした」になる
- /invites … 現在有効な招待の一覧（コード・作成者・使用回数）
"""

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from core import bot, store

JST = timezone(timedelta(hours=9))

_cache = {}  # guild_id -> {code: {"uses": int, "inviter_id": int|None}}


async def _snapshot(guild):
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        return None
    return {
        i.code: {"uses": i.uses or 0, "inviter_id": i.inviter.id if i.inviter else None}
        for i in invites
    }


def _find_used(before: dict, after: dict):
    """使用回数が増えた招待コードを探す。なければ None"""
    for code, info in after.items():
        prev = before.get(code, {"uses": 0})["uses"]
        if info["uses"] > prev:
            return code, info
    return None, None


def _target_channel(guild):
    """入退室Embedの投稿先。/setwelcome で指定されたチャンネルだけ（未指定なら投稿しない）"""
    cfg = store.cfg(guild.id)
    if cfg.get("welcome_channel_id"):
        return guild.get_channel(cfg["welcome_channel_id"])
    return None


def _created_text(member) -> str:
    created = member.created_at.astimezone(JST)
    days = (datetime.now(JST) - created).days
    return f"{created.strftime('%Y-%m-%d %H:%M:%S')} JST\n（約{days}日前）", days


def _footer(guild) -> str:
    now = datetime.now(JST)
    return f"サーバーID: {guild.id} | {now.year}/{now.month:02d}/{now.day:02d}, {now.hour}:{now.minute:02d}"


def build_join_embed(member, invite_text: str) -> discord.Embed:
    created_text, days = _created_text(member)
    embed = discord.Embed(description="📥 メンバーが参加しました！", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ユーザー名", value=f"{member.mention}\n`{member.display_name}`", inline=False)
    embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=False)
    embed.add_field(name="アカウント作成日", value=created_text, inline=False)
    embed.add_field(name="作成からの経過", value=f"{days}日", inline=False)
    embed.add_field(name="アカウント種類", value="🤖 Bot" if member.bot else "👤 ユーザー", inline=False)
    embed.add_field(name="使用した招待", value=invite_text, inline=False)
    embed.add_field(name="👥 サーバー総人数", value=f"{member.guild.member_count}人", inline=False)
    embed.set_footer(text=_footer(member.guild))
    return embed


def build_leave_embed(member) -> discord.Embed:
    created_text, days = _created_text(member)
    embed = discord.Embed(description="📤 メンバーが退出しました！", color=discord.Color.red())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ユーザー名", value=f"{member.mention}\n`{member.display_name}`", inline=False)
    embed.add_field(name="ユーザーID", value=f"`{member.id}`", inline=False)
    embed.add_field(name="アカウント作成日", value=created_text, inline=False)
    embed.add_field(name="作成からの経過", value=f"{days}日", inline=False)
    embed.add_field(name="アカウント種類", value="🤖 Bot" if member.bot else "👤 ユーザー", inline=False)
    if member.joined_at:
        joined = member.joined_at.astimezone(JST)
        stay = (datetime.now(JST) - joined).days
        embed.add_field(name="サーバー参加日", value=f"{joined.strftime('%Y-%m-%d %H:%M:%S')} JST\n（在籍 {stay} 日）", inline=False)
    embed.add_field(name="👥 サーバー総人数", value=f"{member.guild.member_count}人", inline=False)
    embed.set_footer(text=_footer(member.guild))
    return embed


@bot.listen("on_ready")
async def _prime_cache():
    for guild in bot.guilds:
        snap = await _snapshot(guild)
        if snap is not None:
            _cache[guild.id] = snap


@bot.listen("on_invite_create")
async def _on_invite_create(invite: discord.Invite):
    _cache.setdefault(invite.guild.id, {})[invite.code] = {
        "uses": invite.uses or 0,
        "inviter_id": invite.inviter.id if invite.inviter else None,
    }


@bot.listen("on_invite_delete")
async def _on_invite_delete(invite: discord.Invite):
    _cache.get(invite.guild.id, {}).pop(invite.code, None)


@bot.listen("on_member_join")
async def _track_join(member: discord.Member):
    guild = member.guild
    cfg = store.cfg(guild.id)
    if not cfg.get("invite_track_enabled", True):
        return
    ch = _target_channel(guild)
    if ch is None:
        return
    before = _cache.get(guild.id)
    after = await _snapshot(guild)
    if after is None:
        invite_text = "取得できませんでした（BOTに「サーバーの管理」権限が必要です）"
    else:
        code, info = (None, None)
        if before is not None:
            code, info = _find_used(before, after)
        _cache[guild.id] = after
        if code:
            inviter = f"<@{info['inviter_id']}>" if info and info.get("inviter_id") else "不明"
            invite_text = f"`discord.gg/{code}`（作成者: {inviter} / この招待の累計使用回数: {info['uses']} 回）"
        else:
            invite_text = "特定できませんでした（バニティURL・ウィジェット・サーバー発見などの可能性）"
    try:
        await ch.send(embed=build_join_embed(member, invite_text))
    except discord.Forbidden:
        pass


@bot.listen("on_member_remove")
async def _track_leave(member: discord.Member):
    guild = member.guild
    cfg = store.cfg(guild.id)
    if not cfg.get("invite_track_enabled", True):
        return
    ch = _target_channel(guild)
    if ch is None:
        return
    try:
        await ch.send(embed=build_leave_embed(member))
    except discord.Forbidden:
        pass


@bot.tree.command(name="invites", description="現在有効な招待リンクの一覧を見る（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_invites(interaction: discord.Interaction):
    snap = await _snapshot(interaction.guild)
    if snap is None:
        await interaction.response.send_message("❌ 招待一覧を取得できませんでした。BOTに「サーバーの管理」権限が必要です。", ephemeral=True)
        return
    if not snap:
        await interaction.response.send_message("現在有効な招待リンクはないよ。", ephemeral=True)
        return
    invites = await interaction.guild.invites()
    lines = [f"**有効な招待 {len(invites)} 件**（使用回数が多いもの・作成者が不審なものが流出元候補）"]
    for i in sorted(invites, key=lambda x: x.uses or 0, reverse=True):
        inviter = i.inviter.mention if i.inviter else "不明"
        ch = f"#{i.channel.name}" if i.channel else "-"
        lines.append(f"- `discord.gg/{i.code}` 作成者: {inviter} / 使用 {i.uses or 0} 回 / 対象: {ch}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)
