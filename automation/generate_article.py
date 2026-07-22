"""
generate_article.py
--------------------
Script d'auto-publication quotidienne pour OptiSpace.

Ce qu'il fait :
1. Prend le prochain sujet dans la file d'attente (topics_queue.json)
2. Appelle l'API Anthropic pour générer le contenu de l'article (guide ou comparatif)
3. Insère automatiquement les liens affiliés Amazon (tag configuré ci-dessous)
4. Génère un fichier HTML au format du site (même style que les pages existantes)
5. Ajoute l'article à la page d'accueil (index.html)
6. Retire le sujet traité de la file d'attente

Ce script est destiné à être lancé automatiquement chaque jour via GitHub Actions
(voir .github/workflows/daily-publish.yml).

Variables d'environnement requises :
- ANTHROPIC_API_KEY : ta clé API Anthropic (à ajouter dans les "Secrets" du repo GitHub)
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
import urllib.request

# ─── Configuration ────────────────────────────────────────────────────────
AFFILIATE_TAG = "cozynesthomef-21"          # ton tag Amazon Associates
SITE_ROOT = Path(__file__).parent.parent     # racine du site (dossier optispace/)
QUEUE_FILE = Path(__file__).parent / "topics_queue.json"
INDEX_FILE = SITE_ROOT / "index.html"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def load_next_topic():
    """Charge le prochain sujet de la file d'attente et le retire de la liste."""
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    if not queue:
        print("Aucun sujet en attente dans topics_queue.json — file vide.")
        sys.exit(0)

    topic = queue.pop(0)

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    return topic


def call_claude(prompt: str) -> str:
    """Appelle l'API Anthropic et retourne le texte généré."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY manquant dans les variables d'environnement.")

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    return "".join(block.get("text", "") for block in data.get("content", []))


def build_prompt(topic: dict) -> str:
    """Construit le prompt envoyé à Claude selon le type d'article."""
    base = (
        "Tu es rédacteur pour OptiSpace, un site français de comparatifs et guides sur "
        "l'organisation et le rangement des petits espaces (studios, petits appartements). "
        "Ton ton : pratique, direct, sans blabla marketing. Public : gens en location, "
        "petit budget, appartements de 15 à 40 m².\n\n"
    )

    if topic["type"] == "guide":
        return base + (
            f"Écris un guide pratique intitulé « {topic['title']} ».\n"
            f"Angle : {topic['angle']}\n"
            "Structure : une intro courte (2-3 phrases), puis 3 à 4 sections avec un titre "
            "H2 court et un paragraphe de 3-5 phrases chacune, puis une conclusion en liste "
            "à puces (3-4 points).\n"
            "Réponds uniquement avec le contenu, sans balises HTML, sans titre principal "
            "(je l'ajoute moi-même). Sépare les sections par des lignes '## Titre de section'."
        )

    # comparatif
    produits = "\n".join(f"- {p}" for p in topic.get("produits", []))
    return base + (
        f"Écris un comparatif intitulé « {topic['title']} ».\n"
        f"Angle : {topic['angle']}\n"
        f"Produits à comparer :\n{produits}\n\n"
        "Pour chaque produit, donne : un nom court, une description de 2-3 phrases, "
        "2 avantages et 1 limite. Réponds au format suivant pour chaque produit, séparé par "
        "'---' :\n"
        "NOM: ...\nDESCRIPTION: ...\nAVANTAGE1: ...\nAVANTAGE2: ...\nLIMITE: ..."
    )


def affiliate_link(product_name: str) -> str:
    """Génère un lien affilié Amazon. ASIN_A_COMPLETER doit être remplacé manuellement
    par le vrai ASIN une fois le produit choisi (l'IA ne connaît pas les ASIN réels)."""
    return f"https://www.amazon.fr/s?k={urllib.parse.quote(product_name)}&tag={AFFILIATE_TAG}"


def render_guide_html(topic: dict, generated_text: str) -> str:
    sections = re.split(r"\n##\s*", generated_text.strip())
    intro = sections[0].strip()
    body_html = f"<p>{intro}</p>\n"

    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        heading = lines[0].strip()
        paragraph = lines[1].strip() if len(lines) > 1 else ""
        body_html += f"<h2>{heading}</h2>\n<p>{paragraph}</p>\n"

    return TEMPLATE_GUIDE.format(
        title=topic["title"],
        description=topic["angle"],
        body=body_html,
    )


