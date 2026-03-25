---
title: Claude Code の Hooks と Skills でコード品質を自動化する
tags:
  - Python
  - ClaudeCode
  - AI
  - 開発効率化
  - ruff
private: false
updated_at: ''
id: null
organization_url_name: null
slide: false
ignorePublish: false
---

## はじめに

Claude Code には **Hooks** と **Skills（カスタムスラッシュコマンド）** という拡張機能があります。

- **Hooks**: ツール実行の前後に自動でシェルコマンドを走らせる仕組み
- **Skills**: `/コマンド名` で呼び出せるカスタムプロンプト

これらをプロジェクトの `.claude/` ディレクトリに設定しておくことで、「ファイル編集時に自動フォーマット」「.env ファイルの誤編集を防止」「PR前のセルフレビュー」などを Claude Code に組み込めます。

本記事では、Python（FastAPI）プロジェクトで実際に導入した設定を紹介します。

## ディレクトリ構成

```
.claude/
├── settings.json          # Hooks・パーミッション設定
└── commands/              # カスタムスラッシュコマンド
    ├── quality.md         # /quality
    ├── self-review.md     # /self-review
    └── test.md            # /test
```

## Hooks 編

Hooks は `.claude/settings.json` の `hooks` キーに定義します。イベントの種類は以下の 3 つです。

| イベント | タイミング | 用途 |
|---|---|---|
| `PreToolUse` | ツール実行**前** | バリデーション・ブロック |
| `PostToolUse` | ツール実行**後** | 自動整形・後処理 |
| `Notification` | 通知発生時 | デスクトップ通知 |

### 1. PostToolUse: ruff 自動フォーマット

Claude Code が Python ファイルを Write/Edit するたびに、自動で `ruff format` を実行します。

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "file_path=$(cat | jq -r '.tool_input.file_path // empty'); [ -z \"$file_path\" ] && exit 0; case \"$file_path\" in *.py) ruff format --quiet \"$file_path\" 2>/dev/null; exit 0;; *) exit 0;; esac"
          }
        ]
      }
    ]
  }
}
```

**ポイント:**
- `matcher: "Write|Edit"` で Write ツールと Edit ツールの両方にマッチ
- stdin から JSON を受け取り、`jq` で `file_path` を抽出
- `.py` ファイルのみ `ruff format` を実行、それ以外はスキップ
- `2>/dev/null` で ruff 未インストール環境でもエラーにならない

TypeScript/JavaScript も扱うプロジェクトなら、`case` に `*.ts|*.tsx|*.js|*.jsx) npx prettier --write ...` を追加できます。

### 2. PreToolUse: ファイル保護ガード

`.env` ファイル、ロックファイル、アーカイブ済みマイグレーションへの書き込みをブロックします。

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "INPUT=$(cat); FILE=$(echo \"$INPUT\" | jq -r '.tool_input.file_path // empty'); [ -z \"$FILE\" ] && exit 0; case \"$FILE\" in *.env|*.env.*|.env*) echo 'Blocked: .env files are protected.' >&2; exit 2;; */migrations/archive/*) echo 'Blocked: Archived migrations must not be modified.' >&2; exit 2;; *.lock|*.lock.*) echo 'Blocked: Lock files must not be modified manually.' >&2; exit 2;; *) exit 0;; esac"
    }
  ]
}
```

**ポイント:**
- `exit 2` を返すと Claude Code はそのツール実行を**ブロック**する
- `exit 0` はパス（許可）
- stderr にメッセージを出力すると、Claude Code にブロック理由が伝わる

### 3. PreToolUse: ハードコードされたシークレットの検出

