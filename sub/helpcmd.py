# -*- coding: utf-8 -*-
"""
sub/helpcmd.py — /help: 全コマンドの機能一覧（サブBOT）

コマンドの説明文は各コマンドの登録情報から自動で拾うので、
コマンドが増えてもカテゴリに振り分ければ自動で載る（未分類は「その他」へ）。
"""

import discord

from sub.core import bot

CATEGORIES = [
    ("🌟 一般コマンド", ["rank", "leaderboard", "balance", "daily", "pay", "coinrank", "poll", "giveaway", "remind", "userinfo", "serverinfo", "avatar"]),
    ("🛠️ 管理者セットアップ", ["setup_rules", "setup_roles", "setup_recruit", "setup_intro", "setup_tickets", "setup_gate", "settings", "setwelcome", "setlog", "setintro"]),
    ("🛡️ モデレーション（管理系）", ["warn", "warns", "clearwarns", "timeout", "untimeout", "kick", "ban", "unban"]),
]


def build_help_embeds() -> list:
    cmds = {c.name: c for c in bot.tree.get_commands()}
    used = set()
    embeds = [
        discord.Embed(
            title="📖 コマンドヘルプ",
            description=(
                "このBOTで使えるコマンドの一覧です。気になるコマンドは `/コマンド名` で実行できます。\n"
                "ルール同意・ロール選択・募集・自己紹介・チケットは、設置されたパネルのボタンやメニューから操作します。"
            ),
            color=discord.Color.blurple(),
        )
    ]
    for title, names in CATEGORIES:
        lines = []
        for n in names:
            c = cmds.get(n)
            if c is not None:
                lines.append(f"`/{n}` — {c.description}")
                used.add(n)
        if lines:
            embeds.append(discord.Embed(title=title, description="\n".join(lines)[:4000], color=discord.Color.blurple()))
    rest = [n for n in cmds if n not in used and n != "help"]
    if rest:
        lines = [f"`/{n}` — {cmds[n].description}" for n in sorted(rest)]
        embeds.append(discord.Embed(title="📦 その他", description="\n".join(lines)[:4000], color=discord.Color.blurple()))
    return embeds


@bot.tree.command(name="help", description="コマンド一覧と機能の説明を表示する")
async def cmd_help(interaction: discord.Interaction):
    await interaction.response.send_message(embeds=build_help_embeds(), ephemeral=True)
