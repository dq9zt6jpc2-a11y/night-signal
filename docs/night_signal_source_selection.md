# NIGHT SIGNAL source selection

The source portfolio is intentionally separate from the daily seed registry.
Seed sources prove that official and required channels were checked. The
publisher portfolio qualifies articles found in search and supplies domains for
a bounded second-pass query only when a category is evidence-thin.

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
