# -*- coding: utf-8 -*-
"""
荒野行動 公開サーバー向け Discord BOT

機能:
  - ルール同意ゲート（同意ボタンで認証ロール付与）
  - ロール選択パネル（ランク帯 / プレイスタイル / VC など、カテゴリ・ロールは設定で変更可）
  - 募集パネル（項目は設定で変更可の選択形式 + 一言コメント、参加/離脱/締め切り、自動終了）
  - ウェルカムメッセージ
  - 軽いモデレーション（NGワード自動削除、連投対策）
  - 管理者用 設定パネル（!settings）: 募集項目 / ロールカテゴリ / 認証ロール / NGワード をDiscord上で編集

セットアップ系コマンド（管理者のみ）:
  !setup_rules   … このチャンネルにルール同意パネルを設置
  !setup_roles   … このチャンネルにロール選択パネルを設置
  !setup_recruit … このチャンネルに募集パネルを設置（＝募集チャンネルとして登録）
  !setwelcome    … このチャンネルをウェルカム投稿先に設定
  !setlog        … このチャンネルをモデレーションログ先に設定
  !setup_gate    … 認証ロールでチャンネルを隠す権限設定を一括適用（README参照）
  !settings      … 設定パネルを開く
  !bothelp       … コマンド一覧

環境変数: DISCORD_TOKEN（.env ファイルでも可）
データ: 同じフォルダの config.json / recruitments.json に保存（再起動しても消えない）
"""

import os
import json
import time
import copy
import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RECRUIT_PATH = os.path.join(BASE_DIR, "recruitments.json")

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")

# ---------------- デフォルト設定（!settings で変更可能） ----------------
DEFAULT_CONFIG = {
    "verify_role": "メンバー",  # ルール同意で付けるロール名
    "welcome_channel_id": None,
    "log_channel_id": None,
    "recruit_channel_id": None,
    "recruit_expire_hours": 3,
    "ng_words": [],
    # 募集フォームの選択項目（ラベル + 選択肢）
    "recruit_fields": [
        {"label": "モード", "options": ["通常マッチ", "ランクマッチ", "カスタムマッチ", "レジャー"]},
        {"label": "VC", "options": ["VCあり", "VCなし", "どちらでも"]},
        {"label": "ランク帯", "options": ["指定なし", "ブロンズ帯", "シルバー帯", "ゴールド帯", "プラチナ帯", "ダイヤ帯", "マスター以上"]},
    ],
    # ロール選択パネルのカテゴリ（multi=False は1つだけ選べる）
    "role_categories": [
        {"label": "ランク帯", "multi": False, "roles": ["ブロンズ", "シルバー", "ゴールド", "プラチナ", "ダイヤモンド", "マスター", "キング"]},
        {"label": "プレイスタイル", "multi": False, "roles": ["エンジョイ勢", "ガチ勢"]},
        {"label": "VC", "multi": False, "roles": ["VC可", "聞き専", "VC不可"]},
    ],
    # 設置済みパネル（再起動後にボタンを復旧するため）
    "panels": {},  # {"rules": {"channel_id":..,"message_id":..}, "roles": {...}, "recruit": {...}}
}


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(default)


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Store:
    """設定と募集データの永続化"""

    def __init__(self):
        self.configs = _load_json(CONFIG_PATH, {})  # {guild_id(str): config}
        self.recruitments = _load_json(RECRUIT_PATH, {})  # {rid(str): {...}}

    def cfg(self, guild_id) -> dict:
        key = str(guild_id)
        if key not in self.configs:
            self.configs[key] = copy.deepcopy(DEFAULT_CONFIG)
            self.save_config()
        cfg = self.configs[key]
        # 旧バージョンの設定に欠けているキーを補完
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, copy.deepcopy(v))
        return cfg

    def save_config(self):
        _save_json(CONFIG_PATH, self.configs)

    def save_recruitments(self):
        _save_json(RECRUIT_PATH, self.recruitments)


store = Store()

# ---------------- BOT 本体 ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def get_or_create_role(guild: discord.Guild, name: str):
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        try:
            role = await guild.create_role(name=name, reason="BOT自動作成")
        except discord.Forbidden:
            return None
    return role


