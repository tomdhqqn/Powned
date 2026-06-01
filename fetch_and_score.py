"""
PowNed Redactie Agent — feed-fetcher en scorer.

Werkt als volgt:
1. Haalt RSS-feeds op van Nederlandse nieuwsbronnen (afgelopen 48u)
2. Dedupliceert en sorteert
3. Vraagt Claude Haiku om elk item een PowNed-relevantiescore te geven
4. Schrijft alles naar feeds.json

Gebruik: ANTHROPIC_API_KEY env-variabele zetten, dan `python fetch_and_score.py`.
"""

import os
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import feedparser
import requests
from anthropic import Anthropic

# ----- Configuratie -----------------------------------------------------------

FEEDS = [
    # --- Landelijke nieuwssites ---
    {"source": "NOS",                "url": "https://feeds.nos.nl/nosnieuwsalgemeen"},
    {"source": "NOS",                "url": "https://feeds.nos.nl/nosnieuwsbinnenland"},
    {"source": "NOS",                "url": "https://feeds.nos.nl/nosnieuwspolitiek"},
    {"source": "NOS",                "url": "https://feeds.nos.nl/nosnieuwsopmerkelijk"},
    {"source": "RTL",                "url": "https://www.rtlnieuws.nl/service/rss/nieuws/index.xml"},
    {"source": "NU.nl",              "url": "https://www.nu.nl/rss/algemeen"},
    {"source": "Hart van Nederland", "url": "https://www.hartvannederland.nl/nieuws/rss.xml"},
    # --- Kranten ---
    {"source": "Telegraaf",          "url": "https://www.telegraaf.nl/rss"},
    {"source": "Telegraaf",          "url": "https://www.telegraaf.nl/binnenland/rss"},
    {"source": "AD",                 "url": "https://www.ad.nl/home/rss.xml"},
    {"source": "AD",                 "url": "https://www.ad.nl/binnenland/rss.xml"},
    {"source": "Volkskrant",         "url": "https://www.volkskrant.nl/nieuws-achtergrond/rss.xml"},
    {"source": "Trouw",              "url": "https://www.trouw.nl/home/rss.xml"},
    {"source": "BN De Stem",         "url": "https://www.bndestem.nl/home/rss.xml"},
    {"source": "De Stentor",         "url": "https://www.destentor.nl/home/rss.xml"},
    {"source": "PZC",                "url": "https://www.pzc.nl/home/rss.xml"},
    {"source": "Gooi- en Eemlander", "url": "https://www.gooieneemlander.nl/rss"},
    # --- Regionale omroepen ---
    {"source": "Omroep West",        "url": "https://www.omroepwest.nl/rss"},
    {"source": "Omroep Brabant",     "url": "https://www.omroepbrabant.nl/rss"},
    {"source": "NH Nieuws",          "url": "https://www.nhnieuws.nl/rss"},
    {"source": "RTV Noord",          "url": "https://www.rtvnoord.nl/rss"},
    {"source": "L1 Limburg",         "url": "https://www.l1.nl/rss"},
    {"source": "AT5",                "url": "https://www.at5.nl/rss"},
    {"source": "Rijnmond",           "url": "https://www.rijnmond.nl/rss"},
    {"source": "RTV Utrecht",        "url": "https://www.rtvutrecht.nl/rss"},
    # --- Specialistisch ---
    {"source": "Politie",            "url": "https://www.politie.nl/rss/nieuws/"},
    {"source": "Crimesite",          "url": "https://www.crimesite.nl/feed/"},
    {"source": "Regio 15 (Den Haag)","url": "https://regio15.nl/feed/"},
    # --- Zuid-Holland regionaal (toegevoegd op feedbackronde) ---
    {"source": "De Havenloods",      "url": "https://www.dehavenloods.nl/feed/"},
    {"source": "Leidsch Dagblad",    "url": "https://www.leidschdagblad.nl/rss.xml"},
    {"source": "Hart van Holland",   "url": "https://www.hartvanzuidplas.nl/feed/"},
    {"source": "AD Den Haag",        "url": "https://www.ad.nl/den-haag/rss.xml"},
    {"source": "AD Rotterdam",       "url": "https://www.ad.nl/rotterdam/rss.xml"},
    {"source": "Briels Nieuwsland",  "url": "https://www.brielsnieuwsland.nl/feed/"},
    {"source": "Dagblad010",         "url": "https://dagblad010.nl/feed/"},
    {"source": "Delft op Zondag",    "url": "https://www.delftopzondag.nl/feed/"},
    {"source": "Den Haag Centraal",  "url": "https://www.denhaagcentraal.net/feed/"},
    {"source": "Dordt Centraal",     "url": "https://dordtcentraal.nl/feed/"},
    {"source": "Het Kontakt",        "url": "https://www.hetkontakt.nl/feed/"},
    {"source": "Kijk op Zuid-Holland","url": "https://www.kijkopzuid-holland.nl/feed/"},
    {"source": "OPEN Rotterdam",     "url": "https://openrotterdam.nl/feed/"},
    {"source": "RTV Dordrecht",      "url": "https://www.rtvdordrecht.nl/feed/"},
    {"source": "Sleutelstad",        "url": "https://sleutelstad.nl/feed/"},
]

