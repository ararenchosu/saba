# -*- coding: utf-8 -*-
"""
sub/tickets.py — チケット（個別問い合わせ）システム（サブBOT高機能）

- /setup_tickets … チケット受付パネルを設置（種類セレクト式）
- パネルで種類を選ぶと、その人専用のチャンネルを作成
  （見えるのは本人・担当ロール・管理者だけ）
- /ticket_settings … 管理者専用の設定（セレクトメニュー式）:
  パネルの文面、チケットの種類（担当ロール/カテゴリ）、同時上限、チャンネル名形式
- チャンネル内の「🔒 閉じる」ボタンでチャンネルを削除し、ログに記録
"""

import re
import time

import discord
from discord import app_commands

from sub.core import bot, store, log_event, get_or_create_role, requires

CATEGORY_NAME = "🎫 チケット"

_DEFAULT_TYPES = [
    {"key": "t1", "label": "問い合わせ", "role_id": None, "category_id": None,
     "subtypes": []},
    {"key": "t2", "label": "相談", "role_id": None, "category_id": None,
     "subtypes": []},
    {"key": "t3", "label": "その他", "role_id": None, "category_id": None,
     "subtypes": []},
]

# モーダルの中にセレクトを置ける discord.py かどうか（旧版では段階式にフォールバック）
_MODAL_SELECT_OK = hasattr(discord.ui, "Label")


def ticket_settings(cfg: dict) -> dict:
    """チケット設定（なければデフォルトを入れる）"""
    tset = cfg.setdefault("ticket_settings", {})
    tset.setdefault("panel_title", "🎫 お問い合わせ・チケット")
    tset.setdefault("panel_text",
                    "困ったこと・相談は、下のメニューから種類を選んでね。\n"
                    "あなた専用のチャンネルができて、運営だけが見える場所で話せます。")
    tset.setdefault("greeting",
                    "{user} さん、問い合わせありがとうございます。\n"
                    "内容をここに書いてください。運営が対応します。\n"
                    "終わったら下のボタンで閉じてください。")
    tset.setdefault("max_open", 1)
    tset.setdefault("name_format", "user")  # user / number / type
    tset.setdefault("counter", 0)
    tset.setdefault("type_seq", 3)
    if not tset.get("types"):
        tset["types"] = [dict(t) for t in _DEFAULT_TYPES]
    for t in tset["types"]:
        t.setdefault("role_id", None)
        t.setdefault("category_id", None)
        t.setdefault("subtypes", [])
        if not isinstance(t.get("subtype_categories"), dict):
            t["subtype_categories"] = {}
    return tset


def _find_type(tset, key):
    for t in tset["types"]:
        if t["key"] == key:
            return t
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^\w\-]+", "", str(text))[:20] or "ticket"


def _channel_name(tset, ttype, user) -> str:
    fmt = tset.get("name_format", "user")
    if fmt == "number":
        return f"ticket-{int(tset.get('counter', 0)):03d}"
    if fmt == "type":
        return f"{_slug(ttype['label'])}-{user.name}"[:100]
    if fmt == "name_type":
        return f"{user.name}-{_slug(ttype['label'])}"[:100]
    return f"ticket-{user.name}"[:100]


def _open_tickets(guild, user_id):
    out = []
    for ch in guild.text_channels:
        if ch.topic and (ch.topic == f"ticket:{user_id}"
                         or ch.topic.startswith(f"ticket:{user_id}:")):
            out.append(ch)
    return out


# ---------------- パネル ----------------

def build_ticket_panel_embed(cfg: dict) -> discord.Embed:
    tset = ticket_settings(cfg)
    return discord.Embed(title=tset["panel_title"],
                         description=tset["panel_text"],
                         color=discord.Color.blurple())


