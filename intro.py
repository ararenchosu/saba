# -*- coding: utf-8 -*-
"""
intro.py — 自己紹介: パネル（ボタン→フォーム入力）→ 送信先チャンネルへ投稿
フォームの項目は /settings から追加・編集・削除できる（Discordの仕様で最大5項目）。
送信先チャンネルは /setintro で変更可能。
"""

import discord
from discord import app_commands

from core import bot, store


def build_intro_embed(display_name: str, avatar_url, fields: list, values: dict) -> discord.Embed:
    embed = discord.Embed(title=f"📝 {display_name} の自己紹介", color=discord.Color.teal())
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    for f in fields:
        v = (values.get(f["label"]) or "").strip()
        if v:
            embed.add_field(name=f["label"], value=v[:1024], inline=False)
    return embed


class IntroModal(discord.ui.Modal, title="📝 自己紹介を書く"):
    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id
        cfg = store.cfg(guild_id)
        self.fields = cfg.get("intro_fields", [])[:5]
        self.inputs = []
        for f in self.fields:
            ti = discord.ui.TextInput(
                label=f["label"][:45],
                style=discord.TextStyle.paragraph if f.get("long") else discord.TextStyle.short,
                required=bool(f.get("required")),
                max_length=1000 if f.get("long") else 100,
                placeholder="（任意）" if not f.get("required") else None,
            )
            self.inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction):
        values = {f["label"]: str(ti) for f, ti in zip(self.fields, self.inputs)}
        cfg = store.cfg(self.guild_id)
        ch_id = cfg.get("intro_channel_id")
        channel = interaction.guild.get_channel(ch_id) if ch_id else None
        if channel is None:
            await interaction.response.send_message("❌ 自己紹介の送信先チャンネルが未設定だよ。管理者に /setintro の実行を頼んでね。", ephemeral=True)
            return
        embed = build_intro_embed(
            interaction.user.display_name,
            interaction.user.display_avatar.url,
            self.fields,
            values,
        )
        embed.set_footer(text=f"投稿者: {interaction.user}")
        msg = await channel.send(content=f"{interaction.user.mention} さんが自己紹介を投稿したよ！", embed=embed)
        await interaction.response.send_message(f"✅ 自己紹介を投稿したよ → {msg.jump_url}", ephemeral=True)


class IntroPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 自己紹介を書く", style=discord.ButtonStyle.primary, custom_id="intro_open")
    async def open_intro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(interaction.guild.id)
        if not cfg.get("intro_fields"):
            await interaction.response.send_message("自己紹介の項目がまだ設定されていないよ。管理者に頼んでね。", ephemeral=True)
            return
        await interaction.response.send_modal(IntroModal(interaction.guild.id))


def build_intro_panel_embed(cfg: dict) -> discord.Embed:
    dest = cfg.get("intro_channel_id")
    desc = cfg.get("intro_panel_text") or ""
    if dest:
        desc += f"\n\n書いた内容は <#{dest}> に投稿されます。"
    return discord.Embed(title="📝 自己紹介", description=desc, color=discord.Color.teal())


async def refresh_intro_panel(guild) -> bool:
    """設置済みの自己紹介パネルの文章を、現在の設定で書き換える。成功したら True"""
    cfg = store.cfg(guild.id)
    panel = cfg.get("panels", {}).get("intro")
    if not panel:
        return False
    ch = guild.get_channel(panel.get("channel_id"))
    if ch is None:
        return False
    try:
        msg = await ch.fetch_message(panel["message_id"])
        await msg.edit(embed=build_intro_panel_embed(cfg))  # ボタンはそのまま残る
        return True
    except Exception:
        return False


@bot.tree.command(name="setup_intro", description="このチャンネルに自己紹介パネルを設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_intro(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    await interaction.response.send_message(embed=build_intro_panel_embed(cfg), view=IntroPanelView())
    msg = await interaction.original_response()
    cfg["panels"]["intro"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.followup.send("✅ 自己紹介パネルを設置しました。", ephemeral=True)


@bot.tree.command(name="setintro", description="このチャンネルを自己紹介の送信先に設定する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setintro(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    cfg["intro_channel_id"] = interaction.channel.id
    store.save_config()
    await interaction.response.send_message("✅ このチャンネルを自己紹介の送信先にしました。", ephemeral=True)
