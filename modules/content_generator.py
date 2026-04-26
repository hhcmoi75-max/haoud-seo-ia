"""
HAOUD SEO IA — Module 2 : Content Generator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entrée  : JSON/CSV du Module 1 (keywords scorés)
Sortie  : Articles HTML complets dans data/articles/
Upload  : FTP automatique vers free.fr (optionnel)

Types d'articles générés :
  - guide           → article informatif longue traîne (1200-1800 mots)
  - comparatif      → comparaison structurée (1000-1500 mots)
  - modele_document → modèle téléchargeable + explications (800-1200 mots)
  - faq             → page FAQ structurée (800-1200 mots)

Usage CLI :
  python3 modules/content_generator.py --input data/keywords/juridique_mise_en_demeure_XXX.json
  python3 modules/content_generator.py --input data/keywords/juridique_mise_en_demeure_XXX.json --limit 5
  python3 modules/content_generator.py --input data/keywords/juridique_mise_en_demeure_XXX.json --ftp
"""

import argparse
import json
import os
import re
import sys
import time
import ftplib
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS,
    NICHE_RPM_BASE
)

# ─── FTP FREE.FR ─────────────────────────────────────────────────────────────
FTP_HOST     = os.getenv("FTP_HOST",     "ftpperso.free.fr")
FTP_USER     = os.getenv("FTP_USER",     "")
FTP_PASSWORD = os.getenv("FTP_PASSWORD", "")
FTP_DIR      = os.getenv("FTP_DIR",      "/articles")   # dossier sur free.fr

OUTPUT_DIR   = "data/articles"

# ─── PROMPTS PAR TYPE DE CONTENU ─────────────────────────────────────────────

LEGAL_CONTEXT = {
    "france": """Contexte juridique FRANCE uniquement :
- Code civil français (articles 1344 et suivants pour la mise en demeure)
- Procédures : LRAR, huissier de justice, tribunal judiciaire
- Délais : selon le Code civil et la jurisprudence française
- Montants/coûts en euros, références aux lois françaises
- NE PAS mentionner le droit marocain""",

    "maroc": """Contexte juridique MAROC uniquement :
- Code des Obligations et Contrats (DOC) marocain
- Procédures : mise en demeure par lettre recommandée, adoul, tribunal de première instance
- Délais : selon le DOC et la jurisprudence marocaine
- Montants/coûts en dirhams (MAD), références aux lois marocaines
- Vocabulaire adapté : "huissier de justice" existe aussi au Maroc
- NE PAS mentionner le droit français""",
}

