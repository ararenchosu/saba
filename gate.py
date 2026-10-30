# -*- coding: utf-8 -*-
"""
gate.py — 入口まわり: ウェルカム / ルール同意ゲート / ロール選択パネル / ゲート権限設定
"""

import discord
from discord import app_commands
from discord.ext import commands

from core import bot, store, get_or_create_role

# ---------------- ウェルカム ----------------
@bot.listen("on_member_join")
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
    cfg = store.cfg(guild.id)
    embed = discord.Embed(
        title=f"📜 {guild.name} のルール",
        description=cfg.get("rules_text") or "",
        color=discord.Color.orange(),
    )
    return embed


async def refresh_rules_panel(guild: discord.Guild) -> bool:
    """設置済みのルール同意パネルの文章を、現在の設定で書き換える。成功したら True"""
    cfg = store.cfg(guild.id)
    panel = cfg.get("panels", {}).get("rules")
    if not panel:
        return False
    ch = guild.get_channel(panel.get("channel_id"))
    if ch is None:
        return False
    try:
        msg = await ch.fetch_message(panel["message_id"])
        await msg.edit(embed=build_rules_embed(guild))  # ボタンはそのまま残る
        return True
    except Exception:
        return False


# ---------------- ロール選択パネル ----------------
class RoleSelect(discord.ui.Select):
    """カテゴリ1つ分のロール選択（1つだけ選択可）。
    選び直すと同じカテゴリの前のロールと付け替えになる。外すときはパネルのボタンから。"""

    def __init__(self, category: dict):
        self.category_label = category["label"]
        options = [discord.SelectOption(label=name, value=name) for name in category["roles"][:25]]
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
        # 1回限りロールのチェック: 取得済みで今付けていない人は再取得できない
        if value in cat.get("once_roles", []):
            claimed = cfg.get("claimed_once", {})
            if member.id in claimed.get(value, []):
                held = discord.utils.get(interaction.guild.roles, name=value)
                if held is None or held not in member.roles:
                    await interaction.response.send_message(f"⚠️ 「{value}」は1回限りのロールで、あなたは取得済みだよ。", ephemeral=True)
                    return
        # 「どれか1つだけ」カテゴリ: 過去に別ロールを取得していたら他のロールは取得不可
        if cat.get("exclusive_once"):
            claimed_map = cfg.get("claimed_once", {})
            past = [n for n in cat["roles"] if member.id in claimed_map.get(n, [])]
            if past and value not in past:
                await interaction.response.send_message(f"⚠️ 「{cat['label']}」はどれか1つだけ取得できて、あなたは「{past[0]}」を取得済みだよ。他のロールは取得できません。", ephemeral=True)
                return
            if not past:
                # 履歴がなくても、今カテゴリ内の別ロールを付けていれば付け替え不可
                for n in cat["roles"]:
                    if n == value:
                        continue
                    r = discord.utils.get(interaction.guild.roles, name=n)
                    if r and r in member.roles:
                        await interaction.response.send_message(f"⚠️ 「{cat['label']}」はどれか1つだけだよ。すでに「{n}」を付けているので変更できません。", ephemeral=True)
                        return
        role = await get_or_create_role(interaction.guild, value)
        if role is None:
            await interaction.response.send_message("❌ ロールを作成できませんでした（BOTの権限不足）。管理者に連絡してください。", ephemeral=True)
            return
        # 同カテゴリの他のロールを外す（1カテゴリにつき1つまで）
        for name in cat["roles"]:
            other = discord.utils.get(interaction.guild.roles, name=name)
            if other and other.id != role.id and other in member.roles:
                try:
                    await member.remove_roles(other)
                except discord.Forbidden:
                    pass
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message("❌ ロールを付けられませんでした（BOTより上のロール）。管理者に連絡してください。", ephemeral=True)
            return
        # 1回限りロール／「どれか1つだけ」カテゴリは取得を記録する
        if value in cat.get("once_roles", []) or cat.get("exclusive_once"):
            claimed = cfg.setdefault("claimed_once", {})
            if member.id not in claimed.setdefault(value, []):
                claimed[value].append(member.id)
                store.save_config()
        await interaction.response.send_message(f"✅ 「{cat['label']}」→ {value} を付けたよ。", ephemeral=True)


class RoleRemoveView(discord.ui.View):
    """自分が付けているロール（パネルのカテゴリ内）から選んで外す"""

    def __init__(self, role_names: list):
        super().__init__(timeout=180)
        sel = discord.ui.Select(
            placeholder="外すロールを選んでね（複数OK）",
            min_values=1,
            max_values=len(role_names),
            options=[discord.SelectOption(label=n, value=n) for n in role_names[:25]],
        )
        sel.callback = self._remove
        self.add_item(sel)

    async def _remove(self, interaction: discord.Interaction):
        names = set(interaction.data["values"])
        removed, failed = [], []
        for role in list(interaction.user.roles):
            if role.name in names:
                try:
                    await interaction.user.remove_roles(role)
                    removed.append(role.name)
                except discord.Forbidden:
                    failed.append(role.name)
        msg = "🧹 外したよ: " + ", ".join(removed) if removed else "外せるロールがなかったよ。"
        if failed:
            msg += f"\n❌ 権限不足で外せなかった: {', '.join(failed)}"
        await interaction.response.edit_message(content=msg, view=None)


