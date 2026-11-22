# 🎯 ゲートイベント対応実装ロードマップ

## 📋 概要
YWP の **battleType=6** 対応にはゲートイベントの仕組みが**実装されていない**。
以下のステップで段階的に対応を進める。

---

## 🔍 **Phase 1: 情報収集（1-2日）**

### 目標
gameStart の実際の応答構造を把握し、3つの実装パターンのどれに該当するか判定

### やることリスト

#### 1-1. デバッグモード実行
```bash
# YWP のゲートイベント実行ディレクトリで
export YWP_DEBUG_START=1
# ゲーム実行コマンド（game_bot.py など）
```

#### 1-2. ゲートステージをプレイ
- battleType=6 のマップをクリア（28805, 28904, 29008, 29304 など）
- コンソールに `gameStart 生データ` が表示される

#### 1-3. 出力を分析
**探すべきキー：**
```
✓ warpGate / gateList / eventWarp / eventChoice
✓ gateInfo / challengeInfo / eventWarpInfo
✓ warpId / gateSelect / battleCode
```

#### 1-4. 情報を記録
```
出力内容をテキストファイルに保存:
 - gameStart トップレベルのキー
 - warpGate/gateList の構造（複数のゲート？）
 - 敵情報の場所（どこにゲート奥の敵？）
 - battleCode の値
```

#### 1-5. ネットワークログ取得（オプション）
- Fiddler / mitmproxy で通信キャプチャ
- gameStart → (ゲート選択?) → gameEnd の流れを確認
- 新しい API 呼び出しがあるか確認

### 出力例：
```
■ トップレベルのキー:
   battleCode, challengeInfo, enemyYoukaiList, eventWarp, ...

■ ゲート情報:
   warpGate = [
     {'gateId': 1, 'enemyId': 12345, 'difficulty': 'easy'},
     {'gateId': 2, 'enemyId': 12346, 'difficulty': 'hard'},
   ]
```

### ✅ 完了条件
- [ ] gameStart 応答の全体構造を把握
- [ ] ゲート情報キーを特定
- [ ] 複数ゲートの構造を確認
- [ ] 別 API 呼び出しの有無を判定

---

## 💻 **Phase 2: 実装設計（1日）**

### 目標
Phase 1 の情報に基づいて、実装パターンを決定し、設計書を作成

### やることリスト

#### 2-1. パターン判定
```
質問:
Q1. gameStart 応答に warpGate / gateList がある？
  → YES: 2-2 へ進む
  → NO: ゲート情報の場所を探す

Q2.複数のゲートが返される？
  → YES: 2-3 へ進む
  → NO: ゲート選択不要（単純パターン）

Q3. ゲート選択に別 API（selectGate など）が必要？
  → YES: パターン B（別 API）
  → NO: パターン A（gameStart だけ）
```

#### 2-2. 実装パターン決定表

| パターン | 条件 | 実装量 | 優先度 |
|---------|------|--------|--------|
| **A** | gameStart だけで完結 | 小 | 高 |
| **B** | 別 API でゲート選択 | 中 | 中 |
| **C** | ゲートごとに gameStart 繰り返し | 大 | 低 |

#### 2-3. 実装設計書作成
```
1. 修正対象メソッド
   - battle_start()
   - build_game_end()
   - （必要に応じて新メソッド）

2. 追加パラメータ
   - battleType=6 判定
   - gateSelect / gateId 情報の保存方法

3. テスト項目
   - ゲート情報解析
   - ゲート選択ロジック
   - gameEnd パラメータ検証
```

### ✅ 完了条件
- [ ] パターン A/B/C のいずれかを判定
- [ ] 実装対象メソッドを特定
- [ ] 修正内容の詳細設計書を作成

---

## 🛠️ **Phase 3: コード実装（2-3日）**

### 目標
設計に基づいてコード実装し、ゲートイベント対応を追加

### やることリスト（パターン A の場合）

#### 3-1. battle_start() 拡張
[ファイル: YWP/ywp_auto.py](ywp_auto.py:1620)

```python
def battle_start(self, stageId, battleType=None):
    # ... 既存コード ...
    
    if battleType == 6 and isinstance(js, dict):
        # ★ ゲート情報解析（新）
        gates = js.get('warpGate') or js.get('gateList') or js.get('eventWarp')
        
        if gates and isinstance(gates, list) and len(gates) > 0:
            # 複数ゲートの場合は選択
            if len(gates) > 1:
                selected = self._select_gate(gates)
            else:
                selected = gates[0].get('gateId') or 0
            
            # gameEnd で使うため保存
            js['_gateId'] = selected
            js['_gateInfo'] = gates
            log_line(f'ゲート選択: {selected}（ゲート数 {len(gates)}）')
    
    return rc, js, battleType
```

#### 3-2. ゲート選択ロジック実装
```python
def _select_gate(self, gates):
    """複数ゲートから1つ選ぶ
    
    推奨ロジック:
    - 難易度でフィルタ（easy を優先）
    - 敵の攻撃力が最も弱いものを選ぶ
    - ランダム選択（リスク回避）
    """
    if not gates:
        return 0
    
    # ★ ここに選択ロジック実装
    # 例：一番目を選ぶ
    return gates[0].get('gateId', 0)
```