async def log_event(guild: discord.Guild, text: str):
    cfg = store.cfg(guild.id)
    ch_id = cfg.get("log_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if ch:
        try:
            await ch.send(text)
        except Exception:
            pass


# ---------------- ウェルカム ----------------
@bot.event
async def on_member_join(member: discord.Member):
    cfg = store.cfg(member.guild.id)
    ch = None
    if cfg.get("welcome_channel_id"):
        ch = member.guild.get_channel(cfg["welcome_channel_id"])
    if ch is None:
        ch = member.guild.system_channel
    if ch is None:
        return
    rules_hint = ""
    panel = cfg.get("panels", {}).get("rules")
    if panel and panel.get("channel_id"):
        rules_hint = f"\nまずは <#{panel['channel_id']}> でルールを確認して、同意ボタンを押してね。"
    try:
        await ch.send(
            f"🎉 {member.mention} さん、**{member.guild.name}** へようこそ！{rules_hint}\n"
            "ロール選択でランク帯やプレイスタイルを設定すると、募集で一緒に行く人が見つけやすくなるよ。"
        )
    except Exception:
        pass


# ---------------- モデレーション（軽め） ----------------
_recent_msgs = defaultdict(deque)  # (guild_id, user_id) -> deque[(content, ts)]


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        await bot.process_commands(message)
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

    await bot.process_commands(message)


# ---------------- ルール同意ゲート ----------------
class RulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ ルールに同意する", style=discord.ButtonStyle.success, custom_id="rules_agree")
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(interaction.guild.id)
        role = await get_or_create_role(interaction.guild, cfg["verify_role"])
        if role is None:
            await interaction.response.send_message("❌ ロールを付与できませんでした（BOTの権限不足）。管理者に連絡してください。", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("もう認証済みだよ。そのままサーバーを使ってね。", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="ルール同意")
        except discord.Forbidden:
            await interaction.response.send_message("❌ ロールを付与できませんでした（BOTより上のロールは付けられません）。管理者に連絡してください。", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ 認証完了！「{cfg['verify_role']}」ロールを付けたよ。ロール選択も済ませておくと募集で声がかかりやすくなるよ。", ephemeral=True)


def build_rules_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title=f"📜 {guild.name} のルール",
        description=(
            "参加ありがとう！サーバーを使う前に、下のルールを確認して同意ボタンを押してね。\n\n"
            "1. 誹謗中傷・暴言は禁止\n"
            "2. 宣伝・勧誘・荒らし行為は禁止\n"
            "3. 個人情報は載せない\n"
            "4. 募集のドタキャンは一言連絡を\n"
            "5. その他、みんなが気持ちよく遊べるように\n\n"
            "※ ルールの文面はこのメッセージを編集して自由に変えられます（ボタンはそのまま使えます）。"
        ),
        color=discord.Color.orange(),
    )
    return embed


# ---------------- ロール選択パネル ----------------
class RoleSelect(discord.ui.Select):
    """カテゴリ1つ分のロール選択。custom_id にカテゴリ名を持つ"""

    def __init__(self, category: dict):
        self.category_label = category["label"]
        self.multi = bool(category.get("multi"))
        options = [discord.SelectOption(label="（解除する）", value="__none__", emoji="🧹")]
        options += [discord.SelectOption(label=name, value=name) for name in category["roles"][:24]]
        super().__init__(
            placeholder=f"{category['label']} を選んでね",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"rolesel:{category['label']}",
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = store.cfg(interaction.guild.id)
        cat = next((c for c in cfg["role_categories"] if c["label"] == self.category_label), None)
        if cat is None:
            await interaction.response.send_message("⚠️ 設定が変わったみたい。新しいロールパネルを使ってね。", ephemeral=True)
            return
        member = interaction.user
        value = self.values[0]
        # 同カテゴリの他のロールを外す（このUIでは1つずつ付け外しする簡易仕様）
        for name in cat["roles"]:
            role = discord.utils.get(interaction.guild.roles, name=name)
            if role and role in member.roles and name != value:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass
        if value == "__none__":
            await interaction.response.send_message(f"🧹 「{cat['label']}」のロールを外したよ。", ephemeral=True)
            return
        role = await get_or_create_role(interaction.guild, value)
        if role is None:
            await interaction.response.send_message("❌ ロールを作成できませんでした（BOTの権限不足）。管理者に連絡してください。", ephemeral=True)
            return
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message("❌ ロールを付けられませんでした（BOTより上のロール）。管理者に連絡してください。", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ 「{cat['label']}」→ {value} を付けたよ。", ephemeral=True)


class RolePanelView(discord.ui.View):
    def __init__(self, cfg: dict):
        super().__init__(timeout=None)
        for cat in cfg["role_categories"][:5]:  # 1メッセージ最大5行まで
            self.add_item(RoleSelect(cat))


def build_roles_embed(cfg: dict) -> discord.Embed:
    lines = ["下のメニューから当てはまるものを選ぶと、自動でロールが付くよ。", ""]
    for cat in cfg["role_categories"]:
        lines.append(f"**{cat['label']}**: {' / '.join(cat['roles'])}")
    embed = discord.Embed(title="🏷️ ロール選択", description="\n".join(lines), color=discord.Color.blue())
    return embed


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

    async def _refresh(self, interaction: discord.Interaction, rec: dict):
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
        await self._refresh(interaction, rec)
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
        await self._refresh(interaction, rec)

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
        await interaction.response.edit_message(content=f"✅ 募集を投稿したよ → {msg.jump_url}", view=None)
        self.stop()


class RecruitPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 募集を作成", style=discord.ButtonStyle.primary, custom_id="recruit_create")
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitCommentModal(interaction.guild.id))


def build_recruit_embed_panel() -> discord.Embed:
    return discord.Embed(
        title="🎮 メンバー募集",
        description="一緒に遊ぶ人を募集したいときは、下のボタンから募集を作成してね。\n募集は参加ボタンで集まって、満員 or 締め切りで終了します。",
        color=discord.Color.green(),
    )


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

# ---------------- 設定パネル（管理者用） ----------------
def _parse_list(text: str):
    parts = [p.strip() for p in text.replace("、", ",").replace("\n", ",").split(",")]
    return [p for p in parts if p]


class AddFieldModal(discord.ui.Modal, title="募集項目を追加"):
    label = discord.ui.TextInput(label="項目名", max_length=30, placeholder="例: 時間帯")
    options = discord.ui.TextInput(label="選択肢（カンマ区切り）", style=discord.TextStyle.paragraph, max_length=500, placeholder="例: 今すぐ, 夜21時から, 深夜")

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        opts = _parse_list(str(self.options))[:25]
        if not opts:
            await interaction.response.send_message("選択肢が空だったよ。", ephemeral=True)
            return
        if any(f["label"] == str(self.label) for f in cfg["recruit_fields"]):
            await interaction.response.send_message("同じ名前の項目がすでにあるよ。", ephemeral=True)
            return
        cfg["recruit_fields"].append({"label": str(self.label), "options": opts})
        store.save_config()
        await interaction.response.send_message(f"✅ 募集項目「{self.label}」を追加したよ（選択肢: {', '.join(opts)}）。次の募集作成から反映されます。", ephemeral=True)


class AddCategoryModal(discord.ui.Modal, title="ロールカテゴリを追加"):
    label = discord.ui.TextInput(label="カテゴリ名", max_length=30, placeholder="例: よく遊ぶ時間帯")
    roles = discord.ui.TextInput(label="ロール名（カンマ区切り）", style=discord.TextStyle.paragraph, max_length=500, placeholder="例: 昼, 夜, 深夜")

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        names = _parse_list(str(self.roles))[:24]
        if not names:
            await interaction.response.send_message("ロール名が空だったよ。", ephemeral=True)
            return
        if any(c["label"] == str(self.label) for c in cfg["role_categories"]):
            await interaction.response.send_message("同じ名前のカテゴリがすでにあるよ。", ephemeral=True)
            return
        cfg["role_categories"].append({"label": str(self.label), "multi": False, "roles": names})
        store.save_config()
        await interaction.response.send_message(f"✅ カテゴリ「{self.label}」を追加したよ。反映するにはロールパネルを !setup_roles で再設置してね。", ephemeral=True)


class SetVerifyRoleModal(discord.ui.Modal, title="認証ロールを設定"):
    role_name = discord.ui.TextInput(label="ロール名（なければ自動作成）", max_length=50, placeholder="例: メンバー")

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        cfg["verify_role"] = str(self.role_name).strip() or cfg["verify_role"]
        store.save_config()
        await interaction.response.send_message(f"✅ 認証ロールを「{cfg['verify_role']}」にしたよ。", ephemeral=True)


class AddNgWordModal(discord.ui.Modal, title="NGワードを追加"):
    word = discord.ui.TextInput(label="NGワード", max_length=50)

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        w = str(self.word).strip()
        if w and w not in cfg["ng_words"]:
            cfg["ng_words"].append(w)
            store.save_config()
        await interaction.response.send_message(f"✅ NGワードに「{w}」を追加したよ（現在 {len(cfg['ng_words'])} 件）。", ephemeral=True)


def _delete_select(placeholder, custom_id, options, on_pick):
    sel = discord.ui.Select(placeholder=placeholder, options=options, custom_id=custom_id)

    async def _cb(interaction: discord.Interaction):
        await on_pick(interaction, interaction.data["values"][0])

    sel.callback = _cb
    view = discord.ui.View(timeout=180)
    view.add_item(sel)
    return view


class SettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=600)
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("設定は管理者だけだよ。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="募集項目を追加", style=discord.ButtonStyle.primary, row=0)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddFieldModal(self.guild_id))

    @discord.ui.button(label="募集項目を削除", style=discord.ButtonStyle.secondary, row=0)
    async def del_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg["recruit_fields"]:
            await interaction.response.send_message("募集項目は今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            cfg2["recruit_fields"] = [f for f in cfg2["recruit_fields"] if f["label"] != value]
            store.save_config()
            await inter.response.send_message(f"🗑️ 募集項目「{value}」を削除したよ。", ephemeral=True)

        opts = [discord.SelectOption(label=f["label"], value=f["label"]) for f in cfg["recruit_fields"]]
        await interaction.response.send_message("削除する項目を選んでね:", view=_delete_select("項目を選ぶ", "del_field", opts, _pick), ephemeral=True)

    @discord.ui.button(label="ロールカテゴリを追加", style=discord.ButtonStyle.primary, row=1)
    async def add_cat(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddCategoryModal(self.guild_id))

    @discord.ui.button(label="ロールカテゴリを削除", style=discord.ButtonStyle.secondary, row=1)
    async def del_cat(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg["role_categories"]:
            await interaction.response.send_message("カテゴリは今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            cfg2["role_categories"] = [c for c in cfg2["role_categories"] if c["label"] != value]
            store.save_config()
            await inter.response.send_message(f"🗑️ カテゴリ「{value}」を削除したよ。反映には !setup_roles でパネル再設置を。", ephemeral=True)

        opts = [discord.SelectOption(label=c["label"], value=c["label"]) for c in cfg["role_categories"]]
        await interaction.response.send_message("削除するカテゴリを選んでね:", view=_delete_select("カテゴリを選ぶ", "del_cat", opts, _pick), ephemeral=True)

    @discord.ui.button(label="認証ロールを設定", style=discord.ButtonStyle.primary, row=2)
    async def set_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetVerifyRoleModal(self.guild_id))

    @discord.ui.button(label="NGワードを追加", style=discord.ButtonStyle.secondary, row=2)
    async def add_ng(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddNgWordModal(self.guild_id))

    @discord.ui.button(label="現在の設定を表示", style=discord.ButtonStyle.secondary, row=3)
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        lines = [f"認証ロール: **{cfg['verify_role']}**", f"募集の自動終了: {cfg['recruit_expire_hours']}時間", "", "**募集項目**"]
        for f in cfg["recruit_fields"]:
            lines.append(f"- {f['label']}: {' / '.join(f['options'])}")
        lines.append("")
        lines.append("**ロールカテゴリ**")
        for c in cfg["role_categories"]:
            lines.append(f"- {c['label']}: {' / '.join(c['roles'])}")
        lines.append("")
        lines.append(f"**NGワード**: {len(cfg['ng_words'])} 件")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


def build_settings_embed(cfg: dict) -> discord.Embed:
    return discord.Embed(
        title="⚙️ BOT設定（管理者用）",
        description="募集項目・ロールカテゴリ・認証ロール・NGワードをここから変更できます。\n変更はその場で保存され、再起動は不要です。",
        color=discord.Color.purple(),
    )


# ---------------- セットアップ系コマンド ----------------
def _admin():
    return commands.has_permissions(administrator=True)


@bot.command(name="settings")
@_admin()
async def cmd_settings(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    await ctx.send(embed=build_settings_embed(cfg), view=SettingsView(ctx.guild.id))


@bot.command(name="setup_rules")
@_admin()
async def cmd_setup_rules(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    msg = await ctx.send(embed=build_rules_embed(ctx.guild), view=RulesView())
    cfg["panels"]["rules"] = {"channel_id": ctx.channel.id, "message_id": msg.id}
    store.save_config()
    await ctx.send("✅ ルール同意パネルを設置しました。文面はこのメッセージを編集すれば変えられます。", delete_after=15)


@bot.command(name="setup_roles")
@_admin()
async def cmd_setup_roles(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    view = RolePanelView(cfg)
    msg = await ctx.send(embed=build_roles_embed(cfg), view=view)
    cfg["panels"]["roles"] = {"channel_id": ctx.channel.id, "message_id": msg.id}
    store.save_config()
    await ctx.send("✅ ロール選択パネルを設置しました。", delete_after=15)


@bot.command(name="setup_recruit")
@_admin()
async def cmd_setup_recruit(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    cfg["recruit_channel_id"] = ctx.channel.id
    msg = await ctx.send(embed=build_recruit_embed_panel(), view=RecruitPanelView())
    cfg["panels"]["recruit"] = {"channel_id": ctx.channel.id, "message_id": msg.id}
    store.save_config()
    await ctx.send("✅ 募集パネルを設置し、このチャンネルを募集チャンネルに登録しました。", delete_after=15)


@bot.command(name="setwelcome")
@_admin()
async def cmd_setwelcome(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    cfg["welcome_channel_id"] = ctx.channel.id
    store.save_config()
    await ctx.send("✅ このチャンネルをウェルカム投稿先にしました。", delete_after=10)


@bot.command(name="setlog")
@_admin()
async def cmd_setlog(ctx: commands.Context):
    cfg = store.cfg(ctx.guild.id)
    cfg["log_channel_id"] = ctx.channel.id
    store.save_config()
    await ctx.send("✅ このチャンネルをモデレーションログ先にしました。", delete_after=10)


@bot.command(name="setup_gate")
@_admin()
async def cmd_setup_gate(ctx: commands.Context):
    """認証ロールを持たない人に、ルールチャンネル以外を見せない権限設定を一括適用する"""
    cfg = store.cfg(ctx.guild.id)
    guild = ctx.guild
    role = await get_or_create_role(guild, cfg["verify_role"])
    if role is None:
        await ctx.send("❌ 認証ロールを作成できませんでした（BOTにロール管理権限が必要です）。")
        return
    rules_panel = cfg.get("panels", {}).get("rules", {})
    rules_ch_id = rules_panel.get("channel_id")
    done, skipped = 0, 0
    everyone = guild.default_role
    for ch in guild.channels:
        if ch.id == rules_ch_id:
            continue
        try:
            ow = ch.overwrites
            ow[everyone] = discord.PermissionOverwrite(view_channel=False)
            ow[role] = discord.PermissionOverwrite(view_channel=True)
            ow[guild.me] = discord.PermissionOverwrite(view_channel=True)
            await ch.edit(overwrites=ow)
            done += 1
        except Exception:
            skipped += 1
    await ctx.send(
        f"🔒 ゲート設定を適用しました（{done} チャンネル、失敗 {skipped}）。\n"
        "ルールチャンネルだけは全員が見える状態のままです。新しいチャンネルを作った場合は、そのチャンネルでも同じ設定をしてください。"
    )


@bot.command(name="bothelp")
async def cmd_help(ctx: commands.Context):
    embed = discord.Embed(title="🤖 コマンド一覧", color=discord.Color.blurple())
    embed.add_field(
        name="管理者用セットアップ",
        value=(
            "`!setup_rules` ルール同意パネル設置\n"
            "`!setup_roles` ロール選択パネル設置\n"
            "`!setup_recruit` 募集パネル設置\n"
            "`!setwelcome` / `!setlog` 投稿先チャンネル設定\n"
            "`!setup_gate` 認証ゲートの権限を一括適用\n"
            "`!settings` 設定パネル（項目・ロール・NGワード編集）"
        ),
        inline=False,
    )
    embed.add_field(name="使い方", value="募集は募集パネルのボタンから。ロールはロール選択パネルから付けられます。", inline=False)
    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("そのコマンドは管理者だけだよ。", delete_after=10)
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"command error: {error}")


# ---------------- 起動・復旧 ----------------
@bot.event
async def on_ready():
    print(f"ログイン完了: {bot.user} (ID: {bot.user.id})")
    # 設置済みパネルのボタンを復旧
    bot.add_view(RulesView())
    bot.add_view(RecruitPanelView())
    for gid, cfg in store.configs.items():
        panels = cfg.get("panels", {})
        if "roles" in panels:
            try:
                bot.add_view(RolePanelView(cfg), message_id=panels["roles"]["message_id"])
            except Exception as e:
                print(f"ロールパネル復旧失敗 guild={gid}: {e}")
    # 進行中の募集カードのボタンを復旧
    for rid, rec in store.recruitments.items():
        if rec.get("status") == "open" and rec.get("message_id"):
            try:
                bot.add_view(RecruitCardView(rid), message_id=rec["message_id"])
            except Exception as e:
                print(f"募集カード復旧失敗 rid={rid}: {e}")
    if not expire_recruitments.is_running():
        expire_recruitments.start()
    print("------ 荒野行動サーバーBOT 起動完了 ------")


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN が設定されていません。.env ファイルか環境変数に設定してください。")
        raise SystemExit(1)
    bot.run(TOKEN)
