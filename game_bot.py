# -*- coding: utf-8 -*-
"""
メイン + サブ + ぷにぷに を1プロセスで起動するランチャー

YWPフォルダを検索パスに追加し、各Botの start() を呼ぶ。
"""
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
YWP_DIR = BASE_DIR / "YWP"
sys.path.insert(0, str(YWP_DIR))


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


async def _run_all():
    tasks = []

    try:
        tasks.append(asyncio.create_task(start_main_bot()))
        print("✅ メインBOT 起動")
    except Exception as e:
        print(f"⚠️ メイン失敗: {e}")

    try:
        tasks.append(asyncio.create_task(start_sub_bot()))
        print("✅ サブBOT 起動")
    except Exception as e:
        print(f"⚠️ サブ失敗: {e}")
        import traceback
        traceback.print_exc()

    try:
        tasks.append(asyncio.create_task(start_ywp_bot()))
        print("✅ ぷにぷにBOT 起動")
    except Exception as e:
        print(f"⚠️ ぷにぷに失敗: {e}")
        import traceback
        traceback.print_exc()

    if not tasks:
        print("❌ 起動するものがない")
        return

    print(f"🚀 計{len(tasks)}体 起動")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("🛑 停止")
