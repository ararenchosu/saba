# -*- coding: utf-8 -*-
"""
統合ランチャー — 複数のDiscord BOTを一括起動・管理

【読み込み・起動するBOT】
  1) メインBOT     … main_bot.py         （身内用・ルートの各機能モジュール含む）
  2) サブBOT       … sub/bot.py          （本格用・コマンド/機能メイン）
  3) ぷにぷにBOT   … YWP/bot.py          （YWP/PuniPuni自動化モジュール）
  4) RPG専用BOT    … rpgbot/bot.py       （RPG機能専用・データは sub/userdata.py と共有）

【特徴】
  ✅ どれか1体が失敗しても、他のBOTはそのまま起動し続ける
  ✅ YWPフォルダを自動的に検索パスに追加
  ✅ 詳細なエラーメッセージ＋トレースバック表示
  ✅ Ctrl+Cでまとめて安全に停止

【トークン環境変数】 .envファイルまたはシステム環境変数に設定
  メインBOT → DISCORD_TOKEN
  サブBOT   → SUB_DISCORD_TOKEN
  ぷにぷにBOT → YWP_DISCORD_TOKEN
  RPG BOT   → RPG_DISCORD_TOKEN

【FadeHostでの運用】
  このファイルを game_bot.py として配置し、
  main_bot.py / sub/ / YWP/ / rpgbot/ を全て同じ階層にアップロードしてください。
"""

import asyncio
import sys
from pathlib import Path

# === パス設定 ===
BASE_DIR = Path(__file__).resolve().parent
YWP_DIR = BASE_DIR / "YWP"
sys.path.insert(0, str(YWP_DIR))


# === 各BOT起動関数 ===
async def start_main_bot():
    from main_bot import start as _start
    await _start()


async def start_sub_bot():
    from sub.bot import start as _start
    await _start()


async def start_ywp_bot():
    """ぷにぷにBOTを起動"""
    from YWP.bot import start as _start
    await _start()


async def start_rpg_bot():
    """RPG専用BOTを起動"""
    from rpgbot.bot import start as _start
    await _start()


# === メイン実行 ===
async def _run_all():
    tasks = []

    # 1) メインBOT
    try:
        tasks.append(asyncio.create_task(start_main_bot()))
        print("✅ メインBOT 起動")
    except Exception as e:
        print(f"⚠️ メインBOT 起動失敗: {e}")
        import traceback
        traceback.print_exc()

    # 2) サブBOT
    try:
        tasks.append(asyncio.create_task(start_sub_bot()))
        print("✅ サブBOT 起動")
    except Exception as e:
        print(f"⚠️ サブBOT 起動失敗: {e}")
        import traceback
        traceback.print_exc()

    # 3) ぷにぷにBOT
    try:
        tasks.append(asyncio.create_task(start_ywp_bot()))
        print("✅ ぷにぷにBOT 起動")
    except Exception as e:
        print(f"⚠️ ぷにぷにBOT 起動失敗: {e}")
        import traceback
        traceback.print_exc()

    # 4) RPG専用BOT
    try:
        tasks.append(asyncio.create_task(start_rpg_bot()))
        print("✅ RPG専用BOT 起動")
    except Exception as e:
        print(f"⚠️ RPG専用BOT 起動失敗: {e}（他のBOTは継続します）")
        import traceback
        traceback.print_exc()

    # 起動したBOTが0体の場合
    if not tasks:
        print("❌ 起動できるBOTがありませんでした。ファイル構成やトークンを確認してください。")
        return

    # 全BOTの実行を待機
    print(f"🚀 計 {len(tasks)} 体のBOTを起動しました")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("\n🛑 すべてのBOTを停止しました")
