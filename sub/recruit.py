# -*- coding: utf-8 -*-
"""
recruit.py — 募集システム: 募集パネル / 作成フォーム（選択形式）/ 募集カード / 自動終了
募集データは core の store（recruitments.json）に保存され、再起動後に復旧できる。
"""

import os
import time

import discord
from discord.ext import commands, tasks

from discord import app_commands

from sub.core import bot, store

# ---------------- 募集システム ----------------
def _new_rid() -> str:
    return str(int(time.time() * 1000))[-9:] + str(os.getpid() % 97)


def recruit_capacity(rec: dict) -> int:
    return 1 + int(rec.get("slots", 1))  # 作成者 + あと○人


def build_recruit_embed(rec: dict, closed_reason: str = "") -> discord.Embed:
    sels = rec.get("selections", {})
    mode_val = sels.get("モード") or "メンバー"
    if closed_reason:
        title = f"【終了】🎮 {mode_val} 募集"
        color = discord.Color.dark_grey()
    elif len(rec["participants"]) >= recruit_capacity(rec):
        title = f"【満員】🎮 {mode_val} 募集"
        color = discord.Color.green()
    else:
        title = f"🎮 {mode_val} 募集！"
        color = discord.Color.orange()
    embed = discord.Embed(title=title, color=color)
    for label, val in sels.items():
        embed.add_field(name=label, value=str(val), inline=True)
    if rec.get("comment"):
        embed.add_field(name="一言", value=rec["comment"], inline=False)
    members = "、".join(f"<@{uid}>" for uid in rec["participants"]) or "（まだいません）"
    embed.add_field(
        name=f"参加者（{len(rec['participants'])}/{recruit_capacity(rec)}）",
        value=members,
        inline=False,
    )
    embed.set_footer(text=f"作成者: {rec.get('creator_name', '')} / 募集ID: {rec['rid']}" + (f" / {closed_reason}" if closed_reason else ""))
    return embed


class RecruitCardView(discord.ui.View):
    def __init__(self, rid: str):
        super().__init__(timeout=None)
        self.rid = rid
        join_btn = discord.ui.Button(label="参加する", style=discord.ButtonStyle.primary, custom_id=f"recruit_join:{rid}", emoji="🙋")
        leave_btn = discord.ui.Button(label="離脱する", style=discord.ButtonStyle.secondary, custom_id=f"recruit_leave:{rid}", emoji="↩️")
        close_btn = discord.ui.Button(label="締め切る", style=discord.ButtonStyle.danger, custom_id=f"recruit_close:{rid}", emoji="🔒")
        join_btn.callback = self._join
        leave_btn.callback = self._leave
        close_btn.callback = self._close
        self.add_item(join_btn)
        self.add_item(leave_btn)
        self.add_item(close_btn)

    def _rec(self):
        return store.recruitments.get(self.rid)

    async def _update_card(self, interaction: discord.Interaction, rec: dict):
        # ※ discord.ui.View 内部の _refresh と名前が衝突すると BOT が落ちるのでこの名前にしている
        full = len(rec["participants"]) >= recruit_capacity(rec)
        await interaction.message.edit(embed=build_recruit_embed(rec), view=None if full else self)

    async def _join(self, interaction: discord.Interaction):
        rec = self._rec()
        if rec is None or rec.get("status") != "open":
            await interaction.response.send_message("この募集はもう終了しているよ。", ephemeral=True)
            return
        uid = interaction.user.id
        if uid in rec["participants"]:
            await interaction.response.send_message("もう参加済みだよ。", ephemeral=True)
            return
        if len(rec["participants"]) >= recruit_capacity(rec):
            await interaction.response.send_message("満員になっちゃったみたい。", ephemeral=True)
            return
        rec["participants"].append(uid)
        store.save_recruitments()
        await interaction.response.defer()
        await self._update_card(interaction, rec)
        if len(rec["participants"]) >= recruit_capacity(rec):
            ch = interaction.channel
            if ch:
                await ch.send(f"🎉 募集が満員になったよ！ <@{rec['creator_id']}> さん、出発の準備をどうぞ。", delete_after=300)

    async def _leave(self, interaction: discord.Interaction):
        rec = self._rec()
        if rec is None or rec.get("status") != "open":
            await interaction.response.send_message("この募集はもう終了しているよ。", ephemeral=True)
            return
        uid = interaction.user.id
        if uid == rec["creator_id"]:
            await interaction.response.send_message("作成者は離脱できないよ。解散する場合は「締め切る」を押してね。", ephemeral=True)
            return
        if uid not in rec["participants"]:
            await interaction.response.send_message("この募集には参加していないよ。", ephemeral=True)
            return
        rec["participants"].remove(uid)
        store.save_recruitments()
        await interaction.response.defer()
        await self._update_card(interaction, rec)

    async def _close(self, interaction: discord.Interaction):
        rec = self._rec()
        if rec is None or rec.get("status") != "open":
            await interaction.response.send_message("この募集はもう終了しているよ。", ephemeral=True)
            return
        if interaction.user.id != rec["creator_id"] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("締め切れるのは作成者と管理者だけだよ。", ephemeral=True)
            return
        await close_recruitment(rec, "締め切られました")
        await interaction.response.send_message("募集を締め切ったよ。", ephemeral=True)


