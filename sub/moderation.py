# -*- coding: utf-8 -*-
"""
sub/moderation.py — 本格モデレーション（サブBOT高機能）

自動対策: NGワード削除 / 連投検知（管理者は対象外）
監査ログ: メッセージ削除・編集をログチャンネルへ
コマンド: /warn /warns /clearwarns /timeout /untimeout /kick /ban /unban /purge（期間指定の一括削除）
全ての処分は modlogs.json にケースとして記録される。
警告が設定回数に達すると自動でタイムアウト（設定で変更可・0で無効）。
"""

import asyncio
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from sub.core import bot, store, log_event, is_home, requires
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
    if message.id in _purge_suppress:
        return  # /purge で個別削除した分は、まとめログだけ出す
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
@requires(moderate_members=True)
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
@requires(moderate_members=True)
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
@requires(moderate_members=True)
@app_commands.describe(user="リセットする相手")
async def cmd_clearwarns(interaction: discord.Interaction, user: discord.Member):
    n = modlogs.clear_warns(interaction.guild.id, user.id)
    await log_event(interaction.guild, f"🧹 警告リセット: {user.mention}（{n} 件消去）/ 実行: {interaction.user.mention}")
    await interaction.response.send_message(f"🧹 {user.mention} の警告を {n} 件リセットしたよ。", ephemeral=True)


@bot.tree.command(name="timeout", description="メンバーをタイムアウトする（管理系）")
@requires(moderate_members=True)
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
@requires(moderate_members=True)
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
@requires(kick_members=True)
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
@requires(ban_members=True)
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
@requires(ban_members=True)
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


# ---------------- 期間指定の一括削除（/purge） ----------------
PURGE_SCAN_MAX = 3000   # 期間内で走査する最大件数（古い順に取る）
PURGE_OLD_MAX = 300     # 14日以上前のメッセージを1件ずつ消す1回あたりの上限
_BULK_AGE = timedelta(days=14)

# /purge で個別削除中のメッセージID（監査ログの重複投稿を止める）
_purge_suppress: set = set()

_DT_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m-%d")


def _parse_dt(text: str, *, end_of_day: bool):
    """'2026-11-09' '11/9' '11/9 15:30' などを JST の datetime にする。
    時刻なしの場合、end_of_day=True ならその日の 23:59:59 として扱う。
    読めなければ ValueError。"""
    text = (text or "").strip().replace("　", " ")
    parts = text.split()
    if not parts:
        raise ValueError("empty")
    dt = None
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(parts[0], fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError("bad date")
    if dt.year == 1900:
        dt = dt.replace(year=datetime.now(JST).year)
    if len(parts) > 1:
        m = re.match(r"^(\d{1,2}):(\d{2})$", parts[1])
        if not m:
            raise ValueError("bad time")
        dt = dt.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0)
    elif end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=JST)


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y/%m/%d %H:%M") if dt else "（指定なし）"


