# 【準備フェーズ】ゲートイベント対応 - Phase 1 実行ガイド

## 📋 概要

このガイドは、**ゲートイベント実行を待たずに、今すぐできる準備作業** をまとめています。

ゲートイベント実装の第一段階（Phase 1）として：
- ✅ ゲート情報抽出関数を実装済み
- ✅ デバッグログ機能を実装済み
- 🎯 ゲートイベント実行時にゲート情報を収集
- ✏️ 本実装に向けた仕様を確定

---

## 🚀 いますぐやること

### **Step 1: 環境変数を設定**

ゲートイベントが来たら、以下で起動してください：

```bash
# 【重要】環境変数を設定してから YWP を起動
export YWP_DEBUG_GATE=1
python3 start_ywp.py
```

または、ワンライナーで：
```bash
YWP_DEBUG_GATE=1 python3 start_ywp.py
```

### **Step 2: ゲートイベントの周回**

通常通り YWP で周回を実行してください。ゲートが出現したら、自動的に以下がログに出力されます：

```
[GATE_DEBUG] stageId=XXXXX, battleType=6
[GATE_DEBUG] ✓ ゲート関連キーが見つかりました:
  - warpGate: dict (len=5)
  - gateList: list (len=3)
  - selectGate: ...
  ...
```

### **Step 3: ログを確認・保存**

ゲート情報が出力されたら、以下を実施してください：

```bash
# ログをコピー＆保存
cp YWP/logs/ywp-*.log /tmp/gate_debug_$(date +%s).log

# または、このコマンドでゲート情報だけを抽出
grep "\[GATE_DEBUG\]" YWP/logs/ywp-*.log > /tmp/gate_info.txt
```

---

## 📊 収集される情報

準備フェーズで収集すべき情報：

| 項目 | 説明 | 重要度 |
|------|------|--------|
| **ゲート関連キー** | gameStart応答内のゲート情報キー名（warpGate等） | ⭐⭐⭐ |
| **キーの型** | dict か list か、要素数 | ⭐⭐ |
| **ゲート内容** | 敵情報、難易度、報酬等 | ⭐⭐⭐ |
| **選択方法** | 複数ゲートの選別ロジック（難易度優先等） | ⭐⭐⭐ |
| **gameEndパラメータ** | ゲート選択後、gameEndに追加するパラメータ | ⭐⭐⭐ |

---

## 🔍 デバッグ関数の仕様

### `extract_gate_related_keys(js)`

**目的**: gameStart応答からゲート関連キーを抽出

**入力**: gameStart応答（dict）

**出力**: ゲート関連キーのマッピング

**例**:
```python
gate_keys = extract_gate_related_keys(js)
# {
#   'warpGate': {...},
#   'gateList': [...],
#   'eventWarp': {...}
# }
```

### `log_gate_debug(js, stageId, battleType)`

**目的**: ゲート関連情報を標準出力にログ出力

**有効化**: `export YWP_DEBUG_GATE=1`

**出力例**:
```
[GATE_DEBUG] stageId=28805, battleType=6
[GATE_DEBUG] ✓ ゲート関連キーが見つかりました:
  - warpGate: dict (len=5)
  - gateList: list (len=3)
```

---

## 📝 収集後にやること

### **1. ゲート情報をまとめる**

ログから以下を確認：
```
1. どのキーがゲート情報を持つか
2. その型（dict/list）と要素数
3. 内部構造（key-value のマッピング）
```

例：
```json
{
  "warpGate": {
    "gateId": 1,
    "difficulty": "hard",
    "enemy": {...}
  },
  "gateList": [
    {"gateId": 1, ...},
    {"gateId": 2, ...},
    {"gateId": 3, ...}
  ]
}
```

### **2. 選択ロジックを確認**

複数ゲートがある場合：
- ゲート情報の中に「推奨」「難易度」「報酬」の項目があるか
- ランダム選択 vs 固定優先度 か

### **3. gameEndパラメータを特定**

ゲート選択後、gameEndに渡すべきパラメータ：
- ゲートID
- 選択時刻
- その他のメタデータ

---

## 🛠️ トラブルシューティング

### **Q: ゲート関連キーが見つからない**

**A**: 以下を確認してください：
- `YWP_DEBUG_GATE=1` が正しく設定されているか
- battleType=6 のステージで実行しているか
- gameStart応答が正常に返ってきているか

### **Q: ログが多すぎて見づらい**

**A**: 以下で フィルタリングしてください：
```bash
# ゲート関連ログのみ抽出
grep "\[GATE_DEBUG\]" YWP/logs/ywp-*.log

# または、ファイルに保存
grep "\[GATE_DEBUG\]" YWP/logs/ywp-*.log > /tmp/gate.log
```

### **Q: gameStart応答全体を確認したい**

**A**: 既存の `YWP_DEBUG_START=1` を使用してください：
```bash
YWP_DEBUG_START=1 python3 start_ywp.py
```

---

## ✅ チェックリスト

準備フェーズの完了まで：

- [ ] `YWP_DEBUG_GATE=1` を設定可能にした
- [ ] battle_start()にデバッグログの呼び出しを追加（済み）
- [ ] 環境変数が正しく動作することを確認
- [ ] ゲートイベント実行時にログが出力されることを確認
- [ ] ゲート情報を収集・保存した
- [ ] ゲート情報の構造をまとめた
- [ ] 選択ロジックを特定した
- [ ] gameEndパラメータを特定した

---

## 📞 次のフェーズ（Phase 2）へ

ゲート情報の収集が完了したら：

1. 収集したゲート情報を `.docs/GATE_COLLECTED_DATA.md` にまとめてください
2. その情報をもとに、本実装の仕様書を作成します
3. `battle_start()` と `battle_end()` を修正して、ゲート選択ロジックを実装

---

## 📚 参考資料

- `.docs/GATE_IMPLEMENTATION_ROADMAP.md` - 全体の5段階ロードマップ
- `YWP/ywp_auto.py:1620-1660` - `battle_start()` の実装
- `YWP/ywp_auto.py:2825-2880` - デバッグ関数の実装

