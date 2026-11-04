import re
from typing import List, Dict, Any, Optional
from app.config import settings
from app.schemas.page import PageContent

class LegalChunker:
    def __init__(self, target_chunk_size: int = settings.CHUNK_SIZE, overlap: int = settings.CHUNK_OVERLAP):
        self.target_chunk_size = target_chunk_size
        self.overlap = overlap

    def create_chunks(self, pages: List[PageContent]) -> List[Dict[str, Any]]:
        """Processes extracted pages into section-aware legal chunks with page tracking."""
        raw_chunks = []
        chunk_idx = 0

        for page in pages:
            page_number = page.page_number
            text = page.text.strip()
            if not text:
                continue

            # Split text into paragraphs or logical sections
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

            current_section = page.sections_detected[0] if page.sections_detected else None
            current_buffer = ""

            for p in paragraphs:
                # Check if paragraph is or starts with a new section heading
                detected_heading = self._extract_heading(p)
                if detected_heading:
                    current_section = detected_heading

                # Append paragraph to buffer if it fits
                if len(current_buffer) + len(p) + 2 <= self.target_chunk_size:
                    current_buffer += ("\n\n" if current_buffer else "") + p
                else:
                    if current_buffer.strip():
                        raw_chunks.append({
                            "chunk_index": chunk_idx,
                            "text": current_buffer.strip(),
                            "page_number": page_number,
                            "section_heading": current_section
                        })
                        chunk_idx += 1

                        # Sentence-aware overlap from end of current buffer
                        overlap_text = self._get_sentence_overlap(current_buffer)
                        current_buffer = (overlap_text + "\n\n" if overlap_text else "") + p
                    else:
                        # Paragraph itself is longer than chunk size, split by sentences
                        sub_chunks = self._sentence_split(p)
                        for sub_t in sub_chunks:
                            raw_chunks.append({
                                "chunk_index": chunk_idx,
                                "text": sub_t,
                                "page_number": page_number,
                                "section_heading": current_section
                            })
                            chunk_idx += 1
                        current_buffer = ""

            if current_buffer.strip():
                raw_chunks.append({
                    "chunk_index": chunk_idx,
                    "text": current_buffer.strip(),
                    "page_number": page_number,
                    "section_heading": current_section
                })
                chunk_idx += 1

        return raw_chunks

    def _get_sentence_overlap(self, text: str) -> str:
        """Returns the last complete sentence from text to use as overlap."""
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if not sentences:
            return ""
        last_s = sentences[-1]
        if len(last_s) <= self.overlap * 1.5:
            return last_s
        return ""

    def _sentence_split(self, text: str) -> List[str]:
        """Splits large paragraphs into chunks along sentence boundaries."""
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if not sentences:
            return [text]

        chunks = []
        curr = ""
        for s in sentences:
            if len(curr) + len(s) + 1 <= self.target_chunk_size:
                curr += (" " if curr else "") + s
            else:
                if curr:
                    chunks.append(curr)
                curr = s
        if curr:
            chunks.append(curr)
        return chunks

    def _extract_heading(self, line: str) -> Optional[str]:
        """Detects section heading from line or start of paragraph."""
        first_line = line.split("\n")[0].strip()
        match = re.match(r'^((?:SECTION|ARTICLE|CLAUSE)\s+[\dIVXLC]+[^\.\n]*|\d+(\.\d+)*\s+[A-Z\s]{3,60}|[A-Z\s]{4,60})', first_line, re.IGNORECASE)
        if match:
            heading = match.group(1).strip()
            if len(heading) <= 80:
                return heading
        return None
