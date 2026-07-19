# NIGHT SIGNAL 基本設計

更新日: 2026-07-17

## 1. ミッション

NIGHT SIGNALは、各カテゴリの情報を広く確認し、根拠のある重要更新を従来の
形式で並べる。どの項目を読むかは利用者が決める。

掲載数を少なく整えることは目的ではなく、掲載件数の上限も設けない。ただし、
類似情報、既知情報の言い換え、定例・低重要度情報、根拠のない水増し、候補欄、
参考情報欄、確認作業の説明は公開しない。

過去約3か月は継続的にミッションを満たせていない。設計やテストの合格だけで
改善済みとは判断せず、日々の公開結果で信頼性を確認する。

## 2. 公開契約

- 全カテゴリを同じ基本思想で広く探索する。
- 根拠のある独立した重要更新を件数目標で削らない。
- 題名と、更新を理解するために必要十分な事実を根拠の範囲で要約する。
- 参照元が詳しい時は、主体の役割、変化、仕組み、範囲、固有名詞、数値、日付、
  条件、結果のうち、記事理解に必要なものを残す。
- 参照元が薄い時は文章を膨らませない。
- 画像、図、表は文章だけでは重要情報を伝えにくい場合だけ使う。
- 承認待ちで停止しない。
- JST当日号を19:00までに固定URLへ公開する。
- 19:00以降の通常情報は翌日号へ送り、緊急性と影響度が特に高い変化だけ
  当日追記する。
- 前日号を当日号として再公開しない。
- 新規性は直前号との差分を必ず確認し、さらに前2号を既知情報の補助履歴として使う。
  URL、公開日、見出しだけの変更は新規とみなさず、決定、実行、結果、数値の進展は残す。
- Editorへ渡すeventには、既掲載か、本文で明示された出来事日、最新の記事公開日、実効source
  classを分離して付ける。既掲載eventの本文にだけ現れた説明は、公式・登録主要媒体、直近の
  出来事日、決算・重要市況、または根拠ある新分析のいずれもなければ事前除外する。

## 3. 最小構成

```text
Topic definitions
    -> Collect evidence
    -> Edit important updates
    -> Build issue
    -> Publish and verify
```

内容契約は二つだけとする。

- **Evidence**: 実際に確認したURL、取得日時、掲載日、本文または抜粋、取得成否。
- **Issue**: 公開する重要更新、事実ごとの根拠URL、表示順、公開日。

Evidenceには網羅性確認用のトップページや索引も保持する。ただし、Issueの根拠に
できるのは、出典自身の掲載日と対象カテゴリの具体的変化を確認できる記事・発表・
データだけとする。重要候補が見出しだけの場合は、主体と対象を残した限定検索で
別媒体または公式情報の本文を先に解決する。解決できなくても、見出し自体が題名と
別の具体的事実を支えられる場合だけ`headline`深度のEvidenceとして同じEditorへ渡す。
それ以外は水増しせず、探索証跡と掲載根拠を同一視しない。

重要更新の編集中表現はIssue生成の内部データであり、別の公開面や恒久的な
候補台帳にしない。

永続状態は原則として次に限定する。

- `evidence.json`
- `issue.json`
- 再実行に必要な最小checkpoint

同じ内容を候補、決定、cardへ重複保存しない。日次の説明ログや
チャット履歴も作らない。

## 4. 責任境界

- Collectorは取得だけを行い、公開文章を作らない。
- Editorだけが掲載可能Evidenceの抽出、変化点レビュー、重複統合、重要性判断、要約を
  行う。変化点レビューは内部処理であり、新しい永続状態や公開面にしない。
- Editor前は日付、取得成否、カテゴリ主体、ナビゲーション除外に加え、明確な定例更新、
  投資コメント、プレビュー、過去年の概要、カテゴリ名の別分野衝突を決定的に除外する。
  ただし、決定、契約、開始、結果など具体的進展がある場合は残し、曖昧な重要候補を
  個別の過去事例語だけで落とさない。
- Validatorは不正な状態を拒否するが、文章を書き換えない。
- Rendererは`issue.json`を表示するだけで、文章を補修しない。
- Publisherは検証済みIssueの公開と公開確認だけを行う。

