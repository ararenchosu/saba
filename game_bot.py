# -*- coding: utf-8 -*-
"""
ランチャー：メイン + サブ を起動
YWPは別プロセスで起動するためここからは呼ばない
"""
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


async def _run_all():
    tasks = []

    # 1) メインBOT
    try:
        from main_bot import start as start_main
        tasks.append(asyncio.create_task(start_main()))
        print("✅ メインBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ メインBOTの読み込みに失敗: {e}")

    # 2) サブBOT
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
