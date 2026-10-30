# -*- coding: utf-8 -*-
"""
sub/utility.py — 便利ツール（サブBOT高機能）

- /poll … ボタン投票（再起動後も継続）
- /giveaway … 参加ボタン式の抽選（締切で自動抽選）
- /remind … リマインダー（例: 10m / 1h / 2d）
- /userinfo /serverinfo /avatar … 情報表示
"""

import random
import re
import time

import discord
from discord import app_commands
from discord.ext import tasks

from sub.core import bot
from sub.userdata import utility


# ---------------- 投票 ----------------
def build_poll_embed(rec: dict) -> discord.Embed:
    counts = [0] * len(rec["options"])
    for v in rec["votes"].values():
        if 0 <= v < len(counts):
            counts[v] += 1
    total = sum(counts)
    lines = []
    for i, opt in enumerate(rec["options"]):
        pct = int(100 * counts[i] / total) if total else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"**{opt}** — {counts[i]}票（{pct}%）\n{bar}")
    embed = discord.Embed(title=f"📊 {rec['question']}", description="\n".join(lines), color=discord.Color.blue())
    embed.set_footer(text=f"合計 {total} 票")
    return embed


class PollView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        rec = utility.data["polls"].get(str(message_id))
        if rec:
            for i, opt in enumerate(rec["options"]):
                btn = discord.ui.Button(label=opt[:80], style=discord.ButtonStyle.primary, custom_id=f"poll:{message_id}:{i}")
                btn.callback = self._vote
                self.add_item(btn)

    async def _vote(self, interaction: discord.Interaction):
        idx = int(interaction.data["custom_id"].split(":")[2])
        rec = utility.data["polls"].get(str(self.message_id))
        if rec is None:
            await interaction.response.send_message("この投票は終わっているよ。", ephemeral=True)
            return
        rec["votes"][str(interaction.user.id)] = idx
        utility.save()
        await interaction.response.edit_message(embed=build_poll_embed(rec), view=self)


@bot.tree.command(name="poll", description="ボタン投票を作成する")
@app_commands.describe(question="質問", option1="選択肢1", option2="選択肢2", option3="選択肢3（任意）", option4="選択肢4（任意）")
async def cmd_poll(interaction: discord.Interaction, question: str, option1: str, option2: str, option3: str = None, option4: str = None):
    options = [o for o in [option1, option2, option3, option4] if o]
    rec = {"guild_id": interaction.guild.id, "question": question, "options": options, "votes": {}}
    await interaction.response.send_message(embed=build_poll_embed(rec))
    msg = await interaction.original_response()
    utility.data["polls"][str(msg.id)] = rec
    utility.save()
    await msg.edit(view=PollView(msg.id))