APIキーやパスワードが直接コードに書き込まれるのを防ぎます。

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "INPUT=$(cat); CONTENT=$(echo \"$INPUT\" | jq -r '.tool_input.content // .tool_input.new_string // empty'); [ -z \"$CONTENT\" ] && exit 0; if echo \"$CONTENT\" | grep -qE '(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|password\\s*=\\s*[\"'\\'']{1}[^\"'\\'']{8,}[\"'\\'']{1})'; then echo 'Warning: Potential hardcoded secret detected.' >&2; exit 2; fi; exit 0"
    }
  ]
}
```

**検出パターン:**
- `sk-` で始まる OpenAI API キー形式
- `AKIA` で始まる AWS アクセスキー形式
- `password = "..."` のようなハードコードされたパスワード

プロジェクトに合わせてパターンを追加・調整してください。

### 4. PreToolUse: SQL インジェクション検出

f-string で SQL を組み立てるコードをブロックします。

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "INPUT=$(cat); CONTENT=$(echo \"$INPUT\" | jq -r '.tool_input.content // .tool_input.new_string // empty'); [ -z \"$CONTENT\" ] && exit 0; if echo \"$CONTENT\" | grep -qE 'f\"[^\"]*\\b(SELECT|INSERT|UPDATE|DELETE|DROP)\\b'; then echo 'Warning: f-string SQL detected. Use parameterized queries.' >&2; exit 2; fi; exit 0"
    }
  ]
}
```

SQLAlchemy を使っているプロジェクトでは、ORM や `text()` によるパラメータ化クエリを使うべきなので、f-string SQL は基本的にバグです。

### 5. Notification: デスクトップ通知

長い処理の完了時に `notify-send` でデスクトップ通知を送ります。

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "MESSAGE=$(cat | jq -r '.message // \"Claude Code needs your attention\"'); command -v notify-send >/dev/null 2>&1 && notify-send 'Claude Code' \"$MESSAGE\" 2>/dev/null; exit 0"
          }
        ]
      }
    ]
  }
}
```

WSL 環境では `wsl-notify-send` 等に置き換えると Windows 側に通知が飛びます。macOS なら `osascript -e 'display notification ...'` に差し替え可能です。

## Skills（スラッシュコマンド）編

`.claude/commands/` ディレクトリに Markdown ファイルを置くと、`/ファイル名` でスラッシュコマンドとして呼び出せます。

### /quality — 品質チェック一括実行

`.claude/commands/quality.md`:

```markdown
Run all quality checks on the codebase.

Steps:
1. Linting:
   ```
   ruff check src/ tests/
   ```
2. Formatting check:
   ```
   ruff format --check src/ tests/
   ```
3. Run tests:
   ```
   pytest -v --maxfail=5
   ```

Report any issues found with file paths and line numbers.
If issues are found, ask if the user wants them auto-fixed (ruff format, ruff check --fix).
```

**使い方:** Claude Code で `/quality` と入力するだけ。lint、フォーマットチェック、テストを一括実行して結果を報告してくれます。

### /self-review — PR前セルフレビュー

`.claude/commands/self-review.md`:

```markdown
Draft PR作成前のセルフレビューを実施してください。

## レビューの心得
- **まっさらな気持ちで**: 他人が書いたコードを初めて見る客観的な視点でレビューする
- **先入観を捨てる**: 「動いたから大丈夫」ではなく、本当に正しいか疑う

## 手順

### 1. 変更差分の確認
git diff main...HEAD

### 2. 設計原則チェック
- **DRY**: 同じロジックが複数箇所にコピーされていないか
- **KISS**: 不必要に複雑な実装になっていないか
- **SOLID**: 各原則に違反していないか
- **YAGNI**: 今必要でない機能を先回りで実装していないか

### 3. セキュリティレビュー
- SQLインジェクション、シークレット、XSS、情報漏洩

### 4. コーディングレビュー
- 命名規則、型ヒント、不要なprint()、async/await の正しさ

### 5. 過度な修正チェック
- 最小限の変更原則、「ついでに」のリファクタ防止

### 6. 互換性・テスト

## 出力形式
設計原則 / セキュリティ / コーディング / 過度な修正 / 互換性 / テスト
→ 各項目 ✅ or ⚠️ → 総合判定: PR作成OK / 要修正
```

**使い方:** feature ブランチで作業後、`/self-review` を実行。Claude Code が `git diff main...HEAD` を確認して、設計原則・セキュリティ・コーディング規約の観点からレビュー結果を出力します。

### /test — テスト実行

`.claude/commands/test.md`:

```markdown
Run the full test suite for the project.

