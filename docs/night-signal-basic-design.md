# NIGHT SIGNAL 基本設計

更新日: 2026-06-28

## 1. 現状認識

過去約3か月、網羅性、要約品質、日付更新、無人公開のいずれかで失敗が
続いている。単発のテスト合格や1日の公開成功は、信頼性の回復を意味しない。
現時点の運用品質は「100戦100敗を前提とした未証明状態」と評価する。

30夜連続で後述の運用基準を満たすまで、安定済みとは判定しない。設計変更を
完了と呼べるのは、コードが動いた時ではなく、利用者のミッションを継続的に
満たした時である。

## 2. ミッション

NIGHT SIGNALのミッションは次の三点である。

1. 各カテゴリを広く探索し、根拠のある重要更新を漏れにくく並べる。
2. 利用者が読む項目を選べるよう、重要更新を従来形式で公開する。
3. 選ばれた項目には、参照元の情報量に応じた具体的で読みやすい要約を出す。

掲載件数を少なく整えることは目的ではない。不足より過剰を許容する。一方、
根拠のない水増し、候補欄、参考情報欄、確認作業の説明は公開しない。

絶対条件:

- 全カテゴリを同じ基本思想で広く探索する。
- 根拠のある独立した重要更新を件数目標で削らない。
- 事実、今回の変化、重要性、未確定点を根拠の範囲内で要約する。
- 参照元が薄い時は文章を水増ししない。
- 画像、図、表は理解に必要なStoryだけに付ける。
- 承認待ちで停止しない。
- JST当日号を20:00までに固定URLへ公開する。
- 前日号を当日号として再公開しない。

## 3. 設計原則

### 3.1 三つの内容契約

内容データは次の三契約だけを持つ。

```text
Topic Contract
    -> Source Adapters
    -> Evidence Ledger
    -> Editorial Engine
    -> Story Set
    -> Issue Builder
    -> Issue
    -> Publish
```

- **Evidence**: 実際に取得したURL、取得日時、掲載日、本文または抜粋、媒体種別、
  取得成否。判断文や公開用文章を含めない。
- **Story**: 同一事象をクラスタ化した重要更新。変化、重要性、確認事実、
  未確定点、事実ごとの根拠URLを持つ。
- **Issue**: 公開するStoryと表示順、公開日、カテゴリ、詳細ページ情報を持つ。

EvidenceとStoryを同じファイル・同じ処理責任に混在させない。

### 3.2 責任は一段階に一つ

- Source Adapterは取得だけを行い、採否や公開文章を作らない。
- Editorial Engineだけがクラスタリング、重要性判定、要約を行う。
- Validatorは不正状態を拒否するが、文章を書き換えない。
- RendererはIssueを表示するだけで、要約を補修しない。
- Publisherは収集や要約を行わず、検証済みIssueを公開する。

同じ要約をcollector、editor、state、rendererで繰り返し補修する構成は禁止する。

### 3.3 単一owner

- 定刻実行ownerは一つ。
- アプリケーションownerは一つ。
- 日付、状態遷移、再実行判断はownerだけが決める。
- Workflowから内部collectorやeditorを直接呼ばない。
- 日付固有スクリプト、第二の公開経路、別形式のfallback issueを作らない。

## 4. 永続状態

当日状態は次に限定する。

- `evidence.jsonl`: 正規化したEvidence。取得直後に原子的に保存する。
- `stories.json`: Editorial Engineが作ったStory Set。
- `issue.json`: 検証済みの唯一の公開入力。
- `run.json`: ステージ、入力hash、所要時間、token、失敗理由だけを持つ制御状態。

候補、決定、card、manifestを別ファイルへ重複保存しない。日次の説明ログや
チャット履歴も作らない。必要な計測値は`run.json`へ構造化して保持する。

各ステージは入力hashが一致する時だけ再利用する。

- 取得失敗: 完了済みEvidenceを再利用し、失敗したadapterだけ再試行する。
- model失敗: Evidenceを再利用し、Editorial Engineだけ再試行する。
- build失敗: Story Setを再利用する。
- Git/Pages失敗: Issueを再利用し、収集とmodelを再実行しない。

## 5. 網羅性

### 5.1 二層探索

各カテゴリで必ず次を行う。

1. **既知面**: 登録済み公式、主要報道、専門媒体、データ、SNS、動画を確認する。
2. **未知面**: カテゴリ名、全watch topic、material signal語を使って広く発見する。

既知ソースだけでも、検索結果だけでも完了としない。新しい検索技術は未知面を
強化できるが、既知面の確認を置き換えない。

### 5.2 件数と採用

- 公開件数の目標値を設けない。
- 根拠のある独立したmaterial clusterはすべてStoryにする。
- API保護上の上限に達した場合は、削除せず次の処理単位へ分割する。
- 「最大N件だから切る」というeditorial truncationは禁止する。
- 重要更新が0件のカテゴリは、探索済みEvidenceで0件を説明できなければ失敗する。

### 5.3 指摘の扱い

利用者からの抜け漏れ指摘は、個別カテゴリの条件分岐へ直接追加しない。
次のどこで最初に失われたかを分類する。

- source discovery miss
- fetch/content extraction miss
- clustering miss
- materiality miss
- summary/detail miss
- schedule/publication miss

