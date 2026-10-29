# -*- coding: utf-8 -*-
"""
settings.py — 管理者用 設定パネル（/settings）: 募集項目 / ロールカテゴリ / 認証ロール / NGワード の編集
"""

import discord
from discord import app_commands
from discord.ext import commands

from core import bot, store
from gate import refresh_rules_panel

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
        await interaction.response.send_message(f"✅ カテゴリ「{self.label}」を追加したよ。反映するにはロールパネルを /setup_roles で再設置してね。", ephemeral=True)


class EditFieldModal(discord.ui.Modal, title="募集項目を編集"):
    def __init__(self, guild_id, field):
        super().__init__()
        self.guild_id = guild_id
        self.orig_label = field["label"]
        self.label = discord.ui.TextInput(label="項目名", max_length=30, default=field["label"])
        self.options = discord.ui.TextInput(
            label="選択肢（カンマ区切り）",
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=", ".join(field["options"]),
        )
        self.add_item(self.label)
        self.add_item(self.options)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        opts = _parse_list(str(self.options))[:25]
        if not opts:
            await interaction.response.send_message("選択肢が空だったよ。", ephemeral=True)
            return
        new_label = str(self.label).strip()
        for f in cfg["recruit_fields"]:
            if f["label"] == self.orig_label:
                if new_label and new_label != self.orig_label and any(x["label"] == new_label for x in cfg["recruit_fields"]):
                    await interaction.response.send_message("同じ名前の項目がすでにあるよ。", ephemeral=True)
                    return
                if new_label:
                    f["label"] = new_label
                f["options"] = opts
                store.save_config()
                await interaction.response.send_message(f"✅ 募集項目「{f['label']}」を更新したよ（選択肢: {', '.join(opts)}）。次の募集作成から反映されます。", ephemeral=True)
                return
        await interaction.response.send_message("項目が見つからなかったよ（削除されたかも）。", ephemeral=True)


class EditCategoryModal(discord.ui.Modal, title="ロールカテゴリを編集"):
    def __init__(self, guild_id, category):
        super().__init__()
        self.guild_id = guild_id
        self.orig_label = category["label"]
        self.label = discord.ui.TextInput(label="カテゴリ名", max_length=30, default=category["label"])
        self.roles = discord.ui.TextInput(
            label="ロール名（カンマ区切り）",
            style=discord.TextStyle.paragraph,
            max_length=500,
            default=", ".join(category["roles"]),
        )
        self.add_item(self.label)
        self.add_item(self.roles)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        names = _parse_list(str(self.roles))[:24]
        if not names:
            await interaction.response.send_message("ロール名が空だったよ。", ephemeral=True)
            return
        new_label = str(self.label).strip()
        for c in cfg["role_categories"]:
            if c["label"] == self.orig_label:
                if new_label and new_label != self.orig_label and any(x["label"] == new_label for x in cfg["role_categories"]):
                    await interaction.response.send_message("同じ名前のカテゴリがすでにあるよ。", ephemeral=True)
                    return
                if new_label:
                    c["label"] = new_label
                c["roles"] = names
                store.save_config()
                await interaction.response.send_message(
                    f"✅ カテゴリ「{c['label']}」を更新したよ。反映するにはロールパネルを /setup_roles で再設置してね。\n"
                    "※ ロール名を変えても、すでにあるDiscordロール自体の名前は変わりません（新しい名前のロールが別に作られます）。",
                    ephemeral=True,
                )
                return
        await interaction.response.send_message("カテゴリが見つからなかったよ（削除されたかも）。", ephemeral=True)


class AddIntroFieldModal(discord.ui.Modal, title="自己紹介項目を追加"):
    label = discord.ui.TextInput(label="項目名", max_length=30, placeholder="例: 好きな武器")
    required = discord.ui.TextInput(label="必須ですか？（必須 / 任意）", max_length=5, default="任意", required=False)
    style = discord.ui.TextInput(label="入力形式（1行 / 長文）", max_length=5, default="1行", required=False)

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        if len(cfg.get("intro_fields", [])) >= 5:
            await interaction.response.send_message("自己紹介の項目は最大5つまでだよ（Discordのフォーム仕様）。", ephemeral=True)
            return
        name = str(self.label).strip()
        if not name:
            await interaction.response.send_message("項目名が空だったよ。", ephemeral=True)
            return
        if any(f["label"] == name for f in cfg["intro_fields"]):
            await interaction.response.send_message("同じ名前の項目がすでにあるよ。", ephemeral=True)
            return
        cfg["intro_fields"].append({
            "label": name,
            "required": "必須" in str(self.required),
            "long": "長文" in str(self.style),
        })
        store.save_config()
        await interaction.response.send_message(f"✅ 自己紹介項目「{name}」を追加したよ（現在 {len(cfg['intro_fields'])} 項目）。", ephemeral=True)


