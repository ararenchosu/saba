# -*- coding: utf-8 -*-
"""
sub/invites.py — 招待トラッキング（サブBOT）

誰が・どの招待コードから入ってきたかを特定して、ログチャンネルに記録する。
仕組み: 招待ごとの使用回数を控えておき、入室時に増えたコードを突き止める。
- BOTに「サーバーの管理」権限がないと招待一覧を取得できない（その場合は記録できない）
- バニティURL・ウィジェット・サーバー発見からの入室はコードが増えないので「特定不可」になる
- /invites … 現在有効な招待の一覧（コード・作成者・使用回数）を確認できる
"""

import discord
from discord import app_commands

from sub.core import bot, store, log_event

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
    before = _cache.get(guild.id)
    after = await _snapshot(guild)
    if after is None:
        return  # 権限不足などで招待一覧が取れない
    code, info = (None, None)
    if before is not None:
        code, info = _find_used(before, after)
    _cache[guild.id] = after
    if code:
        inviter = f"<@{info['inviter_id']}>" if info and info.get("inviter_id") else "不明"
        await log_event(guild, f"📥 入室: {member.mention}（ID: {member.id}）\n招待コード `{code}` から入室（作成者: {inviter} / この招待の累計使用回数: {info['uses']} 回）")
    else:
        await log_event(guild, f"📥 入室: {member.mention}（ID: {member.id}）\n招待元は特定できませんでした（バニティURL・ウィジェット・サーバー発見など、通常の招待コード経由ではない可能性）")


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
    # 最新情報で表示するために実データも取る
    invites = await interaction.guild.invites()
    lines = [f"**有効な招待 {len(invites)} 件**（使用回数が多いもの・作成者が不審なものが流出元候補）"]
    for i in sorted(invites, key=lambda x: x.uses or 0, reverse=True):
        inviter = i.inviter.mention if i.inviter else "不明"
        ch = f"#{i.channel.name}" if i.channel else "-"
        lines.append(f"- `discord.gg/{i.code}` 作成者: {inviter} / 使用 {i.uses or 0} 回 / 対象: {ch}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)
