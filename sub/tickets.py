# -*- coding: utf-8 -*-
"""個別問い合わせチケットと、担当制の通報受付・対応管理。"""

import asyncio
import io
import uuid

import discord
from discord import app_commands

from sub.core import bot, store, log_event, get_or_create_role, is_trusted, requires
from sub.userdata import reports

CATEGORY_NAME = "🎫 チケット"
_report_locks = {}


def _report_lock(case_id: str) -> asyncio.Lock:
    return _report_locks.setdefault(case_id, asyncio.Lock())


def _report_embed(record: dict) -> discord.Embed:
    status = {
        "pending": "未対応",
        "in_progress": "対応中",
        "completed": "完了",
    }.get(record.get("status"), "不明")
    embed = discord.Embed(
        title=f"🚨 通報案件 #{record['case_id']}",
        description=record["details"],
        color=discord.Color.red() if status == "未対応" else discord.Color.orange(),
    )
    embed.add_field(name="対象", value=record["target"][:1024], inline=True)
    embed.add_field(name="分類", value=record["category"][:1024], inline=True)
    embed.add_field(name="状態", value=status, inline=True)
    if record.get("evidence"):
        embed.add_field(name="参考情報・証拠", value=record["evidence"][:1024], inline=False)
    embed.add_field(name="通報者", value=f"<@{record['reporter_id']}>", inline=True)
    assigned = record.get("assignee_id")
    embed.add_field(name="担当者", value=f"<@{assigned}>" if assigned else "未割り当て", inline=True)
    embed.add_field(name="対応メモ", value=f"{len(record.get('notes', []))}件（担当者のみ閲覧）", inline=True)
    embed.set_footer(text=f"受付日時: {record['created_at']}")
    return embed


def _is_ticket_staff(interaction: discord.Interaction, cfg: dict) -> bool:
    if is_trusted(interaction.user.id) or interaction.user.guild_permissions.administrator:
        return True
    staff_role = discord.utils.get(interaction.guild.roles, name=cfg.get("ticket_role", "スタッフ"))
    return isinstance(interaction.user, discord.Member) and staff_role in interaction.user.roles


def _report_transcript(record: dict, messages: list[discord.Message]) -> bytes:
    lines = [
        f"通報案件 #{record['case_id']}",
        f"状態: {record['status']}",
        f"対象: {record['target']}",
        f"分類: {record['category']}",
        f"通報者: {record['reporter_name']} ({record['reporter_id']})",
        f"担当者: {record.get('assignee_name') or '未割り当て'} ({record.get('assignee_id') or '-'})",
        f"受付日時: {record['created_at']}",
        f"対応開始日時: {record.get('started_at') or '-'}",
        f"完了日時: {record.get('completed_at') or '-'}",
        "",
        "通報内容:",
        record["details"],
    ]
    if record.get("evidence"):
        lines.extend(["", "参考情報・証拠:", record["evidence"]])
    lines.extend(["", "===== チャンネル内の会話 ====="])
    for message in messages:
        timestamp = message.created_at.isoformat(timespec="seconds")
        author = f"{message.author} ({message.author.id})"
        lines.append(f"[{timestamp}] {author}")
        if message.content:
            lines.append(message.content)
        for embed in message.embeds:
            if embed.title:
                lines.append(f"[Embed] {embed.title}")
            if embed.description:
                lines.append(embed.description)
        for attachment in message.attachments:
            lines.append(f"[添付ファイル] {attachment.filename}: {attachment.url}")
        if not message.content and not message.embeds and not message.attachments:
            lines.append("[本文なし]")
        lines.append("")
    if record.get("notes"):
        lines.extend(["===== 担当者メモ ====="])
        for note in record["notes"]:
            lines.append(f"[{note['at']}] {note['author']}: {note['text']}")
    return "\n".join(lines).encode("utf-8")


async def _fetch_report_transcript(channel: discord.TextChannel, record: dict) -> bytes | None:
    try:
        messages = [message async for message in channel.history(limit=None, oldest_first=True)]
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"通報ログ取得失敗 case={record['case_id']}: {exc}")
        return None
    return _report_transcript(record, messages)


