# -*- coding: utf-8 -*-
"""
main.py — ランチャー: メインBOT、サブBOT、ぷにぷにBOTを読み込んで同時に起動する

  読み込み順:
    1) メインBOT（身内用）… main_bot.py ＋ ルートの各機能モジュール
    2) サブBOT（本格用）  … sub/bot.py ＋ sub/ フォルダのパッケージ一式
    3) ぷにぷにBOT        … ywp/bot.py ＋ ywp/ フォルダのパッケージ一式
  どれかの読み込みやトークンが失敗しても、他のBOTだけで起動を続けます。

トークン（.env ファイルでも可）:
  メインBOT … DISCORD_TOKEN
  サブBOT   … SUB_DISCORD_TOKEN
  ぷにぷにBOT … YWP_DISCORD_TOKEN

FadeHost ではこのファイルの中身を game_bot.py という名前で置いてください（sub/ と ywp/ フォルダごとアップロード）。
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

    # 3) ぷにぷにBOT（ywp/bot.py）を読み込んで起動 ★追加
    try:
        from ywp.bot import start as start_ywp

        tasks.append(asyncio.create_task(start_ywp()))
        print("ぷにぷにBOTを読み込みました。")
    except Exception as e:
        print(f"⚠️ ぷにぷにBOTの読み込みに失敗しました（他のBOTのみで継続します）: {e}")

    if not tasks:
        print("❌ 起動できるBOTがありませんでした。")
        return
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        pass
