# YWP ゲートイベント対応 - ドキュメント索引

## 📋 ドキュメント構成

このディレクトリ（`.docs/`）には、YWPボットのゲートイベント対応に関する詳細ドキュメントが格納されています。

---

## 📚 主要ドキュメント

### Phase 1: 準備フェーズ（完了 ✓）

**[GATE_PHASE1_COMPLETE.md](./GATE_PHASE1_COMPLETE.md)**
- Phase 1（準備フェーズ）の完了サマリー
- 実装内容・テスト結果・進捗状況
- **ゲート情報抽出関数の基本実装**

**[GATE_DEBUG_GUIDE.md](./GATE_DEBUG_GUIDE.md)**
- ゲート情報抽出のデバッグガイド
- extract_gate_related_keys() の詳細説明
- 実装手順・トラブルシューティング

**[GATE_EVENT_STRUCTURE.md](./GATE_EVENT_STRUCTURE.md)**
- ゲートイベントのデータ構造分析
- battleType=6 の仕様
- gameStart応答の構造図

### Phase 2: 全イベント解析デバッグ機能（完了 ✓）

**[PHASE2_FULL_EVENT_DEBUG.md](./PHASE2_FULL_EVENT_DEBUG.md)**
- 全イベント解析機能の実装内容
- analyze_event_response()・log_event_debug() の詳細
- テスト結果・動作検証
- すべてのデバッグモード一覧

### Phase 3: Discordパネル実装（完了 ✓）

**[DISCORD_EVENT_ANALYSIS_PANEL.md](./DISCORD_EVENT_ANALYSIS_PANEL.md)** ← **NEW**
- Discordパネルからのイベント解析機能
- EventAnalysisModal・EventAnalysisPanelView の詳細
- 使用方法・入力例
- パネル設置・操作ガイド

---

## 🔧 実装関連

### コード位置

| ファイル | 行番号 | 機能 |
|--------|--------|------|
| `YWP/bot.py` | 10120-10160 | `event_analysis_embed()` |
| `YWP/bot.py` | 10163-10200 | `EventAnalysisModal` |
| `YWP/bot.py` | 10203-10213 | `EventAnalysisPanelView` |
| `YWP/bot.py` | 10216-10245 | `event_analysis_panel_embed()` |
| `YWP/bot.py` | 10248-10267 | `/イベント解析パネル設置` |
| `YWP/ywp_auto.py` | 2825-2880 | `analyze_event_response()` |
| `YWP/ywp_auto.py` | 2882-2920 | `log_event_debug()` |
| `YWP/ywp_auto.py` | 1960-1990 | `extract_gate_related_keys()` |
| `YWP/ywp_auto.py` | 1992-2030 | `log_gate_debug()` |
| `YWP/ywp_auto.py` | 1620-1660 | `battle_start()` ← 統合点 |

### テストスクリプト

| スクリプト | 機能 | 実行コマンド |
|----------|------|-----------|
| `test_gate_debug.py` | ゲート・全イベント解析テスト | `python test_gate_debug.py` |
| `test_discord_event_analysis.py` | Discordパネルテスト | `python test_discord_event_analysis.py` |

**テスト実行結果:**
- test_gate_debug.py: 9/9 ✓ 成功
- test_discord_event_analysis.py: 9/9 ✓ 成功

---

## 🚀 デバッグモード一覧

### YWP_DEBUG_EVENT=1（全イベント解析）

**全イベント情報を詳細出力**
```bash
YWP_DEBUG_EVENT=1 python ywp_auto.py
```

出力内容:
- イベントタイプの判定（通常/ゲート/特殊）
- 応答キー数
- 応答構造（ゲート関連情報の有無）
- 主要キーの値
- 全キー一覧

**対応イベント:**
- ✓ 通常イベント（battleType=1）
- ✓ ゲートイベント（battleType=6）
- ✓ 特殊イベント（battleType=20など）

### YWP_DEBUG_GATE=1（ゲート情報のみ）

**ゲート関連情報のみを出力**
```bash
YWP_DEBUG_GATE=1 python ywp_auto.py
```

出力内容:
- warpGate・gateList・eventWarp の有無
- 各要素の型・サイズ

### YWP_DEBUG_START=1（応答全体ダンプ）

**gameStart応答全体をJSON形式で出力**
```bash
YWP_DEBUG_START=1 python ywp_auto.py
```

出力内容:
- gameStart応答の全JSON構造
- 整形済み出力