一つの処理を複数段階で補修しない。後段が前段の不足を埋める設計は禁止する。

GitHub Actionsは認証不要のWeb Evidence収集、compact packet作成、review適用後の
決定論的検証・commit・Pages公開を担当する。ChatGPT Plusに含まれるWeb Scheduled taskは
compact packetの採否・要約reviewだけを担当する。ローカルPCは診断専用で、本番ownerにしない。
境界はhash付き`evidence.json`、`editor_packet.json`、`editor_review.json`に固定し、
CollectorやPublisherがAI編集を、Web taskが収集やPages公開を代行しない。

## 5. 網羅性

各カテゴリで二つの探索を行う。

1. 登録済みの公式、主要報道、専門媒体、データ、SNS、動画を確認する。
2. カテゴリ、全watch topic、重要変化語から未登録情報を広く発見する。

登録済みソースだけでも、検索結果だけでも完了としない。同一事象は統合するが、
異なる重要更新は残す。処理量が一回の上限を超える場合は切り捨てず分割する。

網羅性はURL到達数ではなく、次の別々の事実で測る。

- 全watch topicについて、実際の検索語、検索成否、結果数をEvidenceへ残す。
- watch topic外の隣接変化を拾うhorizon検索を、日英共通の変化語彙から20語以下の
  bounded queryへ分けて行う。
- 登録ソースの到達確認はsource check、テーマ探索はdiscovery checkとして混同しない。
- 重要更新らしい結果には本文解決を試みる。解決できないqueryは`unresolved`として
  Evidenceに残すが、無関係な本文へ接続して探索完了を装わない。Issueへ渡すのは
  本文、内容のある出典抜粋、または題名と別の事実を支えられる具体的な見出しを
  解決できた項目だけとする。重要候補があるwatch topicで編集可能な根拠が0件なら、
  その候補は公開せずsource gapへ残す。他の検証済みニュースと日次Web公開は続行し、
  次回は同じ未解決テーマだけを優先して深掘りする。
- 結果がないことと、結果を見つけたが本文を取れないことを別の状態にする。

検索回数はカテゴリ単位の大きなOR検索を増やすのではなく、watch topicごとの小さな
検索へ再配分する。語数が多いtopicだけ分割し、設定された語を末尾から捨てない。
検索サービスが返したページは固定件数で切らず、対象期間、カテゴリ、重複を
決定的な前処理で除いてから本文取得する。

本文が弱いwatch topicだけ、登録済み公式ドメイン1件と専門媒体ドメイン1件を
別々の`site:`検索で確認する。複数ドメインを一つのOR検索へ束ねない。検索結果の
記事URLまたは配信元URLが指定ドメインと一致しない場合は、結果数、重要候補数、
解決数のいずれにも算入しない。Bingが失敗または対象ドメイン0件ならGoogle Newsを
同じドメイン条件で一度だけ代替使用する。これは弱いtopicだけの決定的な再検索で、
モデル呼び出しや全カテゴリ再収集を増やさない。

重要候補の定義は探索、本文解決、Editor入力で共有する。検索語に現れた動詞が
想定済みの表現と違うだけで本文解決対象から外してはならない。本文解決の追加検索は
Google Newsの元リンクから配信元へ到達する経路を先に試し、それで解決できない時だけ、
見出し全文、配信元限定、主体・対象を残したevent probeの最大三経路を使う。
候補URLは配信元と同じドメインに限定し、内容一致度で並べて上位だけを読む。

抜け漏れ指摘は、最初に失われた段階を特定する。個別ニュース名を本番コードの
条件分岐へ追加せず、同じ失敗を再現できる評価例として残し、共通処理を直す。

## 6. 要約

Editor前の決定的処理で、同一事象の複数記事だけを一つのeventへまとめる。日付、主体、
対象、工程または結果が異なる事象は別eventのまま保ち、event IDを越えた統合を禁止する。
その後、一回の意味判断で各eventを公開項目または限定された除外理由へ割り当てながら、
参照元本文全体を把握して次を作る。掲載数の上限やカテゴリごとの少数選抜は設けず、
不確実な重要候補は掲載側へ残す。

