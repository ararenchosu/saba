# -*- coding: utf-8 -*-
"""
core.py — 共通基盤: 設定ストア / BOTインスタンス / 汎用ヘルパー
機能モジュール（gate.py / recruit.py / settings.py / moderation.py）は
ここから bot と store を import して使う。
データファイル（config.json / recruitments.json）はこのフォルダに置かれる。
"""

import os
import json
import copy

import discord
from discord.ext import commands

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
RECRUIT_PATH = os.path.join(BASE_DIR, "recruitments.json")

TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("DISCORD_BOT_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")

# ---------------- デフォルト設定（/settings で変更可能） ----------------
DEFAULT_CONFIG = {
    "verify_role": "メンバー",  # ルール同意で付けるロール名
    # ルール同意パネルに表示する文章（/settings から変更可能）
    "rules_text": (
        "参加ありがとう！サーバーを使う前に、下のルールを確認して同意ボタンを押してね。\n\n"
        "1. 誹謗中傷・暴言は禁止\n"
        "2. 宣伝・勧誘・荒らし行為は禁止\n"
        "3. 個人情報は載せない\n"
        "4. 募集のドタキャンは一言連絡を\n"
        "5. その他、みんなが気持ちよく遊べるように"
    ),
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



def _admin():
    """管理者権限チェック（コマンド用デコレータ）"""
    return commands.has_permissions(administrator=True)
