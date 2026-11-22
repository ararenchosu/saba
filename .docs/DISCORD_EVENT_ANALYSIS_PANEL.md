# Discord イベント解析パネル - 実装ガイド

## 概要

**Discordパネルから直接、gameStart応答のイベント構造を解析できる機能を追加しました。**

これにより、実際のゲーム応答を素早くデバッグでき、ゲートイベント実装時の検証がスムーズになります。

---

## ✨ 実装内容

### 新機能コンポーネント

#### 1. **EventAnalysisModal** - JSON入力用モーダル
```python
class EventAnalysisModal(discord.ui.Modal, title="イベント解析"):
    response_input      # gameStart応答（JSON形式）
    stage_id            # stageId
    battle_type         # battleType
```

入力形式:
- JSON（通常形式）: `{"rc": 0, "userId": 123456, ...}`
- Markdown形式: ` ```json {...} ``` `
- battleType は数値: `1`（通常）/ `6`（ゲート）/ `20`（特殊）等

#### 2. **EventAnalysisPanelView** - パネルビュー
```python
class EventAnalysisPanelView(discord.ui.View):
    @button(label='イベント解析', emoji='🔍')
```

ボタンをクリックでモーダルを開く。

#### 3. **event_analysis_embed()** - 解析結果表示
イベント構造を見やすい embed 形式で表示:
- イベントタイプ（通常/ゲート/特殊）
- ゲート関連情報の有無
- 応答キー数
- 主要キーの値
- 全キー一覧（型情報付き）

#### 4. **スラッシュコマンド** - パネル設置
```bash
/イベント解析パネル設置
```
サーバー管理者が実行して、チャンネルにパネルを設置します。

---

## 🚀 使用方法

### ステップ1: パネル設置

Discordサーバーの管理者が、以下のコマンドを実行:

```
/イベント解析パネル設置
```

例：
- チャンネルを選択
- コマンド実行
- ✅ メッセージが表示される
- チャンネルに解析パネルが設置される

### ステップ2: イベント解析実行

**通常ユーザー:**

1. パネルの **「🔍 イベント解析」** ボタンをクリック
2. モーダルが開く
3. 以下の3項目を入力:
   - **gameStart応答（JSON）**: JSON形式のレスポンス
   - **stageId**: ステージID（例: `123`）
   - **battleType**: イベントタイプ（例: `1`）
4. 送信
5. 結果が embed 形式で表示される

### ステップ3: 結果確認

解析結果には以下が含まれます:

```
🔍 イベント解析結果
stageId: 123 | battleType: 6

🚪 ゲート関連情報: ✅ あり

📋 応答キー数: 7 個

🔑 主要キー:
  • rc: 0
  • userId: 123456
  • eventId: 1360
  • eventName: "ゲートイベント"

📚 全キー一覧:
  • rc: int
  • userId: int
  • eventId: int
  • eventName: str (len=7)
  • warpGate: list (len=3)
  • gateList: list (len=3)
  • eventWarp: dict (len=1)
```

---

## 📋 イベントタイプの判定

| battleType | イベント名 | 絵文字 | 特徴 |
|-----------|---------|--------|------|
| 1 | 通常イベント（周回） | 🎪 | 固定ステージ周回 |
| 6 | ゲートイベント（ワープ） | 🚪 | ワープゲート出現 |
| 20 | 特殊イベント | ✨ | その他イベント |

**battleType=6 の場合、自動的に:**
- ゲート関連情報をハイライト
- embed の色が緑に変更
- 重要な情報として表示

---

## 🛠️ 実装の詳細

### ファイル位置

**ファイル:** `YWP/bot.py`

| 機能 | 行番号 | 説明 |
|------|--------|------|
| `event_analysis_embed()` | 10120-10160 | embed作成 |
| `EventAnalysisModal` | 10163-10200 | JSON入力モーダル |
| `EventAnalysisPanelView` | 10203-10213 | パネルビュー |
| `event_analysis_panel_embed()` | 10216-10245 | パネル説明 |
| `/イベント解析パネル設置` | 10248-10267 | スラッシュコマンド |

### 機能フロー

```
ユーザー
  ↓
パネルボタンをクリック
  ↓
EventAnalysisModal が開く
  ↓
JSON・stageId・battleType を入力
  ↓
on_submit() で処理
  ↓
JSON解析 + イベント解析
  ↓
extract_gate_related_keys() でゲート情報検出
  ↓
event_analysis_embed() で結果作成
  ↓
Discord に embed 表示
```

### エラーハンドリング