---

## 📱 Discordパネル使用方法

### 1️⃣ パネル設置（管理者のみ）

```
/イベント解析パネル設置
```

### 2️⃣ イベント解析

1. パネルの **「🔍 イベント解析」** ボタンをクリック
2. gameStart応答をJSON形式で入力
3. stageId と battleType を指定
4. 送信して結果確認

### 3️⃣ 結果表示（embed形式）

```
🔍 イベント解析結果
stageId: 123 | battleType: 6

🚪 ゲート関連情報: ✅ あり (3個)

📋 応答キー数: 7 個

🔑 主要キー:
  • rc: 0
  • userId: 123456
  • eventId: 1360
  • ...

📚 全キー一覧:
  • rc: int
  • userId: int
  • ...
```

---

## 📊 推奨される使用方法

### パターン1: 通常イベントの確認
```bash
YWP_DEBUG_EVENT=1 python ywp_auto.py
# ログから JSON をコピー
# Discord パネルで分析
```
→ 通常イベント（周回）の構造を確認

### パターン2: ゲートイベントの詳細確認
```bash
YWP_DEBUG_EVENT=1 YWP_DEBUG_GATE=1 python ywp_auto.py
# ゲート情報のみピックアップ
# Discord パネルで詳細分析
```
→ ゲート関連情報を含む全イベント情報

### パターン3: Discordパネル直接使用
1. `YWP_DEBUG_EVENT=1` で周回・ログ収集
2. gameStart応答をコピー
3. Discord の **「🔍 イベント解析」** ボタンをクリック
4. JSON貼付・分析実行

→ 最も効率的な検証方法

---

## 🎯 現在の進捗

```
Phase 1: 準備フェーズ        ✓ 完了
├─ ゲート関連キー抽出        ✓ 完了
├─ ゲート関連情報ログ出力    ✓ 完了
├─ テスト作成・実施          ✓ 完了
└─ ドキュメント作成          ✓ 完了

Phase 2: 全イベント解析      ✓ 完了
├─ 全イベント解析関数        ✓ 完了
├─ イベント情報ログ出力      ✓ 完了
├─ battle_start()統合        ✓ 完了
├─ テスト作成・実施          ✓ 完了
└─ ドキュメント作成          ✓ 完了

Phase 3: Discordパネル実装   ✓ 完了
├─ EventAnalysisModal        ✓ 完了
├─ EventAnalysisPanelView    ✓ 完了
├─ embed・パネル表示         ✓ 完了
├─ スラッシュコマンド        ✓ 完了
├─ テスト作成・実施          ✓ 完了
└─ ドキュメント作成          ✓ 完了

Phase 4: ゲートイベント本実装 ⏳ 準備完了
├─ イベント来現待機          ⏳ 
├─ データ収集                ⏳
├─ 実装開始                  ⏳
└─ 本番テスト                ⏳
```

---

## ✅ チェックリスト

- [x] ゲート情報抽出関数の実装
- [x] ゲート関連情報ログ出力
- [x] 全イベント解析関数の実装
- [x] イベント情報ログ出力機能
- [x] battle_start()への統合
- [x] テストスクリプト作成（全イベント）
- [x] テスト実施（全成功）
- [x] ドキュメント作成
- [x] **Discordパネル実装**
- [x] **Discordパネルテスト**
- [x] **Discordパネルドキュメント**
- [x] Gitコミット（3→4コミット）
- [ ] 実ゲートイベント来現
- [ ] ログ収集
- [ ] ゲートイベント本実装

---

## 💡 Tips

**ログが見やすくなるように:**
- `[EVENT_DEBUG]` プレフィックス：全イベント情報
- `[GATE_DEBUG]` プレフィックス：ゲート情報のみ
- 階層化された出力で構造が明確
- 要素数・型情報が一目瞭然

**Discord パネル + デバッグモードの相互利用:**
1. YWP をデバッグモード実行
2. 目的のイベント来現
3. ログから JSON コピー
4. Discord パネル で検証
5. 完全な構造を把握
6. 本実装に進める

---

## 🔗 関連リソース

- **YWP 本体:** `YWP/ywp_auto.py`
- **YWP Bot:** `YWP/bot.py`
- **テストスクリプト:** `test_gate_debug.py`・`test_discord_event_analysis.py`
- **GitHub:** ararenchosu/saba

---

**最終更新:** 2025年
**ステータス:** Phase 3 完了 ✓

