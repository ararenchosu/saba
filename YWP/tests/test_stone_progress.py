import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import bot


class StoneProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path_patch = patch.object(
            bot, 'STONE_PROGRESS_PANELS_FILE',
            os.path.join(self.directory.name, 'panels.json'))
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.jobs_patch = patch.dict(bot.STONE_JOBS, {}, clear=True)
        self.jobs_patch.start()
        self.addCleanup(self.jobs_patch.stop)
        self.panels_patch = patch.dict(bot.STONE_PROGRESS_PANELS, {}, clear=True)
        self.panels_patch.start()
        self.addCleanup(self.panels_patch.stop)
        self.owner = SimpleNamespace(id=42)

    def job(self, number):
        return bot.StoneAccountJob(number, self.owner, 2, number * 100000, None, None)

    async def test_pagination_and_owner_check(self):
        bot.STONE_JOBS[42] = [self.job(i) for i in range(1, 12)]
        panel = bot.StoneProgressPanel(42, 100, 200)
        view = bot.StoneProgressView(panel)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(bot.stone_progress_embed(42).fields), 10)
        next_button = next(button for button in view.children if button.label == '次へ')
        self.assertFalse(next_button.disabled)

        interaction = SimpleNamespace(
            user=self.owner,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        await next_button.callback(interaction)
        self.assertEqual(panel.page, 1)
        self.assertEqual(len(interaction.edit_original_response.await_args.kwargs['embed'].fields), 1)

        other = SimpleNamespace(
            user=SimpleNamespace(id=99),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        self.assertFalse(await view.interaction_check(other))
        self.assertTrue(other.response.send_message.await_args.kwargs['ephemeral'])

        bot.STONE_JOBS[42] = []
        panel.state()
        self.assertEqual(panel.page, 0)

    async def test_saved_panel_restores_and_refreshes_when_jobs_change(self):
        panel = bot.StoneProgressPanel(42, 100, 200)
        bot.STONE_PROGRESS_PANELS[200] = panel
        self.assertTrue(bot.save_stone_progress_panels())
        bot.STONE_PROGRESS_PANELS.clear()
        bot.load_stone_progress_panels()
        panel = bot.STONE_PROGRESS_PANELS[200]
        self.assertEqual((panel.owner_id, panel.channel_id), (42, 100))

        message = SimpleNamespace(edit=AsyncMock())
        channel = MagicMock(spec=discord.TextChannel)
        channel.get_partial_message.return_value = message
        client = SimpleNamespace(get_channel=lambda channel_id: channel)
        await bot.refresh_stone_progress_panel(client, panel)
        self.assertIn('実行中の石垢ジョブはありません', message.edit.await_args.kwargs['embed'].description)
        await bot.refresh_stone_progress_panel(client, panel)
        self.assertEqual(message.edit.await_count, 1)

        job = self.job(1)
        bot.STONE_JOBS[42] = [job]
        await bot.refresh_stone_progress_panel(client, panel)
        self.assertEqual(len(message.edit.await_args.kwargs['embed'].fields), 1)
        job.completed = 1
        await bot.refresh_stone_progress_panel(client, panel)
        self.assertIn('1/2件', message.edit.await_args.kwargs['embed'].fields[0].value)
        bot.STONE_JOBS[42] = []
        await bot.refresh_stone_progress_panel(client, panel)
        self.assertIn('実行中の石垢ジョブはありません', message.edit.await_args.kwargs['embed'].description)

    async def test_command_sends_public_persistent_panel(self):
        async def send_message(**kwargs):
            bot.STONE_JOBS[42] = [self.job(1)]

        response = SimpleNamespace(send_message=AsyncMock(side_effect=send_message))
        interaction = SimpleNamespace(
            user=self.owner,
            channel_id=100,
            response=response,
            original_response=AsyncMock(return_value=SimpleNamespace(id=200)),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch.object(bot.bot, 'add_view') as add_view:
            await bot.stone_account_progress.callback(interaction)
        self.assertFalse(response.send_message.await_args.kwargs.get('ephemeral', False))
        self.assertTrue(response.send_message.await_args.kwargs['view'].is_persistent())
        self.assertEqual(add_view.call_args.kwargs['message_id'], 200)
        panel = bot.STONE_PROGRESS_PANELS[200]
        self.assertNotEqual(panel.rendered, panel.state())
        bot.STONE_PROGRESS_PANELS.clear()
        bot.load_stone_progress_panels()
        self.assertEqual(bot.STONE_PROGRESS_PANELS[200].owner_id, 42)

    async def test_estimate_uses_observed_rate_and_requires_data(self):
        job = self.job(1)
        job.count = 1
        job.current_account = 1
        with patch.object(bot.time, 'monotonic', side_effect=[100.0, 200.0]):
            bot.update_stone_estimate(job, 10)
            self.assertIsNone(job.estimated_finish)
            bot.update_stone_estimate(job, 20)
        remaining = (job.estimated_finish - bot.datetime.now()).total_seconds()
        self.assertAlmostEqual(remaining, (job.target_ypoint - 20) * 10, delta=1)
        field = bot.stone_progress_embed(42).fields
        bot.STONE_JOBS[42] = [job]
        self.assertIn('終了予定:', bot.stone_progress_embed(42).fields[0].value)
        self.assertEqual(field, [])

    async def test_hitodama_recovery_and_other_rc5(self):
        c = SimpleNamespace(
            refresh=MagicMock(),
            info=MagicMock(return_value={'hitodamaRecoverSec': 1}),
            buy_hitodama=MagicMock(side_effect=RuntimeError('Yマネー不足')),
            points=MagicMock(side_effect=[
                {'hitodama': 0, 'freeHitodama': 0},
                {'hitodama': 1, 'freeHitodama': 0},
            ]),
        )
        progress = AsyncMock()
        with patch.object(bot.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(bot, 'maint_window', return_value=None), \
             patch.dict(bot.ACCOUNT_PAUSE, {'paused': False}):
            recovered = await bot.wait_stone_hitodama(c, 123, {'resultCode': 5}, progress)
        self.assertTrue(recovered)
        self.assertEqual(c.refresh.call_count, 2)
        self.assertTrue(any('自然回復' in call.args[0] for call in progress.await_args_list))

        c.points = MagicMock(return_value={'hitodama': 2, 'freeHitodama': 0})
        self.assertFalse(await bot.wait_stone_hitodama(c, 123, {'resultCode': 5}, progress))
        c.points = MagicMock(return_value={'hitodama': 0})
        self.assertFalse(await bot.wait_stone_hitodama(c, 123, {'resultCode': 5}, progress))

    async def test_auto_buy_and_non_money_failure(self):
        c = SimpleNamespace(refresh=MagicMock(), buy_hitodama=MagicMock(return_value=5))
        progress = AsyncMock()
        self.assertTrue(await bot.buy_stone_hitodama(c, 2, progress))
        c.buy_hitodama.assert_called_once_with(bot.HITODAMA_BUY, current=2)
        c.refresh.assert_called_once()
        self.assertTrue(any('5個購入' in call.args[0] for call in progress.await_args_list))
        c.buy_hitodama.side_effect = RuntimeError('ショップ未解放')
        with self.assertRaisesRegex(RuntimeError, '自動購入に失敗.*ショップ未解放'):
            await bot.buy_stone_hitodama(c, 0, progress)

    async def test_rc5_buys_before_retry(self):
        c = SimpleNamespace(
            refresh=MagicMock(),
            points=MagicMock(return_value={'hitodama': 0, 'freeHitodama': 0}),
            buy_hitodama=MagicMock(return_value=5),
        )
        self.assertTrue(await bot.wait_stone_hitodama(c, 123, {'resultCode': 5}, AsyncMock()))
        c.buy_hitodama.assert_called_once_with(bot.HITODAMA_BUY, current=0)

    async def test_clear_stage_retries_confirmed_shortage_and_reports_other_rc5(self):
        c = SimpleNamespace(
            save={},
            battle_start=MagicMock(side_effect=[
                (5, {'resultCode': 5}, 1),
                (0, {'resultCode': 0, 'ywp_user_data': {'hitodama': 1}}, 1),
            ]),
            min_clear_time=MagicMock(return_value=0),
            battle_end=MagicMock(return_value=(0, {'resultCode': 0})),
        )
        handler = AsyncMock(return_value=True)
        with patch.object(bot.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(bot, 'jitter', return_value=0):
            await bot.clear_stage(c, 123, attempts=1, inspect=False, shortage_handler=handler)
        self.assertEqual(c.battle_start.call_count, 2)
        self.assertEqual(c.save['ywp_user_data'], {'hitodama': 1})

        c.battle_start = MagicMock(return_value=(
            5, {'resultCode': 5, 'dialogMsg': '条件を確認'}, 1))
        handler = AsyncMock(return_value=False)
        with patch.object(bot.asyncio, 'sleep', new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, 'ステージ 123: gameStart rc=5'):
                await bot.clear_stage(c, 123, attempts=1, inspect=False, shortage_handler=handler)

    async def test_modal_passes_timing_and_rejects_nonfinite_values(self):
        def label(value):
            return SimpleNamespace(component=SimpleNamespace(value=value))

        modal = SimpleNamespace(
            count=label('1'), target=label('100000'), password=label(''),
            name=label(''), timing=label('12,3'))
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot, 'start_stone_account_job', new=AsyncMock()) as start:
            await bot.StoneAccountModal.on_submit(modal, interaction)
            self.assertEqual(start.await_args.args[-2:], (12.0, 3.0))
            modal.timing = label('nan,3')
            await bot.StoneAccountModal.on_submit(modal, interaction)
            self.assertEqual(start.await_count, 1)
            self.assertTrue(interaction.response.send_message.await_args.kwargs['ephemeral'])

    async def test_stone_flow_uses_battle_time_and_interval(self):
        c = SimpleNamespace(
            refresh=MagicMock(),
            points=MagicMock(return_value={'ypoint': 0, 'hitodama': 4, 'freeHitodama': 0}),
            master_table=MagicMock(return_value=[]),
        )
        record = bot.AccountRecord('test@example.invalid', 'test', client=c)
        job = bot.StoneAccountJob(1, self.owner, 1, 10, None, None, 12, 3)
        job.current_account = 1
        sleep = AsyncMock()
        async def clear_stage(_client, stage_id, *args, **kwargs):
            c.points.return_value = {'ypoint': {1: 0, 2: 1, 3: 10}[stage_id]}
        clear = AsyncMock(side_effect=clear_stage)
        purchase = AsyncMock(return_value=True)
        with patch.object(bot, 'COIN_ACCOUNT_STAGE_IDS', (1,)), \
             patch.object(bot, 'HITODAMA_LOW', 5), \
             patch.object(bot, 'stone_event_stage_groups', return_value=([2], [3], 'event')), \
             patch.object(bot, 'prepare_stone_stage_deck', new=AsyncMock()), \
             patch.object(bot, 'buy_stone_hitodama', new=purchase), \
             patch.object(bot, 'clear_stage', new=clear), \
             patch.object(bot.asyncio, 'sleep', new=sleep), \
             patch.object(bot, 'jitter', side_effect=lambda value, *args, **kw: value), \
             patch.object(bot, 'maint_window', return_value=None), \
             patch.dict(bot.ACCOUNT_PAUSE, {'paused': False}):
            await bot.make_stone_account(record, 10, AsyncMock(), job)
        self.assertTrue(record.stone_ok)
        self.assertEqual(purchase.await_args.args[1], 4)
        self.assertEqual([call.args[1] for call in clear.await_args_list], [1, 2, 3])
        self.assertTrue(all(call.kwargs['battle_time'] == 12 for call in clear.await_args_list))
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [3, 3])


if __name__ == '__main__':
    unittest.main()