class EditIntroFieldModal(discord.ui.Modal, title="自己紹介項目を編集"):
    def __init__(self, guild_id, field):
        super().__init__()
        self.guild_id = guild_id
        self.orig_label = field["label"]
        self.label = discord.ui.TextInput(label="項目名", max_length=30, default=field["label"])
        self.required = discord.ui.TextInput(label="必須ですか？（必須 / 任意）", max_length=5, default="必須" if field.get("required") else "任意", required=False)
        self.style = discord.ui.TextInput(label="入力形式（1行 / 長文）", max_length=5, default="長文" if field.get("long") else "1行", required=False)
        self.add_item(self.label)
        self.add_item(self.required)
        self.add_item(self.style)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        name = str(self.label).strip()
        for f in cfg["intro_fields"]:
            if f["label"] == self.orig_label:
                if name and name != self.orig_label and any(x["label"] == name for x in cfg["intro_fields"]):
                    await interaction.response.send_message("同じ名前の項目がすでにあるよ。", ephemeral=True)
                    return
                if name:
                    f["label"] = name
                f["required"] = "必須" in str(self.required)
                f["long"] = "長文" in str(self.style)
                store.save_config()
                await interaction.response.send_message(f"✅ 自己紹介項目「{f['label']}」を更新したよ。", ephemeral=True)
                return
        await interaction.response.send_message("項目が見つからなかったよ（削除されたかも）。", ephemeral=True)