async def _send_report_transcript(
    guild: discord.Guild,
    channel: discord.TextChannel,
    record: dict,
) -> None:
    payload = await _fetch_report_transcript(channel, record)
    if payload is None:
        return
    sent_to = set(record.setdefault("transcript_sent_to", []))
    recipient_ids = {
        user_id
        for user_id in (record.get("reporter_id"), record.get("assignee_id"))
        if user_id
    }
    for user_id in recipient_ids:
        if not user_id or user_id in sent_to:
            continue
        user = guild.get_member(user_id) or bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                print(f"通報ログ送信先取得失敗 case={record['case_id']} user={user_id}: {exc}")
                continue
        try:
            await user.send(
                content=f"通報案件 #{record['case_id']} の対応ログです。",
                file=discord.File(io.BytesIO(payload), filename=f"report-{record['case_id']}.txt"),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"通報ログDM失敗 case={record['case_id']} user={user_id}: {exc}")
            continue
        sent_to.add(user_id)
        record["transcript_sent_to"] = list(sent_to)
        reports.save()
    if not recipient_ids.issubset(sent_to):
        print(f"通報ログ未送信の宛先あり case={record['case_id']}")


class ReportCaseView(discord.ui.View):
    def __init__(self, case_id: str, completed: bool = False):
        super().__init__(timeout=None)
        self.case_id = case_id

        if completed:
            resend = discord.ui.Button(
                label="未送信ログを再送",
                emoji="📄",
                style=discord.ButtonStyle.secondary,
                custom_id=f"report:{case_id}:resend",
            )
            resend.callback = self._resend
            self.add_item(resend)
            return

        start = discord.ui.Button(
            label="対応開始",
            emoji="🛠️",
            style=discord.ButtonStyle.primary,
            custom_id=f"report:{case_id}:start",
        )
        start.callback = self._start
        self.add_item(start)

        note = discord.ui.Button(
            label="対応メモ",
            emoji="📝",
            style=discord.ButtonStyle.secondary,
            custom_id=f"report:{case_id}:note",
        )
        note.callback = self._open_note
        self.add_item(note)

        complete = discord.ui.Button(
            label="対応完了",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"report:{case_id}:complete",
        )
        complete.callback = self._complete
        self.add_item(complete)

        resend = discord.ui.Button(
            label="未送信ログを再送",
            emoji="📄",
            style=discord.ButtonStyle.secondary,
            custom_id=f"report:{case_id}:resend",
        )
        resend.callback = self._resend
        self.add_item(resend)

    def _record(self, interaction: discord.Interaction) -> dict | None:
        record = reports.data.get(self.case_id)
        if record is None or record.get("guild_id") != interaction.guild_id:
            return None
        return record

    async def _start(self, interaction: discord.Interaction):
        record = self._record(interaction)
        if record is None or record.get("status") != "pending":
            await interaction.response.send_message("この案件は対応開始できません。", ephemeral=True)
            return
        cfg = store.cfg(interaction.guild.id)
        if not _is_ticket_staff(interaction, cfg):
            await interaction.response.send_message("対応開始できるのはスタッフだけです。", ephemeral=True)
            return
        async with _report_lock(self.case_id):
            if record.get("status") != "pending":
                await interaction.response.send_message("別のスタッフが先に対応を開始しました。", ephemeral=True)
                return
            staff_role = discord.utils.get(interaction.guild.roles, name=cfg.get("ticket_role", "スタッフ"))
            try:
                overwrites = dict(interaction.channel.overwrites)
                if staff_role is not None:
                    overwrites[staff_role] = discord.PermissionOverwrite(
                        view_channel=False,
                        send_messages=False,
                    )
                overwrites[interaction.user] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
                await interaction.channel.edit(
                    overwrites=overwrites,
                    reason=f"通報 #{self.case_id} の担当者に割り当て",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"通報担当割り当て失敗 case={self.case_id}: {exc}")
                await interaction.response.send_message("権限の更新に失敗したため、対応を開始できませんでした。", ephemeral=True)
                return
            record["status"] = "in_progress"
            record["assignee_id"] = interaction.user.id
            record["assignee_name"] = str(interaction.user)
            record["started_at"] = discord.utils.utcnow().isoformat(timespec="seconds")
            reports.save()
        await interaction.response.edit_message(embed=_report_embed(record), view=self)

    async def _open_note(self, interaction: discord.Interaction):
        record = self._record(interaction)
        if record is None or record.get("status") != "in_progress":
            await interaction.response.send_message("対応中の案件ではありません。", ephemeral=True)
            return
        if interaction.user.id != record.get("assignee_id"):
            await interaction.response.send_message("対応メモを追加できるのは担当者だけです。", ephemeral=True)
            return
        await interaction.response.send_modal(ReportNoteModal(self.case_id))

    async def _complete(self, interaction: discord.Interaction):
        record = self._record(interaction)
        if record is None or record.get("status") != "in_progress":
            await interaction.response.send_message("対応中の案件ではありません。", ephemeral=True)
            return
        if interaction.user.id != record.get("assignee_id"):
            await interaction.response.send_message("対応完了にできるのは担当者だけです。", ephemeral=True)
            return
        async with _report_lock(self.case_id):
            if record.get("status") != "in_progress":
                await interaction.response.send_message("この案件はすでに完了しています。", ephemeral=True)
                return
            record["status"] = "completed"
            record["completed_at"] = discord.utils.utcnow().isoformat(timespec="seconds")
            reports.save()
        await interaction.response.defer(ephemeral=True)
        await _send_report_transcript(interaction.guild, interaction.channel, record)
        pending = {
            record.get("reporter_id"),
            record.get("assignee_id"),
        } - set(record.get("transcript_sent_to", []))
        view = ReportCaseView(self.case_id, completed=True) if pending else None
        if view:
            bot.add_view(view, message_id=interaction.message.id)
        await interaction.message.edit(embed=_report_embed(record), view=view)
        if pending:
            await interaction.followup.send(
                "対応を完了しましたが、TXTログを送れなかった宛先があります。チャンネルは残し、担当者は「未送信ログを再送」から再試行できます。",
                ephemeral=True,
            )
        else:
            await interaction.followup.send("✅ 対応を完了し、通報者と担当者にTXTログを送信しました。", ephemeral=True)

    async def _resend(self, interaction: discord.Interaction):
        record = self._record(interaction)
        if record is None or record.get("status") != "completed":
            await interaction.response.send_message("未送信ログの再送が必要な案件ではありません。", ephemeral=True)
            return
        if interaction.user.id != record.get("assignee_id"):
            await interaction.response.send_message("ログを再送できるのは担当者だけです。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await _send_report_transcript(interaction.guild, interaction.channel, record)
        pending = {
            record.get("reporter_id"),
            record.get("assignee_id"),
        } - set(record.get("transcript_sent_to", []))
        view = ReportCaseView(self.case_id, completed=True) if pending else None
        if view:
            bot.add_view(view, message_id=interaction.message.id)
        await interaction.message.edit(embed=_report_embed(record), view=view)
        if pending:
            await interaction.followup.send("ログの再送に失敗しました。DM設定を確認して、もう一度お試しください。", ephemeral=True)
        else:
            await interaction.followup.send("✅ 未送信のTXTログを送信しました。", ephemeral=True)


class ReportNoteModal(discord.ui.Modal, title="対応メモを追加"):
    note = discord.ui.TextInput(
        label="担当者用メモ（通報者には表示されません）",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, case_id: str):
        super().__init__()
        self.case_id = case_id

    async def on_submit(self, interaction: discord.Interaction):
        record = reports.data.get(self.case_id)
        if (
            record is None
            or record.get("guild_id") != interaction.guild_id
            or record.get("status") != "in_progress"
            or record.get("assignee_id") != interaction.user.id
        ):
            await interaction.response.send_message("この案件の担当者だけが対応メモを追加できます。", ephemeral=True)
            return
        record.setdefault("notes", []).append({
            "at": discord.utils.utcnow().isoformat(timespec="seconds"),
            "author": str(interaction.user),
            "text": str(self.note).strip(),
        })
        reports.save()
        await interaction.response.send_message("📝 担当者用メモを保存しました。通報者には表示されません。", ephemeral=True)


class ReportModal(discord.ui.Modal, title="🚨 通報する"):
    target = discord.ui.TextInput(label="通報対象（名前・ユーザーIDなど）", max_length=100)
    category = discord.ui.TextInput(label="通報の分類", placeholder="例: 迷惑行為、荒らし、その他", max_length=100)
    details = discord.ui.TextInput(label="通報内容", style=discord.TextStyle.paragraph, max_length=1500)
    evidence = discord.ui.TextInput(
        label="参考情報・証拠（任意）",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("サーバー内から通報してください。", ephemeral=True)
            return
        cfg = store.cfg(guild.id)
        if not cfg.get("tickets_enabled", True):
            await interaction.response.send_message("チケット・通報機能は現在オフです。", ephemeral=True)
            return
        active = next(
            (
                item for item in reports.data.values()
                if item.get("guild_id") == guild.id
                and item.get("reporter_id") == interaction.user.id
                and item.get("status") != "completed"
            ),
            None,
        )
        if active:
            channel = guild.get_channel(active.get("channel_id"))
            link = channel.mention if channel else "以前の案件が対応中です"
            await interaction.response.send_message(f"対応中の通報があります: {link}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        category_channel = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category_channel is None:
            try:
                category_channel = await guild.create_category(CATEGORY_NAME)
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"通報カテゴリ作成失敗 guild={guild.id}: {exc}")
                await interaction.followup.send("チケットカテゴリを作成できませんでした。管理者に連絡してください。", ephemeral=True)
                return
        staff_role = await get_or_create_role(guild, cfg.get("ticket_role", "スタッフ"))
        if staff_role is None:
            await interaction.followup.send("スタッフロールを準備できませんでした。BOTのロール管理権限を確認してください。", ephemeral=True)
            return
        case_id = uuid.uuid4().hex[:12]
        created_at = discord.utils.utcnow().isoformat(timespec="seconds")
        record = {
            "case_id": case_id,
            "guild_id": guild.id,
            "channel_id": None,
            "message_id": None,
            "reporter_id": interaction.user.id,
            "reporter_name": str(interaction.user),
            "target": str(self.target).strip(),
            "category": str(self.category).strip(),
            "details": str(self.details).strip(),
            "evidence": str(self.evidence).strip(),
            "status": "pending",
            "assignee_id": None,
            "assignee_name": None,
            "created_at": created_at,
            "notes": [],
            "transcript_sent_to": [],
        }
        try:
            channel = await guild.create_text_channel(
                name=f"report-{case_id}",
                category=category_channel,
                topic=f"report:{case_id}",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                    ),
                    staff_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_channels=True,
                    ),
                },
                reason=f"通報案件 #{case_id}",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"通報チャンネル作成失敗 guild={guild.id} case={case_id}: {exc}")
            await interaction.followup.send("通報チャンネルを作成できませんでした。BOTのチャンネル管理権限を確認してください。", ephemeral=True)
            return
        record["channel_id"] = channel.id
        reports.data[case_id] = record
        reports.save()
        message = await channel.send(
            content=f"{staff_role.mention} 新しい通報案件です。",
            embed=_report_embed(record),
            view=ReportCaseView(case_id),
        )
        record["message_id"] = message.id
        reports.save()
        bot.add_view(ReportCaseView(case_id), message_id=message.id)
        await interaction.followup.send(
            f"✅ 通報を受け付けました（案件 #{case_id}）。対応状況は {channel.mention} で確認できます。",
            ephemeral=True,
        )


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
        is_staff = interaction.user.guild_permissions.administrator
        await interaction.response.send_message("🔒 このチケットを閉じます。チャンネルは削除されます。")
        await log_event(interaction.guild, f"🎫 チケット終了: {ch.name}（作成者: <@{owner_id}> / 閉じた人: {interaction.user.mention}）")
        try:
            await ch.delete(reason="チケット終了")
        except discord.Forbidden:
            pass


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを作成", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        cfg = store.cfg(guild.id)
        if not cfg.get("tickets_enabled", True):
            await interaction.response.send_message("チケット機能は今オフだよ。", ephemeral=True)
            return
        # 既に自分のチケットがあるか
        for ch in guild.text_channels:
            if ch.topic == f"ticket:{interaction.user.id}":
                await interaction.response.send_message(f"もうあなたのチケットがあるよ: {ch.mention}", ephemeral=True)
                return
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if category is None:
            try:
                category = await guild.create_category(CATEGORY_NAME)
            except discord.Forbidden:
                category = None
        staff_role = await get_or_create_role(guild, cfg.get("ticket_role", "スタッフ"))
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if staff_role is not None:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        try:
            ch = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}"[:100],
                category=category,
                topic=f"ticket:{interaction.user.id}",
                overwrites=overwrites,
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ チャンネルを作成できませんでした（BOTの権限不足）。", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎫 チケット",
            description=f"{interaction.user.mention} さん、問い合わせありがとうございます。\n内容をここに書いてください。運営が対応します。\n終わったら下のボタンで閉じてください。",
            color=discord.Color.blurple(),
        )
        await ch.send(embed=embed, view=TicketCloseView())
        if staff_role is not None:
            await ch.send(f"{staff_role.mention} 新しいチケットです。")
        await log_event(guild, f"🎫 チケット作成: {ch.mention} by {interaction.user.mention}")
        await interaction.response.send_message(f"🎫 チケットを作成したよ: {ch.mention}", ephemeral=True)

    @discord.ui.button(label="通報する", emoji="🚨", style=discord.ButtonStyle.danger, custom_id="ticket_report")
    async def open_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = store.cfg(interaction.guild.id)
        if not cfg.get("tickets_enabled", True):
            await interaction.response.send_message("チケット・通報機能は現在オフです。", ephemeral=True)
            return
        await interaction.response.send_modal(ReportModal())