指摘事例は`evals/missed-stories.jsonl`の再現データに追加し、全カテゴリ共通の
contractまたはadapterを修正する。同じ失敗分類が再発しないことを横断評価する。

## 6. 要約品質

Storyは最低限、次を持つ。

- 読者向け題名
- 今回何が変わったか
- なぜ今読む価値があるか
- 3件以上を基本とする具体的な確認事実
- 未確定点または適用範囲
- 各事実に対応する根拠URL

参照元に十分な本文がある時は、固有名詞、数値、日付、対象、条件、比較軸を
残す。本文がない時は、確認できた題名・掲載日・URL以上に膨らませない。

画像、図、表を付ける条件:

- 文章だけでは主要な比較、推移、形状、配置を正確に伝えにくい。
- 元資料または利用許諾された画像を直接参照できる。
- `necessary_reason`をStoryに記録できる。

条件を満たさない媒体追加は禁止する。

## 7. 拡張性と新技術

拡張点はSource AdapterとEditorial Engineの実装交換だけに限定する。新しいWeb
search、agent、RSS、SNS API、動画字幕、OCR、画像理解、表抽出は、同じEvidence
schemaを出力するadapterとして追加する。新しい公開経路は作らない。

新技術の導入手順:

1. 既存の代表事例と抜け漏れ事例でoffline評価する。
2. production出力に影響しないshadow modeで比較する。
3. 網羅性、事実精度、要約品質、token、時間、失敗率を比較する。
4. 品質を落とさず、少なくとも一つを測定可能に改善した時だけ設定で昇格する。
5. 昇格後も旧実装を恒久的な第二経路として残さず、rollback期間後に削除する。

ベンダー切替容易性そのものを目的にしない。実際に必要な拡張点だけをcontractで
分離し、抽象化が処理分岐を増やす場合は採用しない。

## 8. 効率

- URL metadataと更新有無を先に確認し、本文取得は変更・発見候補を優先する。
- modelへ渡す前にURL重複と同一事象を機械的にまとめる。
- model処理はEvidenceが変わったカテゴリだけに行う。
- fallback modelは実際の失敗後だけ使う。canary用model callは行わない。
- static promptを固定し、利用可能ならprompt cacheを計測して使う。
- reasoning量は固定観念で上げず、抜け漏れ・要約評価で改善した時だけ上げる。
- 日次実行では契約検証と公開境界だけを確認し、全故障simulationは変更時に行う。
- 既公開なら即終了する。

効率指標:

- source fetch数、本文取得数
- model call数、入力token、出力token、cache hit
- categoryごとの処理時間
- 再利用したstageと再実行したstage
- 19:05開始から公開確認までの時間

## 9. 20:00公開と障害回復

- 19:05 JSTに本実行する。
- 19:35 JSTは公開未確認時だけ実行する。
- 二回目は同日・19:00以降・入力hash一致のcheckpointだけ再利用する。
- Pages成功、root URL、dated URL、Issue日付のすべてが一致して初めて成功とする。
- 外部障害で20:00を超えた場合は失敗として記録し、成功扱いにしない。
- 前日号を当日号に見せるfallbackは禁止する。

## 10. 検証と信頼回復

変更時の合格条件:

- 全category/watch topicのEvidence状態が閉じている。
- 登録seed URLがobservedまたはunavailableのどちらかである。
- 公開事実と根拠URLの対応率が100%である。
- 既知の抜け漏れ回帰データがすべて検出・採用される。
- 要約に内部文言、重複、水増し、題名の言い換えだけがない。
- 日付跨ぎ、model失敗、build失敗、Pages失敗から正しいstageだけ再開する。
- root、dated、detailのリンクと日付が一致する。

運用安定の判定:

- 30夜連続で20:00までに公開確認。
- obvious missの未解決再発が0件。
- 公開事実のsource mapping違反が0件。
- 手動承認による停止が0件。
- stale issue公開が0件。

## 11. 現行実装とのギャップ

2026-06-28時点で実装済み:

- timed ownerとapplication ownerの一本化
- 全watch topicを使う探索
- 編集上のカテゴリ3件制限の撤廃（現状はAPI保護上限12件）
- 既知ソースと広域検索の併用
- 事実とURLの対応検証
- 既公開短絡、同日checkpoint、日付跨ぎ拒否
- 19:05本実行、19:35失敗時実行

未実装であり、完成扱いしてはいけない項目:

- EvidenceとStoryの別artifact化
- API保護上限到達時の分割処理（現状は12件で切れる）
- collectorからEditorial責任を完全分離
- ValidatorとRendererによる文章補修の廃止
- stage別入力hashと部分再開
- Evidence差分があるカテゴリだけmodel処理する仕組み
- `evals/missed-stories.jsonl`による指摘回帰評価
- 新技術shadow modeと昇格評価
- 30夜連続の運用実績

## 12. 移行順序

1. `research_bundle.json`を`evidence.jsonl`と`stories.json`へ分離する。
2. collectorをSource Adapter群と取得orchestratorへ縮小する。
3. 公開文章の生成をEditorial Engineだけへ移す。
4. ValidatorとRendererから文章書換えを削除する。
5. stage hashによる再開とtoken/時間計測を実装する。
6. 指摘回帰データとshadow評価を導入する。
7. 30夜の実績で安定性を判定する。

移行中も本番経路を二本にしない。各段階で新契約へ切り替え、旧契約を削除して
から次へ進む。
