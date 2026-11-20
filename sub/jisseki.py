"""サブBOT: 実績の記入パネル (sub/jisseki.py)

- /setup_jisseki: このチャンネルに実績パネルを設置（管理者用）
- /jisseki_settings: 項目・入力欄・文面・記録先の設定（管理者用、セレクトメニュー式）
- パネルで項目を選ぶ → モーダル記入 → 記録先チャンネルへ embed 投稿 + ユーザーごとに集計
- 自動置き直し: パネル設置チャンネルに新しいメッセージが来たら即座に、
  パネルを削除して一番下に再投稿する（会話に埋もれないように）
- 項目ごとにモーダルの入力欄（ラベル/短文・長文/必須・任意）を設定から増やせる
"""
import asyncio
import copy
import datetime as dt

import discord
from discord import app_commands

from sub.core import bot, store, requires, log_event

try:
    from sub.core import features_enabled
except ImportError:  # デプロイ側 core.py が旧版でも落ちないように
    def features_enabled(_guild_id):
        return True

from sub.userdata import utility

JST = dt.timezone(dt.timedelta(hours=9))
MAX_FIELDS = 5  # Discord のモーダル上限
RECORDS_KEEP = 500

_DEFAULT_ITEMS = [
    {"key": "i1", "label": "🏆 勝利・ドン勝", "fields": [
        {"label": "キル数", "style": "short", "required": True,
         "placeholder": "例: 12"},
        {"label": "メモ", "style": "long", "required": False,
         "placeholder": "一言メモ（任意）"}]},
    {"key": "i2", "label": "🎖 ランク到達", "fields": [
        {"label": "到達ランク", "style": "short", "required": True,
         "placeholder": "例: ダイヤモンド"},
        {"label": "メモ", "style": "long", "required": False,
         "placeholder": "一言メモ（任意）"}]},
]


def jisseki_settings(cfg: dict) -> dict:
    jset = cfg.setdefault("jisseki_settings", {})
    jset.setdefault("panel_title", "🏆 実績の記入")
    jset.setdefault("panel_text",
                    "達成した実績は、下のメニューから項目を選んで記入してね。\n"
                    "記入した内容は記録用チャンネルに残ります。")
    jset.setdefault("log_channel_id", None)
    jset.setdefault("post_title", "🏆 実績記録：{item}")
    jset.setdefault("item_seq", len(_DEFAULT_ITEMS))
    if not jset.get("items"):
        jset["items"] = copy.deepcopy(_DEFAULT_ITEMS)
    for item in jset["items"]:
        item.setdefault("fields", [])
    return jset


def _find_item(jset, key):
    for item in jset.get("items", []):
        if item["key"] == key:
            return item
    return None


# ---------------- 記録と集計 ----------------

def _records_all() -> dict:
    return utility.data.setdefault("jisseki_records", {})


def _stats_all() -> dict:
    return utility.data.setdefault("jisseki_stats", {})


def _add_record(guild_id, user_id, item, values: dict):
    gid, uid = str(guild_id), str(user_id)
    records = _records_all().setdefault(gid, [])
    records.append({
        "user": uid, "item_key": item["key"], "item_label": item["label"],
        "values": values, "ts": dt.datetime.now(JST).isoformat(timespec="seconds"),
    })
    del records[:-RECORDS_KEEP]
    stats = _stats_all().setdefault(gid, {}).setdefault(
        uid, {}).setdefault(item["key"], {"count": 0, "sums": {}})
    stats["count"] += 1
    for label, value in values.items():
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            stats["sums"][label] = stats["sums"].get(label, 0) + int(text)
    utility.save()


def _record_embed(user, item, values, jset=None) -> discord.Embed:
    """記入内容そのままの形式（タイトルだけ設定で変更可、全欄を入力順に表示）"""
    template = (jset or {}).get("post_title") or "🏆 実績記録：{item}"
    title = template.replace("{item}", item["label"]).replace(
        "{user}", user.display_name)
    embed = discord.Embed(title=title[:256], color=discord.Color.gold())
    embed.add_field(name="依頼者", value=user.mention, inline=False)
    for label, value in values.items():
        text = str(value).strip()
        embed.add_field(name=label, value=text[:1024] if text else "（未記入）",
                        inline=False)
    now = dt.datetime.now(JST)
    embed.set_footer(text=f"記録日時: {now.strftime('%Y/%m/%d %H:%M')}")
    return embed