def build_ticket_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🎫 お問い合わせ・チケット",
        description="お問い合わせはチケット、通報は通報フォームから送ってね。\n通報チャンネルはスタッフと通報者だけが見られ、対応開始後は担当者と通報者だけが見られます。",
        color=discord.Color.blurple(),
    )


async def refresh_ticket_panels():
    for guild_id, cfg in store.configs.items():
        panel = cfg.get("panels", {}).get("tickets")
        if not panel:
            continue
        guild = bot.get_guild(int(guild_id))
        channel = guild.get_channel(panel.get("channel_id")) if guild else None
        if channel is None:
            continue
        try:
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=build_ticket_panel_embed(), view=TicketPanelView())
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            print(f"チケットパネル更新失敗 guild={guild_id}: {exc}")


def restore_report_views():
    for case_id, record in reports.data.items():
        pending_transcript = {
            record.get("reporter_id"),
            record.get("assignee_id"),
        } - set(record.get("transcript_sent_to", []))
        if record.get("message_id") and (record.get("status") != "completed" or pending_transcript):
            try:
                bot.add_view(
                    ReportCaseView(case_id, completed=record.get("status") == "completed"),
                    message_id=record["message_id"],
                )
            except (ValueError, discord.ClientException) as exc:
                print(f"通報案件View復旧失敗 case={case_id}: {exc}")


@bot.tree.command(name="setup_tickets", description="チケット受付パネルをこのチャンネルに設置する（管理者用）")
@requires(administrator=True)
async def cmd_setup_tickets(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_ticket_panel_embed(), view=TicketPanelView())
    msg = await interaction.original_response()
    cfg = store.cfg(interaction.guild.id)
    cfg.setdefault("panels", {})["tickets"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    store.save_config()
