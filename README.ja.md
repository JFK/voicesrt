# VoiceSRT

[English](README.md)

動画・音声ファイルからAI文字起こしでSRT字幕を生成し、YouTubeメタデータ・キャッチコピー・クイズも一括作成するWebアプリケーション。

## 機能

### 文字起こし & SRT
- **AI文字起こし**: OpenAI Whisper API / Google Gemini API
- **マルチフォーマット対応**: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM
- **LLM後処理**: 3つのモード（Verbatim / Standard / Caption）+ 用語集サポート
- **検証パス**: 固有名詞・地名・漢字の不整合を全文チェック
- **SRTエディタ**: セグメントごとのAIサジェスト付きインライン編集

### YouTube ツール
- **メタデータ生成**: SEO最適化タイトル、チャプター付き概要、15-25タグ
- **トーン参照**: 過去の投稿スタイルに合わせた文体で生成
- **キャッチコピー生成**: サムネイル用テキスト5案（スタイル分類付き）
- **クイズ生成**: 動画内容から4択クイズ5問

### 管理
- **アップロード履歴**: グループ化されたアクションボタンとステータス表示
- **コストダッシュボード**: プロバイダー・モデル・月次のAPI利用コスト追跡
- **設定**: APIキー（暗号化保存）、モデルプリセット、用語集、後処理プロンプト、料金

## スクリーンショット

### アップロード
![アップロード](docs/screenshots/upload.png)

### コストダッシュボード
![コストダッシュボード](docs/screenshots/costs.png)

### 設定
![設定](docs/screenshots/settings.png)

## セットアップ

### Docker（推奨）

```bash
git clone https://github.com/JFK/voicesrt.git
cd voicesrt
cp .env.example .env
# .env に ENCRYPTION_KEY を設定
docker compose up --build
# http://localhost:8000 → 設定 → APIキーを登録
```

### WSL2 (Windows) での Docker

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストール（WSL 2 エンジンを有効化）
2. Settings → Resources → WSL Integration → ディストロを有効化
3. WSL ターミナルで:
```bash
git clone https://github.com/JFK/voicesrt.git
cd voicesrt
cp .env.example .env
# .env に ENCRYPTION_KEY を設定
docker compose up --build
```

### ローカル

```bash
# 前提: Python 3.11+, ffmpeg
pip install -e ".[dev]"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cp .env.example .env
# .env に ENCRYPTION_KEY を設定
uvicorn src.main:app --reload --port 8000
```

## 使い方

### 1. APIキーの設定
設定ページ → OpenAI / Google APIキーを入力。

### 2. アップロード & 文字起こし
アップロードページ → ファイルをドラッグ&ドロップ → プロバイダー・後処理モードを選択 → アップロード & 処理開始。
処理完了後、アップロード履歴に自動遷移。

### 3. SRT編集
アップロード履歴 → **編集**ボタン → SRTエディタ。
セグメントを編集、AIサジェストを活用、自動保存 & ダウンロード。

### 4. YouTubeメタデータ生成
アップロード履歴 → **Meta**ボタン → メタデータエディタ。
チャンネル情報を設定、トーン参照を有効化、タイトル/概要/チャプター/タグを生成。

### 5. キャッチコピー & クイズ生成
アップロード履歴 → **コピー** / **Quiz** ボタン → ワンクリック生成。

## 技術スタック

- **バックエンド**: FastAPI (Python 3.11+), async/await
- **フロントエンド**: Jinja2 + HTMX + Alpine.js + Tailwind CSS（ビルドステップ不要）
- **データベース**: SQLite (SQLAlchemy 2.0 async + aiosqlite + Alembic)
- **AI**: OpenAI Whisper/GPT, Google Gemini
- **音声処理**: ffmpeg
- **セキュリティ**: Fernet暗号化（APIキー）
- **多言語対応**: 英語 / 日本語

## プロバイダー比較

| | OpenAI Whisper | Google Gemini |
|---|---|---|
| 精度 | 高（専用ASRモデル） | 高（マルチモーダルLLM） |
| タイムスタンプ | 正確 | 概算 |
| コスト | $0.006/分 | ~$0.0005/分 (Flash Lite) |
| ファイル制限 | 25MB（自動チャンク分割） | 9.5時間 |

## ライセンス

MIT License
