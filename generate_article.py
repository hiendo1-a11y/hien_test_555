"""
generate_article.py
Gọi Gemini API để tạo bài viết random (không trùng), xuất ra PDF,
sau đó cập nhật index.html với link mới.
"""

import os
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Cấu hình ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-2.5-flash"
PDF_DIR      = Path(".")              # PDF lưu thẳng ở thư mục gốc (giống repo thực tế)
INDEX_HTML   = Path("index.html")
HISTORY_FILE = Path(".article_history.json")  # lưu tiêu đề đã dùng

TOPICS = [
    "Công nghệ & Trí tuệ nhân tạo",
    "Sức khoẻ & Lối sống",
    "Kinh doanh & Khởi nghiệp",
    "Giáo dục & Học tập",
    "Du lịch & Khám phá",
    "Tâm lý & Phát triển bản thân",
    "Môi trường & Thiên nhiên",
    "Văn hoá & Xã hội",
    "Tài chính cá nhân",
    "Khoa học & Khám phá",
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def slugify(text: str) -> str:
    """Chuyển tiêu đề thành tên file an toàn."""
    text = text.lower().strip()
    text = re.sub(r"[àáạảãâầấậẩẫăằắặẳẵ]", "a", text)
    text = re.sub(r"[èéẹẻẽêềếệểễ]", "e", text)
    text = re.sub(r"[ìíịỉĩ]", "i", text)
    text = re.sub(r"[òóọỏõôồốộổỗơờớợởỡ]", "o", text)
    text = re.sub(r"[ùúụủũưừứựửữ]", "u", text)
    text = re.sub(r"[ỳýỵỷỹ]", "y", text)
    text = re.sub(r"[đ]", "d", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]

# ── Gọi Claude API ────────────────────────────────────────────────────────────

def generate_article(used_titles: list[str]) -> dict:
    """Trả về dict: {title, topic, summary, sections}"""
    used_str = "\n".join(f"- {t}" for t in used_titles[-30:]) if used_titles else "(chưa có)"

    prompt = f"""Bạn là nhà báo chuyên viết bài tiếng Việt hay và sâu sắc.

Danh sách tiêu đề đã dùng (KHÔNG được lặp lại chủ đề hoặc tiêu đề tương tự):
{used_str}

Hãy tạo một bài viết HOÀN TOÀN MỚI thuộc một trong các chủ đề: {', '.join(TOPICS)}

Trả về JSON hợp lệ (không có markdown fence) với cấu trúc:
{{
  "title": "Tiêu đề bài viết",
  "topic": "Chủ đề",
  "summary": "Tóm tắt 1-2 câu",
  "sections": [
    {{"heading": "Tên mục", "paragraphs": ["đoạn 1", "đoạn 2"]}},
    ...
  ]
}}

Yêu cầu:
- Tiêu đề hấp dẫn, độc đáo
- 3-4 mục, mỗi mục 1-2 đoạn (~60-80 từ/đoạn)
- Tổng bài viết khoảng 1000 từ (không nhiều hơn)
- Văn phong chuyên nghiệp, thông tin hữu ích
- Chỉ trả về JSON, không thêm gì khác
"""

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    import time
    for attempt in range(3):
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.9,
                    "maxOutputTokens": 1500,
                },
            },
            timeout=60,
        )
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)  # 10s, 20s, 30s
            print(f"⚠️ Rate limit (429), chờ {wait}s... (lần {attempt+1}/3)")
            time.sleep(wait)
            print(f"📡 Status: {resp.status_code}")
            print(f"📡 Response: {resp.text[:500]}")
            continue
        resp.raise_for_status()
        break
    else:
        raise Exception("❌ Gemini API trả 429 liên tục. Chờ vài phút rồi chạy lại, hoặc tạo API key mới tại: https://aistudio.google.com/app/apikey")

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    # strip possible markdown fences
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)

# ── Tạo PDF ───────────────────────────────────────────────────────────────────

def build_pdf(article: dict, pdf_path: Path):
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MyTitle",
        parent=styles["Title"],
        fontSize=22,
        leading=28,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        spaceAfter=4,
    )
    summary_style = ParagraphStyle(
        "Summary",
        parent=styles["Normal"],
        fontSize=12,
        leading=18,
        textColor=colors.HexColor("#444444"),
        leftIndent=10,
        rightIndent=10,
        spaceBefore=6,
        spaceAfter=14,
        borderPad=8,
        backColor=colors.HexColor("#f0f4ff"),
    )
    heading_style = ParagraphStyle(
        "MyHeading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#16213e"),
        spaceBefore=14,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "MyBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=17,
        spaceAfter=8,
    )

    date_str = datetime.now().strftime("%d/%m/%Y")
    story = [
        Paragraph(article["title"], title_style),
        Paragraph(f"Chủ đề: <b>{article['topic']}</b> &nbsp;|&nbsp; Ngày: {date_str}", meta_style),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#3a86ff"), spaceAfter=8),
        Paragraph(article["summary"], summary_style),
    ]

    for sec in article.get("sections", []):
        story.append(Paragraph(sec["heading"], heading_style))
        for para in sec.get("paragraphs", []):
            story.append(Paragraph(para, body_style))
        story.append(Spacer(1, 4))

    doc.build(story)

# ── Cập nhật index.html ───────────────────────────────────────────────────────

def update_index(article: dict, pdf_filename: str):
    """Chèn <li> mới vào <ul> trong index.html hiện có của repo."""
    # Link thẳng tên file (không có prefix thư mục)
    new_item = f'        <li><a href="{pdf_filename}">{article["title"]}</a></li>'

    if not INDEX_HTML.exists():
        # Tạo mới nếu chưa có
        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <title>Danh sách tài liệu</title>
</head>
<body>
  <h1>Hệ thống lưu trữ file</h1>
  <p>Chọn các link dưới đây để kiểm tra dữ liệu:</p>
  <ul>
{new_item}
  </ul>
</body>
</html>
"""
        INDEX_HTML.write_text(html, encoding="utf-8")
    else:
        content = INDEX_HTML.read_text(encoding="utf-8")
        # Chèn bài mới ngay sau thẻ <ul> đầu tiên (lên đầu danh sách)
        content = re.sub(r"(<ul[^>]*>)", rf"\1\n{new_item}", content, count=1)
        INDEX_HTML.write_text(content, encoding="utf-8")

    print(f"✅ index.html đã cập nhật: {article['title']}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    history = load_history()
    used_titles = [h["title"] for h in history]

    print("🤖 Đang tạo bài viết mới...")
    article = generate_article(used_titles)
    print(f"📝 Tiêu đề: {article['title']}")
    print(f"📂 Chủ đề: {article['topic']}")

    # Tạo tên file PDF
    title_slug = slugify(article["title"])
    pdf_filename = f"Test_auto_{title_slug}.pdf"   # format giống các file có sẵn trong repo
    pdf_path = PDF_DIR / pdf_filename

    print("📄 Đang tạo PDF...")
    build_pdf(article, pdf_path)
    print(f"✅ PDF đã lưu: {pdf_filename}")

    update_index(article, pdf_filename)

    # Lưu lịch sử
    history.append({
        "title": article["title"],
        "topic": article["topic"],
        "pdf": pdf_filename,
        "date": datetime.now().isoformat(),
    })
    save_history(history)

    # Ghi output để GitHub Actions dùng
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"pdf_filename={pdf_filename}\n")
            f.write(f"article_title={article['title']}\n")

    print(f"\n🎉 Hoàn tất! File: {pdf_filename}")

if __name__ == "__main__":
    main()
