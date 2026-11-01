# -*- coding: utf-8 -*-
"""
ywp/bot.py — ぷにぷにBOT（自動周回用）の本体

起動処理と on_ready を担当。
実際の起動はランチャー main.py から start() が呼ばれて行われる。
"""

import discord

from ywp.core import bot, TOKEN


# ============================================================
# 起動イベント
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ [ぷにぷに] Logged in as {bot.user} ({bot.user.id})")
    print(f"📡 [ぷにぷに] 接続サーバー: {len(bot.guilds)}件")


# ============================================================
# 起動関数（ランチャーから呼ばれる）
# ============================================================
async def start():
    """ぷにぷにBOTを起動する（ランチャー main.py から呼ばれる）"""
    if not TOKEN:
        print("⚠️ ぷにぷにBOTのトークン（YWP_DISCORD_TOKEN）が未設定のため、ぷにぷにBOTは起動しません。")
        return
    await bot.start(TOKEN)
