# -*- coding: utf-8 -*-
"""
chusen.py — /抽選（締切を日時で指定する抽選）

・/抽選 抽選物 / 当選人数 / 締切（日本時間の日時。日付だけなら23:59）
・参加はボタン（もう一度押すと参加取消）
・締切で自動抽選し、結果を同じメッセージに表示＋当選者へDM
・データは utility.json に保存され、再起動しても継続する
"""

import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from sub.core import bot, requires
from sub.userdata import utility

try:
    from sub.core import features_enabled
except ImportError:  # 旧バージョンの core.py でも動くように
    def features_enabled(guild_id):
        return True

JST = ZoneInfo("Asia/Tokyo")
MAX_DAYS = 30

utility.data.setdefault("chusen", {})


def parse_deadline(text: str):
    """締切文字列（日本時間）を epoch 秒に変換する。解釈できなければ None。"""
    text = (text or "").strip()
    now = datetime.now(JST)
    fmts = ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d",
            "%m/%d %H:%M", "%m-%d %H:%M"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if dt.year == 1900:  # 年なし形式
            dt = dt.replace(year=now.year)
        if "%H" not in fmt:  # 日付だけ → その日の 23:59
            dt = dt.replace(hour=23, minute=59)
        return dt.replace(tzinfo=JST).timestamp()
    return None


def build_chusen_embed(rec: dict) -> discord.Embed:
    ends = int(rec["ends_at"])
    embed = discord.Embed(title=f"🎉 抽選：{rec['prize']}", color=discord.Color.magenta())
    embed.add_field(name="主催", value=f"<@{rec['host_id']}>", inline=True)
    embed.add_field(name="当選人数", value=f"{rec['winners_count']}人", inline=True)
    embed.add_field(name="参加者", value=f"{len(rec['entrants'])}人", inline=True)
    embed.add_field(name="締切", value=f"<t:{ends}:F>（<t:{ends}:R>）", inline=False)
    embed.set_footer(text="下のボタンで参加してね（もう一度押すと参加取消）")
    return embed


def build_result_embed(rec: dict) -> discord.Embed:
    embed = discord.Embed(title=f"🎉 抽選結果：{rec['prize']}", color=discord.Color.gold())
    winners = rec.get("winners") or []
    if winners:
        embed.add_field(name="当選者",
                        value="\n".join(f"<@{u}>" for u in winners), inline=False)
    else:
        embed.add_field(name="当選者", value="なし（参加者がいませんでした）", inline=False)
    embed.add_field(name="当選人数", value=f"{rec['winners_count']}人", inline=True)
    embed.add_field(name="参加者", value=f"{len(rec['entrants'])}人", inline=True)
    embed.add_field(name="主催", value=f"<@{rec['host_id']}>", inline=True)
    return embed


class ChusenView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        btn = discord.ui.Button(label="参加する", emoji="🎉",
                                style=discord.ButtonStyle.success,
                                custom_id=f"chusen_enter:{message_id}")
        btn.callback = self._enter
        self.add_item(btn)

    async def _enter(self, interaction: discord.Interaction):
        rec = utility.data["chusen"].get(str(self.message_id))
        if rec is None or rec.get("ended"):
            return await interaction.response.send_message(
                "この抽選は終わっているよ。", ephemeral=True)
        uid = interaction.user.id
        if uid in rec["entrants"]:
            rec["entrants"].remove(uid)
            utility.save()
            await interaction.response.edit_message(embed=build_chusen_embed(rec), view=self)
            return await interaction.followup.send("参加を取り消したよ。", ephemeral=True)
        rec["entrants"].append(uid)
        utility.save()
        await interaction.response.edit_message(embed=build_chusen_embed(rec), view=self)
        await interaction.followup.send("🎉 参加を受け付けたよ！", ephemeral=True)


@bot.tree.command(name="抽選", description="抽選を開始する（締切は日時で指定・日本時間）")
@requires(manage_messages=True)
@app_commands.rename(prize="抽選物", winners="当選人数", deadline="締切")
@app_commands.describe(prize="抽選の賞品・内容", winners="当選人数（1〜20）",
                       deadline="締切（例: 2026-11-25 20:00 / 日付だけならその日の23:59）")
async def cmd_chusen(interaction: discord.Interaction, prize: str, deadline: str,
                     winners: int = 1):
    ends_at = parse_deadline(deadline)
    if ends_at is None:
        return await interaction.response.send_message(
            "⚠️ 締切の形式が分からなかったよ。例: `2026-11-25 20:00`（日付だけでもOK）",
            ephemeral=True)
    now = time.time()
    if ends_at <= now:
        return await interaction.response.send_message(
            "⚠️ 締切が過去の日時になっています。未来の日時を指定してね。", ephemeral=True)
    if ends_at > now + MAX_DAYS * 86400:
        return await interaction.response.send_message(
            f"⚠️ 締切は{MAX_DAYS}日以内で指定してね。", ephemeral=True)
    winners = max(1, min(int(winners), 20))
    rec = {
        "guild_id": interaction.guild.id,
        "channel_id": interaction.channel.id,
        "prize": prize,
        "winners_count": winners,
        "ends_at": ends_at,
        "host_id": interaction.user.id,
        "entrants": [],
        "ended": False,
        "winners": [],
    }
    await interaction.response.send_message(embed=build_chusen_embed(rec))
    msg = await interaction.original_response()
    utility.data["chusen"][str(msg.id)] = rec
    utility.save()
    await msg.edit(view=ChusenView(msg.id))


async def _finish_chusen(mid: str, rec: dict):
    rec["ended"] = True
    entrants = rec.get("entrants") or []
    winners = (random.sample(entrants, min(rec["winners_count"], len(entrants)))
               if entrants else [])
    rec["winners"] = winners
    utility.save()
    guild = bot.get_guild(rec["guild_id"])
    if guild is None:
        return
    ch = guild.get_channel(rec["channel_id"])
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(int(mid))
        await msg.edit(embed=build_result_embed(rec), view=None)
    except Exception:
        pass
    if winners:
        mentions = " ".join(f"<@{u}>" for u in winners)
        try:
            await ch.send(f"🎉 抽選結果！「{rec['prize']}」の当選者は {mentions} です！"
                          "おめでとうございます！")
        except Exception:
            pass
        for uid in winners:
            try:
                user = bot.get_user(uid) or await bot.fetch_user(uid)
                await user.send(f"🎉 おめでとうございます！ 抽選「{rec['prize']}」に当選しました！\n"
                                f"サーバー: {guild.name}")
            except Exception:
                pass
    else:
        try:
            await ch.send(f"🎁 抽選「{rec['prize']}」は参加者がいなかったため終了しました。")
        except Exception:
            pass


@tasks.loop(seconds=30)
async def chusen_loop():
    now = time.time()
    for mid, rec in list(utility.data["chusen"].items()):
        if not rec.get("ended") and rec["ends_at"] <= now:
            if not features_enabled(rec["guild_id"]):
                continue  # 機能オフ中は抽選を保留する
            await _finish_chusen(mid, rec)


@bot.listen("on_ready")
async def chusen_on_ready():
    for mid, rec in list(utility.data["chusen"].items()):
        if not rec.get("ended"):
            try:
                bot.add_view(ChusenView(int(mid)), message_id=int(mid))
            except Exception:
                pass
    if not chusen_loop.is_running():
        chusen_loop.start()
