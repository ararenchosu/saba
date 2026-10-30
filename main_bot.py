# -*- coding: utf-8 -*-
"""
main_bot.py — メインBOT（身内用）の本体

コマンド登録・起動時のパネル復旧・スラッシュコマンド同期を担当。
実際の起動はランチャー main.py から start() が呼ばれて行われます。
機能モジュールはルートの core.py / gate.py / recruit.py / settings.py / moderation.py / intro.py。
"""

import discord
from discord import app_commands

from core import bot, store, TOKEN
import gate  # noqa: F401  （コマンド・イベント登録のため import）
import recruit  # noqa: F401
import settings  # noqa: F401
import moderation  # noqa: F401
import intro  # noqa: F401
import invites  # noqa: F401  （招待トラッキング）
from gate import RulesView, RolePanelView
from recruit import RecruitPanelView, RecruitCardView, expire_recruitments
from intro import IntroPanelView
from invites import InvitePanelView

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
    bot.add_view(InvitePanelView())
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
    print("------ メインBOT（身内用） 起動完了 ------")


async def start():
    """メインBOTを起動する（ランチャー main.py から呼ばれる）"""
    if not TOKEN:
        print("⚠️ メインBOTのトークン（DISCORD_TOKEN）が未設定のため、メインBOTは起動しません。")
        return
    await bot.start(TOKEN)
