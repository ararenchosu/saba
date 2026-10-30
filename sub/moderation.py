# -*- coding: utf-8 -*-
"""
sub/moderation.py — 本格モデレーション（サブBOT高機能）

自動対策: NGワード削除 / 連投検知（管理者は対象外）
監査ログ: メッセージ削除・編集をログチャンネルへ
コマンド: /warn /warns /clearwarns /timeout /untimeout /kick /ban /unban
全ての処分は modlogs.json にケースとして記録される。
警告が設定回数に達すると自動でタイムアウト（設定で変更可・0で無効）。
"""

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from sub.core import bot, store, log_event, is_home
from sub.userdata import modlogs

JST = timezone(timedelta(hours=9))

# (channel_id, user_id) -> deque[(text, ts)]
_recent = defaultdict(lambda: deque(maxlen=6))
SPAM_COUNT = 4
SPAM_WINDOW = 15  # 秒


def _now_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


# ---------------- 自動対策 ----------------
@bot.listen("on_message")
async def auto_moderation(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if not is_home(message.guild.id):
        return
    if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
        return
    cfg = store.cfg(message.guild.id)
    content = message.content or ""

    for word in cfg.get("ng_words", []):
        if word and word in content:
            try:
                await message.delete()
            except discord.Forbidden:
                return
            await log_event(message.guild, f"🚫 NGワードを削除: {message.author.mention} in {message.channel.mention}（ワード: {word}）")
            try:
                await message.author.send(f"⚠️ サーバー「{message.guild.name}」でNGワードを含むメッセージが削除されました: 「{word}」")
            except discord.Forbidden:
                pass
            return

    key = (message.channel.id, message.author.id)
    q = _recent[key]
    now = time.time()
    q.append((content, now))
    same = [t for (txt, t) in q if txt == content and now - t <= SPAM_WINDOW]
    if len(same) >= SPAM_COUNT:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        await log_event(message.guild, f"🚫 連投を検知して削除: {message.author.mention} in {message.channel.mention}")
        q.clear()


# ---------------- 監査ログ ----------------
@bot.listen("on_message_delete")
async def audit_delete(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    cfg = store.cfg(message.guild.id)
    if not cfg.get("audit_log_enabled", True):
        return
    content = (message.content or "")[:200] or "（内容なし・添付など）"
    await log_event(message.guild, f"🗑️ メッセージ削除: {message.author.mention} in {message.channel.mention}\n> {content}")


@bot.listen("on_message_edit")
async def audit_edit(before: discord.Message, after: discord.Message):
    if after.guild is None or after.author.bot:
        return
    if (before.content or "") == (after.content or ""):
        return
    cfg = store.cfg(after.guild.id)
    if not cfg.get("audit_log_enabled", True):
        return
    await log_event(after.guild, f"✏️ メッセージ編集: {after.author.mention} in {after.channel.mention}\n前: {(before.content or '')[:150]}\n後: {(after.content or '')[:150]}")


# ---------------- 処分コマンド ----------------
def _record(interaction, target, action, reason):
    case = modlogs.add_case(interaction.guild.id, target.id, interaction.user.id, action, reason or "", _now_str())
    return case


@bot.tree.command(name="warn", description="メンバーに警告する（管理系）")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(user="警告する相手", reason="理由")
async def cmd_warn(interaction: discord.Interaction, user: discord.Member, reason: str = ""):
    if user.bot or user.id == interaction.user.id:
        await interaction.response.send_message("その相手には警告できないよ。", ephemeral=True)
        return
    cfg = store.cfg(interaction.guild.id)
    case = _record(interaction, user, "warn", reason)
    count = modlogs.warn_count(interaction.guild.id, user.id)
    await log_event(interaction.guild, f"⚠️ 警告 #{case['id']}: {user.mention}（累計 {count} 回）理由: {reason or 'なし'} / 実行: {interaction.user.mention}")
    try:
        await user.send(f"⚠️ サーバー「{interaction.guild.name}」で警告を受けました。理由: {reason or 'なし'}（累計 {count} 回）")
    except discord.Forbidden:
        pass
    # 自動タイムアウト
    threshold = int(cfg.get("mod_auto_timeout_warnings", 0))
    minutes = int(cfg.get("mod_auto_timeout_minutes", 10))
    extra = ""
    if threshold and count >= threshold:
        try:
            await user.timeout(timedelta(minutes=minutes), reason=f"警告 {count} 回到達のため自動処分")
            _record(interaction, user, "auto_timeout", f"警告{count}回到達")
            extra = f"\n警告が {threshold} 回に達したので、自動で {minutes} 分タイムアウトしました。"
            await log_event(interaction.guild, f"⏱️ 自動タイムアウト: {user.mention} を {minutes} 分（警告 {count} 回）")
        except discord.Forbidden:
            extra = "\n（自動タイムアウトは権限不足で失敗しました）"
    await interaction.response.send_message(f"⚠️ {user.mention} に警告しました（累計 {count} 回）。{extra}", ephemeral=True)


@bot.tree.command(name="warns", description="メンバーの警告・処分履歴を見る（管理系）")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(user="見たい相手")
async def cmd_warns(interaction: discord.Interaction, user: discord.Member):
    cases = modlogs.cases(interaction.guild.id, user.id)
    if not cases:
        await interaction.response.send_message(f"{user.display_name} の処分履歴はないよ。", ephemeral=True)
        return
    lines = [f"**{user.display_name}** の履歴（{len(cases)} 件、警告 {modlogs.warn_count(interaction.guild.id, user.id)} 回）"]
    for c in cases[-10:]:
        lines.append(f"#{c['id']} [{c['action']}] {c['at']} 理由: {c['reason'] or 'なし'}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@bot.tree.command(name="clearwarns", description="メンバーの警告をリセットする（管理系）")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(user="リセットする相手")
async def cmd_clearwarns(interaction: discord.Interaction, user: discord.Member):
    n = modlogs.clear_warns(interaction.guild.id, user.id)
    await log_event(interaction.guild, f"🧹 警告リセット: {user.mention}（{n} 件消去）/ 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"🧹 {user.mention} の警告を {n} 件リセットしたよ。", ephemeral=True)


@bot.tree.command(name="timeout", description="メンバーをタイムアウトする（管理系）")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(user="相手", minutes="分数（最大40320=28日）", reason="理由")
async def cmd_timeout(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str = ""):
    minutes = max(1, min(minutes, 40320))
    try:
        await user.timeout(timedelta(minutes=minutes), reason=reason or None)
    except discord.Forbidden:
        await interaction.response.send_message("❌ 権限不足でタイムアウトできませんでした（相手が管理者/上位ロールの可能性）。", ephemeral=True)
        return
    case = _record(interaction, user, "timeout", f"{minutes}分: {reason}")
    await log_event(interaction.guild, f"⏱️ タイムアウト #{case['id']}: {user.mention} を {minutes} 分。理由: {reason or 'なし'} / 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"⏱️ {user.mention} を {minutes} 分タイムアウトしたよ。", ephemeral=True)


@bot.tree.command(name="untimeout", description="タイムアウトを解除する（管理系）")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(user="相手")
async def cmd_untimeout(interaction: discord.Interaction, user: discord.Member):
    try:
        await user.timeout(None)
    except discord.Forbidden:
        await interaction.response.send_message("❌ 権限不足で解除できませんでした。", ephemeral=True)
        return
    _record(interaction, user, "untimeout", "")
    await log_event(interaction.guild, f"▶️ タイムアウト解除: {user.mention} / 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"▶️ {user.mention} のタイムアウトを解除したよ。", ephemeral=True)


@bot.tree.command(name="kick", description="メンバーをキックする（管理系）")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(user="相手", reason="理由")
async def cmd_kick(interaction: discord.Interaction, user: discord.Member, reason: str = ""):
    try:
        await user.kick(reason=reason or None)
    except discord.Forbidden:
        await interaction.response.send_message("❌ 権限不足でキックできませんでした。", ephemeral=True)
        return
    case = _record(interaction, user, "kick", reason)
    await log_event(interaction.guild, f"👢 キック #{case['id']}: {user.mention} 理由: {reason or 'なし'} / 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"👢 {user.display_name} をキックしたよ。", ephemeral=True)


@bot.tree.command(name="ban", description="メンバーをBANする（管理系）")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(user="相手", reason="理由")
async def cmd_ban(interaction: discord.Interaction, user: discord.Member, reason: str = ""):
    try:
        await user.ban(reason=reason or None)
    except discord.Forbidden:
        await interaction.response.send_message("❌ 権限不足でBANできませんでした。", ephemeral=True)
        return
    case = _record(interaction, user, "ban", reason)
    await log_event(interaction.guild, f"🔨 BAN #{case['id']}: {user.mention} 理由: {reason or 'なし'} / 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"🔨 {user.display_name} をBANしたよ。", ephemeral=True)


@bot.tree.command(name="unban", description="BANを解除する（ユーザーID指定・管理系）")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(user_id="解除するユーザーのID")
async def cmd_unban(interaction: discord.Interaction, user_id: str):
    try:
        target = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(target)
    except Exception:
        await interaction.response.send_message("❌ 解除できませんでした（IDが違うか、BANされていない可能性）。", ephemeral=True)
        return
    await log_event(interaction.guild, f"🔓 BAN解除: {target} / 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"🔓 {target} のBANを解除したよ。", ephemeral=True)
