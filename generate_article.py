"""
generate_article.py
Call Gemini API to generate a random article (no duplicates), export to PDF,
then update index.html with the new link.
"""

import os
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

# ── Config ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-2.5-flash"
PDF_DIR = Path(".")
INDEX_HTML = Path("index.html")
HISTORY_FILE = Path(".article_history.json")

TOPICS = [
    "Technology & Artificial Intelligence",
    "Health & Lifestyle",
    "Business & Entrepreneurship",
    "Education & Learning",
    "Travel & Exploration",
    "Psychology & Self-Development",
    "Environment & Nature",
    "Culture & Society",
    "Personal Finance",
    "Science & Discovery",
]

# ── Helpers ──────────────────────────────────────────────────────────────

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]

# ── Call Gemini API ──────────────────────────────────────────────────────

def generate_article(used_titles: list[str]) -> dict:
    used_str = "\n".join(f"- {t}" for t in used_titles[-30:]) if used_titles else "(none)"

    prompt = f"""You are a professional journalist who writes insightful articles in English.

List of titles already used (DO NOT repeat or use similar titles/topics):
{used_str}

Create a COMPLETELY NEW article on one of these topics: {', '.join(TOPICS)}

Return valid JSON (no markdown fences) with this structure:
{{
  "title": "Article title",
  "topic": "Topic",
  "summary": "1-2 sentence summary",
  "sections": [
    {{"heading": "Section name", "paragraphs": ["paragraph 1", "paragraph 2"]}},
    ...
  ]
}}

Requirements:
- Catchy, unique title
- 3-4 sections, each with 1-2 paragraphs (~60-80 words/paragraph)
- Total article around 1000 words
- Professional tone, useful information
- Return ONLY valid JSON, nothing else
"""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    for attempt in range(3):
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.9,
                    "maxOutputTokens": 8000,
                },
            },
            timeout=120,
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"Rate limit (429), waiting {wait}s... (attempt {attempt+1}/3)")
            print(f"Response: {resp.text[:500]}")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        raise Exception("Gemini API returned 429 repeatedly. Check quota at: https://aistudio.google.com/app/apikey")

    parts = resp.json()["candidates"][0]["content"]["parts"]
    raw = parts[-1]["text"].strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    # Fix common JSON issues from LLM output
    raw = raw.replace("\n", " ")
    raw = re.sub(r",\s*}", "}", raw)
    raw = re.sub(r",\s*]", "]", raw)
    # Find the outermost JSON object
    start = raw.index("{")
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = raw[start:i+1]
                break
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON error: {e}")
        print(f"Raw output (first 500 chars): {raw[:500]}")
        raise

# ── Create PDF ───────────────────────────────────────────────────────────

def build_pdf(article: dict, pdf_path: Path):
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MyTitle", parent=styles["Title"],
        fontSize=22, leading=28, spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#666666"), spaceAfter=4,
    )
    summary_style = ParagraphStyle(
        "Summary", parent=styles["Normal"],
        fontSize=12, leading=18, textColor=colors.HexColor("#444444"),
        leftIndent=10, rightIndent=10, spaceBefore=6, spaceAfter=14,
        borderPad=8, backColor=colors.HexColor("#f0f4ff"),
    )
    heading_style = ParagraphStyle(
        "MyHeading", parent=styles["Heading2"],
        fontSize=14, textColor=colors.HexColor("#16213e"),
        spaceBefore=14, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "MyBody", parent=styles["Normal"],
        fontSize=11, leading=17, spaceAfter=8,
    )

    date_str = datetime.now().strftime("%d/%m/%Y")
    story = [
        Paragraph(article["title"], title_style),
        Paragraph(f"Topic: <b>{article['topic']}</b> &nbsp;|&nbsp; Date: {date_str}", meta_style),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#3a86ff"), spaceAfter=8),
        Paragraph(article["summary"], summary_style),
    ]

    for sec in article.get("sections", []):
        story.append(Paragraph(sec["heading"], heading_style))
        for para in sec.get("paragraphs", []):
            story.append(Paragraph(para, body_style))
        story.append(Spacer(1, 4))

    doc.build(story)

# ── Update index.html ────────────────────────────────────────────────────

def update_index(article: dict, pdf_filename: str):
    new_item = f'        <li><a href="{pdf_filename}">{article["title"]}</a></li>'

    if not INDEX_HTML.exists():
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Article Archive</title>
</head>
<body>
  <h1>Article Archive</h1>
  <p>Auto-generated articles:</p>
  <ul>
{new_item}
  </ul>
</body>
</html>
"""
        INDEX_HTML.write_text(html, encoding="utf-8")
    else:
        content = INDEX_HTML.read_text(encoding="utf-8")
        content = re.sub(r"(<ul[^>]*>)", rf"\1\n{new_item}", content, count=1)
        INDEX_HTML.write_text(content, encoding="utf-8")

    print(f"index.html updated: {article['title']}")

# ── Main ─────────────────────────────────────────────────────────────────

def main():
    history = load_history()
    used_titles = [h["title"] for h in history]

    print("Generating new article...")
    article = generate_article(used_titles)
    print(f"Title: {article['title']}")
    print(f"Topic: {article['topic']}")

    title_slug = slugify(article["title"])
    pdf_filename = f"Test_auto_{title_slug}.pdf"
    pdf_path = PDF_DIR / pdf_filename

    print("Creating PDF...")
    build_pdf(article, pdf_path)
    print(f"PDF saved: {pdf_filename}")

    update_index(article, pdf_filename)

    history.append({
        "title": article["title"],
        "topic": article["topic"],
        "pdf": pdf_filename,
        "date": datetime.now().isoformat(),
    })
    save_history(history)

    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"pdf_filename={pdf_filename}\n")
            f.write(f"article_title={article['title']}\n")

    print(f"Done! File: {pdf_filename}")

if __name__ == "__main__":
    main()