# Paywall-bronnen waar links via archive.ph moeten
PAYWALL_SOURCES = {"Volkskrant", "NRC", "Trouw"}

# Tijdvenster: alleen items van afgelopen 48 uur
MAX_AGE_HOURS = 48

# Maximaal aantal items dat we scoren per run (kostenbeheersing)
MAX_ITEMS_TO_SCORE = 60

# Aantal items per batch in scoring-call (Haiku kan zo'n 8 makkelijk aan)
SCORE_BATCH_SIZE = 8

# Claude-model (Haiku is ~10x goedkoper dan Sonnet en prima voor dit type scoring)
MODEL = "claude-haiku-4-5-20251001"

# User-agent voor RSS requests
HEADERS = {
    "User-Agent": "PowNed Redactie Agent / 1.0 (+https://github.com)"
}

# ----- Helpers ----------------------------------------------------------------

def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:120]

def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def canonical_url(source: str, url: str, title: str) -> str:
    # NOS /l/<id> → /artikel/<id>-<slug>
    m = re.search(r"nos\.nl/l/(\d+)", url or "")
    if m:
        return f"https://nos.nl/artikel/{m.group(1)}-{slugify(title)}"
    # Paywall-bronnen: via archive.ph
    if source in PAYWALL_SOURCES and url and "archive.ph" not in url:
        return f"https://archive.ph/newest/{url}"
    return url

def parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def normalize_title(t: str) -> str:
    """Normaliseer titel voor similarity-vergelijking."""
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Strip veelvoorkomende ruis-woorden die niet helpen bij dedup
    for stop in [" nl", " nederland", " 2024", " 2025", " 2026", " video", " live"]:
        t = t.replace(stop, " ")
    return re.sub(r"\s+", " ", t).strip()

def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()

# Drempel: 0.78 = titels lijken sterk op elkaar (zelfde verhaal andere woordkeuze)
# 0.85 = bijna identiek. 0.65 = thematisch verwant maar mogelijk ander verhaal.
TITLE_SIM_THRESHOLD = 0.78

def dedupe_by_title(items: list[dict]) -> tuple[list[dict], int]:
    """Verwijder items met sterk lijkende titels. Houdt het eerste (op gesorteerde input).
    Voegt 'duplicate_sources' toe aan bewaarde items zodat we tonen welke bronnen ook dit verhaal hadden."""
    kept: list[dict] = []
    dup_count = 0
    for item in items:
        is_dup = False
        for k in kept:
            if k["source"] == item["source"]:
                continue  # zelfde bron met andere titel = geen dedup
            if title_similarity(item["title"], k["title"]) >= TITLE_SIM_THRESHOLD:
                is_dup = True
                k.setdefault("duplicate_sources", [])
                if item["source"] not in k["duplicate_sources"]:
                    k["duplicate_sources"].append(item["source"])
                dup_count += 1
                break
        if not is_dup:
            kept.append(item)
    return kept, dup_count

def extract_image(entry) -> str:
    # Probeer in deze volgorde: media_thumbnail, media_content, enclosure
    for attr in ("media_thumbnail", "media_content"):
        items = getattr(entry, attr, None) or []
        if items and isinstance(items, list) and items[0].get("url"):
            return items[0]["url"]
    enc = getattr(entry, "enclosures", None) or []
    if enc and enc[0].get("href"):
        return enc[0]["href"]
    # Soms staat een <img src=...> in de description
    desc = getattr(entry, "summary", "") or ""
    m = re.search(r'<img[^>]+src="([^"]+)"', desc)
    if m:
        return m.group(1)
    return ""

