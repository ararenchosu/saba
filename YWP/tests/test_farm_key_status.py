import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bot


class FarmKeyStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = SimpleNamespace(id=42)
        self.job = bot.FarmJob(self.owner, 30101001, 10, 5, 2)
        self.jobs = patch.dict(bot.JOBS, {42: [self.job]}, clear=True)
        self.jobs.start()
        self.addCleanup(self.jobs.stop)

    async def test_select_job_shows_key_holdings_and_observed_increase(self):
        self.job.item_prev = {'21359011': 2, '21359016': 4}
        c = SimpleNamespace(save={})
        with patch.object(bot, 'log_line'):
            bot.on_items(self.job, c, {
                'ywp_user_item': '21359011|5*21359016|4',
            })
        interaction = SimpleNamespace(
            data={'values': ['1']}, channel_id=1, message=None,
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await bot.FarmDashboardView(42)._select_job(interaction)
        embed = interaction.response.edit_message.await_args.kwargs['embed']
        key_field = next(field for field in embed.fields if field.name == '🔑 鍵の状況')
        self.assertIn('現在：第1面', key_field.value)
        self.assertIn('第1の鍵（赤）：`5/30,000` / +3', key_field.value)
        self.assertIn('第1の鍵（青）：`4/30,000` / +0', key_field.value)
        self.assertIn('ドロップ以外', key_field.value)

    async def test_update_switches_to_current_preset_stage(self):
        self.job.stage_ids = [30101001, 30101002]
        self.job.stage_pos = 1
        self.job.item_prev = {'21359011': 9, '21359021': 30000}
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        async def finish_refresh():
            await asyncio.sleep(0)
            self.job.refreshed.set()

        task = asyncio.create_task(finish_refresh())
        await bot.FarmDashboardView(42, self.job.jid)._refresh_job(interaction)
        await task
        embed = interaction.edit_original_response.await_args.kwargs['embed']
        text = next(field.value for field in embed.fields if field.name == '🔑 鍵の状況')
        self.assertIn('現在：第2面', text)
        self.assertIn('第2の鍵（赤）：`30,000/30,000（埋まり）`', text)
        self.assertNotIn('第1の鍵', text)

    def test_missing_inventory_and_unrecognised_stage(self):
        self.assertIn('取得できていません', bot.key_status_text(self.job))
        self.job.stage_id = 30101010
        self.assertIn('判定できません', bot.key_status_text(self.job))

    async def test_refresh_updates_inventory_before_reporting_completion(self):
        self.job.item_prev = {'21359011': 2}
        self.job.current_items = bot.tracked_inventory(self.job.item_prev)
        self.job.want_refresh = True
        c = MagicMock()
        c.save = {'ywp_user_item': '21359011|7'}
        c.points.return_value = {}
        c.save_shape.return_value = {}
        c.progress_detail.return_value = {}
        with patch.object(bot, 'maybe_buy_hitodama', AsyncMock()), \
                patch.object(bot, 'log_line'):
            await bot.refresh_points(self.job, c, 2)
        self.assertTrue(self.job.refreshed.is_set())
        self.assertIn('`7/30,000` / +5', bot.key_status_text(self.job))


if __name__ == '__main__':
    unittest.main()
