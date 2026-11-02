# -*- coding: utf-8 -*-
"""
メイン + サブ + ぷにぷに を1プロセスで起動するランチャー
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
    tasks = [
        asyncio.create_task(start_main_bot()),
        asyncio.create_task(start_sub_bot()),
        asyncio.create_task(start_ywp_bot()),
    ]
    print(f"🚀 計{len(tasks)}体 起動")
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("🛑 停止")
