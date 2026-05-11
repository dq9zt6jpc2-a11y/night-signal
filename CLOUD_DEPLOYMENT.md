# NIGHT SIGNAL クラウド公開メモ

## 公開対象

公開するのは `site/` 配下だけです。

Safari書き出しの `safari_export/`、パスワードCSV、支払いカードJSON、履歴JSONは公開禁止です。`.gitignore` で除外しています。

## 推奨構成

- GitHub repository
- GitHub Pages
- GitHub Actions
- 固定URL: GitHub Pages のトップページ
- 公開内容: `site/index.html`
- 履歴: `site/YYYY-MM-DD/`

## 現在作ったもの

- `.github/workflows/pages.yml`
  - GitHub Pagesへ `site/` を公開するワークフロー
  - 手動実行と毎日22:10 JSTの定期実行に対応
- `.gitignore`
  - Safari書き出しや秘密情報を除外
- `.nojekyll`
  - GitHub Pagesで静的ファイルをそのまま配信するためのファイル

## 注意

このワークフローはWeb公開の土台です。

本格的な「23時間調査」は、クラウド上で実行する調査エージェントまたは外部APIキー、SNS/X/YouTubeの取得方法が必要です。GitHub Actionsだけで長時間連続実行するのは制限があるため、現実的には以下のどちらかです。

1. Codexのクラウド/ワークツリー自動実行で調査し、結果をGitHubへ反映する
2. VPSやクラウドサーバーで調査プロセスを常駐または定期実行し、`site/` を更新する

