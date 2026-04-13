# VoiceSRT

[![CI](https://github.com/JFK/voicesrt/actions/workflows/ci.yml/badge.svg)](https://github.com/JFK/voicesrt/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md)

音声・動画ファイルからAI文字起こしでSRT字幕を生成し、編集・後処理・エクスポートまで一括で行えるWebアプリケーション。モバイル対応、リアルタイムストリーミング、プロダクション品質。

## 機能

### 文字起こし
- **AI文字起こし**: OpenAI Whisper API / Google Gemini API
- **ストリーミングエディタ**: 文字起こし中にリアルタイムでセグメントが追加 — 完了を待つ必要なし
- **マルチフォーマット**: MP4, MP3, WAV, MOV, AVI, MKV, M4A, FLAC, OGG, WebM
- **無音検知チャンク分割**: 無音区間で音声を分割し、より自然なセグメント境界を実現
- **LLM後処理**: 3つのモード（Verbatim / Standard / Caption）+ 用語集
- **検証パス**: 固有名詞・地名・漢字の不整合を全文チェック
- **Ollama対応**: ローカルLLMモデル（Qwen3等）で後処理が可能

### SRTエディタ
- **インライン編集**: テキスト、タイムスタンプ、セグメント構造をブラウザ上で編集
- **波形表示**: wavesurfer.jsによる波形表示、話者色付きリージョン、クリックでシーク
- **話者管理**: 話者の登録・セグメント割り当て・自動カラーリング（8色）
- **セグメント操作**: 統合・削除・追加（時間重複バリデーション付き）
- **時間コントロール**: タイムスタンプ編集、±0.1秒のナッジボタン
- **音声再生**: プレイヤーバー内蔵、再生速度コントロール（0.5x〜2x）
- **AI提案**: 用語集対応のセグメント単位AI修正提案（Ollama対応）
- **話者別エクスポート**: 特定の話者のみのSRT/VTTをダウンロード
- **キーボードショートカット**: ナビゲーション、再生、編集の12種ショートカット

### YouTubeツール
- **メタデータ**: SEO最適化タイトル、チャプター付き概要、15-25タグ
- **トーン参照**: 過去の投稿スタイルに合わせた文体で生成
- **キャッチコピー**: サムネイル用テキスト5案（スタイル分類付き）
- **クイズ**: 動画内容から4択クイズ5問

### モデル選択
- **タスクごとのモデル選択**: 生成時にprovider + modelを指定可能（Upload / History / Meta Editor）
- **設定のデフォルト**: プロバイダーごとのデフォルトモデル + リファイン用モデルの上書き
- **Ollama連携**: ローカルOllamaインスタンスからモデル一覧を自動取得、Docker内ネットワーク自動解決

### 管理
- **アップロード履歴**: グループ化されたアクション、ステータス表示、モーダルプレビュー
- **コストダッシュボード**: プロバイダー・モデル・月次のAPI利用コスト追跡
- **設定**: APIキー暗号化保存、モデルプリセット、用語集、後処理プロンプト、料金設定
- **多言語対応**: 英語 / 日本語
- **モバイルレスポンシブ**: ハンバーガーメニュー、レスポンシブグリッド、全ページでタッチ操作に最適化

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

### Docker + Ollama（ローカルLLM）

```bash
# ホストでOllamaを起動: ollama serve
# モデルをプル: ollama pull qwen3:8b
docker compose up --build
# 設定 → Ollama Base URL: http://localhost:11434
# （コンテナ内で host.docker.internal に自動変換）
```

### WSL2（Windows）でのDocker

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストール（WSL 2エンジンを有効化）
2. Settings → Resources → WSL Integration → ディストロを有効化
3. WSLターミナルで:
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
設定ページ → OpenAI / Google APIキーを入力。Ollamaの場合はベースURLを設定しモデルを選択。

### 2. アップロード & 文字起こし
アップロード → ファイルをドラッグ&ドロップ → 音声認識エンジン（Whisper / Gemini）を選択 → リファイン有効時は後処理モデルも選択 → アップロード & 処理開始。

### 3. SRT編集
履歴 → **編集** → SRTエディタ。テキスト編集、話者の割り当て、AI提案の活用、セグメントの統合・分割、タイムスタンプ調整。フルSRT/VTTまたは話者別のエクスポート。

### 4. YouTubeメタデータ生成
履歴 → **Meta** → メタデータエディタ。チャンネル情報を設定、LLMモデルを選択、タイトル/概要/チャプター/タグを生成。

### 5. キャッチコピー & クイズ
履歴 → **コピー** / **Quiz** → モーダル内でモデル選択 → 生成。

## 技術スタック

- **バックエンド**: FastAPI (Python 3.11+), async/await
- **フロントエンド**: Jinja2 + HTMX + Alpine.js + Tailwind CSS（ビルドステップ不要）
- **データベース**: SQLite (SQLAlchemy 2.0 async + aiosqlite + Alembic)
- **AI**: OpenAI Whisper/GPT, Google Gemini, Ollama（ローカル）
- **音声処理**: ffmpeg
- **セキュリティ**: Fernet暗号化（APIキー）
- **多言語対応**: 英語 / 日本語

## プロバイダー比較

| | OpenAI Whisper | Google Gemini | Ollama（ローカル） |
|---|---|---|---|
| 文字起こし | 対応（専用ASR） | 対応（マルチモーダルLLM） | 非対応（Whisper使用） |
| 後処理 | GPTモデル | Geminiモデル | 任意のローカルモデル |
| コスト | $0.006/分（STT）+ LLM | ~$0.0005/分（Flash Lite） | 無料（ローカルHW） |
| ファイル制限 | 25MB（自動チャンク分割） | 9.5時間 | N/A |
| プライバシー | クラウド | クラウド | 完全ローカル |

## ライセンス

MIT License