- 読者向け題名
- 読者が更新を理解するために必要十分な、順序付きの要約文
- 各要約文を支えるEvidence ID

題名の言い換え、同じ文の反復、一般論、媒体名だけの文章を要約として扱わない。
参照元に十分な情報がある時だけ詳しくし、情報がない時は短いままにする。
参照元にない重要性、影響、常識、背景、未確定点を推測で補わない。

Codex Plus reviewへは、event ID、必要な根拠文、短いEvidence ID、Evidenceごとの
watch topic IDだけをcompact packetとして渡す。全Evidenceや作業ログは読ませない。
複数記事を一つのrequestへ詰めるために本文を再切詰めしない。request上限へ近づく時は、
同一事象を分断しない単位でrequestを分ける。同一eventの重複報道だけで上限を超える場合は、
日本語原文、本文量、取得順で決定的に代表ソースを選び、選んだ本文は切り詰めない。選外URLと
本文もEvidenceには保持し、記事ごとのAI採否処理は追加しない。
モデルはevent ID、題名、分類、重要度、根拠ID付き`summary_points`を構造化出力し、
各項目の根拠IDが同じevent境界内にあることを決定的に照合する。
`summary_points`の同じ文列を公開要約、確認事実、事実とURLの対応へ再利用し、summary、
detail summary、what changedを別々に生成しない。URLと掲載日はAIに
書かせず、Evidence IDから決定的に復元する。同一事象を統合する場合も、計画、決定、
実行、結果など状態の進展は別の要約文として残す。

ニュースの網羅性と確認事実を最優先とし、分析は任意の別レイヤーにする。公式・専門・
主要媒体が同じeventに異なる固有事実を加える場合、代表1媒体へ潰さず、本文と固有事実を
requestの損失なき上限までEditorへ渡す。分析を返す場合だけ、同一event内の独立した本文Evidenceを
2件以上引用し、推論、反証、残る不確実性、確信度を分離する。分析の不成立や検証不合格は
分析だけを非掲載とし、検証済みニュースと完全な事実要約を削除・停止しない。最低文字数、
最低文数、一般論、既知背景、同義反復による水増しは禁止する。
専門本文を確保できない候補はsource gapとして残し、薄い見出し要約へ変換しない。一方で、
その候補や任意分析の不成立を理由に、他の検証済みニュースや日次Web公開を停止しない。
Issue内部では同じ文列を検証と出典対応に使うが、詳細ページには要約を一度だけ表示し、
同じ文を要約と事実一覧へ二重表示しない。

各要約文にはEvidence IDを対応させ、その取得済み本文から短いsupport quoteを決定的に
復元する。support quoteは公開せず、翻訳要約や数値変換の根拠確認だけに使う。

掲載可能Evidenceには各段階の短い連番IDを付ける。ただし完全性の単位は記事ではなく
eventとし、すべてのeventが公開項目または限定された除外理由へ一度だけ割り当てられたかを
確認する。同一event内の複数記事に個別の採否説明を生成させず、要約文が引用したEvidence
だけを公開側の根拠対応へ使い、event内の全URLはEvidenceに保持する。reviewがeventの判断を
返さなかった時に薄い文章を機械生成せず、その編集結果を不合格にする。根拠のない要約文だけを
除去した後も必要十分な根拠付き要約が残る場合はevent全体を再生成しない。

本番reviewは`config/night_signal_ai.json`でGPT-5.6 Terra、low reasoningに固定する。
これは長いEvidenceの日本語編集品質とPlus使用量の均衡を取る経路であり、件数や重要事実を
減らすための軽量model routeではない。分析、表・グラフ、高数値密度のeventはpacket上の
`quality_route=true`で明示し、同じreview内で一次情報、複数数値、帰属、矛盾を重点確認する。
JSON responseは`night_signal_plus_editor.py`が全request、全event、Evidence ID境界、support、
日本語copyを決定的に検証する。失敗時は指摘されたeventだけを最大2回修正し、合格済みeventを
再生成しない。GitHub Models、OpenAI API、Copilot creditsは本番経路に置かない。