# ---------------- 抽選 ----------------
def build_giveaway_embed(rec: dict) -> discord.Embed:
    left = max(0, int(rec["ends_at"] - time.time()))
    h, m = divmod(left // 60, 60)
    when = f"あと {h}時間{m}分" if h else f"あと {m}分"
    if rec.get("ended"):
        when = "終了"
    embed = discord.Embed(title="🎁 抽選開催中！", color=discord.Color.magenta())
    embed.add_field(name="賞品", value=rec["prize"], inline=False)
    embed.add_field(name="当選人数", value=f"{rec['winners_count']}人", inline=True)
    embed.add_field(name="参加者", value=f"{len(rec['entrants'])}人", inline=True)
    embed.add_field(name="締切", value=when, inline=True)
    embed.set_footer(text="下のボタンで参加してね")
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id
        btn = discord.ui.Button(label="参加する", emoji="🎉", style=discord.ButtonStyle.success, custom_id=f"giveaway_enter:{message_id}")
        btn.callback = self._enter
        self.add_item(btn)

    async def _enter(self, interaction: discord.Interaction):
        rec = utility.data["giveaways"].get(str(self.message_id))
        if rec is None or rec.get("ended"):
            await interaction.response.send_message("この抽選は終わっているよ。", ephemeral=True)
            return
        uid = interaction.user.id
        if uid in rec["entrants"]:
            await interaction.response.send_message("もう参加済みだよ。", ephemeral=True)
            return
        rec["entrants"].append(uid)
        utility.save()
        await interaction.response.edit_message(embed=build_giveaway_embed(rec), view=self)
        await interaction.followup.send("🎉 参加を受け付けたよ！", ephemeral=True)


@bot.tree.command(name="giveaway", description="抽選を開始する（参加ボタン式）")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(prize="賞品", minutes="開催時間（分）", winners="当選人数")
async def cmd_giveaway(interaction: discord.Interaction, prize: str, minutes: int, winners: int = 1):
    minutes = max(1, min(minutes, 60 * 24 * 7))
    winners = max(1, min(winners, 20))
    rec = {
        "guild_id": interaction.guild.id,
        "channel_id": interaction.channel.id,
        "prize": prize,
        "winners_count": winners,
        "ends_at": time.time() + minutes * 60,
        "host_id": interaction.user.id,
        "entrants": [],
        "ended": False,
    }
    await interaction.response.send_message(embed=build_giveaway_embed(rec))
    msg = await interaction.original_response()
    utility.data["giveaways"][str(msg.id)] = rec
    utility.save()
    await msg.edit(view=GiveawayView(msg.id))


async def _finish_giveaway(mid: str, rec: dict):
    rec["ended"] = True
    utility.save()
    guild = bot.get_guild(rec["guild_id"])
    if guild is None:
        return
    ch = guild.get_channel(rec["channel_id"])
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(int(mid))
        await msg.edit(embed=build_giveaway_embed(rec), view=None)
    except Exception:
        pass
    entrants = rec["entrants"]
    if entrants:
        picked = random.sample(entrants, min(rec["winners_count"], len(entrants)))
        mentions = " ".join(f"<@{u}>" for u in picked)
        await ch.send(f"🎉 抽選結果！「{rec['prize']}」の当選者は {mentions} です！おめでとうございます！")
    else:
        await ch.send(f"🎁 抽選「{rec['prize']}」は参加者がいなかったため終了しました。")


# ---------------- リマインダー ----------------
_DURATION = re.compile(r"^(\d+)\s*(s|m|h|d|秒|分|時間|日)$")
_UNIT = {"s": 1, "秒": 1, "m": 60, "分": 60, "h": 3600, "時間": 3600, "d": 86400, "日": 86400}


@bot.tree.command(name="remind", description="リマインダーを設定する（例: 10m, 1h, 2d）")
@app_commands.describe(when="いつ（例: 10m / 1h / 30s / 2d）", text="内容")
async def cmd_remind(interaction: discord.Interaction, when: str, text: str):
    m = _DURATION.match(when.strip())
    if not m:
        await interaction.response.send_message("時間の形式は `10m`（10分）`1h`（1時間）`30s`（30秒）`2d`（2日）みたいに書いてね。", ephemeral=True)
        return
    secs = int(m.group(1)) * _UNIT[m.group(2)]
    if secs < 10 or secs > 30 * 86400:
        await interaction.response.send_message("10秒〜30日の範囲で指定してね。", ephemeral=True)
        return
    utility.data["reminders"].append({
        "at": time.time() + secs,
        "channel_id": interaction.channel.id,
        "guild_id": interaction.guild.id,
        "user_id": interaction.user.id,
        "text": text,
    })
    utility.save()
    await interaction.response.send_message(f"⏰ 了解。{when} 後にお知らせするよ: 「{text}」", ephemeral=True)


# ---------------- 定期チェック（抽選の締切・リマインダー） ----------------
@tasks.loop(seconds=30)
async def utility_loop():
    now = time.time()
    # 抽選
    for mid, rec in list(utility.data["giveaways"].items()):
        if not rec.get("ended") and rec["ends_at"] <= now:
            await _finish_giveaway(mid, rec)
    # リマインダー
    due = [r for r in utility.data["reminders"] if r["at"] <= now]
    if due:
        utility.data["reminders"] = [r for r in utility.data["reminders"] if r["at"] > now]
        utility.save()
        for r in due:
            guild = bot.get_guild(r["guild_id"])
            ch = guild.get_channel(r["channel_id"]) if guild else None
            if ch is not None:
                try:
                    await ch.send(f"⏰ <@{r['user_id']}> リマインダー: {r['text']}")
                except discord.Forbidden:
                    pass


# ---------------- 情報表示 ----------------
@bot.tree.command(name="userinfo", description="ユーザー情報を表示する")
@app_commands.describe(user="見たい人（省略で自分）")
async def cmd_userinfo(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    embed = discord.Embed(title=f"👤 {target.display_name}", color=discord.Color.blurple())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="ユーザー名", value=str(target), inline=True)
    embed.add_field(name="ID", value=str(target.id), inline=True)
    embed.add_field(name="アカウント作成", value=target.created_at.strftime("%Y-%m-%d"), inline=True)
    if target.joined_at:
        embed.add_field(name="サーバー参加", value=target.joined_at.strftime("%Y-%m-%d"), inline=True)
    roles = [r.name for r in target.roles if r.name != "@everyone"]
    embed.add_field(name=f"ロール（{len(roles)}）", value=", ".join(roles)[:1000] or "なし", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="serverinfo", description="サーバー情報を表示する")
async def cmd_serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🏠 {g.name}", color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="メンバー数", value=str(g.member_count), inline=True)
    embed.add_field(name="チャンネル数", value=str(len(g.channels)), inline=True)
    embed.add_field(name="ロール数", value=str(len(g.roles)), inline=True)
    embed.add_field(name="作成日", value=g.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="オーナー", value=str(g.owner) if g.owner else "-", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="avatar", description="アバター画像を表示する")
@app_commands.describe(user="見たい人（省略で自分）")
async def cmd_avatar(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    embed = discord.Embed(title=f"🖼️ {target.display_name} のアバター", color=discord.Color.blurple())
    embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)
