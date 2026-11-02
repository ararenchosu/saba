import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncio
import json
import os
import time
import random
from datetime import datetime

from ywp.auto import Client, login_email, RC
from ywp.panel import run_farm
from ywp.core import DATA_DIR

# ============================================================
# データファイル
# ============================================================
SESSION_FILE = f"{DATA_DIR}/sessions.json"
LOOP_FILE = f"{DATA_DIR}/loops.json"


def ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(path, default=None):
    ensure_dir()
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default or {}


def save_json(path, data):
    ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_sessions() -> dict:
    return load_json(SESSION_FILE, {})


def save_sessions(data: dict):
    save_json(SESSION_FILE, data)


def load_loops() -> dict:
    return load_json(LOOP_FILE, {})


def save_loops(data: dict):
    save_json(LOOP_FILE, data)


# ============================================================
# 3秒問題対策ヘルパー
# ============================================================
async def safe_defer(interaction: discord.Interaction, ephemeral: bool = True, thinking: bool = True) -> bool:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral, thinking=thinking)
        return True
    except discord.NotFound:
        return False
    except discord.HTTPException:
        return False


async def safe_reply(interaction: discord.Interaction, **kwargs):
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        else:
            return await interaction.response.send
