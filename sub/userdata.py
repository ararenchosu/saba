# -*- coding: utf-8 -*-
"""
sub/userdata.py — ユーザー別データの保存（サブBOT高機能用）

users.json … XP・コインなど {guild_id: {user_id: {...}}}
modlogs.json … モデレーション履歴 {guild_id: [case, ...]}
utility.json … 投票・抽選・リマインダー {polls: {...}, giveaways: {...}, reminders: [...]}
すべて sub/ フォルダ内に保存され、再起動しても残る。
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, "users.json")
MODLOGS_PATH = os.path.join(BASE_DIR, "modlogs.json")
UTILITY_PATH = os.path.join(BASE_DIR, "utility.json")


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, type(default)):
                return data
        except Exception:
            pass
    return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class UserStore:
    """XP・コインなどユーザーごとの数値データ"""

    def __init__(self):
        self.data = _load(USERS_PATH, {})

    def get(self, guild_id: int, user_id: int) -> dict:
        g = self.data.setdefault(str(guild_id), {})
        u = g.setdefault(str(user_id), {})
        u.setdefault("xp", 0)
        u.setdefault("coins", 0)
        u.setdefault("last_xp_at", 0)
        u.setdefault("last_daily", "")
        u.setdefault("daily_streak", 0)
        return u

    def guild_users(self, guild_id: int) -> dict:
        return self.data.get(str(guild_id), {})

    def save(self):
        _save(USERS_PATH, self.data)


class ModLogStore:
    """モデレーションのケース履歴"""

    def __init__(self):
        self.data = _load(MODLOGS_PATH, {})

    def add_case(self, guild_id: int, user_id: int, mod_id: int, action: str, reason: str, at: str) -> dict:
        g = self.data.setdefault(str(guild_id), [])
        case = {
            "id": len(g) + 1,
            "user_id": user_id,
            "mod_id": mod_id,
            "action": action,
            "reason": reason or "",
            "at": at,
        }
        g.append(case)
        self.save()
        return case

    def cases(self, guild_id: int, user_id: int = None) -> list:
        g = self.data.get(str(guild_id), [])
        if user_id is None:
            return list(g)
        return [c for c in g if c.get("user_id") == user_id]

    def warn_count(self, guild_id: int, user_id: int) -> int:
        return sum(1 for c in self.cases(guild_id, user_id) if c.get("action") == "warn")

    def clear_warns(self, guild_id: int, user_id: int) -> int:
        g = self.data.get(str(guild_id), [])
        kept = [c for c in g if not (c.get("user_id") == user_id and c.get("action") == "warn")]
        n = len(g) - len(kept)
        self.data[str(guild_id)] = kept
        self.save()
        return n

    def save(self):
        _save(MODLOGS_PATH, self.data)


class UtilityStore:
    """投票・抽選・リマインダーの状態"""

    def __init__(self):
        self.data = _load(UTILITY_PATH, {"polls": {}, "giveaways": {}, "reminders": []})
        self.data.setdefault("polls", {})
        self.data.setdefault("giveaways", {})
        self.data.setdefault("reminders", [])

    def save(self):
        _save(UTILITY_PATH, self.data)


users = UserStore()
modlogs = ModLogStore()
utility = UtilityStore()
