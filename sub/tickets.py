# -*- coding: utf-8 -*-
"""
sub/tickets.py — チケット（個別問い合わせ）システム（サブBOT高機能）

- /setup_tickets … チケット受付パネルを設置
- 「🎫 チケットを作成」ボタンで、その人専用のチャンネルを作成
  （見えるのは本人・運営ロール・管理者だけ）
- チャンネル内の「🔒 閉じる」ボタンでチャンネルを削除し、ログに記録
"""

import discord
from discord import app_commands

from sub.core import bot, store, log_event, get_or_create_role

CATEGORY_NAME = "🎫 チケット"


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを閉じる", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        owner_id = None
        if ch.topic and ch.topic.startswith("ticket:"):
            try:
                owner_id = int(ch.topic.split(":")[1])
            except Exception:
                owner_id = None
        is_staff = interaction.user.guild_permissions.administrator
        await interaction.response.send_message("🔒 このチケットを閉じます。チャンネルは削除されます。")
        await log_event(interaction.guild, f"🎫 チケット終了: {ch.name}（作成者: <@{owner_id}> / 閉じた人: {interaction.user.mention}）")
        try:
            await ch.delete(reason="チケット終了")
        except discord.Forbidden:
            pass


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを作成", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cfg = store.cfg(guild.id)
        if not cfg.get("tickets_enabled", True):
            await interaction.response.send_message("チケット機能は今オフだよ。", ephemeral=True)
            return
        # 既に自分のチケットがあるか
        for ch in guild.text_channels:
            if ch.topic == f"ticket:{interaction.user.id}":
                await interaction.response.send_message(f"もうあなたのチケットがあるよ: {ch.mention}", ephemeral=True)
                return
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category is None:
            try:
                category = await guild.create_category(CATEGORY_NAME)
            except discord.Forbidden:
                category = None
        staff_role = await get_or_create_role(guild, cfg.get("ticket_role", "スタッフ"))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        try:
            ch = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}"[:100],
                category=category,
                topic=f"ticket:{interaction.user.id}",
                overwrites=overwrites,
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ チャンネルを作成できませんでした（BOTの権限不足）。", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎫 チケット",
            description=f"{interaction.user.mention} さん、問い合わせありがとうございます。\n内容をここに書いてください。運営が対応します。\n終わったら下のボタンで閉じてください。",
            color=discord.Color.blurple(),
        )
        await ch.send(embed=embed, view=TicketCloseView())
        if staff_role is not None:
            await ch.send(f"{staff_role.mention} 新しいチケットです。")
        await log_event(guild, f"🎫 チケット作成: {ch.mention} by {interaction.user.mention}")
        await interaction.response.send_message(f"🎫 チケットを作成したよ: {ch.mention}", ephemeral=True)


def build_ticket_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🎫 お問い合わせ・チケット",
        description="困ったこと・通報・相談は、下のボタンからチケットを作成してね。\nあなた専用のチャンネルができて、運営だけが見える場所で話せます。",
        color=discord.Color.blurple(),
    )


@bot.tree.command(name="setup_tickets", description="チケット受付パネルをこのチャンネルに設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_tickets(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_ticket_panel_embed(), view=TicketPanelView())
    msg = await interaction.original_response()
    cfg = store.cfg(interaction.guild.id)
    cfg.setdefault("panels", {})["tickets"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