#### 3-3. build_game_end() 修正
```python
def build_game_end(self, stageId, battleType, start, clearTime=None):
    # ... 既存コード ...
    
    ge = {
        'stageId': stageId,
        # ... その他パラメータ ...
    }
    
    if battleType == 6:
        # ★ ゲート情報をパラメータに追加（もし必要なら）
        if start.get('_gateId'):
            # ge['gateId'] = start.get('_gateId')
            pass
    
    return ge
```

#### 3-4. ユーティリティメソッド追加
```python
def _parse_gate_difficulty(self, difficulty_str):
    """ゲート難易度を数値に変換"""
    levels = {'easy': 1, 'normal': 2, 'hard': 3, 'extreme': 4}
    return levels.get(difficulty_str, 0)
```

### パターン B の場合（別 API が必要）

#### 3-5. ゲート選択 API 実装
```python
def select_gate(self, stageId, gateId):
    """ゲートを選択する API 呼び出し（推測）"""
    rc, j = self.call('selectGate.nhn', {
        'stageId': stageId,
        'gateId': gateId,
    })
    return rc, j
```

### ✅ 完了条件
- [ ] battle_start() に ゲート情報解析を追加
- [ ] ゲート選択ロジック実装
- [ ] build_game_end() を修正（必要に応じて）
- [ ] 新 API 実装（パターン B の場合）
- [ ] テストケース作成

---

## 🧪 **Phase 4: テスト・検証（2-3日）**

### 目標
実装したコードがゲートイベント対応を正しく実現できることを確認

### やることリスト

#### 4-1. ユニットテスト
```python
def test_gate_parsing():
    """ゲート情報解析テスト"""
    mock_response = {
        'warpGate': [
            {'gateId': 1, 'enemyId': 1001},
            {'gateId': 2, 'enemyId': 1002},
        ]
    }
    gates = mock_response.get('warpGate', [])
    assert len(gates) == 2
    assert gates[0]['gateId'] == 1

def test_gate_selection():
    """ゲート選択ロジックテスト"""
    gates = [
        {'gateId': 1, 'difficulty': 'hard'},
        {'gateId': 2, 'difficulty': 'easy'},
    ]
    selected = client._select_gate(gates)
    assert selected in [1, 2]
```

#### 4-2. 統合テスト
- ゲートイベント実行
- battleType=6 のステージをクリア
- コンソール出力を確認
- ゲート情報が正しく解析されたか確認

#### 4-3. 回帰テスト
- 通常イベント（battleType=1）がまだ動くか確認
- 他の battleType が影響を受けていないか確認

#### 4-4. エラーハンドリング
- ゲート情報が無い場合（フォールバック）
- 複数ゲートが返された場合
- ゲート選択に失敗した場合

### ✅ 完了条件
- [ ] ユニットテストをクリア
- [ ] 統合テストをクリア
- [ ] 回帰テストをクリア
- [ ] エラーハンドリングを実装

---

## 📝 **Phase 5: ドキュメント・整理（1日）**

### やることリスト

#### 5-1. コメント追加
```python
# ゲートイベント（battleType=6）では、gameStart 応答に
# ゲート情報（warpGate など）が含まれ、ゲートを選んでから
# クリアを申告する。詳細は ...
```

#### 5-2. CHANGELOG 更新
```
- ゲートイベント（battleType=6）対応を実装
  - gameStart 応答からゲート情報を解析
  - 複数ゲート時の自動選択ロジック
  - gameEnd パラメータ対応
```

#### 5-3. README 更新
```
## 対応イベント

### ✅ 実装済み
- 通常イベント（battleType=1）
- ゲートイベント（battleType=6）← NEW

### ⏳ 未実装
- ???
```

---

## 📊 実装進捗表

```
フェーズ          開始    完了    予定工数
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 情報収集       Week 1  -       1-2日
2. 設計           Week 1  -       1日
3. 実装           Week 2  -       2-3日
4. テスト         Week 2  -       2-3日
5. ドキュメント   Week 3  -       1日
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
合計:                              8-11日
```

---

## 🚨 リスク・注意点

### リスク 1: ゲート情報の構造が不明
**対策**: Phase 1 で詳しく調査。必要に応じて Level5 に問い合わせ

### リスク 2: 新しい API が必要
**対策**: ネットワークログで事前に確認。実装時間が増えるので早期発見が重要

### リスク 3: gameEnd rc=4（DPS制限）
**対策**: 既存の DPS_RATIO_MAX ロジックは維持。ゲート特有の制限があるか要確認

### リスク 4: ゲート奥の敵が複数
**対策**: gameStart 応答をよく見て、どの敵をターゲットするか判定

---

## 🎯 成功基準

- [ ] ゲートイベント中に battleType=6 を送信
- [ ] ゲート情報を正しく解析
- [ ] 複数ゲート時に自動選択
- [ ] gameEnd で確実にクリア申告（rc=0）
- [ ] 周回効率が通常イベント並みに達成

---

## 📌 次のアクション

**今すぐやること:**
1. ゲートイベント実行中に `YWP_DEBUG_START=1` で出力を確認
2. gameStart 応答の全キーをメモ
3. ゲート情報キーを特定
4. Phase 2（設計）に進む

**質問がある場合:**
- gameStart の具体的な応答構造
- battleType=6 のパラメータ（battleCode など）
- ゲート選択の自動ロジック（難易度優先 vs ランダム）

