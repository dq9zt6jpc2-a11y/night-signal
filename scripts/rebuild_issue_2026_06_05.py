#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rebuild_issue_2026_06_03 as base


base.DATE = "2026-06-05"
base.CHECKED = "2026-06-05T21:40:00+09:00"
base.WINDOW_START = "2026-06-04T20:30:00+09:00"

base.MANUAL_UNPUBLISHED_CATEGORIES = {"SoftBank", "Honda", "YOASOBI / 幾田りら", "日本経済"}

base.DATA.update(
    {
        "OpenAI": (
            "openai",
            "OpenAI / AI",
            "signal",
            "政策 / 規制",
            "safety_security_regulation",
            "OpenAI、事前承認制に反対し連邦AI枠組みを提案",
            "6月3日の政策文書で、モデル事前承認制に反対しつつ、安全、レジリエンス、インフラを束ねる連邦枠組みを提示した。",
            "OpenAIは6月3日に公開したPublic Policy Agendaで、州ごとの断片規制やモデルの事前承認義務よりも、連邦レベルでの一貫した安全基準、AIレジリエンス、インフラ・エネルギー整備を優先する方針を示した。同日、Sam Altmanは米議会訪問で、公開前に政府承認を義務づける案には反対しつつ、政府側の評価能力や標準づくりには協力する立場を示した。OpenAIの論点は、開発速度を止めないまま安全評価を制度化したいというもので、今後の米AI規制がライセンス制へ寄るのか、連邦標準と事後監督へ寄るのかを見る軸になる。",
            "2026-06-03",
            [
                "https://openai.com/index/public-policy-agenda/",
                "https://www.investing.com/news/economy-news/openais-altman-to-urge-us-lawmakers-not-to-require-ai-model-approvals-4724935",
                "https://www.mlex.com/mlex/articles/2485401/openai-says-democratic-governments-need-to-determine-ai-safeguards",
            ],
            [
                "https://openai.com/index/public-policy-agenda/",
                "https://openai.com/index/biodefense-in-the-intelligence-age/",
                "https://www.investing.com/news/economy-news/openais-altman-to-urge-us-lawmakers-not-to-require-ai-model-approvals-4724935",
                "https://www.mlex.com/mlex/articles/2485401/openai-says-democratic-governments-need-to-determine-ai-safeguards",
                "https://x.com/OpenAI",
                "https://www.youtube.com/@OpenAI",
                "https://help.openai.com/en/articles/6825453-network-recommendations-for-chatgpt-errors",
            ],
        ),
        "F1": (
            "f1",
            "F1 / Honda F1",
            "signal",
            "Monaco / Aston Martin",
            "honda_aston_pu",
            "Aston Martin、モナコ向け変色リバリーの技術背景を公開",
            "6月3日のAston Martin公式で、Maaden共同の色調変化リバリーの狙いと素材表現を説明。Hondaワークス初年度の週末に露出材料が一段増えた。",
            "Aston Martinは6月3日、モナコGPで使うMaaden特別リバリーの制作背景を公式に公開した。鉱物資源から高性能工学への変換を表現する企画で、AMR26には見る角度で色味が変わる特殊ラップ素材を使ったと説明している。Formula 1公式ギャラリーでも同じ週末の特別リバリーが確認でき、Hondaワークス初年度のAston Martinは、競争力や信頼性の課題だけでなく、スポンサー露出とブランド演出でも注目を集める構図になった。モナコは低速市街地で競技面以上に露出が大きく、週末前の評価軸として無視しにくい。",
            "2026-06-03",
            [
                "https://www.astonmartinf1.com/en-GB/news/feature/from-rock-to-racetrack-the-story-of-maadens-monaco-grand-prix-livery",
                "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA",
                "https://www.motorsport.com/f1/news/Aston-Martin-reveals-Monaco-GP-livery/10826403/",
            ],
            [
                "https://www.astonmartinf1.com/en-GB/news/feature/from-rock-to-racetrack-the-story-of-maadens-monaco-grand-prix-livery",
                "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA",
                "https://www.motorsport.com/f1/news/Aston-Martin-reveals-Monaco-GP-livery/10826403/",
                "https://www.formula1.com/en/latest/article/formula-1-louis-vuitton-grand-prix-de-monaco-2026.5eqj7xSRWW6dylGmncfs6T",
                "https://x.com/F1",
                "https://www.youtube.com/@Formula1",
                "https://www.astonmartinf1.com/en-GB/news/feature",
            ],
        ),
        "SpaceX": (
            "spacex",
            "SpaceX / 宇宙",
            "hot",
            "IPO / Starlink",
            "business_contracts",
            "SpaceX、IPO価格を135ドルに設定 Starlink基盤で750億ドル調達へ",
            "6月3日にIPO価格を135ドルと公表し、調達額は750億ドル規模。評価の中心にはStarlink加入者1,000万人超の収益基盤がある。",
            "Reutersによる6月3日の報道では、SpaceXはIPO価格を1株135ドルに設定し、5億5,560万株の売り出しで約750億ドルを調達、企業価値は約1.75兆ドルを目指す。別のReuters系報道では、OppenheimerがStarlink加入者が1,000万人を超え、同事業が米通信市場を揺さぶる可能性を強調しており、評価の中心が打ち上げ技術だけでなく通信収益に移っていることが分かる。公式のLaunchesページでも6月のStarlink打ち上げ枠が続いており、足元の反復運用が大型資金調達の裏付けとして読まれている。",
            "2026-06-03",
            [
                "https://www.marketscreener.com/news/spacex-sets-135-price-for-blockbuster-ipo-upending-wall-street-convention-ce7f5ddcd98af720",
                "https://www.investing.com/news/stock-market-news/spacex-will-disrupt-16-trillion-us-communications-industry-oppenheimer-says-4724658",
                "https://www.spacex.com/launches/mission/?gsid=35abb496-27f8-43ea-b793-07ffc2063150&missionId=polarisdawn",
            ],
            [
                "https://www.spacex.com/launches/mission/?gsid=35abb496-27f8-43ea-b793-07ffc2063150&missionId=polarisdawn",
                "https://www.spacex.com/mission/starlink/",
                "https://www.marketscreener.com/news/spacex-sets-135-price-for-blockbuster-ipo-upending-wall-street-convention-ce7f5ddcd98af720",
                "https://www.investing.com/news/stock-market-news/spacex-will-disrupt-16-trillion-us-communications-industry-oppenheimer-says-4724658",
                "https://x.com/SpaceX",
                "https://www.youtube.com/@SpaceX",
                "https://www.spacex.com/",
            ],
        ),
        "北米経済": (
            "north_america",
            "北米経済",
            "macro",
            "生産性 / コスト",
            "us_prices_jobs_fed",
            "米Q1労働生産性は0.3%増、単位労働コスト1.8%増に下方改定",
            "6月4日のBLS改定で、生産性は小幅増にとどまりつつ、賃金コスト圧力は初報より和らいだ。雇用統計直前のFed見通しに効く。",
            "米労働省は6月4日、2026年第1四半期の非農業部門労働生産性を前期比年率0.3%増、単位労働コストを1.8%増へ改定した。初報よりコストの伸びが抑えられた一方で、生産性の伸びも鈍く、インフレ圧力が完全に消えたわけではない。Reuters系の報道は、基調としてはAI導入などが今後の押し上げ要因になり得るとしつつ、まずは6月5日の雇用統計で賃金と雇用者数がどう整合するかが焦点だと整理している。Fedにとっては、景気失速なしで賃金圧力が和らぐ『理想形』に近づくかを測る前哨データになる。",
            "2026-06-04",
            [
                "https://www.bls.gov/news.release/archives/prod2_06042026.htm",
                "https://www.marketscreener.com/news/us-first-quarter-worker-productivity-labor-costs-revised-lower-ce7f5ddcd18af72d",
                "https://www.bls.gov/schedule/2026/home.htm",
            ],
            [
                "https://www.bls.gov/news.release/archives/prod2_06042026.htm",
                "https://www.bls.gov/productivity/home.htm",
                "https://www.marketscreener.com/news/us-first-quarter-worker-productivity-labor-costs-revised-lower-ce7f5ddcd18af72d",
                "https://www.bls.gov/schedule/2026/home.htm",
                "https://www.federalreserve.gov/newsevents.htm",
                "https://www.youtube.com/@CNBCtelevision",
                "https://www.cnbc.com/economy/",
            ],
        ),
        "アジア経済": (
            "asia",
            "アジア経済",
            "macro",
            "インド / 鉄鋼需要",
            "india_vietnam_markets_supply_chain",
            "インド鉄鋼需要、5月は14.33百万トンで9.0%増 内需主導が継続",
            "6月4日の印政府データで、粗鋼生産14.21百万トン、仕上げ鋼需要14.33百万トン。インフラと建設需要が引き続き下支えした。",
            "インド政府は6月4日、5月の粗鋼生産が1,421万トンで前年比2.9%増、仕上げ鋼消費が1,433万トンで同9.0%増になったと発表した。4-5月累計でも仕上げ鋼生産は6.4%増、消費は5.2%増で、インフラ、建設、製造の内需が引き続き強い。Business StandardやSteelOrbisの補足では、供給増だけでなく輸入増圧力も残っており、インドが需要大国である一方で原料・製品フローの調整局面にあることが分かる。アジアの設備投資と素材需要を追う上では、自動車・建設・電力投資の温度感を見る早い指標になる。",
            "2026-06-04",
            [
                "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2268816&lang=1&reg=1",
                "https://www.business-standard.com/markets/capital-market-news/india-s-crude-steel-production-up-around-3-in-may-2026-126060400643_1.html",
                "https://www.steelorbis.com/steel-news/latest-news/india-sees-3-rise-in-crude-steel-output-in-may-2026-imports-up-63-1456862.htm",
            ],
            [
                "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2268816&lang=1&reg=1",
                "https://www.mospi.gov.in/uploads/latestReleases/Press%20Note_Release%20Calendar%20Change.pdf",
                "https://www.business-standard.com/markets/capital-market-news/india-s-crude-steel-production-up-around-3-in-may-2026-126060400643_1.html",
                "https://www.steelorbis.com/steel-news/latest-news/india-sees-3-rise-in-crude-steel-output-in-may-2026-imports-up-63-1456862.htm",
                "https://www.youtube.com/@Reuters",
                "https://asia.nikkei.com/",
                "https://www.pib.gov.in/",
            ],
        ),
        "宇都宮ブレックス": (
            "brex",
            "宇都宮ブレックス",
            "hot",
            "HC人事",
            "club_roster_staff",
            "宇都宮ブレックス、デ・ラファエレ氏を新HCに招聘",
            "6月5日に新ヘッドコーチ就任を公表。欧州トップリーグ実績を持つイタリア人指揮官の採用で、来季の編成と戦術刷新の軸が具体化した。",
            "宇都宮ブレックスは6月5日、2026-27シーズンのヘッドコーチにウォルター・デ・ラファエレ氏が就任すると公表した。B.LEAGUE側の紹介では、イタリアで長く上位クラブを率いてきた57歳の指揮官で、ブレックス公式でも『ブレックスファミリーの一員になれることを光栄に思う』とのコメントが示された。ケビン・ブラスウェル体制後の正式なトップ人事が固まり、今後の補強、アシスタント体制、守備とハーフコート設計がこの人選を軸に動く見通しになった。オフの話題でも重要度が高い確定人事として扱う。",
            "2026-06-05",
            [
                "https://www.utsunomiyabrex.com/",
                "https://www.bleague.jp/media_news/detail/id%3D614023",
                "https://www.youtube.com/@UTSUNOMIYABREX",
            ],
            [
                "https://www.utsunomiyabrex.com/",
                "https://www.utsunomiyabrex.com/news/?contents_type=32%3D&pageID=106",
                "https://www.bleague.jp/media_news/detail/id%3D614023",
                "https://www.shimotsuke.co.jp/",
                "https://x.com/utsunomiyabrex",
                "https://www.youtube.com/@UTSUNOMIYABREX",
                "https://basketballking.jp/",
            ],
        ),
    }
)

