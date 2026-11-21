import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import bot


class YokodoriCompareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.snapshots = patch.dict(bot.YOKODORI_SNAPSHOTS, {}, clear=True)
        self.snapshots.start()
        self.addCleanup(self.snapshots.stop)
        self.sessions = patch.dict(bot.SESSIONS, {42: {}}, clear=True)
        self.sessions.start()
        self.addCleanup(self.sessions.stop)

    def interaction(self):
        return SimpleNamespace(
            user=SimpleNamespace(id=42),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_two_accounts_produce_private_diff(self):
        clients = [
            SimpleNamespace(userId='1', save={'ywp_user_event': '1359|0'}),
            SimpleNamespace(userId='2', save={'ywp_user_event': '1359|1'}),
        ]
        with patch.object(bot, 'acquire_client', AsyncMock(side_effect=clients)), \
                patch.object(bot.proxy_pool, 'release_client'):
            first = self.interaction()
            await bot.yokodori_compare.callback(first, discord.app_commands.Choice(name='off', value='off'))
            second = self.interaction()
            await bot.yokodori_compare.callback(second, discord.app_commands.Choice(name='on', value='on'))

        args = second.followup.send.await_args
        self.assertTrue(args.kwargs['ephemeral'])
        report = args.kwargs['file'].fp.getvalue().decode()
        self.assertIn('-["1359", "0"]', report)
        self.assertIn('+["1359", "1"]', report)
        self.assertIn('比較不可', report)
        self.assertNotIn(42, bot.YOKODORI_SNAPSHOTS)

    async def test_same_account_cannot_be_compared(self):
        client = SimpleNamespace(userId='1', save={'ywp_user_event': '1359|0'})
        with patch.object(bot, 'acquire_client', AsyncMock(return_value=client)), \
                patch.object(bot.proxy_pool, 'release_client'):
            await bot.yokodori_compare.callback(
                self.interaction(), discord.app_commands.Choice(name='off', value='off'))
            second = self.interaction()
            await bot.yokodori_compare.callback(
                second, discord.app_commands.Choice(name='on', value='on'))
        self.assertIn('同じセーブ', second.followup.send.await_args.args[0])
        self.assertIn(42, bot.YOKODORI_SNAPSHOTS)

    def test_missing_and_invalid_tables_are_not_silently_compared(self):
        with self.assertRaises(ValueError):
            bot.yokodori_snapshot({})
        with self.assertRaises(ValueError):
            bot.yokodori_snapshot({'ywp_user_event': {'rows': ['bad']}})


if __name__ == '__main__':
    unittest.main()
