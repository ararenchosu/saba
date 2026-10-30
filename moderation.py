# -*- coding: utf-8 -*-
"""
moderation.py — 軽いモデレーション: NGワード自動削除 / 連投対策
on_message は listen で受ける（コマンド処理は discord.py の標準動作に任せる）。
"""

import time
from collections import defaultdict, deque

from core import bot, store, log_event, is_home

_recent_msgs = defaultdict(deque)  # (guild_id, user_id) -> deque[(content, ts)]


@bot.listen("on_message")
async def moderate_message(message):
    if message.author.bot or message.guild is None:
        return
    if not is_home(message.guild.id):
        return
    cfg = store.cfg(message.guild.id)
    content = message.content or ""

    # NGワード
    hit = next((w for w in cfg.get("ng_words", []) if w and w in content), None)
    if hit and not message.author.guild_permissions.administrator:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.author.send(f"⚠️ NGワードを含む投稿を削除しました（サーバー: {message.guild.name}）。")
        except Exception:
            pass
        await log_event(message.guild, f"🚫 NGワード投稿を削除: {message.author} in {message.channel.mention}")
        return

    # 連投対策: 同じ文を短時間に4回以上
    if not message.author.guild_permissions.administrator:
        key = (message.guild.id, message.author.id)
        now = time.time()
        dq = _recent_msgs[key]
        dq.append((content, now))
        while dq and now - dq[0][1] > 15:
            dq.popleft()
        same = sum(1 for c, _ in dq if c == content)
        if content and same >= 4:
            try:
                await message.delete()
            except Exception:
                pass
            await log_event(message.guild, f"🚫 連投を検知して削除: {message.author} in {message.channel.mention}")
            dq.clear()
            return
