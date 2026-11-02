# -*- coding: utf-8 -*-
"""
main.py — ランチャー: メインBOT（身内用）を読み込んで起動した後に、サブBOT（本格用）を読み込んで起動する

  読み込み順:
    1) メインBOT（身内用）… main_bot.py ＋ ルートの各機能モジュール（core / gate / recruit / settings / moderation / intro）
    2) サブBOT（本格用）  … sub/bot.py ＋ sub/ フォルダのパッケージ一式
  片方の読み込みやトークンが失敗しても、もう片方だけで起動を続けます。

トークン（.env ファイルでも可）:
  メインBOT … DISCORD_TOKEN
  サブBOT   … SUB_DISCORD_TOKEN

FadeHost ではこのファイルの中身を game_bot.py という名前で置いてください（sub/ フォルダごとアップロード）。
"""

import asyncio


async def _run_all():
    tasks = []

    # 1) メインBOTを読み込んで起動
    try:
        from main_bot import start as start_main

        tasks.append(asyncio.create_task(start_main()))
        print("メインBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ メインBOTの読み込みに失敗しました: {e}")

    # 2) サブBOT（sub/bot.py）を読み込んで起動
    try:
        from sub.bot import start as start_sub

        tasks.append(asyncio.create_task(start_sub()))
        print("サブBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ サブBOTの読み込みに失敗しました（メインBOTのみで継続します）: {e}")

    if not tasks:
        print("❌ 起動できるBOTがありませんでした。")
        return
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        pass