class TicketPanelView(discord.ui.View):
    def __init__(self, cfg: dict = None):
        super().__init__(timeout=None)
        tset = ticket_settings(cfg) if cfg is not None else None
        if tset:
            options = [discord.SelectOption(value=t["key"], label=t["label"][:100])
                       for t in tset["types"]]
        else:
            options = [discord.SelectOption(value="none", label="チケットを作成")]
        sel = discord.ui.Select(custom_id="ticket:create",
                                placeholder="🎫 チケットの種類を選んでね",
                                options=options, row=0)

        async def _picked(interaction: discord.Interaction):
            ok = await _precheck(interaction, sel.values[0])
            if ok is None:
                return
            _cfg, tset, ttype = ok
            subtypes = ttype.get("subtypes") or []
            if subtypes and not _MODAL_SELECT_OK:
                return await interaction.response.send_message(
                    "📂 細かい種類を選んでね。",
                    view=SubTypePickView(interaction.user.id, sel.values[0],
                                         subtypes),
                    ephemeral=True)
            return await interaction.response.send_modal(
                TicketContentModal(sel.values[0],
                                   subtypes if _MODAL_SELECT_OK else None))

        sel.callback = _picked
        self.add_item(sel)


async def _precheck(interaction: discord.Interaction, type_key: str):
    """作成前のチェック。通過すれば (cfg, tset, ttype)、だめなら None。"""
    guild = interaction.guild
    cfg = store.cfg(guild.id)
    if not cfg.get("tickets_enabled", True):
        await interaction.response.send_message(
            "チケット機能は今オフだよ。", ephemeral=True)
        return None
    tset = ticket_settings(cfg)
    ttype = _find_type(tset, type_key)
    if ttype is None:
        await interaction.response.send_message(
            "⚠️ その種類は今は使えません。管理者に確認してね。", ephemeral=True)
        return None
    opened = _open_tickets(guild, interaction.user.id)
    max_open = int(tset.get("max_open", 1))
    if len(opened) >= max_open:
        mentions = " ".join(ch.mention for ch in opened)
        await interaction.response.send_message(
            f"⚠️ 開いているチケットが上限（{max_open}件）に達しています: {mentions}",
            ephemeral=True)
        return None
    return cfg, tset, ttype


class TicketContentModal(discord.ui.Modal, title="チケットの内容"):
    def __init__(self, type_key, subtypes=None, subtype=None):
        super().__init__()
        self.type_key = type_key
        self.subtype = subtype
        self.sub_label = None
        if subtypes:
            sel = discord.ui.Select(
                placeholder="細かい種類を選んでね",
                options=[discord.SelectOption(label=str(x)[:100],
                                              value=str(x)[:100])
                         for x in subtypes[:25]])
            self.sub_label = discord.ui.Label(text="細かい種類", component=sel)
            self.add_item(self.sub_label)
        self.content = discord.ui.TextInput(
            label="内容（用件を書いてね）", style=discord.TextStyle.paragraph,
            placeholder="例: 募集のやり方が分かりません", max_length=1000)
        self.add_item(self.content)

    async def on_submit(self, interaction: discord.Interaction):
        subtype = self.subtype
        if self.sub_label is not None:
            values = self.sub_label.component.values
            subtype = values[0] if values else None
        await _create_ticket(interaction, self.type_key,
                             content=str(self.content.value), subtype=subtype)


class SubTypePickView(discord.ui.View):
    """旧 discord.py 向けフォールバック: モーダルの前に細かい種類を選ぶ"""

    def __init__(self, owner_id, type_key, subtypes):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.type_key = type_key
        sel = discord.ui.Select(
            placeholder="細かい種類を選んでね",
            options=[discord.SelectOption(label=str(x)[:100], value=str(x)[:100])
                     for x in subtypes[:25]])

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の選択です。", ephemeral=True)
            await interaction.response.send_modal(
                TicketContentModal(self.type_key, subtype=sel.values[0]))

        sel.callback = _cb
        self.add_item(sel)