base.CLAIM_VERIFICATION.update(
    {
        "OpenAI": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "official_release",
                "claim": "OpenAIが6月3日にPublic Policy Agendaを公開した。",
                "source_url": "https://openai.com/index/public-policy-agenda/",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "official_release",
                "claim": "同文書は安全、ユースセーフティ、AIレジリエンス、AIインフラとエネルギーを政策優先項目として示した。",
                "source_url": "https://openai.com/index/public-policy-agenda/",
            },
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "major_media_confirmation",
                "claim": "Sam Altmanが6月3日に、公開前のモデル承認義務へ反対する考えを米議員に伝える方針だとReutersが報じた。",
                "source_url": "https://www.investing.com/news/economy-news/openais-altman-to-urge-us-lawmakers-not-to-require-ai-model-approvals-4724935",
            },
        ],
        "F1": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "official_release",
                "claim": "Aston Martinが6月3日にMaadenとのモナコGP特別リバリーの制作背景を公開した。",
                "source_url": "https://www.astonmartinf1.com/en-GB/news/feature/from-rock-to-racetrack-the-story-of-maadens-monaco-grand-prix-livery",
            },
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "official_release",
                "claim": "Formula 1公式が同じ特別リバリーのギャラリーを掲載した。",
                "source_url": "https://www.formula1.com/en/latest/article/gallery-aston-martin-reveal-special-livery-for-the-monaco-grand-prix.5cFPFnHMs4SfUK0B0QO4VA",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "major_media_confirmation",
                "claim": "Motorsport.comは今回のモナコ特別リバリーを、苦戦するAston Martinの週末でブランド露出を高める施策として位置づけた。",
                "source_url": "https://www.motorsport.com/f1/news/Aston-Martin-reveals-Monaco-GP-livery/10826403/",
            },
        ],
        "SpaceX": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "major_media_confirmation",
                "claim": "SpaceXが6月3日にIPO価格を1株135ドルへ設定したとReutersが報じた。",
                "source_url": "https://www.marketscreener.com/news/spacex-sets-135-price-for-blockbuster-ipo-upending-wall-street-convention-ce7f5ddcd98af720",
            },
            {
                "claim_type": "numeric",
                "source_state": "published_value",
                "evidence_kind": "major_media_confirmation",
                "claim": "売り出し規模は5億5,560万株、調達額は約750億ドル、評価額は約1.75兆ドルとされた。",
                "source_url": "https://www.marketscreener.com/news/spacex-sets-135-price-for-blockbuster-ipo-upending-wall-street-convention-ce7f5ddcd98af720",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "major_media_confirmation",
                "claim": "Reuters系報道はStarlink加入者が1,000万人超で、SpaceX評価の中心にあると伝えた。",
                "source_url": "https://www.investing.com/news/stock-market-news/spacex-will-disrupt-16-trillion-us-communications-industry-oppenheimer-says-4724658",
            },
            {
                "claim_type": "schedule",
                "source_state": "scheduled",
                "evidence_kind": "major_media_confirmation",
                "claim": "同報道ではNasdaqでの取引開始が6月12日見込みとされた。",
                "source_url": "https://www.marketscreener.com/news/spacex-sets-135-price-for-blockbuster-ipo-upending-wall-street-convention-ce7f5ddcd98af720",
            },
        ],
        "北米経済": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "official_release",
                "claim": "BLSが6月4日に第1四半期のProductivity and Costs改定値を公表した。",
                "source_url": "https://www.bls.gov/news.release/archives/prod2_06042026.htm",
            },
            {
                "claim_type": "numeric",
                "source_state": "published_value",
                "evidence_kind": "official_release",
                "claim": "非農業部門労働生産性は0.3%増、単位労働コストは1.8%増だった。",
                "source_url": "https://www.bls.gov/news.release/archives/prod2_06042026.htm",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "major_media_confirmation",
                "claim": "Reuters系報道は、基調としてAI導入が生産性押し上げ要因になり得る一方、目先は雇用統計との整合が焦点だと整理した。",
                "source_url": "https://www.marketscreener.com/news/us-first-quarter-worker-productivity-labor-costs-revised-lower-ce7f5ddcd18af72d",
            },
            {
                "claim_type": "schedule",
                "source_state": "scheduled",
                "evidence_kind": "official_calendar",
                "claim": "BLSは5月雇用統計を2026年6月5日に公表予定としている。",
                "source_url": "https://www.bls.gov/schedule/2026/home.htm",
            },
        ],
        "アジア経済": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "official_release",
                "claim": "インド政府が6月4日に5月の鉄鋼生産・消費の増加を公表した。",
                "source_url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2268816&lang=1&reg=1",
            },
            {
                "claim_type": "numeric",
                "source_state": "published_value",
                "evidence_kind": "official_release",
                "claim": "5月の粗鋼生産は1,421万トン、仕上げ鋼消費は1,433万トンで、それぞれ前年比2.9%増、9.0%増だった。",
                "source_url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2268816&lang=1&reg=1",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "official_release",
                "claim": "PIBはインド鉄鋼産業が国家鉄鋼政策の2030年300MTPA目標に向けて進んでいると説明した。",
                "source_url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2268816&lang=1&reg=1",
            },
        ],
        "宇都宮ブレックス": [
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "direct_source",
                "claim": "宇都宮ブレックスが6月5日にウォルター・デ・ラファエレ氏のヘッドコーチ就任を告知した。",
                "source_url": "https://www.utsunomiyabrex.com/",
            },
            {
                "claim_type": "announcement",
                "source_state": "confirmed_update",
                "evidence_kind": "major_media_confirmation",
                "claim": "B.LEAGUE公式が2026-27シーズンの宇都宮ブレックス新HC就任決定を報じた。",
                "source_url": "https://www.bleague.jp/media_news/detail/id%3D614023",
            },
            {
                "claim_type": "status",
                "source_state": "confirmed_status",
                "evidence_kind": "direct_source",
                "claim": "クラブの公式YouTubeは会見や関連動画の一次導線として継続確認できる。",
                "source_url": "https://www.youtube.com/@UTSUNOMIYABREX",
            },
        ],
    }
)

base.SOURCE_LABELS.update(
    {
        "investing.com": "Investing.com",
        "bls.gov": "BLS",
        "mlex.com": "MLex",
        "marketscreener.com": "MarketScreener",
        "business-standard.com": "Business Standard",
        "steelorbis.com": "SteelOrbis",
        "pib.gov.in": "PIB India",
        "mospi.gov.in": "MoSPI",
    }
)


def slug(section: str) -> str:
    return f"{section}-signal-2026-06-05.html"


base.slug = slug


if __name__ == "__main__":
    base.main()
    log_path = ROOT / "details" / "extraction-log-2026-06-05.html"
    log_path.write_text(
        log_path.read_text(encoding="utf-8").replace("2026年6月3日版", "2026年6月5日版"),
        encoding="utf-8",
    )
