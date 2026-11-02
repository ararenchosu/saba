# -*- coding: utf-8 -*-
"""
main.py — ランチャー: メインBOT → YWP BOT → サブBOT の順に読み込んで起動

  読み込み順:
    1) メインBOT（身内用）… main_bot.py
    2) YWP BOT（自動周回）… YWP/bot.py
    3) サブBOT（本格用）  … sub/bot.py

  各BOTは個別に起動し、1つが失敗しても他は継続します。

トークン（.env または環境変数）:
  メインBOT … DISCORD_TOKEN
  YWP BOT   … YWP_DISCORD_TOKEN
  サブBOT   … SUB_DISCORD_TOKEN
"""

import asyncio


async def _run_all():
    tasks = []

    # 1) メインBOT
    try:
        from main_bot import start as start_main
        tasks.append(asyncio.create_task(start_main()))
        print("✅ メインBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ メインBOTの読み込みに失敗: {e}")

    # 2) YWP BOT  ← 新規追加
    try:
        from YWP.bot import start as start_ywp
        tasks.append(asyncio.create_task(start_ywp()))
        print("✅ YWP BOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ YWP BOTの読み込みに失敗: {e}")

    # 3) サブBOT
    try:
        from sub.bot import start as start_sub
        tasks.append(asyncio.create_task(start_sub()))
        print("✅ サブBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ サブBOTの読み込みに失敗: {e}")

    if not tasks:
        print("❌ 起動できるBOTがありませんでした。")
        return
    print(f"🚀 計{len(tasks)}体のBotを起動します。")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("🛑 停止しました。")