async def _post_record(interaction, item, values):
    guild = interaction.guild
    jset = jisseki_settings(store.cfg(guild.id))
    target = None
    if jset.get("log_channel_id"):
        target = guild.get_channel(int(jset["log_channel_id"]))
    if target is None:
        loc = store.cfg(guild.id).get("panels", {}).get("jisseki") or {}
        if loc.get("channel_id"):
            target = guild.get_channel(int(loc["channel_id"]))
    if target is None:
        target = interaction.channel
    posted = False
    if target is not None:
        try:
            await target.send(
                embed=_record_embed(interaction.user, item, values, jset))
            posted = True
        except discord.HTTPException:
            pass
    await log_event(guild, f"🏆 実績記録: {item['label']} by {interaction.user.mention}")
    # 記録先がパネルと同じチャンネルなら、投稿の直後にパネルを一番下へ置き直す
    # （記録の投稿は bot 自身の投稿なので、通常のメッセージ検知では対象外のため）
    if posted and target is not None:
        loc = store.cfg(guild.id).get("panels", {}).get("jisseki") or {}
        if (loc.get("channel_id") and int(loc["channel_id"]) == target.id
                and features_enabled(guild.id)):
            asyncio.ensure_future(_repost_now(guild))


# ---------------- パネル ----------------

def build_panel_embed(cfg: dict) -> discord.Embed:
    jset = jisseki_settings(cfg)
    return discord.Embed(title=jset["panel_title"],
                         description=jset["panel_text"],
                         color=discord.Color.gold())


class JissekiPanelView(discord.ui.View):
    def __init__(self, cfg=None):
        super().__init__(timeout=None)
        jset = jisseki_settings(cfg) if cfg is not None else None
        items = jset["items"] if jset else []
        if items:
            options = [discord.SelectOption(value=i["key"], label=i["label"][:100])
                       for i in items[:25]]
        else:
            options = [discord.SelectOption(value="__refresh", label="🏆 実績を記録する")]
        sel = discord.ui.Select(custom_id="jisseki:record",
                                placeholder="🏆 記入する実績を選んでね",
                                options=options, row=0)

        async def _picked(interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None:
                return
            if not features_enabled(guild.id):
                return await interaction.response.send_message(
                    "⚠️ このサーバーでは今オフになっています。", ephemeral=True)
            cfg_now = store.cfg(guild.id)
            jset_now = jisseki_settings(cfg_now)
            if sel.values[0] == "__refresh":
                return await interaction.response.send_message(
                    "🏆 記入する実績を選んでね。",
                    view=JissekiPickView(interaction.user.id, jset_now),
                    ephemeral=True)
            item = _find_item(jset_now, sel.values[0])
            if item is None:
                return await interaction.response.send_message(
                    "⚠️ その項目は今は使えません。管理者に確認してね。", ephemeral=True)
            await interaction.response.send_modal(RecordModal(item))

        sel.callback = _picked
        self.add_item(sel)
        total = discord.ui.Button(custom_id="jisseki:server", label="📊 鯖の総実績",
                                  style=discord.ButtonStyle.secondary, row=1)

        async def _total(interaction: discord.Interaction):
            await _send_server_stats(interaction)

        total.callback = _total
        self.add_item(total)


class JissekiPickView(discord.ui.View):
    """パネル再構築時などに使う、その場限りの項目セレクト"""

    def __init__(self, owner_id, jset):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        sel = discord.ui.Select(
            placeholder="🏆 記入する実績を選んでね",
            options=[discord.SelectOption(value=i["key"], label=i["label"][:100])
                     for i in jset["items"][:25]] or
                    [discord.SelectOption(value="none", label="（項目がありません）")])

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の選択です。", ephemeral=True)
            item = _find_item(jisseki_settings(store.cfg(interaction.guild.id)),
                              sel.values[0])
            if item is None:
                return await interaction.response.send_message(
                    "⚠️ その項目は今は使えません。", ephemeral=True)
            await interaction.response.send_modal(RecordModal(item))

        sel.callback = _cb
        self.add_item(sel)


class RecordModal(discord.ui.Modal):
    def __init__(self, item):
        super().__init__(title=f"実績の記入：{item['label']}"[:45])
        self.item = item
        self.inputs = []
        fields = (item.get("fields") or [])[:MAX_FIELDS]
        if not fields:
            fields = [{"label": "内容", "style": "long", "required": True,
                       "placeholder": ""}]
        for f in fields:
            ti = discord.ui.TextInput(
                label=str(f["label"])[:45],
                style=(discord.TextStyle.paragraph if f.get("style") == "long"
                       else discord.TextStyle.short),
                required=bool(f.get("required", True)),
                placeholder=str(f.get("placeholder") or "")[:100] or None,
                max_length=1000 if f.get("style") == "long" else 200)
            self.inputs.append((f["label"], ti))
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction):
        values = {label: str(ti.value) for label, ti in self.inputs}
        _add_record(interaction.guild.id, interaction.user.id, self.item, values)
        await _post_record(interaction, self.item, values)
        await interaction.response.send_message(
            f"✅ 「{self.item['label']}」を記録しました！", ephemeral=True)


