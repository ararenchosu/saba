# -*- coding: utf-8 -*-
"""
1プロセスで全部起動：メイン + サブ + YWP(ちょすbot#6538)
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
    from YWP.bot import start as _start
    await _start()


async def _run_all():
    tasks = []

    try:
        tasks.append(asyncio.create_task(start_main_bot()))
        print("✅ メインBOT 起動開始")
    except Exception as e:
        print(f"⚠️ メイン失敗: {e}")

    try:
        tasks.append(asyncio.create_task(start_sub_bot()))
        print("✅ サブBOT 起動開始")
    except Exception as e:
        print(f"⚠️ サブ失敗: {e}")

    try:
        tasks.append(asyncio.create_task(start_ywp_bot()))
        print("✅ YWP(ぷにぷに)BOT 起動開始")
    except Exception as e:
        print(f"⚠️ YWP失敗: {e}")
        import traceback
        traceback.print_exc()

    if not tasks:
        print("❌ 起動するものがない")
        return

    print(f"🚀 計{len(tasks)}体 一斉起動")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("🛑 停止")
