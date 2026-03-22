# VideoSRT

MP4動画からAI文字起こしでSRT字幕ファイルを生成するWebアプリケーション。

## Features

- **AI文字起こし**: OpenAI Whisper API / Google Gemini API による高精度な音声認識
- **SRT生成**: タイムスタンプ付きのSRT字幕ファイルを自動生成
- **YouTubeメタデータ**: タイトル・概要欄（チャプターインデックス付き）・タグを自動生成
- **動画編集**: 字幕埋め込み（半透明ハイライト背景）・ロゴオーバーレイ
- **コストダッシュボード**: APIコストをプロバイダ別・月別に追跡
- **Web UI設定**: API鍵・モデル設定をブラウザから管理

## Quick Start

### Docker (推奨)

```bash
# 1. 暗号化キーを生成
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. .env ファイルを作成
cp .env.example .env
# ENCRYPTION_KEY に生成したキーを設定

# 3. 起動
docker compose up --build

# 4. ブラウザで http://localhost:8000 を開く
# 5. Settings でAPIキーを設定
# 6. MP4をアップロードして字幕生成
```

### ローカル開発

```bash
# 前提: Python 3.11+, ffmpeg がインストール済み

pip install -e ".[dev]"

# .env を設定（上記参照）

uvicorn src.main:app --reload --port 8000
```

## 使い方

### 1. APIキー設定
Settings画面で OpenAI / Google の APIキーを設定します。

### 2. MP4アップロード
Upload画面で MP4ファイルをドラッグ&ドロップまたは選択し、プロバイダ（Whisper/Gemini）と言語を選択してアップロードします。

### 3. SRTダウンロード
History画面で処理完了したジョブの「SRT」ボタンからダウンロードできます。

### 4. YouTubeメタデータ
アップロード時に「Generate YouTube metadata」にチェックを入れると、タイトル・概要欄・タグが自動生成されます。History画面の「Meta」ボタンで確認・コピーできます。

### 5. 字幕埋め込み
History画面の「Embed」ボタンで、SRT字幕やロゴを動画に埋め込めます。

## プロバイダ比較

| | OpenAI Whisper | Google Gemini |
|---|---|---|
| 精度 | 高い（ASR専用モデル） | 高い（マルチモーダルLLM） |
| タイムスタンプ | 正確（ASRベース） | やや粗い（LLM推定） |
| コスト | $0.006/分 | ~$0.002/分（2.5 Flash） |
| ファイル制限 | 25MB（自動分割対応） | 9.5時間 |

## License

MIT License