class _PurgeConfirmView(discord.ui.View):
    """削除前の確認ボタン。押した人（コマンド実行者）だけが操作できる。"""

    def __init__(self, owner_id: int, channel, recent: list, old: list, period_label: str, target_label: str):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.channel = channel
        self.recent = recent          # 14日以内 → 一括削除できる分
        self.old = old                # 14日以上前 → 1件ずつ消す分
        self.period_label = period_label
        self.target_label = target_label
        self.message = None
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def on_timeout(self):
        if self.done or self.message is None:
            return
        try:
            await self.message.edit(content="⏰ 確認がタイムアウトしたのでキャンセルしたよ。", embed=None, view=None)
        except Exception:
            pass

    @discord.ui.button(label="🗑️ 削除する", style=discord.ButtonStyle.danger)
    async def do_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        await interaction.response.edit_message(content="🧹 削除中…", embed=None, view=None)
        deleted_bulk = 0
        deleted_solo = 0
        failed = 0

        # 14日以内: 100件ずつ一括削除
        msgs = self.recent
        for i in range(0, len(msgs), 100):
            chunk = msgs[i:i + 100]
            if len(chunk) == 1:
                try:
                    await chunk[0].delete()
                    deleted_solo += 1
                except Exception:
                    failed += 1
                continue
            try:
                await self.channel.delete_messages(chunk)
                deleted_bulk += len(chunk)
            except Exception:
                for m in chunk:
                    try:
                        await m.delete()
                        deleted_solo += 1
                    except Exception:
                        failed += 1

        # 14日以上前: 1件ずつ（上限つき）。個別削除は監査ログに出さない
        old_targets = self.old[:PURGE_OLD_MAX]
        for idx, m in enumerate(old_targets, 1):
            _purge_suppress.add(m.id)
            try:
                await m.delete()
                deleted_solo += 1
            except Exception:
                failed += 1
            finally:
                _purge_suppress.discard(m.id)
            if idx % 25 == 0 and self.message is not None:
                try:
                    await self.message.edit(content=f"🧹 削除中…（古いメッセージ {idx}/{len(old_targets)} 件）")
                except Exception:
                    pass
            await asyncio.sleep(0.35)

        total = deleted_bulk + deleted_solo
        lines = [f"🧹 **削除完了**: 合計 {total} 件（{self.channel.mention}）"]
        lines.append(f"期間: {self.period_label} / 対象: {self.target_label}")
        if failed:
            lines.append(f"⚠️ 削除できなかったもの: {failed} 件")
        if len(self.old) > PURGE_OLD_MAX:
            lines.append(f"ℹ️ 14日以上前のメッセージが残り {len(self.old) - PURGE_OLD_MAX} 件あるよ。同じ条件でもう一度実行すると続きから消せるよ。")
        result = "\n".join(lines)
        if self.message is not None:
            try:
                await self.message.edit(content=result)
            except Exception:
                pass
        await log_event(
            interaction.guild,
            f"🧹 /purge 実行: {self.channel.mention} 期間 {self.period_label} / 対象 {self.target_label} / 削除 {total} 件（失敗 {failed} 件）/ 実行: {interaction.user.mention}",
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def do_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        await interaction.response.edit_message(content="キャンセルしたよ。何も消してない。", embed=None, view=None)


@bot.tree.command(name="purge", description="期間を指定してこのチャンネルのメッセージを一括削除する（管理系）")
@requires(manage_messages=True)
@app_commands.describe(
    start="開始日時（例: 11/1、11/1 9:00、2026-11-01）省略時は制限なし",
    end="終了日時（例: 11/3、11/3 18:00）省略時は今まで",
    user="この人のメッセージだけ消す（省略時は全員分）",
)
async def cmd_purge(interaction: discord.Interaction, start: str = "", end: str = "", user: discord.Member = None):
    channel = interaction.channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("このコマンドはテキストチャンネルで使ってね。", ephemeral=True)
        return
    me = interaction.guild.me
    perms = channel.permissions_for(me) if me else None
    if perms is None or not (perms.manage_messages and perms.read_message_history):
        await interaction.response.send_message("❌ BOTに「メッセージの管理」と「メッセージ履歴を読む」権限がないから消せないよ。", ephemeral=True)
        return
    try:
        start_dt = _parse_dt(start, end_of_day=False) if start.strip() else None
        end_dt = _parse_dt(end, end_of_day=True) if end.strip() else None
    except ValueError:
        await interaction.response.send_message(
            "❌ 日時の形式が読めなかったよ。例: `11/1`、`11/3 18:00`、`2026-11-01` のように書いてね。",
            ephemeral=True,
        )
        return
    if start_dt and end_dt and start_dt > end_dt:
        await interaction.response.send_message("❌ 開始日時が終了日時より後になってるよ。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    targets = []
    skipped_pinned = 0
    scanned = 0
    async for msg in channel.history(limit=PURGE_SCAN_MAX, after=start_dt, before=end_dt, oldest_first=True):
        scanned += 1
        if user is not None and msg.author.id != user.id:
            continue
        if msg.pinned:
            skipped_pinned += 1
            continue
        targets.append(msg)

    if not targets:
        tail = f"（ピン留め {skipped_pinned} 件は対象外）" if skipped_pinned else ""
        await interaction.followup.send(f"その条件で消せるメッセージはなかったよ。{tail}", ephemeral=True)
        return

    cutoff = discord.utils.utcnow() - _BULK_AGE
    recent = [m for m in targets if m.created_at > cutoff]
    old = [m for m in targets if m.created_at <= cutoff]
    period_label = f"{_fmt_dt(start_dt)} 〜 {_fmt_dt(end_dt) if end_dt else '現在'}"
    target_label = user.display_name if user is not None else "全員"

    embed = discord.Embed(title="🧹 一括削除の確認", color=discord.Color.red())
    embed.description = (
        f"チャンネル: {channel.mention}\n"
        f"期間: {period_label}\n"
        f"対象: {target_label}\n"
        f"**削除する件数: {len(targets)} 件**\n"
        f"・14日以内（一括削除）: {len(recent)} 件\n"
        f"・14日以上前（1件ずつ・今回最大 {PURGE_OLD_MAX} 件）: {len(old)} 件"
    )
    if skipped_pinned:
        embed.description += f"\n・ピン留めは消さない: {skipped_pinned} 件"
    if scanned >= PURGE_SCAN_MAX:
        embed.description += f"\n⚠️ 走査上限（{PURGE_SCAN_MAX} 件）に達したので、それより新しい分は含まれてないよ。終わったら残りをもう一度実行してね。"
    embed.set_footer(text="⚠️ 削除は取り消せません。よければ「削除する」を押してね（3分で自動キャンセル）")

    view = _PurgeConfirmView(interaction.user.id, channel, recent, old, period_label, target_label)
    msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    view.message = msg