Steps:
1. Run tests:
   pytest -v --maxfail=5
2. Report results:
   - Total tests passed/failed/skipped
   - Any failing test names and error summaries
```

## settings.json 全体像

最後に、`settings.json` の完全版を掲載します。`permissions` でよく使うコマンドを許可しておくと、実行のたびに確認ダイアログが出なくなり快適です。

```json
{
  "permissions": {
    "allow": [
      "Bash(git log *)",
      "Bash(git status *)",
      "Bash(git diff *)",
      "Bash(git branch *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git checkout *)",
      "Bash(git push *)",
      "Bash(git fetch *)",
      "Bash(ruff check *)",
      "Bash(ruff format *)",
      "Bash(pytest *)",
      "Bash(python -m pytest *)",
      "Bash(alembic *)",
      "Bash(gh issue view *)",
      "Bash(gh issue list *)",
      "Bash(gh pr view *)",
      "Bash(gh pr list *)",
      "Bash(docker compose *)",
      "Bash(docker ps *)",
      "Bash(docker logs *)"
    ],
    "deny": [
      "Bash(rm -rf /)",
      "Bash(sudo rm -rf *)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "file_path=$(cat | jq -r '.tool_input.file_path // empty'); [ -z \"$file_path\" ] && exit 0; case \"$file_path\" in *.py) ruff format --quiet \"$file_path\" 2>/dev/null; exit 0;; *) exit 0;; esac"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "INPUT=$(cat); FILE=$(echo \"$INPUT\" | jq -r '.tool_input.file_path // empty'); [ -z \"$FILE\" ] && exit 0; case \"$FILE\" in *.env|*.env.*|.env*) echo 'Blocked: .env files are protected.' >&2; exit 2;; */migrations/archive/*) echo 'Blocked: Archived migrations must not be modified.' >&2; exit 2;; *.lock|*.lock.*) echo 'Blocked: Lock files must not be modified manually.' >&2; exit 2;; *) exit 0;; esac"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "INPUT=$(cat); CONTENT=$(echo \"$INPUT\" | jq -r '.tool_input.content // .tool_input.new_string // empty'); [ -z \"$CONTENT\" ] && exit 0; if echo \"$CONTENT\" | grep -qE '(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|password\\s*=\\s*[\"'\\'']{1}[^\"'\\'']{8,}[\"'\\'']{1})'; then echo 'Warning: Potential hardcoded secret detected.' >&2; exit 2; fi; exit 0"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "INPUT=$(cat); CONTENT=$(echo \"$INPUT\" | jq -r '.tool_input.content // .tool_input.new_string // empty'); [ -z \"$CONTENT\" ] && exit 0; if echo \"$CONTENT\" | grep -qE 'f\"[^\"]*\\b(SELECT|INSERT|UPDATE|DELETE|DROP)\\b'; then echo 'Warning: f-string SQL detected. Use parameterized queries.' >&2; exit 2; fi; exit 0"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "MESSAGE=$(cat | jq -r '.message // \"Claude Code needs your attention\"'); command -v notify-send >/dev/null 2>&1 && notify-send 'Claude Code' \"$MESSAGE\" 2>/dev/null; exit 0"
          }
        ]
      }
    ]
  }
}
```

## まとめ

| 設定 | 効果 |
|---|---|
| ruff 自動フォーマット | 編集のたびに自動整形。フォーマット忘れゼロ |
| .env 保護 | シークレットファイルの誤編集を防止 |
| シークレット検出 | APIキーのハードコードをブロック |
| SQL インジェクション検出 | f-string SQL を書かせない |
| `/quality` | lint + format + test をワンコマンドで |
| `/self-review` | PR前に設計原則・セキュリティを自動チェック |
| `/test` | テスト実行をワンコマンドで |

Hooks は「Claude Code がミスしないためのガードレール」、Skills は「繰り返す作業の自動化」です。プロジェクトに合わせてカスタマイズしてみてください。
