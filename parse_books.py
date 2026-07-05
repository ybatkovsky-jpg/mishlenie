"""
Book parser: extracts text and structure from PDF, DOC, RTF, FB2, EPUB files.
Saves structured JSON for each book.
"""

import json
import os
import re
import sys
from pathlib import Path

BOOKS_DIR = Path("D:/БИЗНЕС/Мышление книги")


def parse_fb2(filepath: Path) -> dict:
    """Parse FB2 (FictionBook) XML format - structured, easy.
    Handles both namespace-aware and namespace-less FB2 files."""
    from xml.etree import ElementTree as ET

    tree = ET.parse(filepath)
    root = tree.getroot()

    # Detect namespace from root tag
    ns = {}
    tag = root.tag
    if tag.startswith("{"):
        ns_uri = tag.split("}")[0].lstrip("{")
        ns = {"fb": ns_uri}

    def find_el(parent, tag_name):
        """Find element with or without namespace."""
        if ns:
            result = parent.find(f"fb:{tag_name}", ns)
            if result is not None:
                return result
        # Fallback: search by local tag name
        for child in parent.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == tag_name:
                return child
        return None

    def findall_el(parent, tag_name):
        """Find all elements with or without namespace."""
        results = []
        for child in parent.iter():
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == tag_name:
                results.append(child)
        return results

    # Title
    title = filepath.stem
    book_title_elem = find_el(root, "book-title")
    if book_title_elem is not None and book_title_elem.text:
        title = book_title_elem.text

    # Author
    author = ""
    author_elem = find_el(root, "author")
    if author_elem is not None:
        first = find_el(author_elem, "first-name")
        last = find_el(author_elem, "last-name")
        first_name = first.text if first is not None and first.text else ""
        last_name = last.text if last is not None and last.text else ""
        author = f"{first_name} {last_name}".strip()

    # Find body
    body = find_el(root, "body")

    # Sections (chapters)
    sections = []
    if body is not None:
        for i, section in enumerate(findall_el(body, "section")):
            sec_title_elem = find_el(section, "title")
            sec_title = f"Глава {i+1}"
            if sec_title_elem is not None and sec_title_elem.text:
                sec_title = sec_title_elem.text.strip()

            paragraphs = []
            for p in findall_el(section, "p"):
                text = p.text or ""
                # Also get text from nested elements
                for sub in p.iter():
                    if sub.text and sub != p:
                        text += sub.text
                if text.strip():
                    paragraphs.append(text.strip())

            full_text = "\n\n".join(paragraphs)
            if full_text.strip():
                sections.append({
                    "title": sec_title,
                    "text": full_text,
                })

    # If no sections found, extract all text as one section
    if not sections and body is not None:
        all_paras = []
        for p in findall_el(body, "p"):
            text = p.text or ""
            if text.strip():
                all_paras.append(text.strip())
        if all_paras:
            sections.append({"title": "Полный текст", "text": "\n\n".join(all_paras)})

    return {
        "title": title,
        "author": author,
        "format": "fb2",
        "sections": sections,
        "section_count": len(sections),
        "total_chars": sum(len(s["text"]) for s in sections),
    }


def parse_pdf(filepath: Path) -> dict:
    """Parse PDF using PyMuPDF (fitz)."""
    import fitz  # pymupdf

    doc = fitz.open(str(filepath))
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"

    title = filepath.stem
    author = doc.metadata.get("author", "") or ""

    # Try to split into chapters
    sections = split_into_sections(full_text, title)

    return {
        "title": title,
        "author": author,
        "format": "pdf",
        "sections": sections,
        "section_count": len(sections),
        "total_chars": sum(len(s["text"]) for s in sections),
    }


def parse_doc(filepath: Path) -> dict:
    """Parse old .doc format - try antiword, textract, or fallback."""
    # Try converting with python-docx first (may fail for old .doc)
    try:
        from docx import Document
        doc = Document(str(filepath))
        full_text = "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        # Fallback: try antiword via subprocess
        import subprocess
        try:
            result = subprocess.run(
                ["antiword", str(filepath)],
                capture_output=True, text=True, timeout=30,
            )
            full_text = result.stdout
        except Exception:
            # Try textract
            try:
                import textract
                full_text = textract.process(str(filepath)).decode("utf-8", errors="replace")
            except Exception:
                return {"title": filepath.stem, "author": "", "format": "doc",
                        "sections": [], "section_count": 0, "total_chars": 0,
                        "error": "Could not parse .doc file"}

    title = filepath.stem
    sections = split_into_sections(full_text, title)

    return {
        "title": title,
        "author": "",
        "format": "doc",
        "sections": sections,
        "section_count": len(sections),
        "total_chars": sum(len(s["text"]) for s in sections),
    }


def parse_rtf(filepath: Path) -> dict:
    """Parse RTF files."""
    from striprtf.striprtf import rtf_to_text

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        rtf_text = f.read()

    full_text = rtf_to_text(rtf_text)
    title = filepath.stem
    sections = split_into_sections(full_text, title)

    return {
        "title": title,
        "author": "",
        "format": "rtf",
        "sections": sections,
        "section_count": len(sections),
        "total_chars": sum(len(s["text"]) for s in sections),
    }


