# -*- coding: utf-8 -*-
"""
ywp/core.py — ぷにぷにBOTの共通設定

- Botインスタンス
- トークン（環境変数 YWP_DISCORD_TOKEN）
- データフォルダ（ywp/data/）
を提供する。
"""

import os
import discord
from discord.ext import commands

# ============================================================
# 設定
# ============================================================
TOKEN = os.getenv("YWP_DISCORD_TOKEN")          # ← 環境変数から
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)            # なければ作る


# ============================================================
# Intents
# ============================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True


# ============================================================
# Botクラス（setup_hook で Cog を読み込む）
# ============================================================
class YWPBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        cogs = [
            "ywp.auto",
            "ywp.commands",
            "ywp.stages",
            "ywp.panel",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"✅ ぷにぷに ロード: {cog}")
            except Exception as e:
                print(f"❌ ぷにぷに ロード失敗 {cog}: {e}")

        try:
            synced = await self.tree.sync()
            print(f"🔁 ぷにぷに コマンド同期: {len(synced)}件")
            for cmd in synced:
                print(f"    /{cmd.name}")
        except Exception as e:
            print(f"❌ ぷにぷに 同期失敗: {e}")


# ============================================================
# グローバルBotインスタンス
# ============================================================
bot = YWPBot()
