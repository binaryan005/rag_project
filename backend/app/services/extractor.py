import os
import re
from typing import List, Dict, Any, Tuple
from app.schemas.page import PageContent

class DocumentExtractor:
    @staticmethod
    def extract_pdf(file_path: str) -> List[PageContent]:
        """Extracts text page-by-page from PDF files using PyMuPDF (fitz), keeping track of headings."""
        import fitz  # PyMuPDF
        pages: List[PageContent] = []
        
        doc = fitz.open(file_path)
        for page_idx in range(len(doc)):
            page = doc.load_page(page_idx)
            page_num = page_idx + 1
            text = page.get_text("text") or ""
            
            # Detect section headings on page
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            headings = []
            for line in lines:
                if DocumentExtractor._is_potential_heading(line):
                    headings.append(line)
            
            words = text.split()
            pages.append(PageContent(
                page_number=page_num,
                text=text,
                word_count=len(words),
                sections_detected=headings
            ))
            
        doc.close()
        return pages

    @staticmethod
    def extract_docx(file_path: str) -> List[PageContent]:
        """Extracts text from DOCX files using python-docx with section and page tracking."""
        import docx
        doc = docx.Document(file_path)
        
        current_page = 1
        current_text_lines = []
        headings = []
        pages: List[PageContent] = []

        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
                
            # Detect heading style or regex pattern
            if p.style.name.startswith("Heading") or DocumentExtractor._is_potential_heading(text):
                headings.append(text)
            
            current_text_lines.append(text)
            
            # Check for page break in paragraph runs
            has_page_break = any(
                'lastRenderedPageBreak' in run._r.xml or 'pageBreakBefore' in run._r.xml
                for run in p.runs
            )
            
            if has_page_break:
                page_text = "\n".join(current_text_lines)
                pages.append(PageContent(
                    page_number=current_page,
                    text=page_text,
                    word_count=len(page_text.split()),
                    sections_detected=headings
                ))
                current_page += 1
                current_text_lines = []
                headings = []

        # Remaining content on last page
        if current_text_lines or not pages:
            page_text = "\n".join(current_text_lines)
            pages.append(PageContent(
                page_number=current_page,
                text=page_text,
                word_count=len(page_text.split()),
                sections_detected=headings
            ))

        return pages

    @staticmethod
    def extract_txt(file_path: str) -> List[PageContent]:
        """Extracts plain text from .txt files and stores it as a single page."""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as text_file:
            text = text_file.read()

        if not text.strip():
            text = ""

        headings = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and DocumentExtractor._is_potential_heading(stripped):
                headings.append(stripped)

        return [
            PageContent(
                page_number=1,
                text=text,
                word_count=len(text.split()),
                sections_detected=headings
            )
        ]

    @staticmethod
    def extract(file_path: str, file_type: str) -> Tuple[List[PageContent], int]:
        """Unified extraction entrypoint returning list of PageContent and total page count."""
        ext = file_type.lower()
        if ext in ["pdf", ".pdf", "application/pdf"]:
            pages = DocumentExtractor.extract_pdf(file_path)
        elif ext in ["docx", ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            pages = DocumentExtractor.extract_docx(file_path)
        elif ext in ["txt", ".txt", "text/plain"]:
            pages = DocumentExtractor.extract_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
            
        total_pages = len(pages)
        return pages, total_pages

    @staticmethod
    def _is_potential_heading(line: str) -> bool:
        """Determines if line looks like a legal document heading or section title."""
        if len(line) > 120 or len(line) < 3:
            return False
        
        # Regex pattern matching legal contract section headers
        patterns = [
            r'^(SECTION|ARTICLE|CLAUSE)\s+[\dIVXLC]+',
            r'^\d+(\.\d+)*\s+[A-Z]',
            r'^[A-Z\s]{4,80}$',
            r'^(DEFINITIONS|RECITALS|INDEMNIFICATION|TERMINATION|CONFIDENTIALITY|GOVERNING LAW|MISCELLANEOUS)'
        ]
        return any(re.search(pat, line, re.IGNORECASE) for pat in patterns)
