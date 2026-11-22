# Phase 2: 全イベント解析デバッグ機能

## 概要

**Phase 1（準備フェーズ）** で実装したゲート情報抽出機能に加えて、**通常イベント・特殊イベント・ゲートイベント**など **すべてのイベント** を包括的に解析できるデバッグ機能を追加しました。

これにより、YWPボットが実際にどのようなイベント構造を受け取っているかを詳細に把握し、コードが正常に動作しているかを検証可能になりました。

---

## 追加されたデバッグ機能

### 1. `analyze_event_response(response: dict) → dict`

gameStart応答を包括的に解析し、イベントの構造情報を返します。

**戻り値:**
```python
{
    'keys': [...],           # すべてのキーのリスト
    'structure': {...},      # キー→型のマッピング
    'sizes': {...},          # list/dictの要素数
    'has_gate_info': bool    # ゲート関連情報の有無
}
```

**例:**
```python
result = analyze_event_response(js)
# result['keys']     → ['rc', 'userId', 'eventId', ...]
# result['structure'] → {'rc': 'int', 'userId': 'int', ...}
# result['has_gate_info'] → True/False
```

### 2. `log_event_debug(response: dict, stageId: int, battleType: int) → None`

環境変数 `YWP_DEBUG_EVENT=1` のとき、全イベント情報を詳細ログ出力します。

**出力内容:**
- イベントタイプの判定（通常イベント/ゲートイベント/特殊イベント）
- 応答キー数
- 応答構造（ゲート関連情報の有無を含む）
- 主要キーの値
- 全キー一覧

**環境変数:**
- `YWP_DEBUG_EVENT=1` → 有効（出力する）
- `YWP_DEBUG_EVENT=0` または未設定 → 無効（出力しない）

**使用例:**
```bash
# 通常イベント確認
YWP_DEBUG_EVENT=1 python ywp_auto.py

# ゲートイベント確認（全情報 + ゲート詳細）
YWP_DEBUG_EVENT=1 YWP_DEBUG_GATE=1 python ywp_auto.py

# 応答全体を確認（既存機能との併用）
YWP_DEBUG_EVENT=1 YWP_DEBUG_START=1 python ywp_auto.py
```

---

## 実装の詳細

### 追加位置

**ファイル:** `YWP/ywp_auto.py`

#### 1. `analyze_event_response()` 関数（2825-2880行付近）
```python
def analyze_event_response(response: dict) -> dict:
    """gameStart応答を包括的に解析し、イベント構造を返す"""
    keys = list(response.keys()) if isinstance(response, dict) else []
    structure = {}
    sizes = {}
    
    for key, value in response.items():
        value_type = type(value).__name__
        structure[key] = value_type
        if isinstance(value, (list, dict)):
            sizes[key] = len(value)
    
    gate_related = extract_gate_related_keys(response)
    has_gate = len(gate_related) > 0
    
    return {
        'keys': keys,
        'structure': structure,
        'sizes': sizes,
        'has_gate_info': has_gate
    }
```

#### 2. `log_event_debug()` 関数（2882-2920行付近）
```python
def log_event_debug(response: dict, stageId: int, battleType: int) -> None:
    """YWP_DEBUG_EVENT=1 のとき、全イベント情報をログ出力"""
    if os.environ.get('YWP_DEBUG_EVENT') != '1':
        return
    
    # イベントタイプ判定
    event_type = "ゲートイベント（ワープ選択）" if battleType == 6 else "通常イベント（周回）"
    
    # ゲート関連情報の有無
    gate_info = extract_gate_related_keys(response)
    has_gate = "✓ あり" if gate_info else "✗ なし"
    
    # ログ出力
    print(f"[EVENT_DEBUG] ═════════════════════════════════════════════")
    print(f"[EVENT_DEBUG] stageId={stageId}, battleType={battleType}")
    print(f"[EVENT_DEBUG] ═════════════════════════════════════════════")
    print(f"[EVENT_DEBUG] イベントタイプ: {event_type}")
    print(f"[EVENT_DEBUG] 応答キー数: {len(response.keys())}")
    # ... 詳細出力
```

#### 3. `battle_start()` への統合（1620-1660行）
```python
def battle_start(self, stageId, battleType=None):
    # ... 既存コード ...
    if isinstance(js, dict):
        dump_start_payload(js)
        # 全イベント解析ログ出力
        log_event_debug(js, stageId, battleType)
        # ゲート関連情報をデバッグログ出力
        log_gate_debug(js, stageId, battleType)
    return rc, js, battleType
```

