"""
HAOUD SEO IA — Module 1 : Keyword Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sources :
  1. Google Autocomplete  → variantes naturelles réelles (France + Maroc)
  2. Claude API           → expansion sémantique + scoring (intention, RPM, difficulté)
  3. Keywords Everywhere  → volume réel + CPC (validation finale)

Usage CLI :
  python3 modules/keyword_generator.py --seed "mise en demeure" --niche juridique
  python3 modules/keyword_generator.py --seed "lettre de résiliation" --export json csv
"""

import argparse
import json
import csv
import time
import re
import urllib.request
import urllib.parse
import urllib.error
import os
import sys
from datetime import datetime
from typing import Optional

# Ajouter le dossier parent au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ANTHROPIC_API_KEY, KEYWORDS_EVERYWHERE_API_KEY,
    TARGETS, NICHE_RPM_BASE, DEFAULT_NICHE, KG_CONFIG, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. GOOGLE AUTOCOMPLETE
# ─────────────────────────────────────────────────────────────────────────────

AUTOCOMPLETE_PREFIXES = [
    "", "comment ", "pourquoi ", "quel ", "quelle ", "quand ",
    "combien ", "est-ce que ", "peut-on ", "doit-on ",
    "exemple ", "modèle ", "gratuit ", "france ", "maroc ",
    "sans avocat ", "en ligne ", "délai ", "coût ",
]