async def _send_server_stats(interaction: discord.Interaction):
    guild = interaction.guild
    jset = jisseki_settings(store.cfg(guild.id))
    guild_stats = _stats_all().get(str(guild.id), {})
    embed = discord.Embed(title=f"📊 {guild.name} の総実績",
                          color=discord.Color.gold())
    if not guild_stats:
        embed.description = "まだ記録がありません。パネルから記入してね。"
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    lines = []
    total_records = 0
    for item in jset["items"]:
        count = 0
        users = 0
        sums: dict = {}
        for ustats in guild_stats.values():
            st = ustats.get(item["key"])
            if not st:
                continue
            count += int(st.get("count", 0))
            users += 1
            for label, total in (st.get("sums") or {}).items():
                sums[label] = sums.get(label, 0) + int(total)
        if count == 0:
            continue
        total_records += count
        line = f"{item['label']}: **{count}回**（{users}人）"
        for label, total in sums.items():
            line += f" / {label} 合計 {total}"
        lines.append(line)
    if lines:
        embed.description = f"合計 **{total_records}件** の記録\n" + "\n".join(lines)
    else:
        embed.description = "まだ記録がありません。パネルから記入してね。"
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------- 自動置き直し ----------------



def _panel_loc(cfg: dict) -> dict:
    return cfg.setdefault("panels", {}).setdefault("jisseki", {})


async def _repost_panel(guild):
    cfg = store.cfg(guild.id)
    loc = _panel_loc(cfg)
    if not loc.get("channel_id"):
        return
    channel = guild.get_channel(int(loc["channel_id"]))
    if channel is None:
        return
    if loc.get("message_id"):
        try:
            old = await channel.fetch_message(int(loc["message_id"]))
            await old.delete()
        except (discord.NotFound, discord.HTTPException):
            pass
    msg = await channel.send(embed=build_panel_embed(cfg),
                             view=JissekiPanelView(cfg))
    loc["message_id"] = msg.id
    store.save_config()


_repost_locks: dict = {}
_repost_dirty: set = set()


async def _repost_now(guild):
    """即時置き直し。同時に来たメッセージは1回にまとめる（ロック＋再実行フラグ）"""
    lock = _repost_locks.setdefault(guild.id, asyncio.Lock())
    if lock.locked():
        _repost_dirty.add(guild.id)
        return
    async with lock:
        while True:
            _repost_dirty.discard(guild.id)
            await _repost_panel(guild)
            if guild.id not in _repost_dirty:
                break


@bot.listen("on_message")
async def jisseki_on_message(message: discord.Message):
    if message.guild is None or bot.user is None:
        return
    if message.author.id == bot.user.id:
        return  # 自分の投稿（パネル・記録embed）では数え直さない
    cfg = store.cfg(message.guild.id)
    loc = cfg.get("panels", {}).get("jisseki") or {}
    if not loc.get("channel_id"):
        return
    if int(loc["channel_id"]) != message.channel.id:
        return
    if loc.get("message_id") and int(loc["message_id"]) == message.id:
        return
    if not features_enabled(message.guild.id):
        return
    asyncio.ensure_future(_repost_now(message.guild))


