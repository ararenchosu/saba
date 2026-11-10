# -*- coding: utf-8 -*-
"""
rpgbot/core.py — 簡易RPG専用BOTの共通基盤

- BOTインスタンスと、設置パネル位置だけを持つ軽い設定ストア（rpgbot/config.json）。
- お金（$）とRPG進行データはサブBOTと共有するため、ここでは持たない。
  データ本体は sub/userdata.py の users（sub/users.json）で、同一プロセスで
  起動する前提で同じオブジェクトを参照する（カジノ$連動を維持するため）。
- 許可ユーザー（TRUSTED_USER_IDS）と requires はサブBOTと同一仕様。
"""

import os
import json
import copy

import discord
from discord import app_commands
from discord.ext import commands

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

TOKEN = os.environ.get("RPG_DISCORD_TOKEN")

DEFAULT_CONFIG = {
    "panels": {},  # {"rpg": {"channel_id": .., "message_id": ..}}
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
    """設置パネル位置などの最小設定"""

    def __init__(self):
        self.configs = _load_json(CONFIG_PATH, {})

    def cfg(self, guild_id) -> dict:
        key = str(guild_id)
        if key not in self.configs:
            self.configs[key] = copy.deepcopy(DEFAULT_CONFIG)
            self.save_config()
        cfg = self.configs[key]
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, copy.deepcopy(v))
        return cfg

    def save_config(self):
        _save_json(CONFIG_PATH, self.configs)


store = Store()

# ---------------- BOT 本体 ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


class RpgTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True


bot = commands.Bot(command_prefix="!", intents=intents, help_command=None, tree_cls=RpgTree)


def is_home(guild_id) -> bool:
    """担当サーバー制なし（全サーバーで動作）。サブBOTと同仕様。"""
    return True


# ---------------- 許可ユーザー（サブBOTと同一） ----------------
TRUSTED_USER_IDS = {
    1546348374922625065,
    1256574550901133377,
}


def is_trusted(user_id) -> bool:
    return user_id in TRUSTED_USER_IDS


def requires(**perms):
    """権限チェック（サブBOTの core と同一仕様）"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if is_trusted(interaction.user.id):
            return True
        gp = getattr(interaction.user, "guild_permissions", None)
        if gp is None:
            return False
        if gp.administrator:
            return True
        return all(getattr(gp, name, False) for name, want in perms.items() if want)
    return app_commands.check(predicate)