def google_autocomplete(seed: str, gl: str = "fr", hl: str = "fr") -> list[str]:
    """Récupère les suggestions Google Autocomplete pour un seed donné."""
    suggestions = set()

    for prefix in AUTOCOMPLETE_PREFIXES[:KG_CONFIG["autocomplete_max_per_seed"]]:
        query = prefix + seed
        encoded = urllib.parse.quote(query)
        url = (
            f"https://suggestqueries.google.com/complete/search"
            f"?client=firefox&q={encoded}&hl={hl}&gl={gl}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and len(data) > 1:
                    for s in data[1]:
                        if seed.lower() in s.lower():
                            suggestions.add(s.strip().lower())
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️  Autocomplete [{gl}] '{query[:40]}' : {e}")

    return sorted(suggestions)


def collect_autocomplete(seed: str) -> dict[str, list[str]]:
    """Collecte les suggestions pour France et Maroc. Fallback DuckDuckGo si Google bloque."""
    results = {}
    for zone, cfg in TARGETS.items():
        print(f"  🔍 Google Autocomplete [{cfg['label']}]...")
        suggestions = google_autocomplete(seed, gl=cfg["gl"], hl=cfg["hl"])

        # Fallback DuckDuckGo si Google bloque
        if not suggestions:
            print(f"  🦆 Fallback DuckDuckGo [{cfg['label']}]...")
            suggestions = duckduckgo_autocomplete(seed, locale=f"{cfg['hl']}-{cfg['gl']}")

        results[zone] = suggestions
        print(f"     → {len(results[zone])} suggestions")
    return results


def duckduckgo_autocomplete(seed: str, locale: str = "fr-fr") -> list[str]:
    """Suggestions DuckDuckGo comme fallback."""
    suggestions = set()
    prefixes = ["", "comment ", "pourquoi ", "exemple ", "modèle ", "gratuit "]
    for prefix in prefixes[:6]:
        query = prefix + seed
        encoded = urllib.parse.quote(query)
        url = f"https://duckduckgo.com/ac/?q={encoded}&kl={locale}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data:
                    phrase = item.get("phrase", "")
                    if phrase and seed.lower() in phrase.lower():
                        suggestions.add(phrase.strip().lower())
            time.sleep(0.2)
        except Exception:
            pass
    return sorted(suggestions)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CLAUDE API — EXPANSION + SCORING
# ─────────────────────────────────────────────────────────────────────────────

def claude_expand_and_score(
    seed: str,
    autocomplete_suggestions: list[str],
    niche: str,
    rpm_base: float,
) -> list[dict]:
    """
    Envoie les suggestions à Claude pour :
    - Expansion sémantique (nouvelles variantes longue traîne)
    - Scoring : intention, potentiel RPM, difficulté SEO
    - Ciblage France/Maroc
    """
    if not ANTHROPIC_API_KEY:
        print("  ⚠️  ANTHROPIC_API_KEY manquante — scoring simulé")
        return _mock_scoring(autocomplete_suggestions, rpm_base)

    suggestions_str = "\n".join(f"- {s}" for s in autocomplete_suggestions[:40])

    prompt = f"""Tu es un expert SEO francophone spécialisé en niche **{niche}**.

SEED KEYWORD : "{seed}"
RPM BASE ESTIMÉ : {rpm_base}€/1000 vues

SUGGESTIONS GOOGLE AUTOCOMPLETE COLLECTÉES :
{suggestions_str}

Ta mission en 2 parties :

## PARTIE 1 — EXPANSION (exactement {KG_CONFIG['claude_expansions']} nouveaux mots-clés)
Génère {KG_CONFIG['claude_expansions']} mots-clés longue traîne supplémentaires NON présents dans la liste ci-dessus.
Critères : faible concurrence, intention claire, adaptés France ET/OU Maroc francophone.
Exemples de patterns efficaces : "comment [verbe] [objet] sans avocat", "modèle [document] gratuit", "délai [procédure] france/maroc".

## PARTIE 2 — SCORING COMPLET
Score TOUS les mots-clés (liste autocomplete + tes expansions) avec ces métriques :
- intention : "informationnelle" | "transactionnelle" | "navigationnelle" | "comparaison"
- difficulté : 1-10 (1=très facile, 10=très difficile)
- potentiel_rpm : RPM estimé en € (base {rpm_base}€, ajuste selon intention et niche)
- score_global : 1-10 (combinaison difficulté faible + rpm élevé + volume potentiel)
- zone_cible : "france" | "maroc" | "les_deux"
- type_contenu : "guide" | "comparatif" | "modele_document" | "faq" | "liste"

Réponds UNIQUEMENT en JSON valide, format exact :
{{
  "keywords": [
    {{
      "keyword": "...",
      "source": "autocomplete" | "claude_expansion",
      "intention": "...",
      "difficulté": 0,
      "potentiel_rpm": 0.0,
      "score_global": 0,
      "zone_cible": "...",
      "type_contenu": "..."
    }}
  ]
}}

Aucun texte avant ou après le JSON."""

    try:
        import urllib.request
        payload = json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data["content"][0]["text"]
            # Nettoyer les éventuels backticks
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            parsed = json.loads(raw)
            keywords = parsed.get("keywords", [])
            print(f"  ✅ Claude : {len(keywords)} mots-clés scorés")
            return keywords

    except Exception as e:
        print(f"  ❌ Claude API error : {e}")
        return _mock_scoring(autocomplete_suggestions, rpm_base)


def _mock_scoring(suggestions: list[str], rpm_base: float) -> list[dict]:
    """Scoring simulé si pas d'API key (pour tests locaux)."""
    import random
    results = []
    intentions = ["informationnelle", "transactionnelle", "comparaison", "informationnelle"]
    types = ["guide", "comparatif", "modele_document", "faq"]
    zones = ["france", "maroc", "les_deux", "les_deux", "france"]

    for s in suggestions:
        diff = random.randint(1, 5)
        score = random.randint(5, 9)
        results.append({
            "keyword": s,
            "source": "autocomplete",
            "intention": random.choice(intentions),
            "difficulté": diff,
            "potentiel_rpm": round(rpm_base * random.uniform(0.7, 1.3), 1),
            "score_global": score,
            "zone_cible": random.choice(zones),
            "type_contenu": random.choice(types),
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 3. KEYWORDS EVERYWHERE — ENRICHISSEMENT VOLUME + CPC
# ─────────────────────────────────────────────────────────────────────────────

def keywords_everywhere_enrich(keywords: list[dict]) -> list[dict]:
    """
    Enrichit les mots-clés avec volume et CPC via Keywords Everywhere API.
    Doc : https://api.keywordseverywhere.com/docs
    """
    if not KEYWORDS_EVERYWHERE_API_KEY:
        print("  ⚠️  KE_API_KEY manquante — enrichissement KE ignoré")
        for kw in keywords:
            kw["volume_mensuel"] = None
            kw["cpc_eur"] = None
        return keywords

    kw_list = [kw["keyword"] for kw in keywords]
    print(f"  📊 Keywords Everywhere : enrichissement de {len(kw_list)} mots-clés...")

    # KE accepte max 100 par requête
    batch_size = 100
    ke_data = {}

    for i in range(0, len(kw_list), batch_size):
        batch = kw_list[i:i + batch_size]
        try:
            form_data = urllib.parse.urlencode(
                [("dataSource", "gkp"), ("currency", "EUR"), ("country", "fr")]
                + [("kw[]", kw) for kw in batch]
            ).encode("utf-8")

            req = urllib.request.Request(
                "https://api.keywordseverywhere.com/v1/get_keyword_data",
                data=form_data,
                headers={
                    "Authorization": f"Bearer {KEYWORDS_EVERYWHERE_API_KEY}",
                    "Accept": "application/json",
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                for item in result.get("data", []):
                    ke_data[item["keyword"].lower()] = {
                        "volume_mensuel": item.get("vol", 0),
                        "cpc_eur": item.get("cpc", {}).get("value", 0),
                    }
            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ KE error batch {i//batch_size + 1} : {e}")

    # Merge dans les keywords
    for kw in keywords:
        ke = ke_data.get(kw["keyword"].lower(), {})
        kw["volume_mensuel"] = ke.get("volume_mensuel")
        kw["cpc_eur"] = ke.get("cpc_eur")

    enriched = sum(1 for kw in keywords if kw.get("volume_mensuel") is not None)
    print(f"  ✅ KE : {enriched}/{len(keywords)} mots-clés enrichis")
    return keywords


# ─────────────────────────────────────────────────────────────────────────────
# 4. EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_results(keywords: list[dict], seed: str, niche: str, formats: list[str]) -> dict[str, str]:
    """Exporte les résultats en JSON et/ou CSV."""
    os.makedirs(KG_CONFIG["output_dir"], exist_ok=True)

    # Filtrer par score minimum
    filtered = [kw for kw in keywords if kw.get("score_global", 0) >= KG_CONFIG["min_score_export"]]
    # Trier par score_global DESC, potentiel_rpm DESC
    filtered.sort(key=lambda x: (x.get("score_global", 0), x.get("potentiel_rpm", 0)), reverse=True)

    slug = seed.lower().replace(" ", "_")[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base_name = f"{niche}_{slug}_{timestamp}"
    paths = {}

    if "json" in formats:
        path = os.path.join(KG_CONFIG["output_dir"], f"{base_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {
                    "seed": seed,
                    "niche": niche,
                    "generated_at": datetime.now().isoformat(),
                    "total": len(filtered),
                    "sources": {
                        "autocomplete": sum(1 for k in filtered if k.get("source") == "autocomplete"),
                        "claude_expansion": sum(1 for k in filtered if k.get("source") == "claude_expansion"),
                    }
                },
                "keywords": filtered
            }, f, ensure_ascii=False, indent=2)
        paths["json"] = path

    if "csv" in formats:
        path = os.path.join(KG_CONFIG["output_dir"], f"{base_name}.csv")
        if filtered:
            fieldnames = list(filtered[0].keys())
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filtered)
        paths["csv"] = path

    return paths, filtered


def _generate_seed_variants(seed: str) -> list[str]:
    """Génère des variantes longue traîne directement sans autocomplete (fallback local)."""
    prefixes = [
        "comment ", "pourquoi ", "exemple de ", "modèle de ", "lettre de ",
        "délai ", "coût ", "gratuit ", "sans avocat ", "en ligne ",
        "france ", "maroc ", "définition ", "recours après ",
        "comment rédiger ", "quand envoyer ", "que faire après ",
    ]
    suffixes = [
        "", " exemple", " modèle gratuit", " france", " maroc",
        " délai réponse", " sans avocat", " en ligne", " courrier recommandé",
        " locataire", " employeur", " voisin", " assurance",
    ]
    variants = set()
    for p in prefixes:
        variants.add(f"{p}{seed}".strip().lower())
    for s in suffixes:
        variants.add(f"{seed}{s}".strip().lower())
    return sorted(variants)


# ─────────────────────────────────────────────────────────────────────────────
# 5. PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def run(seed: str, niche: str = DEFAULT_NICHE, formats: list[str] = ["json", "csv"]) -> list[dict]:
    """
    Pipeline complet : Autocomplete → Claude → Keywords Everywhere → Export
    """
    print(f"\n{'═'*60}")
    print(f"  HAOUD SEO IA — Keyword Generator")
    print(f"  Seed    : {seed}")
    print(f"  Niche   : {niche}")
    print(f"  Cibles  : France 🇫🇷 + Maroc 🇲🇦")
    print(f"{'═'*60}\n")

    rpm_base = NICHE_RPM_BASE.get(niche, 12.0)

    # Étape 1 : Google Autocomplete
    print("📡 Étape 1/3 — Google Autocomplete...")
    autocomplete = collect_autocomplete(seed)
    all_suggestions = list(set(
        autocomplete.get("france", []) + autocomplete.get("maroc", [])
    ))

    # Si autocomplete vide → Claude génère tout directement
    if not all_suggestions:
        print(f"  ⚠️  Autocomplete indisponible → Claude génère les seeds directement")
        all_suggestions = _generate_seed_variants(seed)
        print(f"  Total unique : {len(all_suggestions)} variantes seed\n")
    else:
        print(f"  Total unique : {len(all_suggestions)} suggestions\n")

    # Étape 2 : Claude expansion + scoring
    print("🤖 Étape 2/3 — Claude API (expansion + scoring)...")
    keywords = claude_expand_and_score(all_suggestions, all_suggestions, niche, rpm_base)
    print()

    # Étape 3 : Keywords Everywhere
    print("📊 Étape 3/3 — Keywords Everywhere (volume + CPC)...")
    keywords = keywords_everywhere_enrich(keywords)
    print()

    # Export
    print(f"💾 Export ({', '.join(formats)})...")
    paths, filtered = export_results(keywords, seed, niche, formats)
    for fmt, path in paths.items():
        print(f"  ✅ {fmt.upper()} → {path}")

    # Résumé
    print(f"\n{'─'*60}")
    print(f"  📈 RÉSUMÉ")
    print(f"  Mots-clés retenus (score ≥ {KG_CONFIG['min_score_export']}) : {len(filtered)}")
    if filtered:
        top5 = filtered[:5]
        print(f"\n  🏆 TOP 5 :")
        for i, kw in enumerate(top5, 1):
            vol = f"vol:{kw.get('volume_mensuel', '?')} " if kw.get("volume_mensuel") else ""
            print(f"  {i}. [{kw.get('score_global', '?')}/10] {kw['keyword']}")
            print(f"     {vol}RPM:{kw.get('potentiel_rpm', '?')}€ | {kw.get('intention', '')} | {kw.get('zone_cible', '')}")
    print(f"{'─'*60}\n")

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAOUD SEO IA — Keyword Generator")
    parser.add_argument("--seed",   required=True,  help="Mot-clé de départ (ex: 'mise en demeure')")
    parser.add_argument("--niche",  default=DEFAULT_NICHE,
                        choices=list(NICHE_RPM_BASE.keys()), help="Niche cible")
    parser.add_argument("--export", nargs="+", default=["json", "csv"],
                        choices=["json", "csv"], help="Formats d'export")
    args = parser.parse_args()

    run(seed=args.seed, niche=args.niche, formats=args.export)