構造化出力はrepositoryのreview schemaで固定し、壊れたJSON全体を別promptで再生成しない。
短い公式発表、英語本文、表・画像中心の資料、分析記事を一律に排除せず、具体的な
事実が題名を超えて取得できたかで同じように判定する。

## 7. 再実行と効率

各段階の完了結果は、同日かつ入力が変わっていない場合だけ再利用する。
収集契約は明示的なrevisionで管理し、探索仕様、Evidence schema、収集対象設定を変えた時だけ
更新する。Editor、要約モデル、検証、rendererの変更では同日Evidenceを無効化しない。

- 取得後の失敗ではEvidenceを再利用する。
- 編集途中の失敗では、Evidence、review契約、request/event payloadの全hashが一致する
  合格済みresponseを再利用する。Validatorが示したrequest/eventだけを修正し、制御フローだけの
  変更で成功済みresponseを全無効化しない。
- 編集後の失敗ではIssueを再利用する。
- GitまたはPagesの失敗で収集やAI処理を繰り返さない。
- 既公開なら即終了する。
- 既公開号を強制再収集する経路は持たない。未公開の前日号だけは、翌日の最終収集開始時刻
  より前に限り、同じ前日Evidenceと前日の日付表示のまま復旧公開できる。当日号の収集開始後
  は前日号をrootへ出さず、それ以前の日付は受け付けない。

公開時刻は`config/night_signal_operations.json`だけが所有する。16:45以降のGitHub Actions
heartbeatはWeb Evidenceとcompact packetだけを収集し、既存artifactがあれば再収集せず、
AI、commit、Pages処理を行わない。GitHub pluginを明示したChatGPT Web Work modeの
primary ownerは17:50、recovery ownerは18:25にaudit-firstで起動し、最新の有効packetを
一度だけreviewする。各ownerは最初に`started` heartbeatを書き、GitHub writeが失敗した場合は
review tokenを使わず停止する。review branchのpushを
受けたGitHub Actionsが検証・commit・Pages公開を行う。後続回は先行回が成功済みなら
小さいstatusだけを確認して即終了する。
未公開の場合も、active collectorを重複dispatchせず、Evidence、review、Issue、commit、Pagesの
完了済み段階を順に再利用する。19:00以降は通常の日次処理を新規開始しない。

18:00のGitHub Actions watchdogはprimary ownerのGitHub到達を検証する。18:35、18:50、
19:05のwatchdogは、review後のevent trigger欠落、restore、
commit、push、Pages、公開反映だけを同じreviewから一度復旧する。review自体がない場合は
AIの代替生成をせず、Evidence欠落、Web owner heartbeat欠落、task停止・権限不足を区別して
失敗を明示する。Web taskの当日heartbeat、review、最終publication auditは別の証拠とし、
repositoryの静的テストだけで本番稼働済みと判定しない。

review validatorは全requestを一度走査して全不合格request/eventを一括報告する。
Web recovery ownerは大きい`editor_review.json`を書き直さず、不合格requestの完全なresponseだけを
`editor_correction.json`へ一度書く。GitHub Actionsは同じEvidence hashを検証してoverlayするため、
合格済みresponseの再生成、再送、再編集を行わない。

Evidenceの構造、source check、discovery check、watch topic、取得チャネル、取得状態の
検証規則は`night_signal_evidence.py`だけが所有する。Editor、Issue validator、coverage
audit、runtime audit、evalは同じ検証結果を使い、各段階で別の解釈を実装しない。
CollectorとEditorの再利用可否は関係ファイルと設定のfingerprintで判定し、設計変更時の
version更新忘れや、検証失敗後の不要な再収集・AI再実行を防ぐ。

取得前にURL重複を除き、review前に同一記事と同一事象を決定的にまとめる。
採否と要約は同じPlus reviewで行い、途中失敗は成功済みrequest/eventから再開する。
reviewはcompact packetだけを読み、確認用canary、全Evidence再読、同じ文章の再生成には
使わない。推論量やmodelを上げるのは、代表Evidenceで網羅性または要約品質が改善する場合だけとする。

