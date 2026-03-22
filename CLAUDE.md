# VideoSRT - 開発ガイド

## プロジェクト概要

MP4動画からAI文字起こしでSRT字幕を生成し、YouTubeメタデータ自動生成・動画編集（字幕埋め込み・ロゴ追加）まで行うWebアプリ。

## 技術スタック

- **Backend**: FastAPI (Python 3.11+)
- **UI**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **DB**: SQLite (SQLAlchemy 2.0 async + aiosqlite)
- **文字起こし**: OpenAI Whisper API / Google Gemini API
- **メタデータ生成**: OpenAI GPT / Google Gemini
- **動画処理**: ffmpeg
- **フォント**: Noto Sans CJK JP
- **デプロイ**: Docker (単一コンテナ)

## 開発環境セットアップ

```bash
# 依存関係インストール
pip install -e ".[dev]"

# 暗号化キー生成
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → .env に ENCRYPTION_KEY=<生成されたキー> を設定

# 開発サーバー起動
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Docker で起動
docker compose up --build
```

## ディレクトリ構造

```
src/
├── main.py          # FastAPI app
├── config.py        # pydantic-settings
├── database.py      # SQLAlchemy
├── templating.py    # Jinja2 templates
├── models/          # ORM models (Job, Setting, CostLog)
├── services/        # ビジネスロジック
│   ├── audio.py     # ffmpeg音声抽出
│   ├── whisper.py   # OpenAI Whisper API
│   ├── gemini.py    # Google Gemini API
│   ├── transcribe.py # オーケストレーター
│   ├── srt.py       # SRT生成
│   ├── metadata.py  # YouTubeメタデータ生成
│   ├── video_edit.py # 動画編集 (字幕埋め込み・ロゴ)
│   ├── crypto.py    # API鍵暗号化
│   └── cost.py      # コスト計算
├── api/             # APIルーター
│   ├── pages.py     # HTMLページ
│   ├── jobs.py      # ジョブCRUD
│   ├── settings.py  # 設定管理
│   └── costs.py     # コストダッシュボード
└── templates/       # Jinja2テンプレート
```

## コーディング規約

- **Python**: 型ヒント必須、ruff でフォーマット・リント
- **命名**: snake_case (関数/変数)、PascalCase (クラス)
- **非同期**: async/await を使用 (SQLAlchemy async, asyncio subprocess)
- **テスト**: pytest + pytest-asyncio

## コミットメッセージ

Conventional Commits 形式:

```
<type>(<scope>): <subject>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

Type: feat, fix, refactor, test, docs, chore
Scope: api, service, ui, db, infra

## テスト

```bash
pytest                    # テスト実行
pytest --cov              # カバレッジ
ruff check src/           # Lint
ruff format src/          # Format
```

## 環境変数

| 変数 | 説明 | 必須 |
|------|------|------|
| ENCRYPTION_KEY | Fernet暗号化キー | Yes |

API鍵はWeb UIの Settings 画面で設定（DB保存、暗号化）。