PROMPTS = {
    "guide": """Tu es un expert juridique francophone spécialisé en droit {pays_label}. Rédige un guide pratique complet et optimisé SEO sur : "{keyword}"

{legal_context}
Niche : {niche}
Longueur : 1400-1800 mots

Structure OBLIGATOIRE en HTML (sans DOCTYPE ni <html> ni <body>, juste le contenu) :
- <h1> : titre accrocheur contenant le mot-clé exact + mention {pays_label}
- Introduction (150 mots) : contexte + pourquoi c'est important en {pays_label}
- <h2> : "Qu'est-ce que {keyword_court} ?" — définition selon le droit {pays_label}
- <h2> : "Comment procéder étape par étape en {pays_label}" — liste numérotée <ol><li>
- <h2> : "Cadre légal {pays_label}" — textes de loi applicables, articles précis
- <h2> : "Les erreurs à éviter" — liste <ul><li>
- <h2> : "Questions fréquentes" — 3 Q/R format <details><summary>
- <h2> : "Conclusion" — résumé + appel à l'action
- Balises <strong> sur les mots-clés importants
- Ton : professionnel mais accessible, rassurant

Réponds UNIQUEMENT avec le HTML, aucun texte avant ou après.""",

    "comparatif": """Tu es un expert en droit {pays_label}. Rédige un article comparatif optimisé SEO sur : "{keyword}"

{legal_context}
Niche : {niche}
Longueur : 1200-1600 mots

Structure OBLIGATOIRE en HTML (sans DOCTYPE ni <html> ni <body>) :
- <h1> : titre comparatif accrocheur avec le mot-clé + mention {pays_label}
- Introduction (120 mots) : problématique selon le droit {pays_label}
- <h2> : tableau comparatif HTML <table> avec colonnes pertinentes
- <h2> : analyse détaillée option 1 (selon loi {pays_label})
- <h2> : analyse détaillée option 2 (selon loi {pays_label})
- <h2> : "Notre recommandation selon votre situation en {pays_label}"
- <h2> : "Questions fréquentes" — 3 Q/R format <details><summary>
- Balises <strong> sur points clés
- Ton : objectif, factuel, expert

Réponds UNIQUEMENT avec le HTML, aucun texte avant ou après.""",

    "modele_document": """Tu es un juriste spécialisé en droit {pays_label}. Rédige une page complète sur : "{keyword}"

{legal_context}
Niche : {niche}
Longueur : 1000-1400 mots

Structure OBLIGATOIRE en HTML (sans DOCTYPE ni <html> ni <body>) :
- <h1> : titre avec le mot-clé exact + mention {pays_label}
- Introduction (100 mots) : à quoi sert ce document selon le droit {pays_label}
- <h2> : "Modèle {keyword_court} ({pays_label})" — modèle dans <div class="modele-doc"><pre> avec mentions obligatoires selon la loi {pays_label}
- <h2> : "Comment remplir ce modèle" — explications adaptées au contexte {pays_label}
- <h2> : "Mentions obligatoires selon la loi {pays_label}" — liste <ul><li>
- <h2> : "Envoi et délais légaux en {pays_label}" — procédure exacte + délais légaux
- <h2> : "Questions fréquentes" — 3 Q/R format <details><summary>
- Ton : pratique, direct, rassurant

Réponds UNIQUEMENT avec le HTML, aucun texte avant ou après.""",

    "faq": """Tu es un expert en droit {pays_label}. Rédige une page FAQ complète optimisée SEO sur : "{keyword}"

{legal_context}
Niche : {niche}
Longueur : 1000-1400 mots

Structure OBLIGATOIRE en HTML (sans DOCTYPE ni <html> ni <body>) :
- <h1> : titre FAQ accrocheur avec le mot-clé + mention {pays_label}
- Introduction (100 mots) : contexte juridique {pays_label}
- 8 à 10 questions/réponses format <details><summary> (schema.org FAQPage)
  → Questions sur procédure, coût, délais selon droit {pays_label}
  → Réponses complètes de 100-150 mots chacune avec références légales {pays_label}
- <h2> : "Résumé" — tableau récapitulatif selon loi {pays_label}
- Balises <strong> sur les termes importants
- Ton : pédagogique, clair, exhaustif

Réponds UNIQUEMENT avec le HTML, aucun texte avant ou après.""",
}

# Fallback si type non reconnu
PROMPTS["liste"] = PROMPTS["guide"]


