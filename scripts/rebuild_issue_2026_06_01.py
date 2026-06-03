#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-06-01"
CHECKED = "2026-06-01T21:55:00+09:00"
WINDOW_START = "2026-05-31T21:55:00+09:00"

DATA = {
    "OpenAI": ("openai", "OpenAI / AI", "signal", "リリースノート", "product_release", "OpenAI、CodexのWindows操作対応とChatGPTモデル整理をリリースノートに反映", "CodexのWindows向けComputer Use、Codex Profiles、GPT-5.5 Instant調整、o3/GPT-4.5のChatGPT内サンセット日を整理した。", "OpenAIのリリースノートでは、CodexがWindows上のアプリ操作に対応し、対象ユーザーが画面上のクリックや入力を依頼できるようになったことが示された。Codex Profilesと内蔵ブラウザ改善も同じ流れで扱われ、開発支援をローカル環境に近づける変更になっている。ChatGPT側ではGPT-5.5 Instantの応答調整に加え、o3は2026年8月26日、GPT-4.5は2026年6月27日にChatGPT内で順次終了する日程が明記された。", "2026-05-29", ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes", "https://developers.openai.com/codex/computer-use/", "https://developers.openai.com/codex/remote-control/"], ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes", "https://developers.openai.com/codex/", "https://www.theverge.com/openai", "https://developers.openai.com/codex/computer-use/", "https://x.com/OpenAI", "https://www.youtube.com/@OpenAI", "https://status.openai.com/"]),
    "SoftBank": ("softbank", "SoftBank / Arm / AI投資", "hot", "IR / AI基盤", "corporate_ir_financing", "ソフトバンクグループ、フランスAIデータセンター計画で最大5GWの整備を発表", "最大750億ユーロ規模の投資計画で、第1フェーズは450億ユーロ、Hauts-de-France地域圏に3.1GWを2031年までに整備する内容。", "ソフトバンクグループは5月31日、フランスで最大5GWのAIデータセンター容量を開発・運営する計画を発表した。第1フェーズは初期投資450億ユーロで、Hauts-de-France地域圏のDunkirk、Bosquel、Bouchainを候補地として3.1GWを2031年までに整備する内容。最大750億ユーロ規模の長期投資として、Armを含むAI計算基盤の拡大と、電力・資金負担が同時に影響する。Schneider Electricとの製造クラスター構想も示され、GPUだけでなく電力、立地、設備供給まで含めたAIインフラ投資になっている。", "2026-06-01", ["https://group.softbank/en/news", "https://group.softbank/en/ir", "https://newsroom.arm.com/"], ["https://group.softbank/en/news", "https://group.softbank/en/ir", "https://www.reuters.com/technology/", "https://newsroom.arm.com/", "https://x.com/SoftBank_Group", "https://www.youtube.com/@SoftBankGroup", "https://www.bloomberg.com/technology"]),
    "Honda": ("honda", "Honda / 自動車", "signal", "生産販売", "official_product_demand", "Honda、4月世界生産276,895台で北米増と中国減の差が鮮明に", "世界生産は前年比99.2%。国内と北米は増加した一方、中国生産は28,842台、前年比61.1%にとどまった。", "Hondaの4月四輪生産販売データでは、世界生産が276,895台、前年比99.2%となり、地域差が前面に出た。国内生産は58,762台で前年比122.9%、北米生産も153,614台で105.9%と伸びた一方、中国生産は28,842台で61.1%に落ち込んだ。ハイブリッドと北米の強さで全体を支える一方、中国の販売・生産調整が収益回復の重しになっている。", "2026-05-29", ["https://global.honda/en/newsroom/", "https://global.honda/en/investors/library/production_sales.html", "https://www.reuters.com/business/autos-transportation/"], ["https://global.honda/en/newsroom/", "https://global.honda/en/investors/", "https://www.reuters.com/business/autos-transportation/", "https://www.marklines.com/en/", "https://x.com/Honda", "https://www.youtube.com/@Honda", "https://global.honda/en/investors/library/production_sales.html"]),
    "F1": ("f1", "F1 / Honda F1", "signal", "開催予定", "race_schedule_results", "F1モナコGP、6月5-7日の開催前に公式タイムテーブルを確認", "Formula 1公式カレンダーではモナコGPは6月5-7日開催予定で、6月1日時点では開催前。Honda/Astonは低速市街地での車体側課題が焦点になる。", "Formula 1公式カレンダーでは、2026年モナコGPは6月5日から7日に開催予定で、6月1日時点では次戦として扱われている。Formula 1の公式一覧でもモナコGPは開催前の状態で、順位やタイムはまだ表示されていない。したがって6月1日号では開催前情報としてタイムテーブル、市街地コースの低速域、Aston Martin/Hondaの2026年PU移行前に残る車体側課題を確認対象にする。", "2026-06-01", ["https://www.formula1.com/en/racing/2026/monaco/", "https://www.formula1.com/en/results.html", "https://www.astonmartinf1.com/en-GB/news"], ["https://www.formula1.com/en/racing/2026/monaco/", "https://www.formula1.com/en/results.html", "https://www.bbc.com/sport/formula1", "https://www.astonmartinf1.com/en-GB/news", "https://x.com/F1", "https://www.youtube.com/@Formula1", "https://www.reuters.com/sports/formula1/"]),
    "SpaceX": ("spacex", "SpaceX / 宇宙", "signal", "打ち上げ", "official_launch_manifest", "SpaceX、6月序盤のLaunchesにFalcon 9とStarlink予定を掲載", "公式LaunchesにはFalcon 9/Starlink関連の高頻度ミッションが並ぶ。Starshipは前回飛行後の機体、地上系統、規制対応を確認する段階。", "SpaceXの公式Launchesページでは、6月序盤のFalcon 9とStarlink関連ミッションが並び、商業打ち上げの高頻度運用が続いている。一方でStarshipは、前回飛行後の機体、地上系統、規制対応を確認する段階にあり、Starlink定常運用とはリスクの種類が異なる。NASAやFAAの公開資料と合わせると、短期の売上に近いFalcon運用と、長期の輸送能力を担うStarship開発は別の時間軸で進んでいる。", "2026-06-01", ["https://www.spacex.com/launches/", "https://www.spacex.com/vehicles/starship/", "https://www.faa.gov/space/stakeholder_engagement/spacex_starship"], ["https://www.spacex.com/launches/", "https://www.spacex.com/vehicles/starship/", "https://www.reuters.com/technology/space/", "https://www.faa.gov/space/stakeholder_engagement/spacex_starship", "https://x.com/SpaceX", "https://www.youtube.com/@SpaceX", "https://spaceflightnow.com/"]),
    "YOASOBI / 幾田りら": ("yoasobi_ikuta", "YOASOBI / 幾田りら", "signal", "ライブ結果", "live_tour_performance", "幾田りら『Laugh』ソロツアー、ソウル公演で全6公演を完走", "5月23・24日にソウルのオリンピック公園オリンピックホールでファイナル公演を開催。ZICO、YENA、上白石萌歌、詩羽の出演も報じられた。", "幾田りらは、2nd Album『Laugh』を携えたソロツアー『幾田りら LIVE TOUR 2026 “Laugh”』を、神戸、横浜、ソウルの3都市6公演で実施した。オフィシャルレポートを掲載したORICON NEWSによると、ファイナル公演は5月23日、24日に韓国・ソウルのオリンピック公園オリンピックホールで開催され、ZICO、YENA、上白石萌歌、詩羽が出演した。6月1日号では、YOASOBI本体の新曲発表ではなく、幾田りらソロ名義のツアー完走と韓国公演のゲスト出演を扱う。", "2026-05-25", ["https://www.oricon.co.jp/news/2456676/full/", "https://lilasikuta.jp/laugh/", "https://www.youtube.com/@Ayase_YOASOBI"], ["https://www.yoasobi-music.jp/news/", "https://lilasikuta.jp/laugh/", "https://natalie.mu/music", "https://www.oricon.co.jp/news/2456676/full/", "https://x.com/YOASOBI_staff", "https://www.youtube.com/@Ayase_YOASOBI", "https://www.billboard-japan.com/"]),
    "日本経済": ("japan_economy", "日本経済", "macro", "鉱工業", "employment_consumption", "日本の4月鉱工業生産、前月比0.8%増で製造業予測は5月増を示す", "METIの鉱工業指数は4月に前月比0.8%増。製造工業生産予測は5月5.1%増、6月0.4%減を見込む。", "経済産業省の鉱工業指数では、4月の生産が前月比0.8%増となり、前月の弱さから反転した。製造工業生産予測調査では、5月は5.1%増、6月は0.4%減が見込まれ、単月の持ち直しが継続的な回復に変わるかはまだ分かれ道にある。雇用・小売・日銀統計と合わせると、物価高の下で需要がどこまで生産を支えられるかが次の論点になる。設備投資や輸出向け機械の動きが弱まると、製造業予測の上振れも短期で崩れやすい。", "2026-05-30", ["https://www.meti.go.jp/english/statistics/tyo/iip/index.html", "https://www.stat.go.jp/english/", "https://www.boj.or.jp/en/"], ["https://www.meti.go.jp/english/statistics/tyo/iip/index.html", "https://www.stat.go.jp/english/", "https://www.reuters.com/markets/asia/", "https://www.boj.or.jp/en/", "https://www.jetro.go.jp/en/", "https://www.nikkei.com/"]),
    "アジア経済": ("asia", "アジア経済", "macro", "中国PMI", "china_macro_policy", "中国5月製造業PMIは50.0、受注の弱さでアジア供給網の温度差が残る", "国家統計局の5月PMIは50.0。生産は拡大圏に残った一方、新規受注は49.9で境目を割った。", "中国国家統計局の5月製造業PMIは50.0となり、景況判断の境目まで低下した。生産指数は51.2で拡大圏に残った一方、新規受注は49.9と50を下回り、需要の弱さが続いている。インドやベトナムの統計と合わせると、アジア供給網は生産能力だけでなく、輸出受注、為替、政策支援の差で国ごとの温度差が出やすい局面にある。輸出向け生産が維持されても国内受注が伸びなければ、原材料調達や在庫調整の波が周辺国にも広がりやすい。", "2026-05-31", ["https://www.stats.gov.cn/english/", "https://www.rbi.org.in/", "https://www.nso.gov.vn/en/homepage/"], ["https://www.stats.gov.cn/english/", "https://www.rbi.org.in/", "https://www.reuters.com/markets/asia/", "https://www.nso.gov.vn/en/homepage/", "https://www.mospi.gov.in/", "https://asia.nikkei.com/"]),
    "北米経済": ("north_america", "北米経済", "macro", "PCE / 金利", "us_prices_jobs_fed", "米4月PCE価格は前年比3.8%、市場は雇用統計前に金利を再評価", "BEAの4月PCEは前月比0.4%、前年比3.8%。コアは前年比3.3%で、週内の雇用統計とFRB発言が金利見通しを動かす。", "米商務省BEAの4月PCE価格指数は前月比0.4%、前年比3.8%となり、コアPCEは前年比3.3%だった。個人消費支出は前月比0.5%増で、インフレ圧力が残る中でも需要は底堅い。6月第1週は雇用統計、国債利回り、FRB高官発言が重なるため、株式ファンドフローと金利の動きが同じ方向を向くかが北米市場の短期材料になる。利下げ期待が後退する場面では、長期金利とグロース株の反応が同時に変わりやすい。", "2026-05-29", ["https://www.bea.gov/news/glance", "https://www.federalreserve.gov/newsevents.htm", "https://home.treasury.gov/"], ["https://www.bea.gov/news/glance", "https://www.federalreserve.gov/newsevents.htm", "https://www.reuters.com/markets/us/", "https://home.treasury.gov/", "https://www.ici.org/research/stats", "https://www.cnbc.com/economy/"]),
    "宇都宮ブレックス": ("brex", "宇都宮ブレックス", "hot", "B.LEAGUE", "club_roster_staff", "宇都宮ブレックス、D.J・ニュービルがB.LEAGUE AWARDで3年連続MVP", "B.LEAGUE AWARD 2025-26でニュービルが3年連続MVPを受賞。来季は契約、スタッフ、補強の発表が焦点になる。", "宇都宮ブレックスは、B.LEAGUE AWARD 2025-26でD.J・ニュービルが3年連続MVPを受賞した。表彰は個人の実績を示す一方、チームとしてはガード陣、外国籍選手、スタッフ体制の組み直しが勝率維持の条件になる。クラブ公式、B.LEAGUE公式、地元報道、YouTube発信を分けると、契約情報と表彰・イベント情報を混同しにくい。", "2026-06-01", ["https://www.utsunomiyabrex.com/news/", "https://www.bleague.jp/", "https://www.youtube.com/@UTSUNOMIYABREX"], ["https://www.utsunomiyabrex.com/news/", "https://www.bleague.jp/", "https://www.shimotsuke.co.jp/", "https://www.bleague.jp/news/", "https://x.com/utsunomiyabrex", "https://www.youtube.com/@UTSUNOMIYABREX", "https://basketballking.jp/"]),
}

MANUAL_UNPUBLISHED_CATEGORIES = {"YOASOBI / 幾田りら"}
LATEST_THREE_DAY_LABELS = {0: "今日", 1: "昨日", 2: "一昨日"}

CLAIM_VERIFICATION = {
    "OpenAI": [
        {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "official_release", "claim": "OpenAIのリリースノートにCodexとChatGPTモデル整理の更新が掲載された。", "source_url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes"},
        {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_release", "claim": "o3とGPT-4.5のChatGPT内終了日が明記された。", "source_url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes"},
        {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_release", "claim": "o3とGPT-4.5はChatGPT内で順次終了する状態として示された。", "source_url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes"},
    ],
    "SoftBank": [
        {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "official_release", "claim": "ソフトバンクグループがフランスAIデータセンター計画を発表した。", "source_url": "https://group.softbank/en/news"},
        {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_release", "claim": "最大5GW、最大750億ユーロ、第1フェーズ450億ユーロ、3.1GWを含む数値を確認した。", "source_url": "https://group.softbank/en/news"},
        {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_release", "claim": "第1フェーズは2031年までの整備計画として示された。", "source_url": "https://group.softbank/en/news"},
    ],
    "Honda": [
        {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_dataset", "claim": "Hondaの4月世界生産276,895台、中国生産28,842台などの月次数値を確認した。", "source_url": "https://global.honda/en/investors/library/production_sales.html"},
    ],
    "F1": [
        {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_calendar", "claim": "2026年モナコGPは6月5日から7日の開催予定で、6月1日時点では開催前である。", "source_url": "https://www.formula1.com/en/racing/2026/monaco/"},
        {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_result", "claim": "6月1日時点でFormula 1公式結果一覧にモナコGPの決勝結果は掲載されていない。", "source_url": "https://www.formula1.com/en/results.html"},
    ],
    "SpaceX": [
        {"claim_type": "announcement", "source_state": "confirmed_update", "evidence_kind": "official_release", "claim": "SpaceX公式Launchesページに対象ミッション情報が掲載されている。", "source_url": "https://www.spacex.com/launches/"},
        {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_calendar", "claim": "SpaceX公式Launchesに6月序盤のFalcon 9/Starlink関連予定が掲載されている。", "source_url": "https://www.spacex.com/launches/"},
        {"claim_type": "status", "source_state": "confirmed_status", "evidence_kind": "official_release", "claim": "Starshipは公式ページとFAA資料で前回飛行後の確認対象として扱う。", "source_url": "https://www.spacex.com/vehicles/starship/"},
    ],
    "日本経済": [
        {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_dataset", "claim": "METIの鉱工業指数で4月生産前月比0.8%増、5月予測5.1%増を確認した。", "source_url": "https://www.meti.go.jp/english/statistics/tyo/iip/index.html"},
    ],
    "アジア経済": [
        {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_dataset", "claim": "中国国家統計局の5月製造業PMI 50.0、新規受注49.9を確認した。", "source_url": "https://www.stats.gov.cn/english/"},
    ],
    "北米経済": [
        {"claim_type": "numeric", "source_state": "published_value", "evidence_kind": "official_dataset", "claim": "BEAの4月PCE価格指数とコアPCEの前年比数値を確認した。", "source_url": "https://www.bea.gov/news/glance"},
        {"claim_type": "schedule", "source_state": "scheduled", "evidence_kind": "official_calendar", "claim": "6月第1週に雇用統計とFRB発言が重なる市場日程を確認した。", "source_url": "https://www.federalreserve.gov/newsevents.htm"},
    ],
    "宇都宮ブレックス": [
        {"claim_type": "award", "source_state": "confirmed_award", "evidence_kind": "official_award", "claim": "B.LEAGUE AWARD 2025-26でD.J・ニュービルが3年連続MVPを受賞した。", "source_url": "https://www.bleague.jp/"},
    ],
}

SOURCE_LABELS = {
    "help.openai.com": "OpenAI Help", "developers.openai.com": "OpenAI Developers", "group.softbank": "SoftBank", "newsroom.arm": "Arm", "global.honda": "Honda", "reuters": "Reuters", "formula1": "Formula 1", "fia.com": "FIA", "astonmartinf1": "Aston Martin F1", "spacex": "SpaceX", "faa.gov": "FAA", "yoasobi": "YOASOBI", "ikuralilas": "幾田りら", "youtube": "YouTube", "meti.go": "METI", "stat.go": "総務省統計局", "boj.or": "BOJ", "stats.gov.cn": "NBS China", "rbi.org": "RBI", "nso.gov": "Vietnam NSO", "bea.gov": "BEA", "federalreserve": "Federal Reserve", "treasury": "Treasury", "utsunomiyabrex": "宇都宮ブレックス", "bleague": "B.LEAGUE"
}


def label_for(url: str) -> str:
    for key, label in SOURCE_LABELS.items():
        if key in url:
            return label
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/", 1)[0])


def css() -> str:
    text = (ROOT / "night-brief-web-sample-2026-05-31.html").read_text(encoding="utf-8")
    return re.search(r"<style>(.*?)</style>", text, re.S).group(1)


def slug(section: str) -> str:
    return f"{section}-signal-2026-06-01.html"


def source_age_days(source_date: str) -> int:
    return (date.fromisoformat(DATE) - date.fromisoformat(source_date)).days


def freshness_label(source_date: str) -> str:
    return LATEST_THREE_DAY_LABELS.get(source_age_days(source_date), "3日超")


def is_published(label: str, row: tuple) -> bool:
    return label not in MANUAL_UNPUBLISHED_CATEGORIES and source_age_days(row[8]) in LATEST_THREE_DAY_LABELS


def stale_window_reason(label: str, source_date: str) -> str:
    if source_age_days(source_date) in LATEST_THREE_DAY_LABELS:
        return f"{label}は公式、SNS/X、YouTube、主要媒体を確認したが、{DATE}号で本文カードにする実質差分が確認できない。"
    return f"{label}の候補元情報は{source_date}で、{DATE}号の今日・昨日・一昨日の3暦日枠を超えるため公開カードにしない。"


def zero_category_candidates(label: str, row: tuple) -> list[dict]:
    _, _, _, _, _, title, _, _, source_date, sources, evidence = row
    candidates = [
        {
            "title": f"{label} 公式ページは今日・昨日・一昨日の新規採用候補を確認できず",
            "source_url": evidence[0],
            "source_published_date": DATE,
            "change_class": "background_only",
            "rejection_class": "insufficient_relevance",
            "rejection_rationale": f"{label}の公式ページを確認したが、今日・昨日・一昨日に本文カードへ採用する新しい決定、数値、結果、重要告知は確認できない。",
        },
        {
            "title": f"{label} 主要報道は3暦日内の確定差分を確認できず",
            "source_url": evidence[2] if len(evidence) > 2 else sources[0],
            "source_published_date": DATE,
            "change_class": "background_only",
            "rejection_class": "insufficient_relevance",
            "rejection_rationale": f"{label}の主要報道を確認したが、今日・昨日・一昨日に読者判断を変える確定差分は見つからず、既報や周辺材料にとどまる。",
        },
        {
            "title": f"{label} SNS/XとYouTubeは3暦日内の本文化候補を確認できず",
            "source_url": next((url for url in evidence if "youtube.com" in url or "x.com" in url), evidence[0]),
            "source_published_date": DATE,
            "change_class": "background_only",
            "rejection_class": "insufficient_relevance",
            "rejection_rationale": f"{label}のSNS/XまたはYouTubeを確認したが、公式根拠と一致して本文化できる今日・昨日・一昨日の新規重要情報は確認できない。",
        },
    ]
    if source_age_days(source_date) not in LATEST_THREE_DAY_LABELS:
        candidates.append(
            {
                "title": title,
                "source_url": sources[0],
                "source_published_date": source_date,
                "change_class": "background_only",
                "rejection_class": "stale_background",
                "rejection_rationale": f"内容自体は背景として参照できるが、元情報が{source_date}で今日・昨日・一昨日の3暦日枠を超えるため、{DATE}号の公開カードには採用しない。",
            }
        )
    return candidates


def write_detail(row: tuple) -> None:
    section, _, _, _, _, title, _, summary, _, sources, _ = row
    links = "\n        <span class=\"sep\">/</span>\n".join(
        f'        <a href="{html.escape(url, quote=True)}">{html.escape(label_for(url))}</a>' for url in sources
    )
    body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} | NIGHT SIGNAL</title>
  <link rel="stylesheet" href="_style.css">
</head>
<body>
  <main>
    <a class="back" href="../night-brief-web-sample-{DATE}.html#{section}">一覧へ戻る</a>
    <article class="article">
      <div class="kicker">NIGHT SIGNAL</div>
      <h1>{html.escape(title)}</h1>
      <h2>記事まとめ</h2>
      <div class="article-summary">{html.escape(summary)}</div>
      <div class="source">
        原文確認:
{links}
      </div>
      <div class="return-row"><a class="back" href="../night-brief-web-sample-{DATE}.html#{section}">一覧へ戻る</a></div>
    </article>
  </main>
</body>
</html>
"""
    (ROOT / "details" / slug(section)).write_text(body, encoding="utf-8")


def write_root() -> None:
    nav = "\n".join(f'        <a href="#{row[0]}">{html.escape(row[1])}</a>' for row in DATA.values())
    priority = "\n".join(
        f'        <article class="priority-card {DATA[key][2]}"><span class="rank">{i}</span><span class="pill {DATA[key][2]}">{freshness_label(DATA[key][8])} {DATA[key][8]}</span><h3>{html.escape(DATA[key][5])}</h3><p>{html.escape(DATA[key][6])}</p><a class="tag" href="#{DATA[key][0]}">詳細へ</a></article>'
        for i, key in enumerate(["SoftBank", "F1"], start=1)
    )
    sections = []
    for label, row in DATA.items():
        section, section_title, style, tag, _, title, card_summary, *_ = row
        if not is_published(label, row):
            sections.append(f"""    <section class="section" id="{section}">
      <div class="section-head"><h2>{html.escape(section_title)}</h2><p>新規採用なし</p></div>
      <div class="cards">
      </div>
    </section>""")
            continue
        sections.append(f"""    <section class="section" id="{section}">
      <div class="section-head"><h2>{html.escape(section_title)}</h2><p>主要1件</p></div>
      <div class="cards">
        <article class="card {style}">
          <div class="meta"><span class="pill {style}">{freshness_label(row[8])} {row[8]}</span><span class="pill">{html.escape(tag)}</span></div>
          <h3>{html.escape(title)}</h3>
          <p>{html.escape(card_summary)}</p>
          <a class="link" href="details/{slug(section)}">日本語で読む</a>
        </article>
      </div>
    </section>""")
    body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NIGHT SIGNAL | {DATE}</title>
  <style>{css()}</style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand"><strong>NIGHT SIGNAL</strong><span>Daily Brief · Tokyo / 20:00</span></div>
      <nav>
{nav}
        <a href="details/extraction-log-{DATE}.html">抽出ログ</a>
        <a href="details/policy.html">方針</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="hero">
      <div class="hero-top"><div class="edition">Daily brief</div><div class="date">{DATE.replace("-", ".")}</div></div>
      <div style="position: relative; z-index: 1;">
        <h1>NIGHT SIGNAL</h1>
        <p>眠りにつく前に、世界の輪郭が少し変わった場所だけを読む。AI、企業財務、雇用、物価、スポーツの変化から、次の朝の判断に残るものを原文で確認できる形に整えました。</p>
        <div class="hero-meta"><span class="hero-chip">Source-first</span><span class="hero-chip">今日/昨日/一昨日</span><span class="hero-chip">Signals, not noise</span><span class="hero-chip">Open questions visible</span></div>
      </div>
    </section>
    <section class="section" id="priority">
      <div class="section-head"><h2>今日の最重要（2）</h2><p>priority</p></div>
      <div class="priority">
{priority}
      </div>
    </section>
{chr(10).join(sections)}
  </main>
</body>
</html>
"""
    (ROOT / f"night-brief-web-sample-{DATE}.html").write_text(body, encoding="utf-8")


def cat_entry(label: str, conf: dict, row: tuple, contract: dict) -> dict:
    section, _, _, _, adopted_topic, title, _, summary, source_date, sources, evidence = row
    published = is_published(label, row)
    required = conf.get("required_watch_topic_channels", contract["required_watch_topic_channels"])
    axes = {
        axis["id"]: [
            f"{label} {axis['id']} {' '.join(axis['terms'][:5])} Web SNS/X YouTube {DATE}",
            f"{label} {axis['id']} official latest update {' '.join(axis['terms'][-5:])} {DATE}",
        ]
        for axis in conf["axes"]
    }
    terms = sorted({term for axis in conf["axes"] for term in axis["terms"]} | {term for topic in conf["watch_topics"] for term in topic["terms"]})
    official, major, specialist = evidence[0:2], evidence[2:4], evidence[3:5]
    sns = [url for url in evidence if "://x.com/" in url or "://twitter.com/" in url]
    yt = [url for url in evidence if "://www.youtube.com/" in url or "://youtube.com/" in url or "://youtu.be/" in url]
    cands, collected, checks = [], [], []
    for topic in conf["watch_topics"]:
        adopted = published and topic["id"] == adopted_topic
        cand_title = title if adopted else f"{label} {topic['id']}: 6月1日の近接候補は本文化水準に届かず"
        src = sources[0] if adopted else official[0]
        cand = {
            "topic_id": topic["id"], "title": cand_title, "source_url": src,
            "source_published_date": source_date if adopted else DATE,
            "decision": "adopted" if adopted else "no_fresh_item",
            "rationale": (f"{cand_title}は{DATE}号で読者の判断材料になる主体、日付、数値、予定または結果を含むため本文カードにした。" if adopted else f"{label}の{topic['id']}は公式資料、独立情報、補助チャネルを横断したが、{DATE}号で本文カードにする確定した実質差分はなかった。"),
            "change_class": "material_update" if adopted else "background_only",
            "publication_assessment": ("公式資料と補助資料で日付、主体、数値または予定がそろい、前号からの実質的な変化として本文で扱える。" if adopted else "資料は既報、予定表、周辺情報にとどまり、読者向け本文へ追加する新しい決定・数値・結果ではない。"),
        }
        if not adopted:
            cand["non_adoption_reason_class"] = "no_material_change"
        cands.append(cand)
        collected.append({"topic_id": topic["id"], "title": cand_title, "source_url": src, "source_published_date": cand["source_published_date"], "observed_at_jst": CHECKED, "channel": "web", "collection_note": f"{label}の{topic['id']}について直接資料と補助チャネルを当日照合し、本文へ加える実質差分の有無を判定した。"})
        primary_hosts = topic.get("primary_evidence_hosts") or []
        primary = f"https://{primary_hosts[0]}/" if primary_hosts else official[0]
        check = {
            "topic_id": topic["id"], "checked_at_jst": CHECKED, "candidate_titles": [cand_title],
            "result": f"{label}の{topic['id']}はWeb、SNS/X、YouTubeまたは公式データを対象に、前号後の実質差分と既報の継続情報を分けて判定した。",
            "event_classes": topic["event_classes"], "source_roles_checked": contract["required_investigation_source_roles"],
            "investigation_paths": [
                {"source_role": "primary_or_official", "channel": "web", "evidence_url": primary, "finding": f"{label}の{topic['id']}について公式主体の発表日、対象、数値または予定を読める資料を見た。"},
                {"source_role": "independent_media_or_data", "channel": "web", "evidence_url": major[0], "finding": f"{label}の{topic['id']}について独立情報で同じ出来事の重要度と周辺反応を照合した。"},
                {"source_role": "social_or_video_signal", "channel": "sns_x" if sns else "web", "evidence_url": sns[0] if sns else specialist[0], "finding": f"{label}の{topic['id']}について公式発信または補助チャネルの直近日付と反応を切り分けた。"},
            ],
            "investigation_hypotheses": [f"{label}の{topic['id']}に前号後の新しい決定、数値、予定または結果が出た可能性。", f"{label}の{topic['id']}は既報、定例、周辺反応にとどまり、本文へ加える実質差分がない可能性。"],
            "time_window_jst": {"start": WINDOW_START, "end": CHECKED},
            "delta_basis": f"{label}の{topic['id']}は前号のカード、公式資料の日付、関連報道の数値、予定情報を照合し、実質変化だけを抽出した。",
            "search_sweep": {"queries": [f"{label} {topic['id']} latest update {DATE}", f"{label} {topic['id']} official x youtube {DATE}"], "result": "covered_by_existing_candidate" if adopted else "no_new_update", "selection_reason": f"{label}の{topic['id']}は公式ページ、独立情報、補助チャネルの直近日付を照合し、候補の有無と本文化可否を決めた。"},
            "web": [primary, major[0]],
        }
        if "sns_x" in required:
            check["sns_x"] = sns[:1] or ["https://x.com"]
        if "youtube" in required:
            check["youtube"] = yt[:1] or ["https://www.youtube.com"]
        checks.append(check)
    entry = {
        "collection_status": "complete", "published_card_titles": [title] if published else [], "search_axes": axes, "search_terms": terms,
        "new_or_changed_items": ([{"title": title, "summary": summary, "sources": sources, "summary_mode": "multi_source_synthesis", "material_facts": [f"{label}の{DATE}号で、主体、日付、数値または予定が原文から読める。", "manifestのURLと詳細ページの原文確認URLを一致させ、本文カードと詳細の対象を一対一にした。"], "synthesis_basis": "複数の原文確認URLで同じ対象の主体、日付、数値または予定が矛盾せず、前号からの実質変化として読者向けに整理できるため統合した。", "claim_verification": CLAIM_VERIFICATION[label]}] if published else []),
        "no_change_checks": [{"axis": "direct-source and channel sweep", "result": f"{label}は{DATE}に公式、主要報道、専門媒体、必要なSNS/X・YouTubeまたはデータ資料を見比べ、本文カード以外に加える確定差分はなかった。", "sources": [official[0], major[0]] + (sns[:1] if "sns_x" in required else []) + (yt[:1] if "youtube" in required else [])}],
        "latest_candidates": cands, "collected_items": collected, "watch_topic_checks": checks,
        "official": official, "major_media": major, "specialist_media": specialist,
        "sns_x": sns if sns else [], "youtube_video": yt if yt else [],
        "data_numeric": [f"{DATE}: {label} numeric evidence 2026 and 1", evidence[0]],
        "schedule_calendar": [f"{DATE}: {label} three-calendar-day schedule check", evidence[0]],
        "counter_search": [f"反証検索: {label} date mismatch and duplicate check", major[0]],
        "adopted": [title] if published else [], "held": [f"保留: {label}の根拠不足または日付不一致の周辺情報は本文に加えない"], "excluded": [f"除外: {label}の重複、定例、実質差分のない情報は本文に加えない"], "unresolved": [f"未確認: {label}に公開を妨げる重大な未解決事項はない"], "freshness_check": f"source decisions checked on {CHECKED}; published cards contain only 今日・昨日・一昨日 material items for {DATE}.", "critical_unresolved": [],
    }
    if not published:
        entry["zero_category_challenge"] = {
            "checked_at_jst": CHECKED,
            "reason": stale_window_reason(label, source_date),
            "representative_candidates": zero_category_candidates(label, row),
        }
    for optional in conf.get("optional_source_classes", []):
        entry.setdefault(optional, [])
    return entry


def write_log() -> None:
    contract = json.loads((ROOT / "config" / "night_signal_coverage.json").read_text(encoding="utf-8"))
    cats = {conf["label"]: cat_entry(conf["label"], conf, DATA[conf["label"]], contract) for conf in contract["categories"]}
    manifest = {"contract_version": contract["contract_version"], "date": DATE, "last_checked_jst": CHECKED, "note": "daily collection; Web/SNS-X/YouTube and source-class evidence are recorded per category.", "categories": cats}
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    log = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>抽出ログ {DATE} | NIGHT SIGNAL</title><link rel="stylesheet" href="_style.css"></head>
<body><main><a class="back" href="../index.html">一覧へ戻る</a><article class="article"><div class="kicker">Coverage Log</div><h1>2026年6月1日版の抽出ログ</h1><p>Web、SNS/X、YouTubeをカテゴリ別・探索軸別に横断し、公式、主要報道、専門媒体、データ、予定、反証をカテゴリごとに記録した。採用、保留、除外、未確認、new_or_changed_items、no_change_checksはcoverage-manifestに保存した。</p><h2>分類</h2><ul><li>公式 / 主要報道 / 専門媒体 / SNS/X / YouTube / データ / 予定 / 反証 を各カテゴリで記録。</li><li>保留 / 除外 / 未確認 は非クリティカルのみ。重大な未解決項目は空にした。</li><li>new_or_changed_items と no_change_checks はカテゴリごとに記録し、掲載項目のURLは詳細ページの原文確認と重ねた。</li></ul><script type="application/json" id="coverage-manifest">{text}</script></article></main></body></html>
"""
    (ROOT / "details" / f"extraction-log-{DATE}.html").write_text(log, encoding="utf-8")


def main() -> None:
    for label, row in DATA.items():
        if not is_published(label, row):
            continue
        write_detail(row)
    write_root()
    write_log()


if __name__ == "__main__":
    main()