---

## テスト結果

### テストスクリプト: `test_gate_debug.py`

**実行:**
```bash
cd /workspaces/saba
python test_gate_debug.py
```

**テスト項目:**
1. ✓ `extract_gate_related_keys()` のテスト（3ケース）
2. ✓ `analyze_event_response()` のテスト（2ケース）
3. ✓ `log_event_debug()` のテスト（3ケース）
4. ✓ `log_gate_debug()` のテスト（1ケース）

**全テスト成功:** 9/9 ✓

---

## 動作検証

### テスト出力例

#### 通常イベント解析
```
[EVENT_DEBUG] ═════════════════════════════════════════════
[EVENT_DEBUG] stageId=123, battleType=1
[EVENT_DEBUG] ═════════════════════════════════════════════
[EVENT_DEBUG] イベントタイプ: 通常イベント（周回）
[EVENT_DEBUG] 応答キー数: 8
[EVENT_DEBUG] 
[EVENT_DEBUG] 【応答構造】
[EVENT_DEBUG]   ✗ ゲート関連情報: なし
[EVENT_DEBUG] 
[EVENT_DEBUG] 【主要キー】
[EVENT_DEBUG]   rc: int = 0
[EVENT_DEBUG]   userId: int = 123456
[EVENT_DEBUG]   eventId: int = 1359
[EVENT_DEBUG]   eventName: str = "ぷにぷにフェスタ"
...
```

#### ゲートイベント解析
```
[EVENT_DEBUG] ═════════════════════════════════════════════
[EVENT_DEBUG] stageId=28805, battleType=6
[EVENT_DEBUG] ═════════════════════════════════════════════
[EVENT_DEBUG] イベントタイプ: ゲートイベント（ワープ選択）
[EVENT_DEBUG] 応答キー数: 7
[EVENT_DEBUG] 
[EVENT_DEBUG] 【応答構造】
[EVENT_DEBUG]   ✓ ゲート関連情報: あり (3個)
[EVENT_DEBUG]       - warpGate: list (len=3)
[EVENT_DEBUG]       - gateList: list (len=3)
[EVENT_DEBUG]       - eventWarp: dict (len=1)
...
```

---

## 利用可能なデバッグモード一覧

| 環境変数 | 機能 | 出力内容 |
|---------|------|---------|
| `YWP_DEBUG_EVENT=1` | 全イベント解析 | イベント構造・タイプ・すべてのキー情報 |
| `YWP_DEBUG_GATE=1` | ゲート情報のみ | warpGate・gateList・eventWarpなど |
| `YWP_DEBUG_START=1` | 応答全体ダンプ | gameStart応答をJSON形式で出力（既存） |

### 推奨される使用方法

**1. 通常イベント確認:**
```bash
YWP_DEBUG_EVENT=1 python ywp_auto.py
```

**2. ゲートイベント確認（詳細）:**
```bash
YWP_DEBUG_EVENT=1 YWP_DEBUG_GATE=1 python ywp_auto.py
```

**3. 応答全体確認:**
```bash
YWP_DEBUG_EVENT=1 YWP_DEBUG_START=1 python ywp_auto.py
```

---

## 次のステップ

✓ **Phase 2 完了:**
- 全イベント解析機能を実装
- battle_start()に統合
- テスト実施（全成功）
- ドキュメント作成

**今後の予定:**
1. ゲートイベント実装の準備完了
2. 実際のゲートイベント来現時に、`YWP_DEBUG_EVENT=1` でログ収集
3. 収集したデータを `.docs/GATE_COLLECTED_DATA.md` にまとめる
4. ゲートイベント本実装を開始

---

## 関連ドキュメント

- [GATE_PHASE1_COMPLETE.md](./GATE_PHASE1_COMPLETE.md) - Phase 1（準備フェーズ）完了サマリー
- [GATE_DEBUG_GUIDE.md](./GATE_DEBUG_GUIDE.md) - ゲート情報抽出ガイド
- [GATE_EVENT_STRUCTURE.md](./GATE_EVENT_STRUCTURE.md) - ゲートイベント構造分析

---

**作成日:** 2025年
**最終更新:** 2025年
