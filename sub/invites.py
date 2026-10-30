# -*- coding: utf-8 -*-
"""
sub/invites.py — 招待トラッキング＋入退室ログ（サブBOT）

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

from sub.core import bot, store, is_home, log_event

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


async def _fetch_invite(guild, code):
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        return None
    for i in invites:
        if i.code == code:
            return i
    return None


def build_join_embed(member, invite_text: str, guard_text: str = None) -> discord.Embed:
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
    if guard_text:
        embed.add_field(name="🛡 招待ガード", value=guard_text, inline=False)
    else:
        embed.add_field(name="ようこそ！", value=f"{member.guild.name}にいらっしゃい！認証があったら認証から認証してね！", inline=False)
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
    # ---- 招待ガード: ONのサーバーでは、権限なしメンバーの招待を作成直後に無効化する ----
    guild = invite.guild
    if not is_home(guild.id):
        return
    cfg = store.cfg(guild.id)
    if not cfg.get("invite_guard_enabled", False):
        return
    inviter = invite.inviter
    if inviter is None or inviter.bot:
        return
    member = guild.get_member(inviter.id)
    if member is None:
        return  # 作成者の権限が確認できない場合は消さない（誤爆防止）
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild:
        return  # 権限持ちの招待はOK
    try:
        await invite.delete()
    except (discord.Forbidden, discord.NotFound):
        return
    _cache.get(guild.id, {}).pop(invite.code, None)
    await log_event(guild, f"🛡 招待ガード: {inviter.mention} の招待 `discord.gg/{invite.code}` を作成直後に無効化しました（このサーバーでは招待を作れるのは権限持ちのみです）")
    try:
        await inviter.send("このサーバーでは、招待リンクを作成できるのは権限を持つメンバーだけに制限されています。作った招待は自動で無効化されました。")
    except Exception:
        pass


@bot.listen("on_invite_delete")
async def _on_invite_delete(invite: discord.Invite):
    _cache.get(invite.guild.id, {}).pop(invite.code, None)


@bot.listen("on_member_join")
async def _track_join(member: discord.Member):
    guild = member.guild
    if not is_home(guild.id):
        return
    cfg = store.cfg(guild.id)
    if not cfg.get("invite_track_enabled", True):
        return
    ch = _target_channel(guild)
    before = _cache.get(guild.id)
    after = await _snapshot(guild)
    code, info = (None, None)
    if after is None:
        invite_text = "取得できませんでした（BOTに「サーバーの管理」権限が必要です）"
    else:
        if before is not None:
            code, info = _find_used(before, after)
        _cache[guild.id] = after
        if code:
            inviter = f"<@{info['inviter_id']}>" if info and info.get("inviter_id") else "不明"
            invite_text = f"`discord.gg/{code}`（作成者: {inviter} / この招待の累計使用回数: {info['uses']} 回）"
        else:
            invite_text = "特定できませんでした（バニティURL・ウィジェット・サーバー発見などの可能性）"

    # ---- 入室時ガード（2重チェック）: 作成時に弾かれなかった権限なし招待からの入室をキックする ----
    guard_text = None
    if cfg.get("invite_guard_enabled", False) and code and info and not member.bot:
        inviter_id = info.get("inviter_id")
        inviter_member = guild.get_member(inviter_id) if inviter_id else None
        if inviter_member is not None:
            ip = inviter_member.guild_permissions
            joiner_admin = member.guild_permissions.administrator
            if not (ip.administrator or ip.manage_guild) and not joiner_admin:
                try:
                    await member.send("このサーバーでは、権限を持つメンバーの招待リンクからのみ参加できます。権限のないメンバーの招待から入室したため、退出となりました。")
                except Exception:
                    pass
                kicked = False
                try:
                    await member.kick(reason="招待ガード（入室時チェック）: 権限のないメンバーの招待からの入室")
                    kicked = True
                except (discord.Forbidden, discord.NotFound):
                    kicked = False
                inv_obj = await _fetch_invite(guild, code)
                if inv_obj is not None:
                    try:
                        await inv_obj.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    if guild.id in _cache:
                        _cache[guild.id].pop(code, None)
                if kicked:
                    guard_text = f"権限のないメンバー（<@{inviter_id}>）の招待から入室したため、自動でキックしました。招待 `discord.gg/{code}` も無効化しました。"
                else:
                    guard_text = f"権限のないメンバー（<@{inviter_id}>）の招待からの入室を検知しましたが、キックできませんでした（BOTのキック権限・ロール位置を確認してください）。招待は無効化しました。"

    if ch is not None:
        try:
            await ch.send(embed=build_join_embed(member, invite_text, guard_text))
        except discord.Forbidden:
            pass
    elif guard_text:
        await log_event(guild, f"📥 入室: {member.mention}（ID: {member.id}）\n🛡 招待ガード: {guard_text}")


@bot.listen("on_member_remove")
async def _track_leave(member: discord.Member):
    guild = member.guild
    if not is_home(guild.id):
        return
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


async def _delete_invites(by_code: dict, codes: list):
    """招待をまとめて削除する。(削除できた, 既に無効だった, 失敗した) のコードリストを返す"""
    done, gone, failed = [], [], []
    for code in codes:
        inv = by_code.get(code)
        if inv is None:
            gone.append(code)
            continue
        try:
            await inv.delete()
            done.append(code)
        except discord.NotFound:
            gone.append(code)
        except discord.Forbidden:
            failed.append(code)
    return done, gone, failed


class InviteDeleteView(discord.ui.View):
    """招待の複数選択 → 確認ボタンで削除、の2段階ビュー"""

    def __init__(self, invites):
        super().__init__(timeout=300)
        self.by_code = {i.code: i for i in invites}
        self.selected = []
        options = []
        for i in invites[:25]:
            inviter = i.inviter.name if i.inviter else "不明"
            ch = f"#{i.channel.name}" if getattr(i, "channel", None) else "-"
            options.append(discord.SelectOption(
                label=f"discord.gg/{i.code}",
                value=i.code,
                description=f"作成者: {inviter} / 使用 {i.uses or 0} 回 / {ch}"[:100],
            ))
        self.select = discord.ui.Select(
            placeholder="無効化する招待を選んでね（複数選択OK）",
            min_values=1, max_values=len(options), options=options,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        self.selected = list(self.select.values)
        lines = ["この招待を無効化します（削除すると、そのリンクからは二度と入れなくなります）："]
        lines += [f"- `discord.gg/{c}`" for c in self.selected]
        lines.append("よければ下の「無効化する」ボタンを押してね。")
        self.clear_items()
        confirm = discord.ui.Button(label="🗑 無効化する", style=discord.ButtonStyle.danger)
        confirm.callback = self._on_confirm
        cancel = discord.ui.Button(label="キャンセル", style=discord.ButtonStyle.secondary)
        cancel.callback = self._on_cancel
        self.add_item(confirm)
        self.add_item(cancel)
        await interaction.response.edit_message(content="\n".join(lines), view=self)

    async def _on_confirm(self, interaction: discord.Interaction):
        done, gone, failed = await _delete_invites(self.by_code, self.selected)
        self.clear_items()
        parts = []
        if done:
            parts.append("無効化した招待: " + "、".join(f"`{c}`" for c in done))
        if gone:
            parts.append("既に無効だった招待: " + "、".join(f"`{c}`" for c in gone))
        if failed:
            parts.append("❌ 削除できなかった招待: " + "、".join(f"`{c}`" for c in failed) + "（BOTの権限を確認してね）")
        if done:
            await log_event(interaction.guild, f"🗑 {interaction.user.mention} が招待を無効化しました: " + "、".join(f"`discord.gg/{c}`" for c in done))
        self.stop()
        await interaction.response.edit_message(content="\n".join(parts) if parts else "対象がありませんでした。", view=self)

    async def _on_cancel(self, interaction: discord.Interaction):
        self.clear_items()
        self.stop()
        await interaction.response.edit_message(content="キャンセルしました。招待はそのままです。", view=self)


@bot.tree.command(name="invite_guard", description="招待ガード（権限なしメンバーの招待を自動で無効化）のON/OFF（管理者用）")
@app_commands.describe(state="on=有効 / off=無効（選ばなければ今の状態を表示）")
@app_commands.choices(state=[
    app_commands.Choice(name="on（有効にする）", value="on"),
    app_commands.Choice(name="off（無効にする）", value="off"),
])
@app_commands.checks.has_permissions(administrator=True)
async def cmd_invite_guard(interaction: discord.Interaction, state: str = None):
    cfg = store.cfg(interaction.guild.id)
    if state is None:
        now = "有効（on）" if cfg.get("invite_guard_enabled", False) else "無効（off）"
        await interaction.response.send_message(f"現在の招待ガード: **{now}**\n有効にすると、権限（管理者/サーバーの管理）を持たないメンバーが作った招待は、作られた直後に自動で無効化されます。", ephemeral=True)
        return
    cfg["invite_guard_enabled"] = state == "on"
    store.save_config()
    if state == "on":
        await interaction.response.send_message("🛡 招待ガードを **有効** にしました。これから作られる招待のうち、権限なしメンバーのものは自動で無効化されます。\n※ 既に存在する招待は対象外です。過去の招待を消したい場合は /invite_delete を使ってね。", ephemeral=True)
    else:
        await interaction.response.send_message("招待ガードを **無効** にしました。誰の招待でも使えます。", ephemeral=True)


@bot.tree.command(name="invite_delete", description="有効な招待リンクを選んで無効化する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_invite_delete(interaction: discord.Interaction):
    try:
        invites = await interaction.guild.invites()
    except discord.Forbidden:
        await interaction.response.send_message("❌ 招待一覧を取得できませんでした。BOTに「サーバーの管理」権限が必要です。", ephemeral=True)
        return
    if not invites:
        await interaction.response.send_message("現在有効な招待リンクはないよ。", ephemeral=True)
        return
    note = ""
    if interaction.guild.vanity_url_code:
        note = f"\n※ バニティURL `discord.gg/{interaction.guild.vanity_url_code}` はここでは消せません。サーバー設定の招待リンクから無効化してね。"
    if len(invites) > 25:
        note += "\n※ 招待が25件を超えているため、使用回数の多い順に25件まで表示しています。"
        invites = sorted(invites, key=lambda x: x.uses or 0, reverse=True)
    await interaction.response.send_message(f"無効化したい招待をメニューから選んでね。{note}", view=InviteDeleteView(invites), ephemeral=True)


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