@bot.listen("on_ready")
async def jisseki_on_ready():
    for guild in bot.guilds:
        cfg = store.cfg(guild.id)
        loc = cfg.get("panels", {}).get("jisseki") or {}
        if not loc.get("channel_id") or not loc.get("message_id"):
            continue
        channel = guild.get_channel(int(loc["channel_id"]))
        if channel is None:
            continue
        try:
            msg = await channel.fetch_message(int(loc["message_id"]))
            await msg.edit(embed=build_panel_embed(cfg), view=JissekiPanelView(cfg))
        except discord.NotFound:
            msg = await channel.send(embed=build_panel_embed(cfg),
                                     view=JissekiPanelView(cfg))
            loc["message_id"] = msg.id
            store.save_config()
        except discord.HTTPException:
            pass


# ---------------- 設定（管理者用・セレクトメニュー式） ----------------

def settings_embed(guild_id) -> discord.Embed:
    cfg = store.cfg(guild_id)
    jset = jisseki_settings(cfg)
    embed = discord.Embed(title="🏆 実績パネルの設定", color=discord.Color.gold())
    embed.add_field(name="パネルタイトル", value=jset["panel_title"], inline=False)
    embed.add_field(name="項目数", value=f"{len(jset['items'])}件", inline=True)
    embed.add_field(name="送信タイトル", value=jset.get("post_title") or "-", inline=True)
    log_ch = jset.get("log_channel_id")
    embed.add_field(name="記録の投稿先",
                    value=f"<#{log_ch}>" if log_ch else "パネルのチャンネル", inline=True)
    names = "、".join(i["label"] for i in jset["items"]) or "（なし）"
    embed.add_field(name="項目", value=names[:1000], inline=False)
    return embed


async def _refresh_installed_panel(guild):
    cfg = store.cfg(guild.id)
    loc = cfg.get("panels", {}).get("jisseki") or {}
    if not loc.get("channel_id") or not loc.get("message_id"):
        return
    channel = guild.get_channel(int(loc["channel_id"]))
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(int(loc["message_id"]))
        await msg.edit(embed=build_panel_embed(cfg), view=JissekiPanelView(cfg))
    except discord.HTTPException:
        pass


class JissekiSettingsView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        sel = discord.ui.Select(
            placeholder="設定する項目を選んでね",
            options=[
                discord.SelectOption(value="text", label="📝 文面・パネル",
                                     description="タイトルと説明文"),
                discord.SelectOption(value="items", label="🎯 実績の項目",
                                     description="項目とモーダルの入力欄"),
                discord.SelectOption(value="logch", label="📍 記録の投稿先",
                                     description="記録embedを送るチャンネル"),
            ])

        async def _picked(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            kind = sel.values[0]
            if kind == "text":
                view = JTextSettingsView(self.owner_id, self.guild_id)
            elif kind == "items":
                view = JItemListView(self.owner_id, self.guild_id)
            else:
                view = JLogChannelView(self.owner_id, self.guild_id)
            await interaction.response.send_message(
                embed=settings_embed(self.guild_id), view=view, ephemeral=True)

        sel.callback = _picked
        self.add_item(sel)


class _JTextModal(discord.ui.Modal):
    def __init__(self, guild_id, field, title, style, required=True):
        super().__init__(title=title)
        self.guild_id = guild_id
        self.field = field
        current = jisseki_settings(store.cfg(guild_id))[field]
        self.input = discord.ui.TextInput(label=title, style=style,
                                          default=str(current), max_length=1500,
                                          required=required)
        self.add_item(self.input)

    async def on_submit(self, interaction: discord.Interaction):
        jisseki_settings(store.cfg(self.guild_id))[self.field] = str(self.input.value)
        store.save_config()
        await _refresh_installed_panel(interaction.guild)
        await interaction.response.send_message("✅ 保存しました。", ephemeral=True)


class JTextSettingsView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        for label, field, style in (
                ("📝 パネルタイトルを編集", "panel_title", discord.TextStyle.short),
                ("📄 パネル説明文を編集", "panel_text", discord.TextStyle.paragraph),
                ("🏆 送信タイトルを編集", "post_title", discord.TextStyle.short)):
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)

            async def _cb(interaction: discord.Interaction, f=field, st=style, lb=label):
                if interaction.user.id != self.owner_id:
                    return await interaction.response.send_message(
                        "⚠️ これは他の人の設定画面です。", ephemeral=True)
                await interaction.response.send_modal(
                    _JTextModal(self.guild_id, f, lb.replace("を編集", ""), st))

            btn.callback = _cb
            self.add_item(btn)


