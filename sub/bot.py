# -*- coding: utf-8 -*-
"""
sub/bot.py — サブBOT（本格用）の本体

コマンド登録・起動時のパネル復旧・スラッシュコマンド同期を担当。
実際の起動はランチャー main.py から start() が呼ばれて行われます。
機能モジュールはこの sub/ フォルダ内の各モジュール。トークンは SUB_DISCORD_TOKEN。
"""

import time

import discord
from discord import app_commands

from sub.core import bot, store, TOKEN, home_guild_id
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
from sub import casino  # noqa: F401  （カジノ）
from sub.gate import RulesView, RolePanelView
from sub.recruit import RecruitPanelView, RecruitCardView, expire_recruitments
from sub.intro import IntroPanelView
from sub.tickets import TicketPanelView, TicketCloseView
from sub.invites import InvitePanelView
from sub.casino import CasinoPanelView
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


STARTED_AT = time.time()


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}日{h}時間{m}分"
    if h:
        return f"{h}時間{m}分"
    return f"{m}分"


@bot.tree.command(name="botinfo", description="BOTの稼働状況（所属サーバー数など）を表示する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_botinfo(interaction: discord.Interaction):
    home = home_guild_id()
    lines = []
    total_members = 0
    for g in bot.guilds:
        total_members += g.member_count or 0
        mark = ""
        if home is not None:
            mark = "（担当）" if g.id == home else "（担当外）"
        lines.append(f"・{g.name} … {g.member_count}人{mark}")
    embed = discord.Embed(title="🤖 BOT稼働状況", color=discord.Color.blurple())
    embed.add_field(name="所属サーバー数", value=f"{len(bot.guilds)} 件", inline=True)
    embed.add_field(name="合計メンバー数", value=f"{total_members} 人", inline=True)
    embed.add_field(name="稼働時間", value=_fmt_uptime(time.time() - STARTED_AT), inline=True)
    embed.add_field(name="所属サーバー", value="\n".join(lines)[:1024] if lines else "なし", inline=False)
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
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except Exception:
        pass



# ---------------- 起動・復旧 ----------------
@bot.event
async def on_ready():
    print(f"ログイン完了: {bot.user} (ID: {bot.user.id})")
    # スラッシュコマンドを同期
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}件")
    except Exception as e:
        print(f"スラッシュコマンド同期失敗: {e}")
    # 設置済みパネルのボタンを復旧
    bot.add_view(RulesView())
    bot.add_view(RecruitPanelView())
    bot.add_view(IntroPanelView())
    bot.add_view(settings.SettingsView())  # 設定パネルを永続化（再起動後もボタンが効く）
    bot.add_view(TicketPanelView())
    bot.add_view(TicketCloseView())
    bot.add_view(InvitePanelView())
    bot.add_view(CasinoPanelView())
    # 進行中の投票・抽選のボタンを復旧
    for mid in utility_store.data.get("polls", {}):
        try:
            bot.add_view(PollView(int(mid)), message_id=int(mid))
        except Exception as e:
            print(f"投票復旧失敗 mid={mid}: {e}")
    for mid, rec in utility_store.data.get("giveaways", {}).items():
        if not rec.get("ended"):
            try:
                bot.add_view(GiveawayView(int(mid)), message_id=int(mid))
            except Exception as e:
                print(f"抽選復旧失敗 mid={mid}: {e}")
    if not utility_loop.is_running():
        utility_loop.start()
    for gid, cfg in store.configs.items():
        panels = cfg.get("panels", {})
        if "roles" in panels:
            try:
                bot.add_view(RolePanelView(cfg), message_id=panels["roles"]["message_id"])
            except Exception as e:
                print(f"ロールパネル復旧失敗 guild={gid}: {e}")
    # 進行中の募集カードのボタンを復旧
    for rid, rec in store.recruitments.items():
        if rec.get("status") == "open" and rec.get("message_id"):
            try:
                bot.add_view(RecruitCardView(rid), message_id=rec["message_id"])
            except Exception as e:
                print(f"募集カード復旧失敗 rid={rid}: {e}")
    if not expire_recruitments.is_running():
        expire_recruitments.start()
    try:
        await bot.change_presence(activity=discord.Game(name=f"{len(bot.guilds)} 件のサーバーで稼働中"))
    except Exception:
        pass
    print("------ サブBOT（本格用） 起動完了 ------")


async def start():
    """サブBOTを起動する（ランチャー main.py から呼ばれる）"""
    if not TOKEN:
        print("⚠️ サブBOTのトークン（SUB_DISCORD_TOKEN）が未設定のため、サブBOTは起動しません。")
        return
    await bot.start(TOKEN)
