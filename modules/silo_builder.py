"""
HAOUD SEO IA — Module 3 : Silo Builder
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entrée  : Articles HTML dans data/articles/
Sortie  :
  - Silos thématiques (regroupement automatique par Claude)
  - Maillage interne injecté dans chaque article
  - Page index par silo (liste + résumés)
  - Page d'accueil globale du site
  - Upload FTP automatique

Usage CLI :
  python3 modules/silo_builder.py
  python3 modules/silo_builder.py --ftp
  python3 modules/silo_builder.py --dry-run   (analyse sans modifier les fichiers)
"""

import argparse
import ftplib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ARTICLES_DIR = "data/articles"
SILOS_DIR    = "data/silos"
FTP_HOST     = os.getenv("FTP_HOST",     "ftpperso.free.fr")
FTP_USER     = os.getenv("FTP_USER",     "")
FTP_PASSWORD = os.getenv("FTP_PASSWORD", "")
FTP_DIR      = os.getenv("FTP_DIR",      "ROOT")

SITE_NAME    = "Droit Pratique Francophone"
SITE_URL     = f"http://{FTP_USER}.free.fr"

# ─── CSS PARTAGÉ ──────────────────────────────────────────────────────────────
SHARED_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; color: #1a1a2e; line-height: 1.7; background: #f8f9fa; }
    .container { max-width: 960px; margin: 0 auto; padding: 40px 20px; }
    header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 40px 20px; margin-bottom: 40px; }
    nav { background: #0f3460; padding: 12px 20px; }
    nav a { color: #a8d8ea; text-decoration: none; margin-right: 20px; font-size: 0.9rem; }
    nav a:hover { color: white; }
    h1 { font-size: 2rem; font-weight: 700; line-height: 1.3; }
    h2 { font-size: 1.4rem; color: #1a1a2e; margin: 36px 0 16px; padding-bottom: 8px; border-bottom: 2px solid #e8f4fd; }
    h3 { font-size: 1.1rem; margin: 20px 0 10px; }
    p { margin-bottom: 14px; }
    a { color: #0066cc; }
    .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; margin: 24px 0; }
    .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); border-left: 4px solid #0066cc; transition: transform 0.2s; }
    .card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
    .card h3 { margin: 0 0 8px; font-size: 1rem; }
    .card h3 a { text-decoration: none; color: #1a1a2e; }
    .card h3 a:hover { color: #0066cc; }
    .card .meta { font-size: 0.8rem; color: #888; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; margin: 4px 2px; }
    .badge-guide { background: #e8f4fd; color: #0066cc; }
    .badge-comparatif { background: #fef3e8; color: #e67e22; }
    .badge-modele { background: #e8f8e8; color: #27ae60; }
    .badge-faq { background: #f3e8fd; color: #8e44ad; }
    .silo-block { background: white; border-radius: 12px; padding: 28px; margin-bottom: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); }
    .silo-title { font-size: 1.3rem; font-weight: 700; color: #1a1a2e; margin-bottom: 6px; }
    .silo-desc { color: #666; font-size: 0.9rem; margin-bottom: 16px; }
    .internal-links { background: #f0f7ff; border-left: 4px solid #0066cc; border-radius: 0 8px 8px 0; padding: 16px 20px; margin: 32px 0; }
    .internal-links h4 { font-size: 0.9rem; color: #0066cc; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
    .internal-links ul { list-style: none; }
    .internal-links li { margin-bottom: 6px; }
    .internal-links li::before { content: '→ '; color: #0066cc; }
    footer { margin-top: 60px; padding: 24px; text-align: center; font-size: 0.8rem; color: #999; border-top: 1px solid #e0e0e0; }
"""

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def slug_to_title(filename: str) -> str:
    """Convertit un nom de fichier slug en titre lisible."""
    name = filename.replace(".html", "").replace("-", " ")
    return name.capitalize()


def extract_h1(html: str) -> str:
    """Extrait le <h1> d'un fichier HTML."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return ""


def extract_meta_description(html: str) -> str:
    """Extrait la meta description."""
    match = re.search(r'<meta name="description" content="([^"]*)"', html, re.IGNORECASE)
    return match.group(1) if match else ""


def extract_type(html: str) -> str:
    """Extrait le type d'article depuis le HTML."""
    for t in ["Guide pratique", "Comparatif", "Modèle document", "FAQ"]:
        if t.lower() in html.lower():
            return t
    return "Guide"


def badge_class(type_label: str) -> str:
    m = {"guide pratique": "badge-guide", "comparatif": "badge-comparatif",
         "modèle document": "badge-modele", "faq": "badge-faq"}
    return m.get(type_label.lower(), "badge-guide")


def load_articles() -> list[dict]:
    """Charge tous les articles HTML depuis data/articles/."""
    articles = []
    if not os.path.exists(ARTICLES_DIR):
        return articles
    for fname in os.listdir(ARTICLES_DIR):
        if not fname.endswith(".html"):
            continue
        path = os.path.join(ARTICLES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        title = extract_h1(html) or slug_to_title(fname)
        articles.append({
            "filename": fname,
            "path": path,
            "title": title,
            "meta": extract_meta_description(html),
            "type": extract_type(html),
            "html": html,
            "url": f"{SITE_URL}/{fname}",
        })
    return articles


# ─── CLAUDE : GROUPEMENT EN SILOS ────────────────────────────────────────────

def claude_build_silos(articles: list[dict]) -> dict:
    """Demande à Claude de regrouper les articles en silos thématiques."""
    if not ANTHROPIC_API_KEY:
        return _mock_silos(articles)

    article_list = "\n".join(
        f'{i+1}. [{a["type"]}] {a["title"]} ({a["filename"]})'
        for i, a in enumerate(articles)
    )

    prompt = f"""Tu es un expert SEO. Voici {len(articles)} articles d'un site juridique francophone :

{article_list}

Regroupe-les en silos thématiques SEO cohérents.
Règles :
- 2 à 5 silos maximum
- Chaque article dans UN SEUL silo
- Chaque silo a un article "pilier" (le plus complet/général)
- Les autres articles sont des "satellites" qui pointent vers le pilier

Réponds UNIQUEMENT en JSON valide :
{{
  "silos": [
    {{
      "id": "silo_slug",
      "nom": "Nom du silo",
      "description": "Description courte du silo (1 phrase)",
      "pilier": "filename_pilier.html",
      "satellites": ["filename1.html", "filename2.html"]
    }}
  ]
}}"""

    try:
        payload = json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": 1500,
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
            raw = data["content"][0]["text"].strip()
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            return json.loads(raw)
    except Exception as e:
        print(f"  ❌ Claude silos error : {e}")
        return _mock_silos(articles)


def _mock_silos(articles: list[dict]) -> dict:
    """Silo unique de fallback."""
    files = [a["filename"] for a in articles]
    return {"silos": [{
        "id": "silo_principal",
        "nom": "Droit pratique",
        "description": "Guides et modèles de documents juridiques",
        "pilier": files[0] if files else "",
        "satellites": files[1:] if len(files) > 1 else [],
    }]}


# ─── MAILLAGE INTERNE ────────────────────────────────────────────────────────

def inject_internal_links(article: dict, silo: dict, articles_by_file: dict) -> str:
    """Injecte un bloc de liens internes dans un article HTML."""
    related = []

    # Pilier en premier si l'article est satellite
    if article["filename"] != silo["pilier"] and silo["pilier"] in articles_by_file:
        pilier = articles_by_file[silo["pilier"]]
        related.append({"title": f"📌 {pilier['title']} (article pilier)", "url": pilier["url"]})

    # Satellites liés (max 4)
    for sat_file in silo.get("satellites", [])[:4]:
        if sat_file != article["filename"] and sat_file in articles_by_file:
            sat = articles_by_file[sat_file]
            related.append({"title": sat["title"], "url": sat["url"]})

    if not related:
        return article["html"]

    links_html = "\n".join(
        f'<li><a href="{r["url"]}">{r["title"]}</a></li>'
        for r in related
    )

    block = f"""
<div class="internal-links">
  <h4>📚 Articles liés dans ce silo</h4>
  <ul>
    {links_html}
  </ul>
</div>"""

    # Injecter avant le </div> final du container
    html = article["html"]
    if '<footer' in html:
        html = html.replace("<footer", block + "\n  <footer", 1)
    else:
        html = html.replace("</body>", block + "\n</body>", 1)

    return html


# ─── PAGE INDEX PAR SILO ─────────────────────────────────────────────────────

def build_silo_index(silo: dict, articles_by_file: dict) -> str:
    """Génère la page index d'un silo."""
    all_files = [silo["pilier"]] + silo.get("satellites", [])
    cards = ""
    for fname in all_files:
        if fname not in articles_by_file:
            continue
        a = articles_by_file[fname]
        bc = badge_class(a["type"])
        cards += f"""
    <div class="card">
      <h3><a href="{a['url']}">{a['title']}</a></h3>
      <p style="font-size:0.85rem;color:#666;margin:8px 0">{a['meta'][:100]}...</p>
      <span class="badge {bc}">{a['type']}</span>
    </div>"""

    pilier_html = ""
    if silo["pilier"] in articles_by_file:
        p = articles_by_file[silo["pilier"]]
        pilier_html = f"""
    <div style="background:#fff;border-radius:10px;padding:20px;margin-bottom:24px;border:2px solid #0066cc">
      <div style="font-size:0.8rem;color:#0066cc;font-weight:700;margin-bottom:6px">📌 ARTICLE PILIER</div>
      <h2 style="border:none;margin:0 0 8px"><a href="{p['url']}">{p['title']}</a></h2>
      <p style="color:#666;font-size:0.9rem">{p['meta']}</p>
    </div>"""

    now = datetime.now()
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{silo['description']} - Guides pratiques et modèles de documents.">
  <title>{silo['nom']} — {SITE_NAME}</title>
  <style>{SHARED_CSS}</style>
</head>
<body>
  <header>
    <div class="container">
      <div style="font-size:0.8rem;opacity:0.7;margin-bottom:8px">
        <a href="{SITE_URL}/index.html" style="color:#a8d8ea">🏠 Accueil</a> › {silo['nom']}
      </div>
      <h1>{silo['nom']}</h1>
      <p style="opacity:0.8;margin-top:8px">{silo['description']}</p>
    </div>
  </header>
  <div class="container">
    {pilier_html}
    <h2>Tous les guides ({len(all_files)} articles)</h2>
    <div class="card-grid">{cards}</div>
  </div>
  <footer>
    <div class="container">© {now.year} {SITE_NAME} · Contenu généré automatiquement · Pour information uniquement</div>
  </footer>
</body>
</html>"""


# ─── PAGE D'ACCUEIL GLOBALE ───────────────────────────────────────────────────

def build_homepage(silos_data: dict, articles_by_file: dict) -> str:
    """Génère la page d'accueil du site."""
    silos_html = ""
    total_articles = len(articles_by_file)

    for silo in silos_data.get("silos", []):
        all_files = [silo["pilier"]] + silo.get("satellites", [])
        cards = ""
        for fname in all_files[:3]:  # max 3 cartes par silo sur l'accueil
            if fname not in articles_by_file:
                continue
            a = articles_by_file[fname]
            bc = badge_class(a["type"])
            cards += f"""
        <div class="card">
          <h3><a href="{a['url']}">{a['title']}</a></h3>
          <span class="badge {bc}">{a['type']}</span>
        </div>"""

        silo_url = f"{SITE_URL}/silo_{silo['id']}.html"
        silos_html += f"""
    <div class="silo-block">
      <div class="silo-title">📂 {silo['nom']}</div>
      <div class="silo-desc">{silo['description']}</div>
      <div class="card-grid">{cards}</div>
      <a href="{silo_url}" style="display:inline-block;margin-top:12px;font-size:0.9rem">
        Voir tous les articles de ce silo →
      </a>
    </div>"""

    now = datetime.now()
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Guides juridiques pratiques pour la France et le Maroc. Modèles de documents gratuits, conseils et procédures.">
  <title>{SITE_NAME} — Guides juridiques France & Maroc</title>
  <style>{SHARED_CSS}</style>
</head>
<body>
  <header>
    <div class="container">
      <h1>⚖️ {SITE_NAME}</h1>
      <p style="opacity:0.8;margin-top:8px">Guides pratiques, modèles de documents et conseils juridiques pour la France 🇫🇷 et le Maroc 🇲🇦</p>
      <div style="margin-top:16px;font-size:0.85rem;opacity:0.6">{total_articles} articles · Mis à jour le {now.strftime('%d/%m/%Y')}</div>
    </div>
  </header>
  <div class="container">
    <h2>Nos guides par thématique</h2>
    {silos_html}
  </div>
  <footer>
    <div class="container">© {now.year} {SITE_NAME} · Contenu généré automatiquement · Pour information uniquement</div>
  </footer>
</body>
</html>"""


# ─── FTP UPLOAD ───────────────────────────────────────────────────────────────

def ftp_upload_file(ftp: ftplib.FTP, filepath: str, filename: str) -> bool:
    try:
        with open(filepath, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)
        return True
    except Exception as e:
        print(f"    ❌ FTP upload {filename} : {e}")
        return False


def ftp_connect() -> ftplib.FTP | None:
    if not FTP_USER or not FTP_PASSWORD:
        print("  ⚠️  FTP credentials manquants")
        return None
    try:
        ftp = ftplib.FTP(FTP_HOST, timeout=20)
        ftp.login(FTP_USER, FTP_PASSWORD)
        if FTP_DIR and FTP_DIR not in ("/", "ROOT"):
            try:
                ftp.mkd(FTP_DIR)
            except Exception:
                pass
            ftp.cwd(FTP_DIR)
        return ftp
    except Exception as e:
        print(f"  ❌ FTP connexion : {e}")
        return None


# ─── PIPELINE PRINCIPAL ───────────────────────────────────────────────────────

def run(dry_run: bool = False, ftp: bool = False):
    print(f"\n{'═'*60}")
    print(f"  HAOUD SEO IA — Silo Builder")
    print(f"  Mode    : {'DRY RUN (aucun fichier modifié)' if dry_run else 'PRODUCTION'}")
    print(f"  FTP     : {'✅ activé' if ftp else '❌ désactivé'}")
    print(f"{'═'*60}\n")

    # Charger les articles
    articles = load_articles()
    if not articles:
        print(f"❌ Aucun article trouvé dans {ARTICLES_DIR}")
        return

    print(f"📂 {len(articles)} article(s) chargé(s)\n")
    articles_by_file = {a["filename"]: a for a in articles}

    # Construire les silos via Claude
    print("🤖 Claude — Analyse et regroupement en silos...")
    silos_data = claude_build_silos(articles)
    silos = silos_data.get("silos", [])
    print(f"  ✅ {len(silos)} silo(s) créé(s)")
    for s in silos:
        n_sat = len(s.get("satellites", []))
        print(f"     📂 {s['nom']} — pilier: {s['pilier']} + {n_sat} satellites")
    print()

    os.makedirs(SILOS_DIR, exist_ok=True)
    generated_files = []

    # FTP connexion
    ftp_conn = ftp_connect() if ftp else None

    # Pour chaque silo
    for silo in silos:
        print(f"  🔧 Silo : {silo['nom']}")
        all_files = [silo["pilier"]] + silo.get("satellites", [])

        # Injecter maillage interne dans chaque article
        for fname in all_files:
            if fname not in articles_by_file:
                continue
            article = articles_by_file[fname]
            enriched_html = inject_internal_links(article, silo, articles_by_file)

            if not dry_run:
                with open(article["path"], "w", encoding="utf-8") as f:
                    f.write(enriched_html)
                print(f"     ✅ Maillage injecté → {fname}")

                if ftp_conn:
                    ftp_upload_file(ftp_conn, article["path"], fname)
                    print(f"     🌐 FTP → {SITE_URL}/{fname}")

        # Générer page index du silo
        silo_filename = f"silo_{silo['id']}.html"
        silo_path = os.path.join(SILOS_DIR, silo_filename)
        silo_html = build_silo_index(silo, articles_by_file)

        if not dry_run:
            with open(silo_path, "w", encoding="utf-8") as f:
                f.write(silo_html)
            generated_files.append((silo_path, silo_filename))
            print(f"     📄 Index silo → {silo_path}")

            if ftp_conn:
                ftp_upload_file(ftp_conn, silo_path, silo_filename)
                print(f"     🌐 FTP → {SITE_URL}/{silo_filename}")
        print()

    # Générer page d'accueil
    homepage_path = os.path.join(SILOS_DIR, "index.html")
    homepage_html = build_homepage(silos_data, articles_by_file)

    if not dry_run:
        with open(homepage_path, "w", encoding="utf-8") as f:
            f.write(homepage_html)
        print(f"  🏠 Page d'accueil → {homepage_path}")

        if ftp_conn:
            ftp_upload_file(ftp_conn, homepage_path, "index_seo.html")
            print(f"  🌐 FTP → {SITE_URL}/index_seo.html")

    if ftp_conn:
        ftp_conn.quit()

    # Sauvegarder la structure JSON
    if not dry_run:
        structure_path = os.path.join(SILOS_DIR, "structure.json")
        with open(structure_path, "w", encoding="utf-8") as f:
            json.dump(silos_data, f, ensure_ascii=False, indent=2)

    # Résumé
    print(f"\n{'─'*60}")
    print(f"  📈 RÉSUMÉ")
    print(f"  Silos créés       : {len(silos)}")
    print(f"  Articles maillés  : {len(articles)}")
    print(f"  Pages index       : {len(silos)} silos + 1 accueil")
    if ftp and not dry_run:
        print(f"\n  🌐 Site en ligne  : {SITE_URL}/index_seo.html")
    print(f"{'─'*60}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HAOUD SEO IA — Silo Builder")
    parser.add_argument("--ftp",     action="store_true", help="Upload vers free.fr")
    parser.add_argument("--dry-run", action="store_true", help="Analyse sans modifier les fichiers")
    args = parser.parse_args()
    run(dry_run=args.dry_run, ftp=args.ftp)