class RolePanelView(discord.ui.View):
    def __init__(self, cfg: dict):
        super().__init__(timeout=None)
        cats = cfg["role_categories"][:5]  # 1メッセージ最大5行まで
        for cat in cats:
            self.add_item(RoleSelect(cat))
        # カテゴリが4つ以下のときだけ、5行目に「外す」ボタンを置ける
        if len(cats) <= 4:
            btn = discord.ui.Button(label="付けているロールを外す", emoji="🧹", style=discord.ButtonStyle.danger, custom_id="roledel_open")
            btn.callback = self._open_remove
            self.add_item(btn)

    async def _open_remove(self, interaction: discord.Interaction):
        cfg = store.cfg(interaction.guild.id)
        cat_names = {name for c in cfg["role_categories"] for name in c["roles"]}
        held = [r.name for r in interaction.user.roles if r.name in cat_names]
        if not held:
            await interaction.response.send_message("今は外せるロール（このパネルで付けるもの）が付いていないよ。", ephemeral=True)
            return
        await interaction.response.send_message("外すロールを選んでね（この画面はあなたにだけ見えます）:", view=RoleRemoveView(held), ephemeral=True)


def build_roles_embed(cfg: dict) -> discord.Embed:
    lines = [cfg.get("roles_panel_text") or "", ""]
    for cat in cfg["role_categories"]:
        once = set(cat.get("once_roles", []))
        names = " / ".join(f"{r}（1回限り）" if r in once else r for r in cat["roles"])
        suffix = "（どれか1つだけ・変更不可）" if cat.get("exclusive_once") else ""
        lines.append(f"**{cat['label']}**: {names}{suffix}")
    embed = discord.Embed(title="🏷️ ロール選択", description="\n".join(lines), color=discord.Color.blue())
    return embed


async def refresh_roles_panel(guild: discord.Guild) -> bool:
    """設置済みのロール選択パネルの文章を、現在の設定で書き換える。成功したら True"""
    cfg = store.cfg(guild.id)
    panel = cfg.get("panels", {}).get("roles")
    if not panel:
        return False
    ch = guild.get_channel(panel.get("channel_id"))
    if ch is None:
        return False
    try:
        msg = await ch.fetch_message(panel["message_id"])
        await msg.edit(embed=build_roles_embed(cfg))  # メニューはそのまま残る
        return True
    except Exception:
        return False



# ---------------- セットアップ系コマンド（入口まわり） ----------------
@bot.tree.command(name="setup_rules", description="このチャンネルにルール同意パネルを設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_rules(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    await interaction.response.send_message(embed=build_rules_embed(interaction.guild), view=RulesView())
    msg = await interaction.original_response()
    cfg["panels"]["rules"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.followup.send("✅ ルール同意パネルを設置しました。文面はこのメッセージを編集すれば変えられます。", ephemeral=True)


@bot.tree.command(name="setup_roles", description="このチャンネルにロール選択パネルを設置する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_roles(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    view = RolePanelView(cfg)
    await interaction.response.send_message(embed=build_roles_embed(cfg), view=view)
    msg = await interaction.original_response()
    cfg["panels"]["roles"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
    await interaction.followup.send("✅ ロール選択パネルを設置しました。", ephemeral=True)


@bot.tree.command(name="setwelcome", description="このチャンネルをウェルカム投稿先に設定する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setwelcome(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    cfg["welcome_channel_id"] = interaction.channel.id
    store.save_config()
    await interaction.response.send_message("✅ このチャンネルをウェルカム投稿先にしました。", ephemeral=True)


@bot.tree.command(name="setup_gate", description="認証ロールでチャンネルを隠すゲート権限を一括適用する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup_gate(interaction: discord.Interaction):
    """認証ロールを持たない人に、ルールチャンネル以外を見せない権限設定を一括適用する"""
    await interaction.response.defer(ephemeral=True)
    cfg = store.cfg(interaction.guild.id)
    guild = interaction.guild
    role = await get_or_create_role(guild, cfg["verify_role"])
    if role is None:
        await interaction.followup.send("❌ 認証ロールを作成できませんでした（BOTにロール管理権限が必要です）。", ephemeral=True)
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
    await interaction.followup.send(
        f"🔒 ゲート設定を適用しました（{done} チャンネル、失敗 {skipped}）。\n"
        "ルールチャンネルだけは全員が見える状態のままです。新しいチャンネルを作った場合は、そのチャンネルでも同じ設定をしてください。",
        ephemeral=True,
    )


@bot.tree.command(name="setlog", description="このチャンネルをモデレーションログ先に設定する（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setlog(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    cfg["log_channel_id"] = interaction.channel.id
    store.save_config()
    await interaction.response.send_message("✅ このチャンネルをモデレーションログ先にしました。", ephemeral=True)

