# -*- coding: utf-8 -*-
"""
omikuji.py — おみくじ（サブBOT）

・設定系はスラッシュコマンド4つ（管理者用）:
  /おみくじチャンネル設定・/おみくじチャンネル解除
  /恋みくじチャンネル設定・/恋みくじチャンネル解除
  （実行したチャンネルを、その種類の専用チャンネルに設定する）
・引くのは通常メッセージ: 設定されたチャンネルで「おみくじ」「恋みくじ」と
  送信するだけ。それ以外のチャンネルで送信されても無視する。
・結果は同じチャンネルに「抽選中...」→「抽選完了！」＋embedで表示。
"""

import asyncio
import random

import discord

from sub.core import bot, store, requires

try:
    from sub.core import features_enabled
except ImportError:  # 旧バージョンの core.py でも動くように
    def features_enabled(guild_id):
        return True

# (ラベル, 絵文字, 確率%, 一言リスト)
STANDARD = [
    ("大吉", "🎉", 12, [
        "絶好調！ 落としたトーストはバター面を上にして着地する日。",
        "今日はツイてる。探し物が一発で見つかる予報。",
        "何をやっても上手くいく気がする。知らんけど。"]),
    ("中吉", "😊", 16, [
        "なかなか良い日。小さなラッキーが3回くらいある見込み。",
        "信号にあまり引っかからない日。地味に嬉しい。",
        "コンビニの新商品に手を伸ばすと吉。"]),
    ("吉", "😌", 20, [
        "普通が一番。『平常運転』という名の安定感。",
        "可もなく不可もなく。でもそれが一番平和。",
        "今日のハイライトは昼ごはん。力を入れて選ぼう。"]),
    ("小吉", "🙂", 18, [
        "ささやかな幸せが来る。プリンのカラメルがちょうどいい苦さ、みたいな。",
        "靴下が左右揃っているだけで勝ち組な日。",
        "小さな親切をすると、少し大きな親切が返ってくるかも。"]),
    ("末吉", "😐", 15, [
        "後半から良くなる日。午前中は無理しないで。",
        "末広がり。最後の最後でいいことがあるタイプ。",
        "今日は準備の日。本番は明日らしい。"]),
    ("凶", "😖", 11, [
        "傘を忘れそう。でも降らないかもしれない。賭けだね。",
        "スマホの充電は早めに。なんとなくそんな気がする。",
        "今日は慎重に。でも凶はここから上がるだけ、とも言う。"]),
    ("大凶", "💀", 8, [
        "逆にレア。ここまで来ると笑えてくるやつ。スクショ推奨。",
        "今日は家で大人しくが最適解。ゲーム日和とも言う。",
        "大凶のあとは上り坂しかない。明日が楽しみだね。"]),
]

LOVE = [
    ("大吉", "💖", 12, [
        "恋愛運は絶好調！ 気になる人と目が合う確率が上がっている日。",
        "思い切った一歩が実を結びそう。連絡は今日中に送るのが吉。",
        "あなたの魅力が3割増し（当社比）。自信を持って。"]),
    ("中吉", "💗", 16, [
        "良い流れが来ているよ。共通の趣味の話で距離が縮まりそう。",
        "笑顔が鍵。今日の笑顔はいつもより効く。",
        "偶然の再会や連絡に期待。スマホは手元に。"]),
    ("吉", "💓", 20, [
        "穏やかで安定した恋愛運。いつも通りの優しさが一番効く日。",
        "焦らずマイペースで。相手も同じペースかもしれない。",
        "友達との時間が、巡り巡って恋に効いてくる日。"]),
    ("小吉", "💞", 18, [
        "小さなドキドキの予感。いつもと違う道を通ると何かあるかも。",
        "さりげない気遣いが相手に届く日。大げさじゃなくていい。",
        "髪型や服装の小さな変化に、誰かが気づいてくれるかも。"]),
    ("末吉", "💘", 15, [
        "後半から運気上昇。夕方以降の誘いは乗ってみて吉。",
        "今は種まきの時期。今日の優しさは来週効いてくる。",
        "片思いの人は、まず挨拶から。それだけで一歩前進。"]),
    ("凶", "💔", 11, [
        "今日は恋の暴走注意報。送る前にメッセージを3回読み直して。",
        "無理に進めない方がいい日。距離感を大事に。",
        "嫉妬は禁物。今日は自分の時間を楽しむのが正解。"]),
    ("大凶", "🖤", 8, [
        "恋愛運は一旦お休みの日。でも大凶はレア。自分磨きに全振りしよう。",
        "今日の失言は明日の笑い話。深く考えすぎないで。",
        "運は貯金中。次の引き直し（明日）に期待。"]),
]