async def _create_ticket(interaction: discord.Interaction, type_key: str,
                         content: str = None, subtype: str = None):
    guild = interaction.guild
    checked = await _precheck(interaction, type_key)
    if checked is None:
        return
    cfg, tset, ttype = checked
    # カテゴリ（細かい種類の指定 → 種類の指定 → デフォルト名で探す/作る）
    category = None
    sub_cat_id = (ttype.get("subtype_categories") or {}).get(subtype) if subtype else None
    if sub_cat_id:
        found = guild.get_channel(int(sub_cat_id))
        if found is not None and getattr(found, "type", None) == discord.ChannelType.category:
            category = found
    if category is None and ttype.get("category_id"):
        found = guild.get_channel(int(ttype["category_id"]))
        if found is not None and getattr(found, "type", None) == discord.ChannelType.category:
            category = found
    if category is None:
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if category is None:
        try:
            category = await guild.create_category(CATEGORY_NAME)
        except discord.Forbidden:
            category = None
    # 担当ロール（種類の指定 → なければ従来の ticket_role を自動作成）
    staff_role = None
    if ttype.get("role_id"):
        staff_role = guild.get_role(int(ttype["role_id"]))
    if staff_role is None:
        staff_role = await get_or_create_role(guild, cfg.get("ticket_role", "スタッフ"))
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True),
    }
    if staff_role is not None:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True)
    if tset.get("name_format") == "number":
        tset["counter"] = int(tset.get("counter", 0)) + 1
        store.save_config()
    try:
        ch = await guild.create_text_channel(
            name=_channel_name(tset, ttype, interaction.user),
            category=category,
            topic=f"ticket:{interaction.user.id}:{ttype['key']}",
            overwrites=overwrites,
        )
    except discord.Forbidden:
        return await interaction.response.send_message(
            "❌ チャンネルを作成できませんでした（BOTの権限不足）。", ephemeral=True)
    greeting = str(tset["greeting"]).replace("{user}", interaction.user.mention)
    embed = discord.Embed(title=f"🎫 チケット（{ttype['label']}）",
                          description=greeting, color=discord.Color.blurple())
    if subtype:
        embed.add_field(name="📂 細かい種類", value=str(subtype)[:100], inline=False)
    if content:
        embed.add_field(name="📝 内容", value=content[:1024], inline=False)
    await ch.send(embed=embed, view=TicketCloseView())
    if staff_role is not None:
        await ch.send(f"{staff_role.mention} 新しいチケット（{ttype['label']}）です。")
    kind_label = ttype['label'] + (f" / {subtype}" if subtype else "")
    await log_event(guild, f"🎫 チケット作成: {ch.mention}（{kind_label}）"
                           f" by {interaction.user.mention}")
    await interaction.response.send_message(
        f"🎫 チケットを作成したよ: {ch.mention}", ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを閉じる", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        owner_id = None
        if ch.topic and ch.topic.startswith("ticket:"):
            try:
                owner_id = int(ch.topic.split(":")[1])
            except Exception:
                owner_id = None
        await interaction.response.send_message("🔒 このチケットを閉じます。チャンネルは削除されます。")
        await log_event(interaction.guild, f"🎫 チケット終了: {ch.name}（作成者: <@{owner_id}> / 閉じた人: {interaction.user.mention}）")
        try:
            await ch.delete(reason="チケット終了")
        except discord.Forbidden:
            pass


async def _refresh_panel(guild):
    cfg = store.cfg(guild.id)
    loc = (cfg.get("panels") or {}).get("tickets")
    if not loc:
        return
    ch = guild.get_channel(int(loc["channel_id"]))
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(int(loc["message_id"]))
        await msg.edit(embed=build_ticket_panel_embed(cfg),
                       view=TicketPanelView(cfg))
    except Exception:
        pass


@bot.listen("on_ready")
async def tickets_on_ready():
    for gid in list(store.configs):
        guild = bot.get_guild(int(gid))
        if guild is not None:
            await _refresh_panel(guild)


@bot.tree.command(name="setup_tickets", description="チケット受付パネルをこのチャンネルに設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_tickets(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    await interaction.response.send_message(embed=build_ticket_panel_embed(cfg),
                                            view=TicketPanelView(cfg))
    msg = await interaction.original_response()
    cfg.setdefault("panels", {})["tickets"] = {"channel_id": interaction.channel.id,
                                               "message_id": msg.id}
    store.save_config()


# ---------------- 管理者設定（セレクトメニュー式） ----------------

class _TextModal(discord.ui.Modal):
    def __init__(self, guild_id, field, label, style):
        super().__init__(title=label)
        self.guild_id = guild_id
        self.field = field
        cfg = store.cfg(guild_id)
        current = ticket_settings(cfg)[field]
        self.input = discord.ui.TextInput(label=label, style=style,
                                          default=str(current), max_length=1000)
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        ticket_settings(cfg)[self.field] = str(self.input.value)
        store.save_config()
        await _refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ 保存しました。", ephemeral=True)


class TicketSettingsView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        sel = discord.ui.Select(
            placeholder="設定する項目を選んでね",
            options=[
                discord.SelectOption(value="text", label="📝 パネルの文面",
                                     description="タイトル・説明文・挨拶文"),
                discord.SelectOption(value="types", label="🎫 チケットの種類",
                                     description="種類の追加・担当ロール・カテゴリ"),
                discord.SelectOption(value="create", label="⚙️ 作成まわりの設定",
                                     description="同時上限・チャンネル名の形式"),
            ])

        async def _picked(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            kind = sel.values[0]
            if kind == "text":
                view = TextSettingsView(self.owner_id, self.guild_id)
            elif kind == "types":
                view = TypeListView(self.owner_id, self.guild_id)
            else:
                view = CreateSettingsView(self.owner_id, self.guild_id)
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=view)

        sel.callback = _picked
        self.add_item(sel)


def settings_embed(guild_id) -> discord.Embed:
    cfg = store.cfg(guild_id)
    tset = ticket_settings(cfg)
    types = "、".join(t["label"] for t in tset["types"]) or "なし"
    fmt_name = {"user": "ticket-名前", "number": "ticket-連番",
                "type": "種類-名前", "name_type": "名前-種類"}.get(tset.get("name_format"), "ticket-名前")
    embed = discord.Embed(title="🎫 チケット設定", color=discord.Color.blurple())
    embed.add_field(name="パネルタイトル", value=str(tset["panel_title"])[:100], inline=False)
    embed.add_field(name="種類", value=types[:200], inline=False)
    embed.add_field(name="同時上限", value=f"{tset['max_open']}件", inline=True)
    embed.add_field(name="チャンネル名", value=fmt_name, inline=True)
    embed.set_footer(text="設定はサーバーごとに保存されます")
    return embed


class TextSettingsView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        for label, field, style in (
                ("タイトルを編集", "panel_title", discord.TextStyle.short),
                ("パネルの説明文を編集", "panel_text", discord.TextStyle.paragraph),
                ("チケットの挨拶文を編集", "greeting", discord.TextStyle.paragraph)):
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

            async def _cb(interaction: discord.Interaction, _f=field, _l=label, _s=style):
                if interaction.user.id != self.owner_id:
                    return await interaction.response.send_message(
                        "⚠️ これは他の人の設定画面です。", ephemeral=True)
                await interaction.response.send_modal(
                    _TextModal(self.guild_id, _f, _l, _s))

            btn.callback = _cb
            self.add_item(btn)


class TypeListView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        cfg = store.cfg(guild_id)
        tset = ticket_settings(cfg)
        options = [discord.SelectOption(value=t["key"], label=t["label"][:100],
                                        description="タップで編集")
                   for t in tset["types"]]
        sel = discord.ui.Select(placeholder="編集する種類を選んでね", options=options)

        async def _picked(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            view = TypeEditView(self.owner_id, self.guild_id, sel.values[0])
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=view)

        sel.callback = _picked
        self.add_item(sel)
        add = discord.ui.Button(label="➕ 種類を追加", style=discord.ButtonStyle.success, row=1)

        async def _add(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(_TypeAddModal(self.guild_id))

        add.callback = _add
        self.add_item(add)


class _TypeAddModal(discord.ui.Modal, title="チケットの種類を追加"):
    name = discord.ui.TextInput(label="種類の名前（例: 問い合わせ）", max_length=50)

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        tset = ticket_settings(cfg)
        seq = int(tset.get("type_seq", 3)) + 1
        tset["type_seq"] = seq
        tset["types"].append({"key": f"t{seq}", "label": str(self.name.value),
                              "role_id": None, "category_id": None, "subtypes": []})
        store.save_config()
        await _refresh_panel(interaction.guild)
        await interaction.response.send_message(
            f"✅ 種類「{self.name.value}」を追加しました。", ephemeral=True)


class _TypeRenameModal(discord.ui.Modal, title="種類の名前を変更"):
    name = discord.ui.TextInput(label="新しい名前", max_length=50)

    def __init__(self, guild_id, type_key):
        super().__init__()
        self.guild_id = guild_id
        self.type_key = type_key

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        ttype = _find_type(ticket_settings(cfg), self.type_key)
        if ttype is not None:
            ttype["label"] = str(self.name.value)
            store.save_config()
            await _refresh_panel(interaction.guild)
        await interaction.response.send_message("✅ 名前を変更しました。", ephemeral=True)


class _SubTypesModal(discord.ui.Modal, title="細かい種類を編集"):
    def __init__(self, guild_id, type_key):
        super().__init__()
        self.guild_id = guild_id
        self.type_key = type_key
        ttype = _find_type(ticket_settings(store.cfg(guild_id)), type_key) or {}
        current = "\n".join(ttype.get("subtypes") or [])
        self.input = discord.ui.TextInput(
            label="細かい種類（1行に1つ・空なら細分化なし）",
            style=discord.TextStyle.paragraph, default=current,
            required=False, max_length=1000)
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        lines = [ln.strip() for ln in str(self.input.value).splitlines()
                 if ln.strip()][:25]
        ttype = _find_type(ticket_settings(store.cfg(self.guild_id)), self.type_key)
        if ttype is not None:
            ttype["subtypes"] = lines
            mapping = ttype.get("subtype_categories") or {}
            ttype["subtype_categories"] = {
                k: v for k, v in mapping.items() if k in lines}
            store.save_config()
            await _refresh_panel(interaction.guild)
        await interaction.response.send_message(
            f"✅ 細かい種類を {len(lines)} 件に設定しました。", ephemeral=True)


class TypeEditView(discord.ui.View):
    def __init__(self, owner_id, guild_id, type_key):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.type_key = type_key
        cfg = store.cfg(guild_id)
        ttype = _find_type(ticket_settings(cfg), type_key) or {}
        role_sel = discord.ui.RoleSelect(placeholder="担当ロールを選ぶ", row=0)

        async def _role(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            t = _find_type(ticket_settings(store.cfg(self.guild_id)), self.type_key)
            if t is not None and role_sel.values:
                t["role_id"] = role_sel.values[0].id
                store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        role_sel.callback = _role
        self.add_item(role_sel)
        cat_sel = discord.ui.ChannelSelect(
            placeholder="作成先カテゴリを選ぶ",
            channel_types=[discord.ChannelType.category], row=1)

        async def _cat(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            t = _find_type(ticket_settings(store.cfg(self.guild_id)), self.type_key)
            if t is not None and cat_sel.values:
                t["category_id"] = cat_sel.values[0].id
                store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        cat_sel.callback = _cat
        self.add_item(cat_sel)
        rename = discord.ui.Button(label="✏️ 名前を変更", style=discord.ButtonStyle.primary, row=2)

        async def _rename(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(
                _TypeRenameModal(self.guild_id, self.type_key))

        rename.callback = _rename
        self.add_item(rename)
        clear = discord.ui.Button(label="担当ロール/カテゴリを未指定に戻す",
                                  style=discord.ButtonStyle.secondary, row=2)

        async def _clear(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            t = _find_type(ticket_settings(store.cfg(self.guild_id)), self.type_key)
            if t is not None:
                t["role_id"] = None
                t["category_id"] = None
                store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        clear.callback = _clear
        self.add_item(clear)
        subs = discord.ui.Button(label="📂 細かい種類を編集",
                                 style=discord.ButtonStyle.primary, row=3)

        async def _subs(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(
                _SubTypesModal(self.guild_id, self.type_key))

        subs.callback = _subs
        self.add_item(subs)
        delete = discord.ui.Button(label="🗑 この種類を削除", style=discord.ButtonStyle.danger, row=3)

        async def _delete(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            tset = ticket_settings(store.cfg(self.guild_id))
            if len(tset["types"]) <= 1:
                return await interaction.response.send_message(
                    "⚠️ 種類は最低1つ必要です。", ephemeral=True)
            tset["types"] = [t for t in tset["types"] if t["key"] != self.type_key]
            store.save_config()
            await _refresh_panel(interaction.guild)
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id),
                view=TypeListView(self.owner_id, self.guild_id))

        delete.callback = _delete
        self.add_item(delete)
        subplace = discord.ui.Button(label="📍 細かい種類の作成場所",
                                     style=discord.ButtonStyle.primary, row=4)

        async def _subplace(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            t = _find_type(ticket_settings(store.cfg(self.guild_id)),
                           self.type_key) or {}
            if not (t.get("subtypes") or []):
                return await interaction.response.send_message(
                    "⚠️ 先に「📂 細かい種類を編集」で細かい種類を登録してね。",
                    ephemeral=True)
            await interaction.response.send_message(
                "📍 作成場所を設定する細かい種類を選んでね。",
                view=SubtypePlaceView(self.owner_id, self.guild_id, self.type_key),
                ephemeral=True)

        subplace.callback = _subplace
        self.add_item(subplace)
        note = f"編集中: {ttype.get('label', '?')}"
        self._note = note


class SubtypePlaceView(discord.ui.View):
    """細かい種類を選んで、その作成場所を設定する画面へ進む"""

    def __init__(self, owner_id, guild_id, type_key):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.type_key = type_key
        ttype = _find_type(ticket_settings(store.cfg(guild_id)), type_key) or {}
        mapping = ttype.get("subtype_categories") or {}
        options = []
        for name in (ttype.get("subtypes") or [])[:25]:
            cid = mapping.get(name)
            options.append(discord.SelectOption(
                label=str(name)[:100], value=str(name)[:100],
                description=f"作成場所ID: {cid}" if cid else "作成場所: 未設定"))
        sel = discord.ui.Select(placeholder="細かい種類を選んでね", options=options)

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_message(
                f"📍 「{sel.values[0]}」の作成場所（カテゴリ）を選んでね。",
                view=SubtypePlacePickView(self.owner_id, self.guild_id,
                                          self.type_key, sel.values[0]),
                ephemeral=True)

        sel.callback = _cb
        self.add_item(sel)


class SubtypePlacePickView(discord.ui.View):
    """選んだ細かい種類に作成先カテゴリを割り当てる画面"""

    def __init__(self, owner_id, guild_id, type_key, subtype):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.type_key = type_key
        self.subtype = subtype
        cat_sel = discord.ui.ChannelSelect(
            placeholder="作成先カテゴリを選んでね",
            channel_types=[discord.ChannelType.category], min_values=1, max_values=1)

        async def _pick(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            ttype = _find_type(ticket_settings(store.cfg(self.guild_id)),
                               self.type_key)
            if ttype is not None:
                mapping = ttype.get("subtype_categories") or {}
                mapping[self.subtype] = cat_sel.values[0].id
                ttype["subtype_categories"] = mapping
                store.save_config()
            await interaction.response.edit_message(
                content=f"✅ 「{self.subtype}」の作成場所を"
                        f"「{cat_sel.values[0].name}」に設定しました。",
                view=None)

        cat_sel.callback = _pick
        self.add_item(cat_sel)
        clear = discord.ui.Button(label="この細かい種類の場所をクリア",
                                  style=discord.ButtonStyle.secondary)

        async def _clear(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            ttype = _find_type(ticket_settings(store.cfg(self.guild_id)),
                               self.type_key)
            if ttype is not None:
                mapping = ttype.get("subtype_categories") or {}
                mapping.pop(self.subtype, None)
                ttype["subtype_categories"] = mapping
                store.save_config()
            await interaction.response.edit_message(
                content=f"✅ 「{self.subtype}」の作成場所をクリアしました。",
                view=None)

        clear.callback = _clear
        self.add_item(clear)


class CreateSettingsView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        max_sel = discord.ui.Select(
            placeholder="1人あたりの同時チケット上限",
            options=[discord.SelectOption(value=str(n), label=f"{n}件まで")
                     for n in (1, 2, 3, 4, 5)], row=0)

        async def _max(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            ticket_settings(store.cfg(self.guild_id))["max_open"] = int(max_sel.values[0])
            store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        max_sel.callback = _max
        self.add_item(max_sel)
        fmt_sel = discord.ui.Select(
            placeholder="チャンネル名の形式",
            options=[
                discord.SelectOption(value="user", label="ticket-名前",
                                     description="例: ticket-taro"),
                discord.SelectOption(value="number", label="ticket-連番",
                                     description="例: ticket-001"),
                discord.SelectOption(value="type", label="種類-名前",
                                     description="例: 問い合わせ-taro"),
                discord.SelectOption(value="name_type", label="名前-種類",
                                     description="例: taro-問い合わせ"),
            ], row=1)

        async def _fmt(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            ticket_settings(store.cfg(self.guild_id))["name_format"] = fmt_sel.values[0]
            store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        fmt_sel.callback = _fmt
        self.add_item(fmt_sel)



@bot.tree.command(name="ticket_settings", description="チケットの設定（文面・種類・作成まわり）（管理者用）")
@requires(administrator=True)
async def cmd_ticket_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=settings_embed(interaction.guild.id),
        view=TicketSettingsView(interaction.user.id, interaction.guild.id),
        ephemeral=True)
