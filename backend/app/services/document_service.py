import os
import shutil
import uuid
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from app.config import settings
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk
from app.services.extractor import DocumentExtractor
from app.services.chunker import LegalChunker
from app.services.embedder import EmbeddingService
from app.schemas.page import PageContent, DocumentPagesResponse

class DocumentService:
    @staticmethod
    def save_upload_file(file: UploadFile) -> Tuple[str, str, int]:
        """Saves UploadFile to disk and returns (file_path, file_type, file_size)."""
        filename = file.filename
        ext = os.path.splitext(filename)[1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )

        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = os.path.getsize(file_path)
        return file_path, ext.lstrip('.'), file_size

    @staticmethod
    def create_document(db: Session, filename: str, file_path: str, file_type: str, file_size: int) -> Document:
        """Creates initial Document record in UPLOADED status."""
        doc = Document(
            filename=filename,
            file_path=file_path,
            file_type=file_type,
            file_size=file_size,
            status=DocumentStatus.UPLOADED,
            total_pages=0
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    @staticmethod
    def process_document(db_or_id, document_id: Optional[str] = None):
        """Pipeline execution for document processing, chunking, and embedding."""
        from app.database import SessionLocal

        if isinstance(db_or_id, str):
            doc_id = db_or_id
            db = SessionLocal()
            own_session = True
        else:
            doc_id = document_id
            # When run via FastAPI BackgroundTasks, the request db session is closed by the dependency.
            # Use a fresh session to ensure background operations succeed reliably.
            db = SessionLocal()
            own_session = True

        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if not doc:
                return

            # 1. Update status to PROCESSING
            doc.status = DocumentStatus.PROCESSING
            db.commit()

            # 2. Page-aware text extraction
            pages, total_pages = DocumentExtractor.extract(doc.file_path, doc.file_type)
            doc.total_pages = total_pages

            # Store page text cache in meta_info for GET /documents/{id}/pages
            pages_data = [
                {
                    "page_number": p.page_number,
                    "text": p.text,
                    "word_count": p.word_count,
                    "sections_detected": p.sections_detected
                }
                for p in pages
            ]
            doc.meta_info = {"pages": pages_data}
            db.commit()

            # 3. Legal document chunking
            chunker = LegalChunker()
            chunk_dicts = chunker.create_chunks(pages)

            if chunk_dicts:
                # 4. Generate local embeddings
                texts = [c["text"] for c in chunk_dicts]
                embedder = EmbeddingService()
                embeddings = embedder.generate_embeddings(texts)

                # 5. Store chunks in database
                chunk_objects = []
                for c_dict, emb in zip(chunk_dicts, embeddings):
                    chunk_obj = Chunk(
                        document_id=doc.id,
                        chunk_index=c_dict["chunk_index"],
                        text=c_dict["text"],
                        page_number=c_dict["page_number"],
                        section_heading=c_dict["section_heading"],
                        embedding=emb
                    )
                    chunk_objects.append(chunk_obj)
                
                db.add_all(chunk_objects)

            # 6. Update status to COMPLETED
            doc.status = DocumentStatus.COMPLETED
            db.commit()

        except Exception as e:
            try:
                db.rollback()
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.status = DocumentStatus.FAILED
                    doc.error_message = str(e)
                    db.commit()
            except Exception:
                pass
        finally:
            if own_session:
                db.close()

    @staticmethod
    def get_document(db: Session, document_id: str) -> Optional[Document]:
        return db.query(Document).filter(Document.id == document_id).first()

    @staticmethod
    def list_documents(db: Session, skip: int = 0, limit: int = 100) -> List[Document]:
        return db.query(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def delete_document(db: Session, document_id: str) -> bool:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return False

        # Remove raw file from disk if exists
        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass

        # Cascade deletes chunks automatically
        db.delete(doc)
        db.commit()
        return True

    @staticmethod
    def get_document_pages(db: Session, document_id: str) -> Optional[DocumentPagesResponse]:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return None

        meta = doc.meta_info or {}
        pages_raw = meta.get("pages", [])
        
        pages = [
            PageContent(
                page_number=p["page_number"],
                text=p["text"],
                word_count=p.get("word_count", len(p["text"].split())),
                sections_detected=p.get("sections_detected", [])
            )
            for p in pages_raw
        ]

        return DocumentPagesResponse(
            document_id=doc.id,
            total_pages=doc.total_pages,
            pages=pages
        )