LUCKY_ITEMS = ["片方だけの靴下", "温かい缶コーヒー", "予備の充電ケーブル",
               "昨日買ったプリン", "折れてないポッキー", "ふかふかのタオル",
               "小銭入れの奥の500円玉", "Wi-Fiの届く角の席", "予備のマスク",
               "猫の抜け毛"]
LUCKY_COLORS = ["赤", "青", "金色", "虹色", "抹茶色", "どピンク", "猫柄", "透明"]
LOVE_SPOTS = ["いつもの通学・通勤路", "コンビニの前", "ゲームの中（VC）",
              "カフェの窓際の席", "駅のホーム", "よく行くお店", "SNSのタイムライン"]

RANK_COLORS = {"大吉": discord.Color.gold(), "中吉": discord.Color.green(),
               "吉": discord.Color.blurple(), "小吉": discord.Color.blue(),
               "末吉": discord.Color.light_grey(), "凶": discord.Color.dark_grey(),
               "大凶": discord.Color.darker_grey()}

# 種類ごとの設定: (表示名, テーブル, configキー)
KINDS = {
    "おみくじ": ("おみくじ", STANDARD, "omikuji_channel_id"),
    "恋みくじ": ("恋みくじ", LOVE, "koimikuji_channel_id"),
}


def _draw(table):
    r = random.randint(1, 100)
    acc = 0
    for row in table:
        acc += row[2]
        if r <= acc:
            return row
    return table[-1]


def _result_embed(user, kind, row):
    label, emoji, _w, messages = row
    if kind == "恋みくじ":
        embed = discord.Embed(
            title="💖 恋みくじ結果",
            description=f"{user.mention} の今日の恋占い\n# {emoji} {label}\n{random.choice(messages)}",
            color=discord.Color.pink())
        embed.add_field(name="💘 ラッキースポット", value=random.choice(LOVE_SPOTS), inline=True)
    else:
        embed = discord.Embed(
            title="🔮 おみくじ結果",
            description=f"{user.mention} の運勢\n# {emoji} {label}\n{random.choice(messages)}",
            color=RANK_COLORS.get(label, discord.Color.blurple()))
    embed.add_field(name="🍀 ラッキーアイテム", value=random.choice(LUCKY_ITEMS), inline=True)
    embed.add_field(name="🎨 ラッキーカラー", value=random.choice(LUCKY_COLORS), inline=True)
    return embed


async def _run_draw(message, kind):
    _name, table, _key = KINDS[kind]
    row = _draw(table)
    try:
        msg = await message.channel.send(
            f"🔮 {message.author.mention} が{kind}を引いています… **抽選中...**")
    except discord.Forbidden:
        return
    await asyncio.sleep(1.5)
    try:
        await msg.edit(content=f"✅ {message.author.mention} の{kind}、**抽選完了！**",
                       embed=_result_embed(message.author, kind, row))
    except discord.NotFound:
        pass


@bot.listen("on_message")
async def omikuji_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if not features_enabled(message.guild.id):
        return
    content = (message.content or "").strip()
    kind = KINDS.get(content)
    if kind is None:
        return
    cfg = store.cfg(message.guild.id)
    if cfg.get(kind[2]) != message.channel.id:
        return  # 設定されたチャンネル以外は無視
    await _run_draw(message, content)


# ---------------- チャンネル設定（スラッシュコマンド4つ・管理者用） ----------------

def _make_set_command(kind):
    _name, _table, key = KINDS[kind]

    @bot.tree.command(name=f"{kind}チャンネル設定",
                      description=f"このチャンネルを{kind}専用チャンネルに設定する（管理者用）")
    @requires(administrator=True)
    async def _cmd(interaction: discord.Interaction):
        cfg = store.cfg(interaction.guild.id)
        cfg[key] = interaction.channel.id
        store.save_config()
        await interaction.response.send_message(
            f"✅ このチャンネルを{kind}専用チャンネルにしました。"
            f"ここで「{kind}」と送信すると引けます。", ephemeral=True)

    return _cmd


def _make_unset_command(kind):
    _name, _table, key = KINDS[kind]

    @bot.tree.command(name=f"{kind}チャンネル解除",
                      description=f"{kind}専用チャンネルの設定を解除する（管理者用）")
    @requires(administrator=True)
    async def _cmd(interaction: discord.Interaction):
        cfg = store.cfg(interaction.guild.id)
        if cfg.get(key):
            cfg[key] = None
            store.save_config()
            await interaction.response.send_message(
                f"✅ {kind}専用チャンネルの設定を解除しました。"
                f"再開するには専用にしたいチャンネルで /{kind}チャンネル設定 を実行してください。",
                ephemeral=True)
        else:
            await interaction.response.send_message(
                f"{kind}専用チャンネルは最初から未設定です。", ephemeral=True)

    return _cmd


for _kind in KINDS:
    _make_set_command(_kind)
    _make_unset_command(_kind)
