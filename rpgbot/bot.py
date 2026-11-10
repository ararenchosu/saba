# -*- coding: utf-8 -*-
"""
rpgbot/bot.py — 簡易RPG専用BOTの本体

起動はランチャー main.py から start() が呼ばれて行われます（メイン・サブと同じ
プロセスで動く3本目のBOT）。トークンは RPG_DISCORD_TOKEN。
お金とRPGデータは sub/userdata.py 経由でサブBOTと共有します。
"""

import time

import discord
from discord import app_commands
from discord.ext import tasks

from rpgbot.core import bot, TOKEN, requires
from rpgbot import rpg  # noqa: F401  （コマンド・イベント登録のため import）
from rpgbot.rpg import RpgPanelView

# ---- 二重読み込み対策 ----
# 起動側でこのファイルが万一2回実行されても、コマンドの二重登録エラーで
# 落ちないようにする（先に登録された分を外してから登録し直す）。
for _dup_name in ("botinfo",):
    if bot.tree.get_command(_dup_name) is not None:
        bot.tree.remove_command(_dup_name)

# ===== スマホ表示パッチ（他のBOTと同一） =====
def _apply_mobile_status_patch() -> None:
    try:
        import discord.gateway as _gw
    except Exception:
        return
    _classes = []
    for _name in ("DiscordWebSocket", "DiscordClientWebSocket", "DiscordShardWebSocket"):
        _found = getattr(_gw, _name, None)
        if _found is not None and _found not in _classes:
            _classes.append(_found)
    for cls in _classes:
        if getattr(cls, "_mobile_status_patched", False):
            continue
        _orig_send = cls.send_as_json

        async def _patched_send(self, data, _orig=_orig_send):
            try:
                if isinstance(data, dict) and data.get("op") == 2:
                    props = (data.get("d") or {}).get("properties")
                    if isinstance(props, dict):
                        props["os"] = "iOS"
                        props["browser"] = "Discord iOS"
                        props["device"] = "Discord iOS"
            except Exception:
                pass
            return await _orig(self, data)

        cls.send_as_json = _patched_send
        cls._mobile_status_patched = True


_apply_mobile_status_patch()

STARTED_AT = time.time()


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}日{h}時間{m}分"
    if h:
        return f"{h}時間{m}分"
    return f"{m}分"


@bot.tree.command(name="botinfo", description="BOTの稼働状況（所属サーバー数など）を表示する（管理者用）")
@requires(administrator=True)
async def cmd_botinfo(interaction: discord.Interaction):
    lines = []
    total_members = 0
    for g in bot.guilds:
        total_members += g.member_count or 0
        lines.append(f"・{g.name} … {g.member_count}人")
    embed = discord.Embed(title="⚔️ RPG BOT稼働状況", color=discord.Color.dark_teal())
    embed.add_field(name="所属サーバー数", value=f"{len(bot.guilds)} 件", inline=True)
    embed.add_field(name="合計メンバー数", value=f"{total_members} 人", inline=True)
    embed.add_field(name="稼働時間", value=_fmt_uptime(time.time() - STARTED_AT), inline=True)
    embed.add_field(name="所属サーバー", value="\n".join(lines)[:1024] if lines else "なし", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure) and not isinstance(error, app_commands.MissingPermissions):
        text = "そのコマンドは管理者（または許可されたユーザー）だけだよ。"
    elif isinstance(error, app_commands.MissingPermissions):
        text = "そのコマンドは管理者だけだよ。"
    else:
        text = "エラーが発生しました。時間をおいてもう一度試してね。"
        print(f"tree error: {error}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except Exception:
        pass


# ---------------- ステータスのローテーション（他のBOTと同一方式） ----------------
def _status_entries():
    entries = [f"{len(bot.guilds)} 件のサーバーで稼働中 | RPGパネルから冒険！"]
    for cmd in bot.tree.get_commands():
        desc = cmd.description or ""
        label = ""
        if desc.endswith("（管理者用）"):
            label = "（管理者用）"
            desc = desc[: -len("（管理者用）")]
        entries.append(f"/{cmd.name}：{desc}{label}"[:128])
    return entries


_status_index = 0


@tasks.loop(seconds=15)
async def rotate_status():
    global _status_index
    entries = _status_entries()
    if not entries:
        return
    text = entries[_status_index % len(entries)]
    _status_index += 1
    try:
        await bot.change_presence(activity=discord.Game(name=text))
    except Exception:
        pass


# ---------------- 起動・復旧 ----------------
@bot.event
async def on_ready():
    print(f"ログイン完了: {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンド同期: {len(synced)}件")
    except Exception as e:
        print(f"スラッシュコマンド同期失敗: {e}")
    bot.add_view(RpgPanelView())
    try:
        await bot.change_presence(activity=discord.Game(name=f"{len(bot.guilds)} 件のサーバーで稼働中 | RPGパネルから冒険！"))
    except Exception:
        pass
    if not rotate_status.is_running():
        rotate_status.start()
    print("------ RPG専用BOT 起動完了 ------")


async def start():
    """RPG専用BOTを起動する（ランチャー main.py から呼ばれる）"""
    if not TOKEN:
        print("⚠️ RPG BOTのトークン（RPG_DISCORD_TOKEN）が未設定のため、RPG BOTは起動しません。")
        return
    await bot.start(TOKEN)