async def close_recruitment(rec: dict, reason: str):
    rec["status"] = "closed"
    store.save_recruitments()
    guild = bot.get_guild(rec["guild_id"])
    if guild is None:
        return
    ch = guild.get_channel(rec["channel_id"])
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(rec["message_id"])
        await msg.edit(embed=build_recruit_embed(rec, closed_reason=reason), view=None)
    except Exception:
        pass


class RecruitCommentModal(discord.ui.Modal, title="🎮 募集を作成"):
    comment = discord.ui.TextInput(label="一言コメント（任意）", required=False, max_length=100, placeholder="例: まったり行きましょう！")

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        view = RecruitCreateView(self.guild_id, str(self.comment).strip())
        await interaction.response.send_message("募集の内容を選んでね（この画面はあなたにだけ見えます）:", view=view, ephemeral=True)


class RecruitCreateView(discord.ui.View):
    """募集作成フォーム: あと何人 + 設定項目（最大4つ/ページ）を選択 → 確定"""

    PAGE_FIELDS = 3  # 1ページ=最大5行まで（あと何人セレクト+項目3+ボタンで5行に収める）

    def __init__(self, guild_id: int, comment: str):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.comment = comment
        self.page = 0
        self.selections = {}
        self.slots = 3
        self._build()

    def _fields(self):
        cfg = store.cfg(self.guild_id)
        return cfg["recruit_fields"]

    def _pages(self):
        n = len(self._fields())
        return max(1, (n + self.PAGE_FIELDS - 1) // self.PAGE_FIELDS)

    def _build(self):
        self.clear_items()
        fields = self._fields()
        start = self.page * self.PAGE_FIELDS
        chunk = fields[start:start + self.PAGE_FIELDS]

        if self.page == 0:
            slot_sel = discord.ui.Select(
                placeholder="あと何人募集する？",
                options=[discord.SelectOption(label=f"あと{i}人", value=str(i)) for i in range(1, 8)],
                custom_id="rc_slots",
            )

            async def _slot_cb(inter: discord.Interaction):
                self.slots = int(inter.data["values"][0])
                await inter.response.defer()

            slot_sel.callback = _slot_cb
            self.add_item(slot_sel)

        for field in chunk:
            sel = discord.ui.Select(
                placeholder=f"{field['label']} を選んでね",
                options=[discord.SelectOption(label=o, value=o) for o in field["options"][:25]],
                custom_id=f"rc_field:{field['label']}",
            )

            async def _field_cb(inter: discord.Interaction, label=field["label"]):
                self.selections[label] = inter.data["values"][0]
                await inter.response.defer()

            sel.callback = _field_cb
            self.add_item(sel)

        if self.page < self._pages() - 1:
            nxt = discord.ui.Button(label="次へ ▶", style=discord.ButtonStyle.secondary)

            async def _next_cb(inter: discord.Interaction):
                self.page += 1
                self._build()
                await inter.response.edit_message(view=self)

            nxt.callback = _next_cb
            self.add_item(nxt)
        else:
            done = discord.ui.Button(label="✅ この内容で募集する", style=discord.ButtonStyle.success)

            async def _done_cb(inter: discord.Interaction):
                await self._submit(inter)

            done.callback = _done_cb
            self.add_item(done)

    async def _submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        missing = [f["label"] for f in cfg["recruit_fields"] if f["label"] not in self.selections]
        if missing:
            await interaction.response.send_message(f"⚠️ 未選択の項目があるよ: {'、'.join(missing)}（前のページも確認してね）", ephemeral=True)
            return
        ch_id = cfg.get("recruit_channel_id")
        channel = interaction.guild.get_channel(ch_id) if ch_id else interaction.channel
        if channel is None:
            channel = interaction.channel
        rid = _new_rid()
        ordered = {f["label"]: self.selections[f["label"]] for f in cfg["recruit_fields"]}
        rec = {
            "rid": rid,
            "guild_id": interaction.guild.id,
            "channel_id": channel.id,
            "message_id": None,
            "creator_id": interaction.user.id,
            "creator_name": interaction.user.display_name,
            "comment": self.comment,
            "selections": ordered,
            "slots": self.slots,
            "participants": [interaction.user.id],
            "created_at": time.time(),
            "status": "open",
        }
        view = RecruitCardView(rid)
        msg = await channel.send(embed=build_recruit_embed(rec), view=view)
        rec["message_id"] = msg.id
        store.recruitments[rid] = rec
        store.save_recruitments()
        bot.add_view(view, message_id=msg.id)
        try:
            await interaction.response.edit_message(content=f"✅ 募集を投稿したよ → {msg.jump_url}", view=None)
        except Exception:
            # 投稿自体は完了しているので、確認表示の通信が切れても落とさない
            try:
                await interaction.followup.send(f"✅ 募集を投稿したよ → {msg.jump_url}", ephemeral=True)
            except Exception:
                pass
        self.stop()


class RecruitPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 募集を作成", style=discord.ButtonStyle.primary, custom_id="recruit_create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitCommentModal(interaction.guild.id))