class JLogChannelView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        sel = discord.ui.ChannelSelect(
            placeholder="記録の投稿先チャンネルを選ぶ",
            channel_types=[discord.ChannelType.text], min_values=1, max_values=1)

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            jisseki_settings(store.cfg(self.guild_id))["log_channel_id"] = sel.values[0].id
            store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        sel.callback = _cb
        self.add_item(sel)
        clear = discord.ui.Button(label="投稿先をパネルのチャンネルに戻す",
                                  style=discord.ButtonStyle.secondary)

        async def _clear(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            jisseki_settings(store.cfg(self.guild_id))["log_channel_id"] = None
            store.save_config()
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id), view=self)

        clear.callback = _clear
        self.add_item(clear)


class JItemListView(discord.ui.View):
    def __init__(self, owner_id, guild_id):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        jset = jisseki_settings(store.cfg(guild_id))
        options = [discord.SelectOption(value=i["key"], label=i["label"][:100],
                                        description=f"入力欄 {len(i.get('fields') or [])}件")
                   for i in jset["items"][:25]]
        sel = discord.ui.Select(placeholder="編集する項目を選んでね",
                                options=options or
                                [discord.SelectOption(value="none", label="（項目なし）")])

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            if sel.values[0] == "none":
                return await interaction.response.send_message(
                    "⚠️ 項目がありません。下のボタンから追加してね。", ephemeral=True)
            await interaction.response.send_message(
                embed=settings_embed(self.guild_id),
                view=JItemEditView(self.owner_id, self.guild_id, sel.values[0]),
                ephemeral=True)

        sel.callback = _cb
        self.add_item(sel)
        add = discord.ui.Button(label="➕ 項目を追加", style=discord.ButtonStyle.success)

        async def _add(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(_JItemAddModal(self.guild_id))

        add.callback = _add
        self.add_item(add)


class _JItemAddModal(discord.ui.Modal, title="実績の項目を追加"):
    name = discord.ui.TextInput(label="項目名", max_length=50)

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        jset = jisseki_settings(store.cfg(self.guild_id))
        jset["item_seq"] = int(jset.get("item_seq", 0)) + 1
        jset["items"].append({
            "key": f"i{jset['item_seq']}", "label": str(self.name.value),
            "fields": [{"label": "内容", "style": "long", "required": True,
                        "placeholder": ""}]})
        store.save_config()
        await _refresh_installed_panel(interaction.guild)
        await interaction.response.send_message(
            f"✅ 項目「{self.name.value}」を追加しました。入力欄は項目の編集から増やせます。",
            ephemeral=True)


class _JItemRenameModal(discord.ui.Modal, title="項目の名前を変更"):
    def __init__(self, guild_id, item_key):
        super().__init__()
        self.guild_id = guild_id
        self.item_key = item_key
        item = _find_item(jisseki_settings(store.cfg(guild_id)), item_key) or {}
        self.name = discord.ui.TextInput(label="項目名", default=item.get("label", ""),
                                         max_length=50)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        item = _find_item(jisseki_settings(store.cfg(self.guild_id)), self.item_key)
        if item is not None:
            item["label"] = str(self.name.value)
            store.save_config()
            await _refresh_installed_panel(interaction.guild)
        await interaction.response.send_message("✅ 変更しました。", ephemeral=True)


class JItemEditView(discord.ui.View):
    def __init__(self, owner_id, guild_id, item_key):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.item_key = item_key
        rename = discord.ui.Button(label="✏️ 名前を変更", style=discord.ButtonStyle.primary, row=0)

        async def _rename(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(
                _JItemRenameModal(self.guild_id, self.item_key))

        rename.callback = _rename
        self.add_item(rename)
        fields_btn = discord.ui.Button(label="🧩 入力欄を編集", style=discord.ButtonStyle.primary, row=0)

        async def _fields(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_message(
                "🧩 入力欄を選んでね。",
                view=JFieldListView(self.owner_id, self.guild_id, self.item_key),
                ephemeral=True)

        fields_btn.callback = _fields
        self.add_item(fields_btn)
        delete = discord.ui.Button(label="🗑 この項目を削除", style=discord.ButtonStyle.danger, row=1)

        async def _delete(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            jset = jisseki_settings(store.cfg(self.guild_id))
            if len(jset["items"]) <= 1:
                return await interaction.response.send_message(
                    "⚠️ 項目は最低1つ必要です。", ephemeral=True)
            jset["items"] = [i for i in jset["items"] if i["key"] != self.item_key]
            store.save_config()
            await _refresh_installed_panel(interaction.guild)
            await interaction.response.edit_message(
                embed=settings_embed(self.guild_id),
                view=JItemListView(self.owner_id, self.guild_id))

        delete.callback = _delete
        self.add_item(delete)


class JFieldListView(discord.ui.View):
    def __init__(self, owner_id, guild_id, item_key):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.item_key = item_key
        item = _find_item(jisseki_settings(store.cfg(guild_id)), item_key) or {}
        fields = item.get("fields") or []
        options = []
        for idx, f in enumerate(fields[:MAX_FIELDS]):
            kind = "長文" if f.get("style") == "long" else "短文"
            req = "必須" if f.get("required", True) else "任意"
            options.append(discord.SelectOption(
                value=str(idx), label=str(f["label"])[:100],
                description=f"{kind}・{req}"))
        sel = discord.ui.Select(
            placeholder="編集する入力欄を選んでね",
            options=options or [discord.SelectOption(value="none", label="（入力欄なし）")])

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            if sel.values[0] == "none":
                return await interaction.response.send_message(
                    "⚠️ 入力欄がありません。下のボタンから追加してね。", ephemeral=True)
            await interaction.response.send_message(
                "🧩 入力欄の編集",
                view=JFieldEditView(self.owner_id, self.guild_id, self.item_key,
                                    int(sel.values[0])),
                ephemeral=True)

        sel.callback = _cb
        self.add_item(sel)
        for label, style in (("➕ 短文の欄を追加", "short"), ("➕ 長文の欄を追加", "long")):
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.success)

            async def _add(interaction: discord.Interaction, st=style):
                if interaction.user.id != self.owner_id:
                    return await interaction.response.send_message(
                        "⚠️ これは他の人の設定画面です。", ephemeral=True)
                item_now = _find_item(jisseki_settings(store.cfg(self.guild_id)),
                                      self.item_key) or {}
                if len(item_now.get("fields") or []) >= MAX_FIELDS:
                    return await interaction.response.send_message(
                        f"⚠️ 入力欄は最大{MAX_FIELDS}件までです。", ephemeral=True)
                await interaction.response.send_modal(
                    _JFieldAddModal(self.guild_id, self.item_key, st))

            btn.callback = _add
            self.add_item(btn)


class _JFieldAddModal(discord.ui.Modal, title="入力欄を追加"):
    def __init__(self, guild_id, item_key, style):
        super().__init__()
        self.guild_id = guild_id
        self.item_key = item_key
        self.style = style
        self.label_input = discord.ui.TextInput(label="欄の名前（例: キル数）",
                                                max_length=45)
        self.hint_input = discord.ui.TextInput(
            label="入力ヒント（任意・欄の中に薄く出る文字）", required=False,
            max_length=100)
        self.add_item(self.label_input)
        self.add_item(self.hint_input)

    async def on_submit(self, interaction: discord.Interaction):
        item = _find_item(jisseki_settings(store.cfg(self.guild_id)), self.item_key)
        if item is not None:
            fields = item.setdefault("fields", [])
            if len(fields) < MAX_FIELDS:
                fields.append({"label": str(self.label_input.value),
                               "style": self.style, "required": True,
                               "placeholder": str(self.hint_input.value)})
                store.save_config()
        await interaction.response.send_message(
            "✅ 入力欄を追加しました。必須/任意は欄の編集から切り替えられます。",
            ephemeral=True)


class _JFieldRenameModal(discord.ui.Modal, title="入力欄の名前を変更"):
    def __init__(self, guild_id, item_key, idx):
        super().__init__()
        self.guild_id = guild_id
        self.item_key = item_key
        self.idx = idx
        item = _find_item(jisseki_settings(store.cfg(guild_id)), item_key) or {}
        fields = item.get("fields") or []
        current = fields[idx]["label"] if 0 <= idx < len(fields) else ""
        self.name = discord.ui.TextInput(label="欄の名前", default=current, max_length=45)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        item = _find_item(jisseki_settings(store.cfg(self.guild_id)), self.item_key)
        if item is not None and 0 <= self.idx < len(item.get("fields") or []):
            item["fields"][self.idx]["label"] = str(self.name.value)
            store.save_config()
        await interaction.response.send_message("✅ 変更しました。", ephemeral=True)


class JFieldEditView(discord.ui.View):
    def __init__(self, owner_id, guild_id, item_key, idx):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.item_key = item_key
        self.idx = idx

        def _field():
            item = _find_item(jisseki_settings(store.cfg(self.guild_id)),
                              self.item_key) or {}
            fields = item.get("fields") or []
            return fields[self.idx] if 0 <= self.idx < len(fields) else None

        rename = discord.ui.Button(label="✏️ 名前を変更", style=discord.ButtonStyle.primary, row=0)

        async def _rename(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            await interaction.response.send_modal(
                _JFieldRenameModal(self.guild_id, self.item_key, self.idx))

        rename.callback = _rename
        self.add_item(rename)
        req = discord.ui.Button(label="必須/任意を切替", style=discord.ButtonStyle.secondary, row=0)

        async def _req(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            f = _field()
            if f is not None:
                f["required"] = not bool(f.get("required", True))
                store.save_config()
                state = "必須" if f["required"] else "任意"
                return await interaction.response.send_message(
                    f"✅ この欄は「{state}」になりました。", ephemeral=True)
            await interaction.response.send_message("⚠️ 欄が見つかりません。", ephemeral=True)

        req.callback = _req
        self.add_item(req)
        style_btn = discord.ui.Button(label="短文/長文を切替", style=discord.ButtonStyle.secondary, row=0)

        async def _style(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            f = _field()
            if f is not None:
                f["style"] = "long" if f.get("style") != "long" else "short"
                store.save_config()
                kind = "長文" if f["style"] == "long" else "短文"
                return await interaction.response.send_message(
                    f"✅ この欄は「{kind}」になりました。", ephemeral=True)
            await interaction.response.send_message("⚠️ 欄が見つかりません。", ephemeral=True)

        style_btn.callback = _style
        self.add_item(style_btn)
        delete = discord.ui.Button(label="🗑 この欄を削除", style=discord.ButtonStyle.danger, row=1)

        async def _delete(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "⚠️ これは他の人の設定画面です。", ephemeral=True)
            item = _find_item(jisseki_settings(store.cfg(self.guild_id)), self.item_key)
            if item is not None and 0 <= self.idx < len(item.get("fields") or []):
                item["fields"].pop(self.idx)
                store.save_config()
            await interaction.response.edit_message(
                content="✅ 入力欄を削除しました。", view=None)

        delete.callback = _delete
        self.add_item(delete)


# ---------------- コマンド ----------------

@bot.tree.command(name="setup_jisseki", description="実績の記入パネルをこのチャンネルに設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_jisseki(interaction: discord.Interaction):
    guild = interaction.guild
    cfg = store.cfg(guild.id)
    jisseki_settings(cfg)
    loc = _panel_loc(cfg)
    if loc.get("channel_id") and loc.get("message_id"):
        old_ch = guild.get_channel(int(loc["channel_id"]))
        if old_ch is not None:
            try:
                old = await old_ch.fetch_message(int(loc["message_id"]))
                await old.delete()
            except discord.HTTPException:
                pass
    msg = await interaction.channel.send(embed=build_panel_embed(cfg),
                                         view=JissekiPanelView(cfg))
    loc["channel_id"] = interaction.channel.id
    loc["message_id"] = msg.id
    store.save_config()
    await interaction.response.send_message(
        "✅ 実績パネルを設置しました。このチャンネルでは新しいメッセージが"
        "来るたびに自動で一番下へ置き直されます。", ephemeral=True)


@bot.tree.command(name="jisseki_settings", description="実績パネルの設定（項目・入力欄・記録先）（管理者用）")
@requires(administrator=True)
async def cmd_jisseki_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=settings_embed(interaction.guild.id),
        view=JissekiSettingsView(interaction.user.id, interaction.guild.id),
        ephemeral=True)
