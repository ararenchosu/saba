# -*- coding: utf-8 -*-
"""
main.py — 荒野行動 公開サーバー向け Discord BOT の起動ファイル

このファイルは「起動」だけを担当します。機能は別ファイルに分かれています:
  core.py        … 設定ストア / BOTインスタンス / 汎用ヘルパー
  gate.py        … ウェルカム / ルール同意ゲート / ロール選択パネル
  recruit.py     … 募集システム
  settings.py    … 管理者用 設定パネル（/settings）
  moderation.py  … NGワード / 連投対策

環境変数: DISCORD_TOKEN（.env ファイルでも可）
KataBump の Startup ファイル名は main.py にしてください。
"""

import discord
from discord import app_commands

from core import bot, store, TOKEN
import gate  # noqa: F401  （コマンド・イベント登録のため import）
import recruit  # noqa: F401
import settings  # noqa: F401
import moderation  # noqa: F401
from gate import RulesView, RolePanelView
from recruit import RecruitPanelView, RecruitCardView, expire_recruitments

@bot.tree.command(name="bothelp", description="コマンド一覧を表示する")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 コマンド一覧", color=discord.Color.blurple())
    embed.add_field(
        name="管理者用セットアップ（すべて / コマンド）",
        value=(
            "`/setup_rules` ルール同意パネル設置\n"
            "`/setup_roles` ロール選択パネル設置\n"
            "`/setup_recruit` 募集パネル設置\n"
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
    if isinstance(error, app_commands.MissingPermissions):
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
    print("------ 荒野行動サーバーBOT 起動完了 ------")


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN が設定されていません。.env ファイルか環境変数に設定してください。")
        raise SystemExit(1)
    bot.run(TOKEN)
