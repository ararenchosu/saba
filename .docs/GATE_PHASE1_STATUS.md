# 🚀 【準備フェーズ完了】ゲートイベント対応 実行ロードマップ

## ✅ 完了した準備

| 項目 | 状態 | 詳細 |
|------|------|------|
| extract_gate_related_keys() | ✅ 実装 | gameStart応答からゲート情報を抽出 |
| log_gate_debug() | ✅ 実装 | YWP_DEBUG_GATE=1 で有効化 |
| battle_start() 統合 | ✅ 実装 | デバッグログを自動呼び出し |
| テストスクリプト | ✅ 完成 | test_gate_debug.py（全テスト成功） |
| ガイドドキュメント | ✅ 完成 | GATE_PHASE1_GUIDE.md |

---

## 🎯 今後のフロー

### **Phase 1: 情報収集（現在地・ゲート実行時）**

**やること:**
```bash
# ゲートイベント実行時に以下で起動
export YWP_DEBUG_GATE=1
python3 start_ywp.py
```

**得られる情報:**
- ✓ ゲート関連キーの特定（warpGate, gateList, eventWarp等）
- ✓ キーの型と構造
- ✓ ゲート内の敵・難易度・報酬情報

**所要時間:** ゲート出現まで待機 → 1周回

---

### **Phase 2: 情報整理・仕様確定（本実装前）**

**やること:**
1. ゲート情報をJSON形式でまとめる
2. `.docs/GATE_COLLECTED_DATA.md` を作成
3. ゲート選択ロジックを決定
4. gameEndパラメータを特定

**成果物:**
- `.docs/GATE_COLLECTED_DATA.md` - 収集データとの仕様
- `.docs/GATE_IMPLEMENTATION_SPEC.md` - 実装仕様書

**所要時間:** 2-4時間（ログ分析）

---

### **Phase 3: コード実装（準備完了後）**

**修正対象:**
1. `YWPClient.battle_start()` - ゲート情報を受け取る
2. 新規メソッド `_select_gate()` - ゲート選択ロジック
3. 新規メソッド `_handle_gate_event()` - ゲート処理全体
4. `YWPClient.battle_end()` - gameEndにゲート情報を追加

**実装コード例:**
```python
def battle_start(self, stageId, battleType=None):
    # ... 既存のコード ...
    if isinstance(js, dict):
        # 【Phase 3】ゲート処理を追加
        if battleType == 6 and 'warpGate' in js:
            gate_info = self._select_gate(js)
            js['_selected_gate'] = gate_info
        
        dump_start_payload(js)
        log_gate_debug(js, stageId, battleType)
    
    return rc, js, battleType
```

**所要時間:** 3-6時間（実装・テスト）

---

### **Phase 4: テスト・検証（本番前）**

**実施項目:**
- [ ] ユニットテスト（_select_gate()）
- [ ] 統合テスト（battle_start() → battle_end()）
- [ ] 複数ゲート選択テスト
- [ ] エラーハンドリングテスト
- [ ] ゲート周回の成功率検証

**所要時間:** 2-4時間

---

### **Phase 5: デプロイ・ドキュメント更新**

**実施項目:**
- [ ] 本番デプロイ
- [ ] README.md を更新
- [ ] ゲートイベント対応を明記
- [ ] 周回効率の報告

**所要時間:** 1時間

---

## 📂 ファイル構成

```
.docs/
├── GATE_IMPLEMENTATION_ROADMAP.md    ← 全体の5段階ロードマップ
├── GATE_PHASE1_GUIDE.md              ← 準備フェーズ実行ガイド【現在地】
├── GATE_COLLECTED_DATA.md            ← 【Phase 2】収集データまとめ
├── GATE_IMPLEMENTATION_SPEC.md       ← 【Phase 2】実装仕様書
└── GATE_TEST_RESULTS.md              ← 【Phase 4】テスト結果

YWP/
├── ywp_auto.py                       ← メイン実装ファイル
│   ├── extract_gate_related_keys()   ✅ 実装済
│   ├── log_gate_debug()              ✅ 実装済
│   ├── _select_gate()                ⏳ Phase 3 で実装予定
│   └── _handle_gate_event()          ⏳ Phase 3 で実装予定
└── logs/
    └── ywp-*.log                     ← デバッグログ出力先

test_gate_debug.py                    ← テストスクリプト
```

---

## ⏰ タイムライン

| フェーズ | 状態 | 予定工数 | 開始日 | 完了予定 |
|---------|------|---------|--------|---------|
| **Phase 1** | ✅ 完了 | 0h | - | - |
| **Phase 2** | 🔄 待機 | 2-4h | ゲート実行時 | 同日 |
| **Phase 3** | ⏳ 予定 | 3-6h | Phase 2 完了後 | +1-2日 |
| **Phase 4** | ⏳ 予定 | 2-4h | Phase 3 完了後 | +1日 |
| **Phase 5** | ⏳ 予定 | 1h | Phase 4 完了後 | +0.5日 |
| **合計** | - | 8-15h | - | +3-4日 |

---

## 🎓 チェックリスト - Phase 1（準備完了時点）

準備フェーズの完了確認：

- [x] `extract_gate_related_keys()` を実装
- [x] `log_gate_debug()` を実装
- [x] `battle_start()` にデバッグログを統合
- [x] テストスクリプトを実装・実行（全成功）
- [x] ガイドドキュメントを作成
- [x] コミットして Git に保存
- [ ] ゲートイベント実行時に YWP_DEBUG_GATE=1 で検証
- [ ] ゲート情報をログから抽出

---

## 📞 トラブルシューティング

### **Q: ゲート関連キーが見つからない場合**

**A**: 以下を確認：
```bash
# 1. battleType=6 のステージか確認
grep "battleType=6" YWP/logs/ywp-*.log

# 2. gameStart応答全体を確認
export YWP_DEBUG_START=1
python3 start_ywp.py

# 3. ゲート情報の場所が異なる可能性
grep -i "warp\|gate\|choice" YWP/logs/ywp-*.log
```

### **Q: 環境変数が反映されない**

**A**: 以下を試してください：
```bash
# 1. 環境変数を確認
echo $YWP_DEBUG_GATE

# 2. ワンライナーで実行
YWP_DEBUG_GATE=1 python3 start_ywp.py

# 3. エクスポートしてから実行
export YWP_DEBUG_GATE=1
python3 start_ywp.py
```

---

## 🔗 参考リンク

- [YWP ゲートイベント対応ロードマップ](.docs/GATE_IMPLEMENTATION_ROADMAP.md)
- [Phase 1 実行ガイド](.docs/GATE_PHASE1_GUIDE.md)
- [テストスクリプト](/test_gate_debug.py)
- [YWP/ywp_auto.py](/YWP/ywp_auto.py)（1620-1660行: battle_start）

---

## 💡 Tips

1. **ゲート実行を待つ必要はありません** - 準備フェーズはすでに完了しています
2. **環境変数は重要** - YWP_DEBUG_GATE=1 を忘れずに設定してください
3. **ログは保存してください** - 後で分析する際に必要です
4. **複数ゲート情報に注目** - ゲート選択ロジックの実装に必須
5. **gameEndパラメータを特定** - Phase 3 の実装に直結

---

**作成日**: 2026-11-22  
**最終更新**: 2026-11-22  
**ステータス**: 準備フェーズ完了 ✅
