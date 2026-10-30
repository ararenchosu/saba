# -*- coding: utf-8 -*-
"""
sub/bot.py — サブBOT（本格用）の本体

コマンド登録・起動時のパネル復旧・スラッシュコマンド同期を担当。
実際の起動はランチャー main.py から start() が呼ばれて行われます。
機能モジュールはこの sub/ フォルダ内の各モジュール。トークンは SUB_DISCORD_TOKEN。
"""

import discord
from discord import app_commands

from sub.core import bot, store, TOKEN
from sub import gate  # noqa: F401  （コマンド・イベント登録のため import）
from sub import recruit  # noqa: F401
from sub import settings  # noqa: F401
from sub import moderation  # noqa: F401
from sub import intro  # noqa: F401
from sub import level  # noqa: F401  （高機能: レベル/XP）
from sub import economy  # noqa: F401  （高機能: コイン経済）
from sub import tickets  # noqa: F401  （高機能: チケット）
from sub import utility  # noqa: F401  （高機能: 投票・抽選・リマインダー・情報）
from sub import helpcmd  # noqa: F401  （/help コマンド一覧）
from sub import invites  # noqa: F401  （招待トラッキング）
from sub.gate import RulesView, RolePanelView
from sub.recruit import RecruitPanelView, RecruitCardView, expire_recruitments
from sub.intro import IntroPanelView
from sub.tickets import TicketPanelView, TicketCloseView
from sub.utility import PollView, GiveawayView, utility_loop
from sub.userdata import utility as utility_store

@bot.tree.command(name="bothelp", description="コマンド一覧を表示する")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 コマンド一覧", color=discord.Color.blurple())
    embed.add_field(
        name="管理者用セットアップ（すべて / コマンド）",
        value=(
            "`/setup_rules` ルール同意パネル設置\n"
            "`/setup_roles` ロール選択パネル設置\n"
            "`/setup_recruit` 募集パネル設置\n"
            "`/setup_intro` 自己紹介パネル設置 / `/setintro` 自己紹介の送信先設定\n"
            "`/setwelcome` / `/setlog` 投稿先チャンネル設定\n"
            "`/setup_gate` 認証ゲートの権限を一括適用\n"
            "`/settings` 設定パネル（項目・ロール・NGワード編集）"
        ),
        inline=False,
    )
    embed.add_field(
        name="一般コマンド",
        value=(
            "`/rank` `/leaderboard` レベルと順位\n"
            "`/balance` `/daily` `/pay` `/coinrank` コイン\n"
            "`/poll` 投票 / `/giveaway` 抽選 / `/remind` リマインダー\n"
            "`/userinfo` `/serverinfo` `/avatar` 情報表示"
        ),
        inline=False,
    )
    embed.add_field(
        name="管理系コマンド",
        value="`/warn` `/warns` `/clearwarns` 警告 / `/timeout` `/untimeout` / `/kick` `/ban` `/unban` / `/setup_tickets` チケット設置",
        inline=False,
    )
    embed.add_field(name="使い方", value="募集は募集パネルのボタンから。ロールはロール選択パネルから付けられます。", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure) and not isinstance(error, app_commands.MissingPermissions):
        text = "このBOTの担当サーバーではないため、このサーバーでは動作しません。"
    elif isinstance(error, app_commands.MissingPermissions):
        text = "そのコマンドは管理者だけだよ。"
    else:
        text = "エラーが発生しました。時間をおいてもう一度試してね。"
        print(f"tree error: {error}")