def render_comparatif_html(topic: dict, generated_text: str) -> str:
    products_raw = generated_text.strip().split("---")
    products_html = ""

    for i, block in enumerate(products_raw, start=1):
        fields = dict(
            re.findall(r"(NOM|DESCRIPTION|AVANTAGE1|AVANTAGE2|LIMITE):\s*(.+)", block)
        )
        if not fields.get("NOM"):
            continue
        rank_label = "#1 — Meilleur choix global" if i == 1 else f"#{i}"
        link = affiliate_link(fields["NOM"])
        products_html += f"""
  <div class="product">
    <div class="product-img">[Image produit]</div>
    <div class="product-body">
      <span class="product-rank">{rank_label}</span>
      <h3>{fields.get('NOM', '')}</h3>
      <p>{fields.get('DESCRIPTION', '')}</p>
      <div class="pros-cons">
        <div class="pros"><span class="label">+ Avantages</span>{fields.get('AVANTAGE1', '')}<br>{fields.get('AVANTAGE2', '')}</div>
        <div class="cons"><span class="label">− Limites</span>{fields.get('LIMITE', '')}</div>
      </div>
      <a href="{link}" class="btn-buy" rel="sponsored nofollow" target="_blank">Voir le prix sur Amazon</a>
      <span class="price-note">⚠️ Lien de recherche générique — à remplacer par le lien du produit exact choisi</span>
    </div>
  </div>"""

    return TEMPLATE_COMPARATIF.format(
        title=topic["title"],
        description=topic["angle"],
        products=products_html,
    )


TEMPLATE_GUIDE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | OptiSpace</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="assets/css/guide.css">
</head>
<body>
<header><div class="logo"><a href="index.html">OptiSpace</a></div></header>
<div class="wrap">
  <div class="breadcrumb"><a href="index.html">Accueil</a> / Guides</div>
  <h1>{title}</h1>
  <div class="article-body">
{body}
  </div>
</div>
<footer><div class="wrap"><p>OptiSpace participe au Programme Partenaires d'Amazon EU.</p></div></footer>
</body>
</html>
"""

TEMPLATE_COMPARATIF = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | OptiSpace</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="assets/css/comparatif.css">
</head>
<body>
<header><div class="logo"><a href="index.html">OptiSpace</a></div></header>
<div class="wrap">
  <div class="breadcrumb"><a href="index.html">Accueil</a> / Comparatifs</div>
  <h1>{title}</h1>
  <p class="intro">{description}</p>
  <div class="disclosure-note">
    En tant que Partenaire Amazon, OptiSpace perçoit une commission sur les achats remplissant les conditions requises.
  </div>
{products}
</div>
<footer><div class="wrap"><p>OptiSpace participe au Programme Partenaires d'Amazon EU.</p></div></footer>
</body>
</html>
"""


def update_homepage(topic: dict):
    """Insère automatiquement un lien vers le nouvel article sur la page d'accueil."""
    index_html = INDEX_FILE.read_text(encoding="utf-8")

    if topic["type"] == "comparatif":
        marker = "<!-- AUTO_COMPARATIFS_INSERT -->"
        snippet = f"""      <div class="card">
        <div class="card-top"><span class="tag">Comparatif</span></div>
        <div class="card-body">
          <h3>{topic['title']}</h3>
          <p>{topic['angle']}</p>
          <a href="{topic['slug']}.html" class="link">Voir le comparatif →</a>
        </div>
      </div>
      {marker}"""
    else:
        marker = "<!-- AUTO_GUIDES_INSERT -->"
        snippet = f"""      <a href="{topic['slug']}.html" class="guide-row">
        <span class="idx">•</span>
        <span class="title">{topic['title']}</span>
        <span class="meta">Nouveau</span>
      </a>
      {marker}"""

    if marker not in index_html:
        print(f"⚠️  Marqueur {marker} introuvable dans index.html — ajout à la homepage sauté.")
        return

    index_html = index_html.replace(marker, snippet)
    INDEX_FILE.write_text(index_html, encoding="utf-8")
    print("Page d'accueil mise à jour avec le nouvel article.")


def main():
    topic = load_next_topic()
    print(f"Génération de l'article : {topic['title']} ({topic['type']})")

    prompt = build_prompt(topic)
    generated_text = call_claude(prompt)

    if topic["type"] == "guide":
        html = render_guide_html(topic, generated_text)
    else:
        html = render_comparatif_html(topic, generated_text)

    out_path = SITE_ROOT / f"{topic['slug']}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Article publié : {out_path}")

    update_homepage(topic)

    if topic["type"] == "comparatif":
        print(
            "⚠️  RAPPEL : les liens affiliés générés sont des liens de recherche "
            "génériques (pas des ASIN précis). Va remplacer les liens 'Voir le prix' "
            "par les vrais liens produits Amazon avant de partager cet article."
        )


if __name__ == "__main__":
    import urllib.parse
    main()