def parse_epub(filepath: Path) -> dict:
    """Parse EPUB files."""
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(filepath))
        title = filepath.stem
        full_text = ""

        for item in book.get_items():
            if item.get_type() == 9:  # ITEM_DOCUMENT
                soup = BeautifulSoup(item.get_content(), "html.parser")
                full_text += soup.get_text() + "\n"

        sections = split_into_sections(full_text, title)
        return {
            "title": title, "author": "", "format": "epub",
            "sections": sections, "section_count": len(sections),
            "total_chars": sum(len(s["text"]) for s in sections),
        }
    except ImportError:
        return {"title": filepath.stem, "author": "", "format": "epub",
                "sections": [], "section_count": 0, "total_chars": 0,
                "error": "ebooklib/bs4 not installed"}


def split_into_sections(text: str, title: str) -> list[dict]:
    """Try to split text into chapters based on common patterns."""
    # Russian chapter patterns
    patterns = [
        r"\n\s*(Глава\s+\d+[\.\:]*.*?)(?=\n\s*(?:Глава\s+\d+|Часть\s+\d+|Заключение|Приложение|$))",
        r"\n\s*(ГЛАВА\s+\d+[\.\:]*.*?)(?=\n\s*(?:ГЛАВА\s+\d+|ЧАСТЬ\s+\d+|ЗАКЛЮЧЕНИЕ|ПРИЛОЖЕНИЕ|$))",
        r"\n\s*(Часть\s+\d+[\.\:]*.*?)(?=\n\s*(?:Глава\s+\d+|Часть\s+\d+|Заключение|Приложение|$))",
        r"\n\s*(\d+\.\s+[А-ЯA-Z][^\n]+)(?=\n\s*\d+\.\s+[А-ЯA-Z]|$)",
    ]

    for pattern in patterns:
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if len(matches) >= 2:
            sections = []
            for i, match in enumerate(matches):
                start = match.start()
                end = matches[i+1].start() if i+1 < len(matches) else len(text)
                chunk = text[start:end].strip()
                header = match.group(1).strip()[:100]
                sections.append({"title": header, "text": chunk})
            return sections

    # No chapters found — return whole text
    return [{"title": title, "text": text[:500000]}]  # Limit to 500k chars


def parse_book(filepath: Path) -> dict | None:
    """Parse a book file, auto-detecting format."""
    suffix = filepath.suffix.lower()
    print(f"  Parsing: {filepath.name} ({suffix})...", flush=True)

    parsers = {
        ".fb2": parse_fb2,
        ".pdf": parse_pdf,
        ".doc": parse_doc,
        ".rtf": parse_rtf,
        ".epub": parse_epub,
    }

    if suffix not in parsers:
        print(f"    SKIP: unsupported format {suffix}")
        return None

    try:
        result = parsers[suffix](filepath)
        if result.get("error"):
            print(f"    ERROR: {result['error']}")
            return None
        print(f"    OK: {result['section_count']} sections, {result['total_chars']:,} chars")
        return result
    except Exception as e:
        print(f"    FAIL: {e}")
        return None


def find_best_format(book_dir: Path, base_name: str) -> Path | None:
    """Find the best format for a book: FB2 > EPUB > PDF > DOC > RTF."""
    for ext in [".fb2", ".epub", ".pdf", ".doc", ".rtf"]:
        candidate = book_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    return None


def main():
    books = []

    # Priority books (by thinking type) — prefer FB2 when available
    priority = [
        # (path_relative_to_books_dir, thinking_type)
        ("4К - навыки будущего/Непряхин Н., Пащенко Т. - Критическое мышление. Железная логика на все случаи жизни (4К - навыки будущего) - 2020.pdf", "critical"),
        ("Логика/Челпанов - Учебник логики.doc", "logical"),
        ("Талеб Нассим Николас - Черный лебедь (Человек Мыслящий. Идеи, способные изменить мир) - 2020/Талеб Нассим Николас - Черный лебедь (Человек Мыслящий. Идеи, способные изменить мир) - 2020.rtf", "systemic"),
        ("Barri_Dzh_Neylbaff_Avinash_Dixit_-_Teoria_igr_Iskusstvo_strategicheskogo_myshlenia_v_biznese_i_zhizni.fb2", "strategic"),
        ("Edvard_de_Bono_Shest_shlyap_myshlenia.fb2", "creative"),
        ("Essentsializm_Put_k_prostote.fb2", "analytical"),
        ("Iskusstvo_yasno_myslit_Rolf_Dobelli__Z-Library.fb2", "critical"),
        # Bonus books
        ("Medouz_D_-_Azbuka_sistemnogo_myshlenia.fb2", "systemic"),
        ("Slow.pdf", "analytical"),
        ("Боно де Э. - Гениально! Инструменты решения креативных задач - 2016.pdf", "creative"),
        ("Майкл Микалко - Рисовый штурм и еще 21 способ мыслить нестандартно - 2018.pdf", "creative"),
        ("О'Коннор Джозеф, Макдермотт Иан - Искусство системного мышления (Искусство думать) - 2013.pdf", "systemic"),
        ("Сьюзан Дэвид - Эмоциональная гибкость - 2017.fb2", "emotional"),
        ("SHipelik_Logika-Teoriya-argumentatsii.pdf", "logical"),
    ]

    for rel_path, thinking_type in priority:
        filepath = BOOKS_DIR / rel_path
        if not filepath.exists():
            print(f"MISSING: {rel_path}")
            continue

        print(f"\n{'='*60}")
        print(f"[{thinking_type}] {filepath.name}")
        result = parse_book(filepath)
        if result:
            result["thinking_type"] = thinking_type
            result["file"] = rel_path
            books.append(result)

    # Save results
    output_path = Path("D:/CLAUDE/Project/Mishlenie/data/books.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(books, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"TOTAL: {len(books)} books parsed")
    total_chars = sum(b["total_chars"] for b in books)
    print(f"Total characters: {total_chars:,}")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