class RulesTextModal(discord.ui.Modal, title="ルール文章を変更"):
    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id
        cfg = store.cfg(guild_id)
        self.text = discord.ui.TextInput(
            label="ルール文章",
            style=discord.TextStyle.paragraph,
            max_length=4000,
            default=cfg.get("rules_text", ""),
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = store.cfg(self.guild_id)
        cfg["rules_text"] = str(self.text).strip()
        store.save_config()
        updated = await refresh_rules_panel(interaction.guild)
        if updated:
            await interaction.response.send_message("✅ ルール文章を更新して、設置済みのパネルにも反映したよ。", ephemeral=True)
        else:
            await interaction.response.send_message("✅ ルール文章を保存したよ（設置済みパネルが見つからなかったので、次に /setup_rules で設置するときに使われます）。", ephemeral=True)


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

    @discord.ui.button(label="募集項目を編集", style=discord.ButtonStyle.secondary, row=0)
    async def edit_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg["recruit_fields"]:
            await interaction.response.send_message("募集項目は今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            field = next((f for f in cfg2["recruit_fields"] if f["label"] == value), None)
            if field is None:
                await inter.response.send_message("項目が見つからなかったよ。", ephemeral=True)
                return
            await inter.response.send_modal(EditFieldModal(self.guild_id, field))

        opts = [discord.SelectOption(label=f["label"], value=f["label"]) for f in cfg["recruit_fields"]]
        await interaction.response.send_message("編集する項目を選んでね:", view=_delete_select("項目を選ぶ", "edit_field", opts, _pick), ephemeral=True)

    @discord.ui.button(label="募集項目を削除", style=discord.ButtonStyle.danger, row=0)
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

    @discord.ui.button(label="ロールカテゴリを編集", style=discord.ButtonStyle.secondary, row=1)
    async def edit_cat(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg["role_categories"]:
            await interaction.response.send_message("カテゴリは今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            cat = next((c for c in cfg2["role_categories"] if c["label"] == value), None)
            if cat is None:
                await inter.response.send_message("カテゴリが見つからなかったよ。", ephemeral=True)
                return
            await inter.response.send_modal(EditCategoryModal(self.guild_id, cat))

        opts = [discord.SelectOption(label=c["label"], value=c["label"]) for c in cfg["role_categories"]]
        await interaction.response.send_message("編集するカテゴリを選んでね:", view=_delete_select("カテゴリを選ぶ", "edit_cat", opts, _pick), ephemeral=True)

    @discord.ui.button(label="ロールカテゴリを削除", style=discord.ButtonStyle.danger, row=1)
    async def del_cat(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg["role_categories"]:
            await interaction.response.send_message("カテゴリは今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            cfg2["role_categories"] = [c for c in cfg2["role_categories"] if c["label"] != value]
            store.save_config()
            await inter.response.send_message(f"🗑️ カテゴリ「{value}」を削除したよ。反映には /setup_roles でパネル再設置を。", ephemeral=True)

        opts = [discord.SelectOption(label=c["label"], value=c["label"]) for c in cfg["role_categories"]]
        await interaction.response.send_message("削除するカテゴリを選んでね:", view=_delete_select("カテゴリを選ぶ", "del_cat", opts, _pick), ephemeral=True)

    @discord.ui.button(label="ルール文章を変更", style=discord.ButtonStyle.primary, row=2)
    async def edit_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RulesTextModal(self.guild_id))

    @discord.ui.button(label="認証ロールを設定", style=discord.ButtonStyle.primary, row=2)
    async def set_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetVerifyRoleModal(self.guild_id))

    @discord.ui.button(label="NGワードを追加", style=discord.ButtonStyle.secondary, row=2)
    async def add_ng(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddNgWordModal(self.guild_id))

    @discord.ui.button(label="自己紹介項目を追加", style=discord.ButtonStyle.primary, row=3)
    async def add_intro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if len(cfg.get("intro_fields", [])) >= 5:
            await interaction.response.send_message("自己紹介の項目は最大5つまでだよ（Discordのフォーム仕様）。", ephemeral=True)
            return
        await interaction.response.send_modal(AddIntroFieldModal(self.guild_id))

    @discord.ui.button(label="自己紹介項目を編集", style=discord.ButtonStyle.secondary, row=3)
    async def edit_intro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg.get("intro_fields"):
            await interaction.response.send_message("自己紹介項目は今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            field = next((f for f in cfg2["intro_fields"] if f["label"] == value), None)
            if field is None:
                await inter.response.send_message("項目が見つからなかったよ。", ephemeral=True)
                return
            await inter.response.send_modal(EditIntroFieldModal(self.guild_id, field))

        opts = [discord.SelectOption(label=f["label"], value=f["label"]) for f in cfg["intro_fields"]]
        await interaction.response.send_message("編集する項目を選んでね:", view=_delete_select("項目を選ぶ", "edit_intro", opts, _pick), ephemeral=True)

    @discord.ui.button(label="自己紹介項目を削除", style=discord.ButtonStyle.danger, row=3)
    async def del_intro(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(self.guild_id)
        if not cfg.get("intro_fields"):
            await interaction.response.send_message("自己紹介項目は今ないよ。", ephemeral=True)
            return

        async def _pick(inter, value):
            cfg2 = store.cfg(self.guild_id)
            cfg2["intro_fields"] = [f for f in cfg2["intro_fields"] if f["label"] != value]
            store.save_config()
            await inter.response.send_message(f"🗑️ 自己紹介項目「{value}」を削除したよ。", ephemeral=True)

        opts = [discord.SelectOption(label=f["label"], value=f["label"]) for f in cfg["intro_fields"]]
        await interaction.response.send_message("削除する項目を選んでね:", view=_delete_select("項目を選ぶ", "del_intro", opts, _pick), ephemeral=True)

    @discord.ui.button(label="現在の設定を表示", style=discord.ButtonStyle.secondary, row=4)
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
        dest = cfg.get("intro_channel_id")
        lines.append(f"**自己紹介**（送信先: {f'<#{dest}>' if dest else '未設定'}）")
        for f in cfg.get("intro_fields", []):
            lines.append(f"- {f['label']}{'（必須）' if f.get('required') else ''}{'（長文）' if f.get('long') else ''}")
        lines.append("")
        lines.append(f"**NGワード**: {len(cfg['ng_words'])} 件")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


def build_settings_embed(cfg: dict) -> discord.Embed:
    return discord.Embed(
        title="⚙️ BOT設定（管理者用）",
        description="募集項目・ロールカテゴリ・認証ロール・NGワードをここから変更できます。\n変更はその場で保存され、再起動は不要です。",
        color=discord.Color.purple(),
    )



# ---------------- コマンド ----------------
@bot.tree.command(name="settings", description="BOT設定パネルを開く（管理者用）")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_settings(interaction: discord.Interaction):
    cfg = store.cfg(interaction.guild.id)
    await interaction.response.send_message(embed=build_settings_embed(cfg), view=SettingsView(interaction.guild.id))

