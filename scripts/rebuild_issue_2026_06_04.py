#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rebuild_issue_2026_06_03 as base


base.DATE = "2026-06-04"
base.CHECKED = "2026-06-04T21:45:00+09:00"
base.WINDOW_START = "2026-06-03T20:45:00+09:00"

base.MANUAL_UNPUBLISHED_CATEGORIES = {"SoftBank", "Honda", "YOASOBI / 幾田りら", "宇都宮ブレックス"}

base.DATA.update(
    {
        "OpenAI": (
            "openai",
            "OpenAI / AI",
            "signal",
            "Codex / Sites",
            "product_release",
            "OpenAI、Codexにロール別プラグイン、Sites、注釈を追加",
            "6月2日の公式発表で、Codexのプラグイン、共有URL付きSitesプレビュー、画面上注釈が追加された。週次利用者500万人超、非開発者20%という利用拡大も示された。",
            "OpenAIは6月2日、Codexを開発者以外の業務にも広げる新機能として、ロール別プラグイン、Sites、注釈を発表した。SitesはCodexが作成したインタラクティブなWebサイトやアプリをワークスペース内でURL共有できるプレビュー機能として説明されている。公式発表では、Codexの週次利用者が500万人を超え、非開発者が全体の約20%を占め、その伸びが開発者より速いことも示された。今回の更新は、コード差分を出す開発支援から、社内ツール、資料、ダッシュボード、顧客レビュー用ページまでを同じ製品体験で扱う方向を明確にした。Help Centerのプラグイン説明も、プラグインがワークフロー、スキル、承認済みアプリ連携を束ねる仕組みで、データ権限そのものを増やすものではないと整理している。",
            "2026-06-02",
            [
                "https://openai.com/index/codex-for-every-role-tool-workflow/",
                "https://help.openai.com/en/articles/20001256",
                "https://developers.openai.com/codex/explore",
            ],
            [
                "https://openai.com/index/codex-for-every-role-tool-workflow/",
                "https://help.openai.com/en/articles/20001256",
                "https://9to5mac.com/2026/06/02/openai-putting-codex-inside-chatgpt-app-everywhere-releasing-6-business-plugins/",
                "https://developers.openai.com/codex/explore",
                "https://x.com/OpenAI",
                "https://www.youtube.com/@OpenAI",
                "https://status.openai.com/",
            ],
        ),
        "F1": (
            "f1",
            "F1 / Honda F1",
            "signal",
            "Monaco / Aston Martin",
            "honda_aston_pu",
            "Aston Martin、Maaden特別リバリーをF1公式ギャラリーでも公開",
            "F1公式とAston Martin公式が、モナコGP用のMaaden特別リバリーを6月3日に掲載。Hondaワークス初年度の露出面でも週末の材料が増えた。",
            "Formula 1公式は6月3日、Aston MartinがモナコGPで走らせるMaaden特別リバリーのギャラリーを掲載した。Aston Martin公式の特集も、Principal PartnerであるMaadenとの共同企画として、通常の緑を土系の色調へ変えるデザインを説明している。モナコGPは6月5日から7日の週末で、まだ競技結果ではなく、車体露出、スポンサー活用、開催前の注目材料が中心になる。Hondaワークス初年度のAston Martinはパワーユニット性能だけで評価されがちだが、モナコでは低速市街地、ブランド露出、スポンサー施策が同時に前面へ出る。",
            "2026-06-03",
            [
                "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA",
                "https://www.astonmartinf1.com/en-GB/news/feature/from-rock-to-racetrack-the-story-of-maadens-monaco-grand-prix-livery",
                "https://www.formula1.com/en/latest/article/formula-1-louis-vuitton-grand-prix-de-monaco-2026.5eqj7xSRWW6dylGmncfs6T",
            ],
            [
                "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA",
                "https://www.astonmartinf1.com/en-GB/news/feature/from-rock-to-racetrack-the-story-of-maadens-monaco-grand-prix-livery",
                "https://www.motorsport.com/f1/news/Aston-Martin-reveals-Monaco-GP-livery/10826403/",
                "https://www.formula1.com/en/latest/article/formula-1-louis-vuitton-grand-prix-de-monaco-2026.5eqj7xSRWW6dylGmncfs6T",
                "https://x.com/F1",
                "https://www.youtube.com/@Formula1",
                "https://as.com/motor/formula_1/un-aston-especial-para-monaco-f202606-n/",
            ],
        ),
        "SpaceX": (
            "spacex",
            "SpaceX / 宇宙",
            "signal",
            "Starlink",
            "official_launch_manifest",
            "SpaceX、6月4日にStarlink 17-44のFalcon 9打ち上げ枠",
            "RocketLaunch.Liveは6月4日14:00 UTCのStarlink 17-44を掲載。公式Launchesの6月Starlink枠と合わせ、Falcon 9の高頻度運用が続く。",
            "6月4日時点の打ち上げ予定では、RocketLaunch.LiveがStarlink 17-44を同日14:00 UTCのFalcon 9ミッションとして掲載している。SpaceX公式Launchesも6月のStarlinkミッション枠を示しており、Starship開発とは別に、Falcon 9による低軌道通信網の増設が短い間隔で続いている。直近のStarship Flight 12は大型輸送能力の開発案件だが、Starlinkの運用打ち上げは収益化済みサービスの容量追加に近い。6月4日号では、実証開発と商用運用の時間軸を分け、Falcon 9の反復運用がSpaceXの足元を支える点を扱う。",
            "2026-06-04",
            [
                "https://www.rocketlaunch.live/launch/starlink-17-44",
                "https://www.spacex.com/launches/",
                "https://www.spacex.com/vehicles/starship/",
            ],
            [
                "https://www.spacex.com/launches/",
                "https://www.rocketlaunch.live/launch/starlink-17-44",
                "https://www.space.com/space-exploration/launches-spacecraft/spacex-starlink-10-53-1085-ccsfs-asog",
                "https://www.spacex.com/vehicles/starship/",
                "https://x.com/SpaceX",
                "https://www.youtube.com/@SpaceX",
                "https://spaceflightnow.com/",
            ],
        ),
        "日本経済": (
            "japan_economy",
            "日本経済",
            "macro",
            "サービスPMI",
            "employment_consumption",
            "日本5月サービスPMIは50.0、13カ月の拡大が停止",
            "6月3日の民間PMIで、日本サービス業は50.0に低下。中東情勢由来のコスト上昇と12年ぶりの販売価格インフレが重しになった。",
            "6月3日に報じられたS&P Globalの日本サービス業PMIは、5月に50.0へ低下し、4月の51.0から鈍化した。Reuters系の報道は、13カ月続いた拡大が止まり、中東情勢に伴うコスト上昇が需要を抑え、販売価格インフレが12年ぶりの高水準になったと伝えている。製造業PMIが拡大圏を維持する一方で、サービス業は価格転嫁と需要の弱さが同時に出ており、日銀の物価判断では賃金だけでなく企業の価格設定と家計需要の耐久力が焦点になる。",
            "2026-06-03",
            [
                "https://www.investing.com/news/economic-indicators/japans-services-activity-stagnates-in-may-as-costs-surge-pmi-shows-4723210",
                "https://www.pmi.spglobal.com/",
                "https://www.boj.or.jp/en/announcements/press",
            ],
            [
                "https://www.investing.com/news/economic-indicators/japans-services-activity-stagnates-in-may-as-costs-surge-pmi-shows-4723210",
                "https://www.pmi.spglobal.com/",
                "https://www.reuters.com/markets/asia/",
                "https://www.boj.or.jp/en/announcements/press",
                "https://x.com/Bank_of_Japan_e",
                "https://www.youtube.com/@BankofJapan",
                "https://www.nikkei.com/",
            ],
        ),
        "アジア経済": (
            "asia",
            "アジア経済",
            "macro",
            "中国PMI",
            "china_macro_policy",
            "中国5月CaixinサービスPMIは54.4、3カ月ぶり高水準",
            "6月3日公表の民間PMIで、中国サービス業は54.4に上昇。新規事業と外需の回復が支えた一方、コスト圧力は残った。",
            "6月3日に公表された中国のCaixinサービス業PMIは、5月に54.4となり、前月の52.6から上昇した。Reuters系の報道は、サービス活動が3カ月ぶりの速いペースで拡大し、新規事業と海外需要の回復が支えになった一方で、コスト圧力が企業に残ると伝えた。国家統計局の製造業PMIが50.0付近で足踏みするなか、民間サービスPMIの改善は、中国景気を製造業だけでなく内需・サービス側から見直す材料になる。アジア供給網を見るうえでは、財の生産よりもサービス需要と外需の回復が同時に出ている点を切り分けたい。",
            "2026-06-03",
            [
                "https://ng.investing.com/economic-calendar/chinese-caixin-services-pmi-596",
                "https://www.investing.com/news/economy-news/china-services-activity-grows-at-fastest-pace-in-three-months-private-pmi-shows-4723261",
                "https://www.stats.gov.cn/english/PressRelease/202606/t20260601_1963851.html",
            ],
            [
                "https://www.stats.gov.cn/english/PressRelease/202606/t20260601_1963851.html",
                "https://ng.investing.com/economic-calendar/chinese-caixin-services-pmi-596",
                "https://www.investing.com/news/economy-news/china-services-activity-grows-at-fastest-pace-in-three-months-private-pmi-shows-4723261",
                "https://www.rbi.org.in/",
                "https://www.nso.gov.vn/en/homepage/",
                "https://asia.nikkei.com/",
                "https://www.youtube.com/@Reuters",
            ],
        ),
        "北米経済": (
            "north_america",
            "北米経済",
            "macro",
            "ADP雇用",
            "us_prices_jobs_fed",
            "米5月ADP民間雇用は122千人増、雇用統計前の金利材料に",
            "6月3日のADP報告で5月民間雇用は市場予想を上回って増加。週末の米雇用統計とFed見通しを読む前哨戦になった。",
            "6月3日に公表されたADPの5月民間雇用は122千人増となり、Reuters系の報道は市場予想を上回ったと伝えた。ただし、同じ報道では、ADPが金曜日の米雇用統計そのものを予測するものではなく、他の労働市場指標は安定化を示すとの注意も併記している。今週はADP、ISMサービス、失業保険、雇用統計が連続するため、単月の強い数字だけで金利観測を固めるより、賃金、求人、サービス業の雇用項目との整合性が焦点になる。",
            "2026-06-03",
            [
                "https://www.investing.com/news/economy-news/us-private-payrolls-increase-in-may-adp-says-4724242",
                "https://adpemploymentreport.com/",
                "https://www.bls.gov/schedule/news_release/empsit.htm",
            ],
            [
                "https://adpemploymentreport.com/",
                "https://www.investing.com/news/economy-news/us-private-payrolls-increase-in-may-adp-says-4724242",
                "https://www.reuters.com/markets/us/",
                "https://www.federalreserve.gov/newsevents.htm",
                "https://www.bls.gov/schedule/news_release/empsit.htm",
                "https://www.cnbc.com/economy/",
                "https://www.youtube.com/@CNBCtelevision",
            ],
        ),
    }
)

