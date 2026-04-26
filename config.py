"""
HAOUD SEO IA — Configuration centrale
"""

import os

# ─── API KEYS ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
KEYWORDS_EVERYWHERE_API_KEY = os.getenv("KE_API_KEY", "")  # Keywords Everywhere

# ─── CIBLAGE ─────────────────────────────────────────────────────────────────
TARGETS = {
    "france": {
        "gl": "fr",          # Google country
        "hl": "fr",          # Language
        "label": "🇫🇷 France",
        "rpm_multiplier": 1.0,
    },
    "maroc": {
        "gl": "ma",
        "hl": "fr",
        "label": "🇲🇦 Maroc",
        "rpm_multiplier": 0.35,  # RPM Maroc ≈ 35% du RPM France
    },
}

# ─── NICHE PAR DÉFAUT ────────────────────────────────────────────────────────
DEFAULT_NICHE = "juridique"

NICHE_RPM_BASE = {
    "juridique":         18.0,
    "assurance":         20.0,
    "credit":            25.0,
    "immobilier_maroc":  12.0,
    "finance_perso":     16.0,
    "visa_immigration":  10.0,
    "sante_bien_etre":   11.0,
}

# ─── KEYWORD GENERATOR ───────────────────────────────────────────────────────
KG_CONFIG = {
    "autocomplete_max_per_seed": 10,   # suggestions Google par seed
    "claude_expansions":          20,   # variantes supplémentaires via Claude
    "min_score_export":            5,   # score minimum pour inclure dans export (sur 10)
    "output_dir":                 "data/keywords",
}

# ─── CLAUDE MODEL ────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 2000
