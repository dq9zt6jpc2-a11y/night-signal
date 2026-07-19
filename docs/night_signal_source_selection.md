# NIGHT SIGNAL source selection

The source portfolio is intentionally separate from the daily seed registry.
Seed sources prove that official and required channels were checked. The
publisher portfolio qualifies articles found in search and supplies domains for
a bounded second-pass query only when a category lacks body-rich Evidence from
a trusted official, major, or specialist source. Google News and Bing are
discovery indexes, not source-quality substitutes.

## Specialist-first depth

General search remains the broad recall and counterexample layer. Information
depth comes from official releases and topic-matched specialist publishers.
Each specialist may declare `topic_ids_by_category`; the recovery pass searches
those open publishers before unrelated, mixed-access, or restricted publishers.
Official seed pages may declare `depth_topic_ids`. For each evidence-thin topic,
the recovery pass issues at most one single-domain official query and one
single-domain specialist query. Results must match that exact registered domain;
an index result from Wikipedia or another unrelated publisher cannot satisfy the
topic. If Bing is unavailable or returns no matching-domain result, that same
query is retried once through Google News RSS. The default budget is therefore
two deterministic searches per weak topic, with
`NIGHT_SIGNAL_DEPTH_RECOVERY_MAX_QUERIES` available as an operational cap.
Strong topics add no query, adding a publisher adds no unconditional fetch, and
the recovery pass adds no model request.

Coverage contracts may declare `required_discovery_roles`. Collection fails
fast when the configured portfolio loses a required domain such as telecom,
Japanese AI, China automotive, Formula One technical analysis, or local
basketball. This checks portfolio structure without imposing a card quota.

## Selection rules

Candidates are reviewed on editorial specialization, primary-source proximity,
complementarity, freshness, search discoverability, body retrieval stability,
noise, and editorial reliability. A famous outlet is not automatically fetched
for every category.

- `search_priority: 1` is used before priority 2 in category-specific depth
  recovery. It includes the broad wires/business publications and the strongest
  category specialist sources.
- `search_priority: 2` adds general newspapers and analysis publications after
  the higher-yield sources.
- `restricted` and `restricted_or_mixed` sources may identify a story, but a
  headline or abstract is not body evidence. Publication requires an accessible
  primary source or independently readable corroboration.
- The publisher list does not create a fixed card count and does not relax
  novelty, materiality, category identity, or evidence-depth validation.

This design keeps Reuters, Kyodo, NHK, Financial Times, Bloomberg, The
Economist, The Wall Street Journal, Nikkei, Nikkei Business, Asahi, Yomiuri,
Mainichi, Toyo Keizai, Diamond Online, The Information, MIT Technology Review,
IEEE Spectrum, Semafor, TechCrunch, and The Register in the discovery system
without paying to access them or downloading every home page every day.

Category specialists complement rather than replace that baseline: data-center
and telecom publications for SoftBank, EV publications for Honda, F1
publications for Formula One, local macro publications for China/India/Vietnam,
music publications for YOASOBI, and basketball publications for the Brex.

## Learning without self-corruption

`scripts/night_signal_eval.py` records per-category source diagnostics in each
day's `eval_report.json`: material topics without trusted body Evidence,
specialist recovery yield, unavailable web seeds, published-source classes,
source concentration, causes, and bounded actions. The report carries the
previous three issues and marks recurring causes, so later maintenance starts
from executed evidence instead of rediscovering the same failure.

Before model review, `source_gap_report.json` records the same failure boundary
at collection time. If packet preparation stops, the workflow uploads this as a
diagnostic artifact with a distinct name; it is never mistaken for reusable
final Evidence.

Daily evidence may activate a bounded topic-specific search and existing fetch
fallbacks. It must not automatically add, delete, or downgrade publishers:
registry changes remain reviewed and deterministic. This prevents a transient
outage or one noisy article from permanently teaching the collector a bad
source.

## Interaction and publication-safety boundaries

- Specialist priority must not remove broad recall: general search still finds
  breaking stories and checks for omissions.
- More sources must not create more model review by default: related-company
  official pages are deterministic seeds; the larger publisher portfolio is
  gap-only and the query budget is fixed.
- Restricted headlines never become body Evidence. Open sources are searched
  first and inaccessible claims require accessible corroboration.
- Source unavailability is recorded and uses the bounded reader/search fallback;
  it does not silently count as observed and it does not bypass publication
  quality gates.
- A portfolio-schema error fails before network collection, while an individual
  source outage remains an explicit nonfatal source result. This preserves daily
  publication recovery without hiding coverage loss.
