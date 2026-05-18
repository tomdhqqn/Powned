# PowNed Redactie Dashboard — setup-instructies

Een dagelijks redactiedashboard voor PowNed dat automatisch RSS-feeds ophaalt van
~25 Nederlandse nieuwsbronnen, ze scoort op PowNed-relevantie met Claude AI, en
de meest kansrijke leads van de afgelopen 48 uur in een werkende web-interface toont.

**Wat je krijgt:**
- Een werkend dashboard op een eigen URL (bv. `https://jouwnaam.github.io/powned-redactie/`)
- Elke ochtend om 08:30 automatisch verse data
- Filters op score, categorie, bron, locatie en zoekwoord
- "Oppakken" / "Afwijzen" per item
- AI-gegenereerde score, reden en samenvatting per artikel

**Wat het kost:**
- GitHub: **gratis**
- Claude API: ~**€0,05 per refresh** met Haiku-model, dus ~**€2 per maand** bij dagelijks draaien
- Anthropic geeft je $5 startkrediet → eerste 2-3 maanden gratis

---

## Setup in 5 stappen (~20 minuten eenmalig)

### Stap 1 — GitHub-account aanmaken (1 min)

Ga naar [github.com/join](https://github.com/join). Kies een username (bv. `powned-redactie` of `jouwnaam`), e-mailadres en wachtwoord. Klik op de bevestigingslink in je mail.

### Stap 2 — Nieuwe repository maken (2 min)

1. Ga naar [github.com/new](https://github.com/new)
2. **Repository name:** `powned-redactie`
3. **Public** of **Private** — jij kiest (Public = gratis hosting via GitHub Pages, Private kan ook maar dan moet je elders hosten)
4. **NIET** vinkje "Add a README file" aanzetten — dat doe ik voor je
5. Klik **Create repository**

### Stap 3 — Bestanden uploaden (5 min)

Op de lege repo-pagina zie je de tekst _"uploading an existing file"_. Klik daarop, of ga naar `https://github.com/JOUWNAAM/powned-redactie/upload/main`.

**Sleep deze bestanden in het vak** (ze staan allemaal in dezelfde map als deze README):

- `fetch_and_score.py`
- `requirements.txt`
- `index.html`
- `.gitignore`
- `README.md`

**Belangrijk voor de workflow-file:** GitHub vereist dat workflow-bestanden in de map `.github/workflows/` staan. Dat doe je als volgt:

1. Sleep eerst de andere 5 bestanden naar boven en commit ze (knop **Commit changes** onderaan).
2. Klik op **Add file → Create new file**.
3. Bij **Name your file** typ je letterlijk: `.github/workflows/refresh.yml` (de schuine streepjes maken automatisch de mappen).
4. Plak de inhoud van het bestand `refresh.yml` (uit deze map) in het vak eronder.
5. Klik **Commit new file**.

### Stap 4 — API-key als Secret opslaan (2 min)

1. Ga in je repo naar **Settings** (tab bovenaan)
2. In het linkermenu: **Secrets and variables → Actions**
3. Klik **New repository secret**
4. **Name:** `ANTHROPIC_API_KEY`
5. **Secret:** plak je nieuwe Claude API-key (de `sk-ant-...` die je net hebt aangemaakt)
6. Klik **Add secret**

⚠️ Deze key is alleen leesbaar door GitHub Actions, niemand (ook jij niet) kan 'm later nog uitlezen — alleen vervangen.

### Stap 5 — GitHub Pages activeren (1 min)

1. Nog steeds in **Settings** van je repo
2. In het linkermenu: **Pages**
3. **Source:** Deploy from a branch
4. **Branch:** `main` en `/(root)`
5. Klik **Save**

Wacht ~30 seconden. Bovenaan de Pages-pagina verschijnt je dashboard-URL:
`https://JOUWNAAM.github.io/powned-redactie/`

### Eerste refresh draaien (1 min)

De eerste cron-run staat morgenochtend gepland, maar je wilt waarschijnlijk **nu** al data zien.

1. Ga in je repo naar tab **Actions**
2. Links zie je **Daily refresh** — klik erop
3. Rechts: **Run workflow** → groen knopje **Run workflow**
4. Wacht 1-2 minuten (de fetch + scoring duurt ongeveer een minuut)
5. Refresh je dashboard-URL

Klaar. Je hebt een werkend, dagelijks ververst redactiedashboard.

---

## Wat draait er precies?

| Bestand | Doel |
|---|---|
| `fetch_and_score.py` | Haalt RSS-feeds op, parseert, vraagt Claude om scoring, schrijft `feeds.json` |
| `requirements.txt` | Lijst van Python-pakketten die GitHub Actions installeert |
| `.github/workflows/refresh.yml` | Cron-job die elke ochtend 08:30 het Python-script start en de output commit |
| `index.html` | Het dashboard zelf (statisch, leest `feeds.json` in) |
| `feeds.json` | Output van het script — wordt automatisch aangemaakt na de eerste run |

## Bronnen toevoegen / weghalen

Open `fetch_and_score.py` in GitHub (klik op het bestand → potlood-icoon rechtsboven). De lijst staat bovenaan onder `FEEDS = [...]`. Voeg toe / verwijder / wijzig. Commit. Volgende cron-run gebruikt automatisch de nieuwe lijst.

## Tijden aanpassen

Wil je een andere tijd dan 08:30? Open `.github/workflows/refresh.yml` en pas `cron: '30 7 * * *'` aan. Cron-uren in **UTC** (dus voor Nederlandse 08:30 zomertijd = `30 6`, wintertijd = `30 7`).

## Problemen?

Check **Actions** tab in je repo. Klik op de meest recente run. Als 'ie rood is, lees de logs — meestal staat de fout er heel duidelijk in.

Veelvoorkomende fouten:
- _"ANTHROPIC_API_KEY not set"_ → Secret niet of verkeerd opgeslagen (Stap 4)
- _"401 unauthorized"_ → API-key ongeldig of verlopen — maak een nieuwe en update de Secret
- _"Insufficient credits"_ → API-budget op, voeg geld toe op console.anthropic.com
- _"feed XYZ failed"_ → die bron biedt geen RSS meer; verwijder uit `FEEDS` in het script

## Wat is er anders dan het Cowork-prototype?

- **Verse data:** dit script draait echt op een internet-server (GitHub), niet in een sandbox met cache
- **Echte AI-scoring:** roept de Claude API direct aan, geen tussenstap
- **Geen Cowork nodig:** het dashboard draait op een eigen URL die je kunt delen met de redactie
- **Geen bridge-issues:** standaard browser-gedrag, werkt overal

## Vragen of uitbreiden?

Vraag me (Claude) in een chat-sessie. Bv:
- "Voeg een paywall-bypass toe voor Volkskrant via archive.ph"
- "Maak een tweede categorie 'Sport'"
- "Stuur me een mail als er items met score boven de 90 zijn"