日次処理では公開に必要な検証だけを行う。全故障simulationは設計・実装変更時に
行い、日次処理へ積み上げない。

同じIssue契約を同一段階で繰り返し検証しない。Editorの出力境界、Rendererの入力境界、
Evidence網羅性、公開HTMLの各境界で一回ずつ検証し、同じ検証関数を連続実行しない。
公開HTMLの反映待ちはPages workflow内で一度監査し、最終ownerはcommit、remote HEAD、
root URL、dated URLの一致を`publication_audit.py`で確認する。これはPages jobのgreenと
公開内容の一致が別条件であるためで、収集やAI reviewの再実行理由にはしない。

永続化する公開状態は現在号と直前3号に限定する。Editorは直前3号を新規性比較に使い、
読者はarchiveから同じ3号を確認できる。次号が全local gateに合格した後で4号より古いstate、
sample、dated siteと未使用detailを削除する。失敗途中では公開中の履歴を削除しない。
旧形式のvalidationや日付別contract分岐は持たない。旧collection modeは直前3号を表示・監査する
移行互換としてだけ受理し、新規Evidenceには生成しない。

## 8. 拡張と新技術

新しい検索、Web agent、RSS、SNS API、動画字幕、OCR、画像理解、表抽出は、
既存Collectorを置き換えるEvidence取得手段として評価する。新しい要約modelは
既存Editorを置き換える候補として評価する。
カテゴリ識別語、watch topic、探索軸、必須チャネルは
`config/night_signal_coverage.json`だけが所有し、カテゴリ追加でPythonの判定分岐を増やさない。

新技術は本番出力と分離して比較し、網羅性、事実精度、要約品質、処理時間、
tokenのいずれかを品質低下なしで改善する場合だけ切り替える。切替後に旧方式を
恒久的な第二経路として残さない。

日次経路は、認証不要の登録ソース確認、日英および地域現地語の
topic別ニュース探索、bounded horizon探索、媒体別の公開index探索、重要候補だけの
event probeを使う。
毎週月曜日だけOpenAI公式latest-model文書を確認し、ChatGPT Scheduled taskで利用できる新しい
互換世代・tierを候補化する。変更がない日は追加の比較や報告を行わない。候補がある時だけ、
固定した代表Evidenceで事実精度、除外精度、event完全性、要約品質、処理時間、総tokenを
GPT-5.6 Terraと一回比較する。品質非劣化と同等以下のtoken使用を満たしても、本番設定は
自動変更せず評価結果を確認して反映する。モデル確認不能は当日公開を止めない。

Responses API `web_search`は全source metadata、domain filter、画像検索、長時間検索制御を
利用できるが追加費用が発生するため、現行の日次経路へは追加しない。探索仕様の定期評価と、
将来費用条件が変わった時の置換候補とする。Deep Research、Programmatic Tool Calling、
Multi-agentも同様に比較対象とし、日次へ並行経路として足さない。YouTube、X、Meta、
TikTokの公式APIは精度面で有力だが、認証、利用資格、quota、費用を満たす場合だけ、
公開index探索を置き換えるadapterとして導入する。
サイトマップ、動画字幕、OCR、画像・表抽出も、必要な媒体で本文取得率が改善する
ことを評価例で確認してから既存取得手段と交換する。

将来のベンダー切替自体を目的にした抽象化は作らない。実際に必要な取得契約と
Issue契約だけを安定させる。

## 9. 公開成功

次のすべてが一致した時だけ成功とする。

- 当日EvidenceとIssueの日付
- commitとremote HEAD
- Pages完了
- root URLとdated URLの日付・内容
- 公開Issueの根拠URLと詳細リンク

19:00を超えた公開、当日号の欠落、古い号の再表示は失敗として扱う。

## 10. 禁止事項

- 失敗事例ごとの本番分岐や専用スクリプト
- 候補欄、参考情報欄、確認情報欄の追加
- 同じ状態の複数ファイル保存
- 複数owner、複数公開経路
- 後段ValidatorやRendererによる文章生成・補修
- 品質改善が測定されていない技術の本番追加
- 完了していない機能を基本設計上の既成事実として記載すること