```python
# JSON解析エラー
❌ JSON形式エラー: ...

# battleType バリデーション
❌ battleType は数値で指定してください: ...

# その他エラー
❌ エラー: ...
```

---

## 📌 入力例

### 通常イベント（battleType=1）

```
gameStart応答:
{
  "rc": 0,
  "userId": 123456,
  "eventId": 1359,
  "eventName": "ぷにぷにフェスタ",
  "stageData": {"stageId": 123, "difficulty": 1},
  "enemy": [
    {"id": 100, "name": "ザコ敵1"},
    {"id": 101, "name": "ザコ敵2"}
  ],
  "eventPoint": 50
}

stageId: 123
battleType: 1
```

**結果:**
```
🎪 イベント解析結果
stageId: 123 | battleType: 1
イベントタイプ: 通常イベント（周回）
ゲート関連情報: ❌ なし
```

### ゲートイベント（battleType=6）

```
gameStart応答:
{
  "rc": 0,
  "userId": 123456,
  "eventId": 1360,
  "eventName": "ゲートイベント",
  "warpGate": [
    {"gateId": 1, "difficulty": "hard"},
    {"gateId": 2, "difficulty": "normal"}
  ],
  "gateList": [
    {"gateId": 1, "name": "ゲート1"},
    {"gateId": 2, "name": "ゲート2"}
  ],
  "eventWarp": {"warpId": 999}
}

stageId: 28805
battleType: 6
```

**結果:**
```
🚪 イベント解析結果
stageId: 28805 | battleType: 6
イベントタイプ: ゲートイベント（ワープ選択）
ゲート関連情報: ✅ あり (3個)
  - warpGate: list (len=2)
  - gateList: list (len=2)
  - eventWarp: dict (len=1)
```

---

## 🔗 他機能との連携

### YWP_DEBUG_EVENT との連携

**YWPをデバッグモード付きで実行中:**
```bash
YWP_DEBUG_EVENT=1 python ywp_auto.py
```

**結果:**
- YWP が自動でイベント情報をログ出力
- そのJSONをコピーして Discord パネルに貼付
- 詳細な構造分析が可能

### YWP_DEBUG_GATE との連携

**ゲートイベント情報のみ:**
```bash
YWP_DEBUG_EVENT=1 YWP_DEBUG_GATE=1 python ywp_auto.py
```

**結果:**
- ゲート関連情報を優先表示
- パネルでも自動的にゲート情報をハイライト

---

## ✅ テスト結果

### テストスクリプト実行

```bash
python test_discord_event_analysis.py
```

**テスト項目（3テスト、9ケース）:**

✓ event_analysis_embed()
  - 通常イベント解析
  - ゲートイベント解析

✓ モーダル入力パース
  - 通常のJSON形式
  - Markdown形式
  - battleType パース

✓ イベントタイプ判定
  - battleType=1（通常）
  - battleType=6（ゲート）
  - battleType=20（特殊）

**テスト結果: ✓ 全成功**

---

## 🎁 利点

✅ **リアルタイム検証**
  - 実際のゲーム応答をすぐに確認
  - デバッグモードのセットアップが不要

✅ **ユーザーフレンドリー**
  - GUI パネル操作
  - embed 形式で見やすい表示
  - エラーメッセージが分かりやすい

✅ **開発効率化**
  - ゲートイベント実装時に活躍
  - JSON を貼付するだけで解析
  - 複数の応答データを同時検証可能

✅ **既存機能との統合**
  - YWP bot に自然に統合
  - extract_gate_related_keys() を再利用
  - Phase 2 デバッグ機能と完全連携

---

## 🚀 次のステップ

1. **パネル設置:**
   ```
   /イベント解析パネル設置
   ```

2. **実ゲートイベント来現時:**
   - `YWP_DEBUG_EVENT=1` で周回
   - ログから JSON を取得
   - Discord パネルで検証

3. **ゲートイベント本実装:**
   - 検証済みの応答構造を基に実装
   - デバッグパネルで動作確認
   - 本番環境にリリース

---

## 📚 関連ドキュメント

- [PHASE2_FULL_EVENT_DEBUG.md](./PHASE2_FULL_EVENT_DEBUG.md) - 全イベント解析デバッグ機能
- [GATE_PHASE1_COMPLETE.md](./GATE_PHASE1_COMPLETE.md) - Phase 1 完了サマリー
- [INDEX.md](./INDEX.md) - ドキュメント索引

---

**実装完了日:** 2025年
**ステータス:** ✓ 完了・テスト済み
