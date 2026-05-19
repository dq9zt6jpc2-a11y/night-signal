# NIGHT SIGNAL 運用メモ

## できたもの

- `site/index.html`
  - PCで毎日開く固定URL
  - 最新号そのものを表示する
  - Safariのお気に入りに入れる対象
- `site/2026-05-10/index.html`
  - 日付別の履歴ページ
- `site/2026-05-10/details/`
  - 日本語詳細ページ
- `scripts/send_line.py`
  - LINE Messaging APIでURLを送るスクリプト
- `scripts/build_latest.py`
  - 最新号への入口ページを作るスクリプト
- `scripts/sync_site.py`
  - 作業用HTMLを `site/2026-05-10/` へ同期し、Safariで戻るリンクが壊れないように調整するスクリプト

## PCで毎日見る方法

1. Safariで `site/index.html` を開く
2. そのページをお気に入りに追加する
3. 毎日夜はそのお気に入りを開く

日付ごとのページが増えても、見るURLは `site/index.html` のまま固定します。  
`site/index.html` は常に最新号を表示し、ページ下部に直近7日分の履歴リンクを残します。

## 履歴の扱い

- `site/YYYY-MM-DD/` は日付別の保存版です。
- `site/index.html` は最新号です。
- `scripts/sync_site.py` 実行時に、7日を超えた日付別フォルダは削除します。
- 1週間内の情報は、後から追えるように履歴リンクとして残します。

## 次に必要な設定

1. Web公開先を決める
   - GitHub Pages
   - Netlify
   - Vercel

2. `site/` を公開する

3. LINE公式アカウントを作る

4. Messaging APIを有効化して以下を取得する
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `LINE_USER_ID`

5. LINE送信テスト

```bash
python3 scripts/send_line.py "https://公開URL/2026-05-10/"
```

## 本番の毎晩処理

1. `config/night_signal_coverage.json` のカテゴリと探索軸に沿って最新情報を収集する
2. 既存・新規を含めて、直近24〜72時間を中心に網羅的に調査する
3. 各カテゴリで公式、主要報道、専門媒体、SNS/X、YouTube、データ、予定、反証を確認する
4. 迷う材料は落とさず、抽出ログの `held` / `unresolved` に残す
5. 日本語記事を優先して確認し、日本語記事がない場合は英語記事を本文まで読み、日本語要約を作成する
6. トップページ、詳細ページ、抽出ログの `coverage-manifest` を更新する
7. `published_card_titles` とトップページのカード見出しを一致させる
8. `python3 scripts/sync_site.py YYYY-MM-DD` で `site/index.html` と日付別履歴へ同期する
9. `python3 scripts/coverage_audit.py YYYY-MM-DD` と `python3 scripts/quality_gate.py YYYY-MM-DD` を通す
10. `python3 scripts/pre22_audit.py YYYY-MM-DD` を通してからcommit/pushする
11. `python3 scripts/publication_audit.py YYYY-MM-DD` で公開URLまで確認する

## 再発防止の中核

- 収集範囲の正は `config/night_signal_coverage.json`。
- 抽出ログは作業メモではなく、網羅収集の証跡。
- `scripts/coverage_audit.py` は、検索軸、情報源の多様性、URL根拠数、掲載カードと抽出ログの一致を検査する。
- `scripts/quality_gate.py` は `coverage_audit.py` を内包しているため、構造化収集契約を満たさない当日版は公開できない。