def build_recruit_embed_panel(cfg: dict) -> discord.Embed:
    return discord.Embed(
        title="🎮 メンバー募集",
        description=cfg.get("recruit_panel_text") or "",
        color=discord.Color.green(),
    )


async def refresh_recruit_panel(guild) -> bool:
    """設置済みの募集パネルの文章を、現在の設定で書き換える。成功したら True"""
    cfg = store.cfg(guild.id)
    panel = cfg.get("panels", {}).get("recruit")
    if not panel:
        return False
    ch = guild.get_channel(panel.get("channel_id"))
    if ch is None:
        return False
    try:
        msg = await ch.fetch_message(panel["message_id"])
        await msg.edit(embed=build_recruit_embed_panel(cfg))  # ボタンはそのまま残る
        return True
    except Exception:
        return False


@tasks.loop(minutes=1)
async def expire_recruitments():
    now = time.time()
    for rec in list(store.recruitments.values()):
        if rec.get("status") != "open":
            continue
        cfg = store.cfg(rec["guild_id"])
        limit = float(cfg.get("recruit_expire_hours", 3)) * 3600
        if now - rec.get("created_at", now) > limit:
            await close_recruitment(rec, "自動終了（時間切れ）")


# ---------------- セットアップ系コマンド（募集） ----------------
@bot.tree.command(name="setup_recruit", description="このチャンネルに募集パネルを設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_recruit(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    cfg["recruit_channel_id"] = interaction.channel.id
    await interaction.response.send_message(embed=build_recruit_embed_panel(cfg), view=RecruitPanelView())
    msg = await interaction.original_response()
    cfg["panels"]["recruit"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.followup.send("✅ 募集パネルを設置し、このチャンネルを募集チャンネルに登録しました。", ephemeral=True)

