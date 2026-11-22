#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ゲート情報抽出関数のテストスクリプト

実際にゲートイベントが実行される前に、
デバッグ関数が正しく動作することを確認します。
"""

import os
import sys
import json

# YWP/ywp_auto.py から 関数をインポート
sys.path.insert(0, '/workspaces/saba')
from YWP.ywp_auto import extract_gate_related_keys, analyze_event_response, log_event_debug, log_gate_debug


def test_extract_gate_related_keys():
    """extract_gate_related_keys() のテスト"""
    print("=" * 70)
    print("【テスト 1】extract_gate_related_keys() のテスト")
    print("=" * 70)
    
    # テストケース 1: ゲート情報あり
    test_response_with_gate = {
        'rc': 0,
        'userId': 123456,
        'warpGate': {
            'gateId': 1,
            'difficulty': 'hard',
            'enemy': {'id': 100, 'name': 'ボス'}
        },
        'gateList': [
            {'gateId': 1, 'difficulty': 'hard'},
            {'gateId': 2, 'difficulty': 'normal'},
            {'gateId': 3, 'difficulty': 'easy'}
        ],
        'eventWarp': {'warpId': 999},
        'gameStart': {'battleCode': 'ABC123'},
        'otherField': 'これはゲート関連ではない'
    }
    
    result = extract_gate_related_keys(test_response_with_gate)
    print(f"✓ ゲート関連キーが見つかりました:")
    for key in sorted(result.keys()):
        print(f"  - {key}")
    
    expected_gates = {'warpGate', 'gateList', 'eventWarp'}
    actual_gates = set(result.keys())
    if expected_gates.issubset(actual_gates):
        print(f"✓ テスト 1 成功: すべてのゲート関連キーが検出されました")
    else:
        print(f"✗ テスト 1 失敗: 期待値={expected_gates}, 実際={actual_gates}")
    print()
    
    # テストケース 2: ゲート情報なし
    test_response_no_gate = {
        'rc': 0,
        'userId': 123456,
        'gameStart': {'battleCode': 'ABC123'},
        'userData': {'name': 'Player'},
        'stageInfo': {'stageId': 123}
    }
    
    result = extract_gate_related_keys(test_response_no_gate)
    if len(result) == 0:
        print(f"✓ テスト 2 成功: ゲート関連キーなしのレスポンスで空の辞書を返しました")
    else:
        print(f"✗ テスト 2 失敗: ゲートなしなのに {len(result)} 個のキーが返されました")
    print()
    
    # テストケース 3: 大文字小文字を区別しない検索
    test_response_mixed_case = {
        'WarpGate': {'data': 1},
        'EVENTWARP': {'data': 2},
        'selectGATE': {'data': 3}
    }
    
    result = extract_gate_related_keys(test_response_mixed_case)
    if len(result) == 3:
        print(f"✓ テスト 3 成功: 大文字小文字を区別せずに検出しました")
    else:
        print(f"✗ テスト 3 失敗: 期待値=3個, 実際={len(result)}個")
    print()


def test_analyze_event_response():
    """analyze_event_response() のテスト"""
    print("=" * 70)
    print("【テスト 2】analyze_event_response() のテスト")
    print("=" * 70)
    
    # テストケース 1: 通常イベント構造
    test_normal_event = {
        'rc': 0,
        'userId': 123456,
        'eventId': 1359,
        'eventName': 'ぷにぷにフェスタ',
        'stageData': {'stageId': 123, 'difficulty': 1},
        'enemy': [
            {'id': 100, 'name': 'ザコ敵1'},
            {'id': 101, 'name': 'ザコ敵2'}
        ],
        'eventPoint': 50
    }
    
    result = analyze_event_response(test_normal_event)
    print(f"✓ イベント解析成功")
    print(f"  キー数: {len(result['keys'])}")
    print(f"  構造: {result['structure']}")
    
    if len(result['keys']) > 0:
        print(f"✓ テスト 2-1 成功: 通常イベントを解析しました")
    else:
        print(f"✗ テスト 2-1 失敗: キーが取得できませんでした")
    print()
    
    # テストケース 2: ゲートイベント構造
    test_gate_event = {
        'rc': 0,
        'userId': 123456,
        'eventId': 1360,
        'warpGate': [
            {'gateId': 1, 'difficulty': 'hard'},
            {'gateId': 2, 'difficulty': 'normal'}
        ],
        'gateList': [
            {'gateId': 1, 'name': 'ゲート1'},
            {'gateId': 2, 'name': 'ゲート2'}
        ]
    }
    
    result = analyze_event_response(test_gate_event)
    if 'warpGate' in result['structure']:
        print(f"✓ テスト 2-2 成功: ゲートイベントを解析しました")
        print(f"  warpGate: {result['structure']['warpGate']}")
        print(f"  warpGate 要素数: {result['sizes']['warpGate']}")
    else:
        print(f"✗ テスト 2-2 失敗: warpGate が検出されませんでした")
    print()


def test_log_event_debug():
    """log_event_debug() のテスト"""
    print("=" * 70)
    print("【テスト 3】log_event_debug() のテスト")
    print("=" * 70)
    
    # テストケース 1: YWP_DEBUG_EVENT=1 で実行
    print("\n【テスト 3-1】YWP_DEBUG_EVENT=1 で実行（通常イベント）")
    os.environ['YWP_DEBUG_EVENT'] = '1'
    
    test_response = {
        'rc': 0,
        'userId': 123456,
        'eventId': 1359,
        'eventName': 'ぷにぷにフェスタ',
        'stageData': {'stageId': 123, 'difficulty': 1},
        'enemy': [
            {'id': 100, 'name': 'ザコ敵1'},
            {'id': 101, 'name': 'ザコ敵2'},
            {'id': 102, 'name': 'ザコ敵3'}
        ],
        'eventPoint': 50,
        'rewards': {'coin': 1000, 'exp': 500}
    }
    
    print("期待される出力: イベント情報の詳細ログ")
    print("実際の出力:")
    log_event_debug(test_response, 123, 1)
    print("✓ テスト 3-1 成功: 通常イベント情報が出力されました")
    print()
    
    # テストケース 2: YWP_DEBUG_EVENT=1 で実行（ゲートイベント）
    print("【テスト 3-2】YWP_DEBUG_EVENT=1 で実行（ゲートイベント）")
    os.environ['YWP_DEBUG_EVENT'] = '1'
    
    test_gate_response = {
        'rc': 0,
        'userId': 123456,
        'eventId': 1360,
        'eventName': 'ゲートイベント',
        'warpGate': [
            {'gateId': 1, 'difficulty': 'hard', 'enemy': {'id': 200}},
            {'gateId': 2, 'difficulty': 'normal', 'enemy': {'id': 201}},
            {'gateId': 3, 'difficulty': 'easy', 'enemy': {'id': 202}}
        ],
        'gateList': [
            {'gateId': 1, 'name': 'ゲート1'},
            {'gateId': 2, 'name': 'ゲート2'},
            {'gateId': 3, 'name': 'ゲート3'}
        ],
        'eventWarp': {'warpId': 999}
    }
    
    print("実際の出力:")
    log_event_debug(test_gate_response, 28805, 6)
    print("✓ テスト 3-2 成功: ゲートイベント情報が出力されました")
    print()
    
    # テストケース 3: YWP_DEBUG_EVENT=0 で実行
    print("【テスト 3-3】YWP_DEBUG_EVENT=0 で実行（出力されない）")
    os.environ['YWP_DEBUG_EVENT'] = '0'
    print("期待される出力: （なし）")
    print("実際の出力:")
    log_event_debug(test_response, 123, 1)
    print("✓ テスト 3-3 成功: デバッグモード無効時は出力されません")
    print()


def test_log_gate_debug():
    """log_gate_debug() のテスト"""
    print("=" * 70)
    print("【テスト 4】log_gate_debug() のテスト")
    print("=" * 70)
    
    # テストケース 1: YWP_DEBUG_GATE=1 で実行
    print("\n【テスト 4-1】YWP_DEBUG_GATE=1 で実行")
    os.environ['YWP_DEBUG_GATE'] = '1'
    
    test_response = {
        'rc': 0,
        'warpGate': {'gateId': 1, 'difficulty': 'hard'},
        'gateList': [
            {'gateId': 1, 'name': 'ゲート1'},
            {'gateId': 2, 'name': 'ゲート2'}
        ],
        'otherField': 'test'
    }
    
    print("実際の出力:")
    log_gate_debug(test_response, 28805, 6)
    print("✓ テスト 4-1 成功: ゲート関連情報が出力されました")
    print()


def main():
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  ゲートイベント対応 - 全イベント解析テスト".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\n")
    
    try:
        test_extract_gate_related_keys()
        test_analyze_event_response()
        test_log_event_debug()
        test_log_gate_debug()
        
        print("=" * 70)
        print("【テスト結果】")
        print("=" * 70)
        print("✓ すべてのテストが完了しました")
        print("\n【利用可能なデバッグモード】")
        print("1. YWP_DEBUG_EVENT=1  - 全イベント情報を詳細出力")
        print("2. YWP_DEBUG_GATE=1   - ゲート関連情報のみ出力")
        print("3. YWP_DEBUG_START=1  - gameStart応答全体をダンプ（既存）")
        print("\n【推奨される使用方法】")
        print("- 通常イベント確認: YWP_DEBUG_EVENT=1")
        print("- ゲートイベント確認: YWP_DEBUG_EVENT=1 + YWP_DEBUG_GATE=1")
        print("- 応答全体確認: YWP_DEBUG_START=1")
        print("\n")
        
        return 0
    
    except Exception as e:
        print(f"\n✗ テスト実行エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