def fetch_one(feed: dict, max_age: timedelta) -> tuple[list[dict], str | None]:
    """Haalt één RSS-feed op en parseert items uit het tijdvenster. Returnt (items, error)."""
    try:
        resp = requests.get(feed["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        return [], f"http: {e}"

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        return [], f"parse: {parsed.bozo_exception}"

    cutoff = datetime.now(timezone.utc) - max_age
    items = []
    for entry in parsed.entries:
        pub = parse_date(entry)
        if not pub or pub < cutoff:
            continue
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        description = strip_html(entry.get("summary") or entry.get("description") or "")[:400]
        items.append({
            "id": f"{feed['source'].lower().replace(' ', '-')}-{abs(hash(link)) % 10**10}",
            "source": feed["source"],
            "title": title,
            "description": description,
            "url": canonical_url(feed["source"], link, title),
            "pubDate": pub.isoformat(),
            "image": extract_image(entry),
        })
    return items, None

# ----- Scoring via Claude -----------------------------------------------------

POWNED_PROMPT = """Je bent een redactieassistent voor PowNed.nl, een Nederlandse opiniesite met een
eigenzinnige, satirische, politiek-incorrecte stijl. PowNed schrijft over:

- POLITIEK & DEN HAAG (kabinet, kamervragen, schandalen, PVV/VVD/D66/GL-PvdA, WOO)
- OPMERKELIJK/CONTROVERSIEEL (BN'er-schandalen, bizarre incidenten, satirisch)
- MEDIA & CANCEL CULTURE (woke, NPO-kritiek, vrijheid van meningsuiting)
- MISDAAD & INCIDENTEN NL (rellen, FIOD, vandalisme, geweld tegen politie)
- EVENT (aangekondigde demonstraties, debatten, congressen — datum vooruit)

Minder relevant: routinematig buitenland zonder NL-link, financiële markten, sport, weer.
Lokaal nieuws kan sterk zijn — PowNed wil regionale verhalen vroeg spotten.

Beoordeel ELK artikel hieronder:
- score: 0-100
- category: Politiek | Opmerkelijk | Media | Misdaad | Event | Overig
- location: kies UITSLUITEND uit deze 14 opties (provincies + Landelijk + Internationaal):
            Landelijk | Drenthe | Flevoland | Friesland | Gelderland | Groningen |
            Limburg | Noord-Brabant | Noord-Holland | Overijssel | Utrecht | Zeeland |
            Zuid-Holland | Internationaal
  Stad → provincie mapping (gebruik dit consistent):
    Amsterdam, Haarlem, Alkmaar, Hilversum → Noord-Holland
    Rotterdam, Den Haag, Leiden, Delft, Dordrecht, Gouda, Schiedam, Zoetermeer → Zuid-Holland
    Utrecht (stad), Amersfoort, Nieuwegein → Utrecht (provincie)
    Eindhoven, Tilburg, Breda, Den Bosch, Helmond → Noord-Brabant
    Groningen (stad), Veendam → Groningen
    Maastricht, Heerlen, Roermond, Venlo → Limburg
    Arnhem, Nijmegen, Apeldoorn, Ede → Gelderland
    Zwolle, Enschede, Hengelo, Deventer → Overijssel
    Leeuwarden, Drachten, Sneek → Friesland
    Middelburg, Vlissingen, Goes → Zeeland
    Almere, Lelystad → Flevoland
    Assen, Emmen, Hoogeveen → Drenthe
  Alleen 'Landelijk' als het geen specifieke provincie betreft. 'Internationaal' alleen voor buitenland.
- reason: één korte zin (max 18 woorden), waarom (niet) relevant
- summary: 2 zinnen, neutraal-feitelijk

Geef ALLEEN een geldige JSON-array terug, géén uitleg eromheen:
[{"id":"...","score":87,"category":"Politiek","location":"Den Haag","reason":"...","summary":"..."}]
"""

def score_batch(client: Anthropic, items: list[dict]) -> dict[str, dict]:
    """Geeft een dict id → score-velden terug."""
    batch_input = [
        {"id": it["id"], "source": it["source"], "title": it["title"], "description": it["description"]}
        for it in items
    ]
    user_msg = POWNED_PROMPT + "\n\nArtikelen:\n" + json.dumps(batch_input, ensure_ascii=False)
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            print(f"  ! batch-score: geen JSON-array gevonden in response", file=sys.stderr)
            return {}
        scored = json.loads(m.group(0))
        return {s["id"]: s for s in scored if isinstance(s, dict) and "id" in s}
    except Exception as e:
        print(f"  ! batch-score faalde: {e}", file=sys.stderr)
        return {}

# ----- Main pipeline ----------------------------------------------------------

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("FOUT: ANTHROPIC_API_KEY env-variabele niet gezet.", file=sys.stderr)
        sys.exit(1)

    print(f"PowNed refresh start — {datetime.now(timezone.utc).isoformat()}")
    print(f"Doel: items van afgelopen {MAX_AGE_HOURS}u uit {len(FEEDS)} feeds.\n")

    # === STAP 1: feeds ophalen ===
    all_items: list[dict] = []
    successful_feeds = []
    failed_feeds = []
    for f in FEEDS:
        items, err = fetch_one(f, timedelta(hours=MAX_AGE_HOURS))
        if err:
            print(f"  ✗ {f['source']:24s} ({f['url']}) — {err}")
            failed_feeds.append({"source": f["source"], "url": f["url"], "error": err})
        else:
            print(f"  ✓ {f['source']:24s} ({len(items)} items)")
            successful_feeds.append({"source": f["source"], "url": f["url"], "count": len(items)})
            all_items.extend(items)

    # === STAP 2: dedupe + sort ===
    # Eerst URL-dedup (exact match), daarna titel-similarity-dedup (zelfde verhaal van andere bron).
    seen_urls = set()
    url_unique = []
    for it in sorted(all_items, key=lambda x: x["pubDate"], reverse=True):
        if it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        url_unique.append(it)
    print(f"\nNa URL-dedupe: {len(url_unique)} items.")

    unique, dup_by_title = dedupe_by_title(url_unique)
    print(f"Na titel-dedupe: {len(unique)} items ({dup_by_title} duplicaten samengevoegd).")

    unique = unique[:MAX_ITEMS_TO_SCORE]

    # === STAP 3: scoring via Claude ===
    if not unique:
        print("Geen items om te scoren.")
        scored_items = []
    else:
        client = Anthropic(api_key=api_key)
        scores: dict[str, dict] = {}
        for i in range(0, len(unique), SCORE_BATCH_SIZE):
            batch = unique[i : i + SCORE_BATCH_SIZE]
            print(f"  → scoring batch {i // SCORE_BATCH_SIZE + 1} ({len(batch)} items)…")
            scores.update(score_batch(client, batch))
            time.sleep(0.5)  # vriendelijk zijn voor de API

        scored_items = []
        for it in unique:
            s = scores.get(it["id"], {})
            scored_items.append({
                **it,
                "score": s.get("score", 50),
                "category": s.get("category", "Overig"),
                "location": s.get("location", "Landelijk"),
                "reason": s.get("reason", "Geen score beschikbaar."),
                "summary": s.get("summary", it["description"][:200]),
            })

    # === STAP 4: schrijven ===
    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "feeds_total": len(FEEDS),
            "feeds_succeeded": len(successful_feeds),
            "feeds_failed": len(failed_feeds),
            "items_collected": len(all_items),
            "items_after_dedupe": len(unique),
            "items_scored": len(scored_items),
            "items_high_score": sum(1 for x in scored_items if x.get("score", 0) >= 70),
        },
        "fetchedFeeds": successful_feeds,
        "failedFeeds": failed_feeds,
        "items": scored_items,
    }
    with open("feeds.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n=== Klaar ===")
    print(f"Feeds geslaagd: {output['stats']['feeds_succeeded']}/{output['stats']['feeds_total']}")
    print(f"Items binnen:   {output['stats']['items_collected']}")
    print(f"Na dedupe:      {output['stats']['items_after_dedupe']}")
    print(f"Gescoord:       {output['stats']['items_scored']}")
    print(f"Score ≥ 70:     {output['stats']['items_high_score']}  ← kansrijke leads")

if __name__ == "__main__":
    main()