base.CLAIM_VERIFICATION.update(
    {
        "OpenAI": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "official_release", "claim": "OpenAIが6月2日にCodexのロール別プラグイン、Sites、注釈を発表した。", "source_url": "https://openai.com/index/codex-for-every-role-tool-workflow/"},
            {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_release", "claim": "Codexの週次利用者500万人超、非開発者約20%という利用状況が公式発表に示された。", "source_url": "https://openai.com/index/codex-for-every-role-tool-workflow/"},
            {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_release", "claim": "Sitesはワークスペース内でURL共有できるプレビュー機能として説明された。", "source_url": "https://openai.com/index/codex-for-every-role-tool-workflow/"},
        ],
        "F1": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "official_release", "claim": "Formula 1公式が6月3日にAston MartinのモナコGP向けMaaden特別リバリーのギャラリーを公開した。", "source_url": "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA"},
            {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_calendar", "claim": "2026年モナコGPは6月5日から7日の開催予定で、6月4日時点では開催前である。", "source_url": "https://www.formula1.com/en/latest/article/formula-1-louis-vuitton-grand-prix-de-monaco-2026.5eqj7xSRWW6dylGmncfs6T"},
        ],
        "SpaceX": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "major_media_confirmation", "claim": "RocketLaunch.Liveが6月4日のStarlink 17-44 Falcon 9ミッションを掲載した。", "source_url": "https://www.rocketlaunch.live/launch/starlink-17-44"},
            {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "major_media_confirmation", "claim": "RocketLaunch.Liveが6月4日14:00 UTCのStarlink 17-44 Falcon 9ミッションを掲載している。", "source_url": "https://www.rocketlaunch.live/launch/starlink-17-44"},
            {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_release", "claim": "SpaceX公式Launchesは6月のStarlinkミッション枠を継続して示している。", "source_url": "https://www.spacex.com/launches/"},
            {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_release", "claim": "Starshipは公式ページでFalcon 9の商用運用とは別の開発系統として確認できる。", "source_url": "https://www.spacex.com/vehicles/starship/"},
        ],
        "日本経済": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "major_media_confirmation", "claim": "6月3日に日本の5月サービス業PMIが報じられ、サービス活動の停滞が示された。", "source_url": "https://www.investing.com/news/economic-indicators/japans-services-activity-stagnates-in-may-as-costs-surge-pmi-shows-4723210"},
            {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "major_media_confirmation", "claim": "日本の5月サービス業PMIは50.0で、4月の51.0から低下した。", "source_url": "https://www.investing.com/news/economic-indicators/japans-services-activity-stagnates-in-may-as-costs-surge-pmi-shows-4723210"},
            {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "major_media_confirmation", "claim": "同報道は13カ月続いたサービス業の拡大が止まったと説明した。", "source_url": "https://www.investing.com/news/economic-indicators/japans-services-activity-stagnates-in-may-as-costs-surge-pmi-shows-4723210"},
        ],
        "アジア経済": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "major_media_confirmation", "claim": "6月3日に中国のCaixinサービス業PMIが公表され、サービス活動の改善が報じられた。", "source_url": "https://www.investing.com/news/economy-news/china-services-activity-grows-at-fastest-pace-in-three-months-private-pmi-shows-4723261"},
            {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "major_media_confirmation", "claim": "中国の5月Caixinサービス業PMIは54.4となり、前月52.6から上昇した。", "source_url": "https://ng.investing.com/economic-calendar/chinese-caixin-services-pmi-596"},
            {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "major_media_confirmation", "claim": "Reuters系報道は中国サービス活動が3カ月ぶりの速いペースで拡大したと伝えた。", "source_url": "https://www.investing.com/news/economy-news/china-services-activity-grows-at-fastest-pace-in-three-months-private-pmi-shows-4723261"},
        ],
        "北米経済": [
            {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "major_media_confirmation", "claim": "6月3日にADPの5月民間雇用報告が公表され、雇用統計前の材料として報じられた。", "source_url": "https://www.investing.com/news/economy-news/us-private-payrolls-increase-in-may-adp-says-4724242"},
            {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "major_media_confirmation", "claim": "ADPの5月民間雇用は122千人増となり、市場予想を上回った。", "source_url": "https://www.investing.com/news/economy-news/us-private-payrolls-increase-in-may-adp-says-4724242"},
            {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_calendar", "claim": "BLSの5月雇用統計はADP後に公表予定で、ADPは前哨材料として扱う。", "source_url": "https://www.bls.gov/schedule/news_release/empsit.htm"},
        ],
    }
)

base.SOURCE_LABELS.update(
    {
        "9to5mac": "9to5Mac",
        "investing.com": "Investing.com",
        "adpemploymentreport": "ADP",
        "bls.gov": "BLS",
    }
)


def slug(section: str) -> str:
    return f"{section}-signal-2026-06-04.html"


base.slug = slug


if __name__ == "__main__":
    base.main()
    log_path = ROOT / "details" / "extraction-log-2026-06-04.html"
    log_path.write_text(
        log_path.read_text(encoding="utf-8").replace("2026年6月3日版", "2026年6月4日版"),
        encoding="utf-8",
    )
