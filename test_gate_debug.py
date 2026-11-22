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

# YWP/ywp_auto.py から extract_gate_related_keys と log_gate_debug をインポート
sys.path.insert(0, '/workspaces/saba')
from YWP.ywp_auto import extract_gate_related_keys, log_gate_debug


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


def test_log_gate_debug():
    """log_gate_debug() のテスト"""
    print("=" * 70)
    print("【テスト 2】log_gate_debug() のテスト")
    print("=" * 70)
    
    # テストケース 1: YWP_DEBUG_GATE=1 で実行
    print("\n【テスト 2-1】YWP_DEBUG_GATE=1 で実行")
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
    
    print("期待される出力:")
    print("  [GATE_DEBUG] stageId=28805, battleType=6")
    print("  [GATE_DEBUG] ✓ ゲート関連キーが見つかりました:")
    print("    - warpGate: dict (len=2)")
    print("    - gateList: list (len=2)")
    print()
    print("実際の出力:")
    log_gate_debug(test_response, 28805, 6)
    
    # テストケース 2: YWP_DEBUG_GATE=0 で実行
    print("\n【テスト 2-2】YWP_DEBUG_GATE=0 で実行（出力されない）")
    os.environ['YWP_DEBUG_GATE'] = '0'
    print("期待される出力: （なし）")
    print("実際の出力:")
    log_gate_debug(test_response, 28805, 6)
    print("✓ テスト 2-2 成功: デバッグモード無効時は出力されません")
    print()
    
    # テストケース 3: ゲート関連情報がない場合
    print("\n【テスト 2-3】ゲート関連情報がない場合")
    os.environ['YWP_DEBUG_GATE'] = '1'
    test_response_no_gate = {
        'rc': 0,
        'userId': 123456,
        'gameStart': {'battleCode': 'ABC123'}
    }
    print("期待される出力:")
    print("  [GATE_DEBUG] stageId=123, battleType=1")
    print("  [GATE_DEBUG] ゲート関連キーが見つかりません")
    print()
    print("実際の出力:")
    log_gate_debug(test_response_no_gate, 123, 1)
    print()


def main():
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  ゲートイベント対応 - デバッグ関数テスト".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\n")
    
    try:
        test_extract_gate_related_keys()
        test_log_gate_debug()
        
        print("=" * 70)
        print("【テスト結果】")
        print("=" * 70)
        print("✓ すべてのテストが完了しました")
        print("\n【次のステップ】")
        print("1. ゲートイベントが来るまで待機")
        print("2. YWP_DEBUG_GATE=1 で YWP を起動")
        print("3. ゲート情報をログから収集")
        print("4. .docs/GATE_COLLECTED_DATA.md に情報をまとめる")
        print("\n")
        
        return 0
    
    except Exception as e:
        print(f"\n✗ テスト実行エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