# ─── TEMPLATE HTML COMPLET ───────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{meta_description}">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; color: #1a1a2e; line-height: 1.7; background: #f8f9fa; }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 40px 20px; }}
    header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 40px 20px; margin-bottom: 40px; }}
    header .container {{ padding: 0 20px; }}
    h1 {{ font-size: 2rem; font-weight: 700; line-height: 1.3; margin-bottom: 12px; }}
    .meta {{ font-size: 0.85rem; opacity: 0.7; }}
    h2 {{ font-size: 1.4rem; color: #1a1a2e; margin: 36px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e8f4fd; }}
    p {{ margin-bottom: 16px; }}
    ul, ol {{ margin: 16px 0 16px 24px; }}
    li {{ margin-bottom: 8px; }}
    strong {{ color: #0066cc; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.9rem; }}
    th {{ background: #1a1a2e; color: white; padding: 12px; text-align: left; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #e0e0e0; }}
    tr:nth-child(even) {{ background: #f5f9ff; }}
    details {{ margin: 12px 0; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; }}
    summary {{ padding: 14px 18px; background: #f5f9ff; cursor: pointer; font-weight: 600; }}
    summary:hover {{ background: #e8f4fd; }}
    details[open] summary {{ background: #1a1a2e; color: white; }}
    details > *:not(summary) {{ padding: 16px 18px; }}
    .modele-doc {{ background: #fffef0; border: 2px dashed #f0c040; border-radius: 8px; padding: 24px; margin: 20px 0; }}
    .modele-doc pre {{ font-family: 'Courier New', monospace; font-size: 0.9rem; white-space: pre-wrap; line-height: 1.8; }}
    .badge-zone {{ display: inline-block; background: #e8f4fd; color: #0066cc; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; margin-bottom: 16px; }}
    footer {{ margin-top: 60px; padding: 24px; text-align: center; font-size: 0.8rem; color: #999; border-top: 1px solid #e0e0e0; }}
    @media(max-width:600px) {{ h1 {{ font-size: 1.5rem; }} }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <div class="badge-zone">{zone_label}</div>
      <h1>{title}</h1>
      <div class="meta">Mis à jour le {date} · {niche_label} · {type_label}</div>
    </div>
  </header>
  <div class="container">
    {content}
  </div>
  <footer>
    <div class="container">
      © {year} HAOUD SEO IA · Contenu généré automatiquement · Pour information uniquement
    </div>
  </footer>
</body>
</html>"""


# ─── GÉNÉRATION CLAUDE ────────────────────────────────────────────────────────

def generate_article(kw: dict, niche: str, force_zone: str = None) -> str | None:
    """Génère le contenu HTML d'un article via Claude API."""
    keyword     = kw["keyword"]
    type_c      = kw.get("type_contenu", "guide")
    zone        = force_zone or kw.get("zone_cible", "les_deux")
    prompt_tpl  = PROMPTS.get(type_c, PROMPTS["guide"])

    pays_map   = {"france": "France", "maroc": "Maroc"}
    pays_label = pays_map.get(zone, "France")
    legal_ctx  = LEGAL_CONTEXT.get(zone, LEGAL_CONTEXT["france"])
    keyword_court = " ".join(keyword.split()[:3])

    prompt = prompt_tpl.format(
        keyword=keyword,
        keyword_court=keyword_court,
        pays_label=pays_label,
        legal_context=legal_ctx,
        niche=niche,
    )

    try:
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

        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["content"][0]["text"].strip()
            # Nettoyer éventuels backticks html
            content = re.sub(r"```html\s*|\s*```", "", content).strip()
            return content

    except Exception as e:
        print(f"    ❌ Claude error : {e}")
        return None


def build_html(kw: dict, content: str, niche: str, force_zone: str = None) -> str:
    """Enveloppe le contenu dans le template HTML complet."""
    keyword   = kw["keyword"]
    type_c    = kw.get("type_contenu", "guide")
    zone      = force_zone or kw.get("zone_cible", "les_deux")
    rpm       = kw.get("potentiel_rpm", 0)

    zone_map  = {"france": "France 🇫🇷", "maroc": "Maroc 🇲🇦", "les_deux": "France 🇫🇷 & Maroc 🇲🇦"}
    type_map  = {"guide": "Guide pratique", "comparatif": "Comparatif", "modele_document": "Modèle document", "faq": "FAQ", "liste": "Liste"}
    niche_map = {"juridique": "Droit & Juridique", "assurance": "Assurance", "credit": "Crédit", "immobilier_maroc": "Immobilier Maroc", "finance_perso": "Finance personnelle"}

    title = keyword.capitalize()
    meta  = f"Tout savoir sur {keyword} : guide complet, étapes, conseils pratiques pour la France et le Maroc."
    now   = datetime.now()

    return HTML_TEMPLATE.format(
        title=title,
        meta_description=meta[:160],
        zone_label=zone_map.get(zone, "France & Maroc"),
        date=now.strftime("%d/%m/%Y"),
        year=now.year,
        niche_label=niche_map.get(niche, niche),
        type_label=type_map.get(type_c, type_c),
        content=content,
    )


def slug(keyword: str) -> str:
    """Convertit un keyword en slug de fichier."""
    s = keyword.lower().strip()
    s = re.sub(r"[àáâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[îï]", "i", s)
    s = re.sub(r"[ôö]", "o", s)
    s = re.sub(r"[ùûü]", "u", s)
    s = re.sub(r"[ç]", "c", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60]


# ─── FTP UPLOAD ───────────────────────────────────────────────────────────────

def ftp_upload(filepath: str, filename: str) -> bool:
    """Upload un fichier HTML vers free.fr via FTP."""
    if not FTP_USER or not FTP_PASSWORD:
        print("    ⚠️  FTP_USER/FTP_PASSWORD manquants — upload ignoré")
        return False
    try:
        ftp = ftplib.FTP(FTP_HOST, timeout=15)
        ftp.login(FTP_USER, FTP_PASSWORD)
        # Créer le dossier si nécessaire
        try:
            ftp.mkd(FTP_DIR)
        except Exception:
            pass
        ftp.cwd(FTP_DIR)
        with open(filepath, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)
        ftp.quit()
        return True
    except Exception as e:
        print(f"    ❌ FTP error : {e}")
        return False


# ─── PIPELINE PRINCIPAL ───────────────────────────────────────────────────────

def run(input_file: str, niche: str = "juridique", limit: int = None, ftp: bool = False):
    """Pipeline complet : lecture JSON → génération articles → export HTML → FTP."""

    print(f"\n{'═'*60}")
    print(f"  HAOUD SEO IA — Content Generator")
    print(f"  Input   : {input_file}")
    print(f"  Niche   : {niche}")
    print(f"  FTP     : {'✅ activé' if ftp else '❌ désactivé'}")
    print(f"{'═'*60}\n")

    # Charger les keywords
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    keywords = data.get("keywords", data) if isinstance(data, dict) else data

    # Trier par score décroissant, appliquer limit
    keywords.sort(key=lambda x: (x.get("score_global", 0), x.get("potentiel_rpm", 0)), reverse=True)
    if limit:
        keywords = keywords[:limit]

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total   = len(keywords)
    success = 0
    errors  = 0
    urls    = []

    print(f"📝 {total} article(s) à générer...\n")

    for i, kw in enumerate(keywords, 1):
        keyword  = kw["keyword"]
        type_c   = kw.get("type_contenu", "guide")
        score    = kw.get("score_global", "?")
        rpm      = kw.get("potentiel_rpm", "?")
        zone     = kw.get("zone_cible", "les_deux")

        # Déterminer les zones à générer
        if zone == "les_deux":
            zones_to_gen = ["france", "maroc"]
        else:
            zones_to_gen = [zone]

        print(f"  [{i}/{total}] {keyword}")
        print(f"         type:{type_c} | score:{score}/10 | RPM:{rpm}€ | zones:{'+'.join(zones_to_gen)}")

        for z in zones_to_gen:
            z_label = "🇫🇷" if z == "france" else "🇲🇦"
            print(f"         {z_label} Génération version {z}...")

            content = generate_article(kw, niche, force_zone=z)
            if not content:
                errors += 1
                print(f"         ❌ Échec génération {z}")
                continue

            html = build_html(kw, content, niche, force_zone=z)

            # Nom de fichier avec suffixe zone
            z_suffix = "-france" if z == "france" else "-maroc"
            filename = f"{slug(keyword)}{z_suffix}.html"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)

            success += 1
            print(f"         ✅ Sauvegardé → {filepath}")

            if ftp:
                uploaded = ftp_upload(filepath, filename)
                if uploaded:
                    url = f"http://{FTP_USER}.free.fr/{filename}"
                    urls.append(url)
                    print(f"         🌐 En ligne → {url}")

            time.sleep(1)

        print()

    # Résumé
    print(f"{'─'*60}")
    print(f"  📈 RÉSUMÉ")
    print(f"  ✅ Générés   : {success}/{total}")
    print(f"  ❌ Erreurs   : {errors}/{total}")
    print(f"  📁 Dossier   : {os.path.abspath(OUTPUT_DIR)}")
    if urls:
        print(f"\n  🌐 Articles en ligne :")
        for url in urls:
            print(f"     {url}")
    print(f"{'─'*60}\n")

    return success


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAOUD SEO IA — Content Generator")
    parser.add_argument("--input",  required=True, help="Fichier JSON du Module 1")
    parser.add_argument("--niche",  default="juridique", choices=list(NICHE_RPM_BASE.keys()))
    parser.add_argument("--limit",  type=int, default=None, help="Nombre d'articles max à générer")
    parser.add_argument("--ftp",    action="store_true", help="Upload vers free.fr via FTP")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Fichier introuvable : {args.input}")
        sys.exit(1)

    run(
        input_file=args.input,
        niche=args.niche,
        limit=args.limit,
        ftp=args.ftp,
    )
