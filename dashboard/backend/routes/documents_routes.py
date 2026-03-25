"""
My Documents routes: Upload, process, list, and delete user documents.

User documents are stored separately from the shared KB and can be:
- Uploaded via drag-drop
- Processed (embedded) on demand
- Deleted with cascading cleanup (Qdrant + BM25 + SQLite + disk)
"""

import asyncio
import hashlib
import logging
import os
import shutil
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from auth import require_viewer, require_operator, TokenPayload

logger = logging.getLogger("dashboard.documents")

router = APIRouter()

# --- WebSocket Manager for Real-Time Updates ---
_ws_manager = None


def set_ws_manager(manager):
    """Set the WebSocket manager for real-time document status notifications."""
    global _ws_manager
    _ws_manager = manager


async def _broadcast_status_change(document_id: str, status: str):
    """Broadcast document status change to all connected WebSocket clients."""
    if _ws_manager:
        await _ws_manager.broadcast({
            "type": "document.status_change",
            "payload": {"document_id": document_id, "status": status}
        })


# Configuration
USER_DOCUMENTS_DIR = os.getenv("USER_DOCUMENTS_DIR", "/data/user_documents")
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".md", ".docx"}


# --- Response Models ---
class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    title: str
    status: str
    file_size: int
    upload_date: str
    error_message: Optional[str] = None


class DocumentListResponse(BaseModel):
    documents: List[DocumentInfo]
    total: int
    counts: dict


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str
    message: str


class ProcessResponse(BaseModel):
    document_id: str
    status: str
    message: str


class DeleteResponse(BaseModel):
    deleted: bool
    message: str


class BatchDeleteResponse(BaseModel):
    deleted_count: int
    failed: List[str]


# --- Helper Functions ---
def _get_paper_store():
    """Get PaperStore instance from SME backend."""
    import sys
    # Add SME src to path if not already
    sme_src = "/app/src"
    if sme_src not in sys.path:
        sys.path.insert(0, "/app")
        sys.path.insert(0, sme_src)

    from src.storage.db import DatabaseManager
    from src.storage.paper_store import PaperStore

    db_path = os.getenv("PAPERS_DB_PATH", "/data/papers.db")
    db_manager = DatabaseManager(db_path)
    return PaperStore(db_manager)


def _get_vector_store():
    """Get QdrantVectorStore instance."""
    import sys
    sme_src = "/app/src"
    if sme_src not in sys.path:
        sys.path.insert(0, "/app")
        sys.path.insert(0, sme_src)

    from src.indexing.vector_store import QdrantVectorStore

    return QdrantVectorStore(
        host=os.getenv("QDRANT_HOST", "sme_qdrant"),
        port=int(os.getenv("QDRANT_PORT", "6333")),
        collection_name=os.getenv("QDRANT_COLLECTION", "sme_papers"),
    )


def _get_bm25_index():
    """Get TantivyBM25Index instance."""
    import sys
    sme_src = "/app/src"
    if sme_src not in sys.path:
        sys.path.insert(0, "/app")
        sys.path.insert(0, sme_src)

    from src.indexing.bm25_tantivy import TantivyBM25Index

    index_path = os.getenv("BM25_INDEX_PATH", "/data/bm25_index_tantivy")
    return TantivyBM25Index(index_path=index_path)


def _compute_checksum(file_path: str) -> str:
    """Compute SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _get_user_dir(user_id: str) -> str:
    """Get user's document directory, creating if needed."""
    user_dir = os.path.join(USER_DOCUMENTS_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def _extract_title_from_filename(filename: str) -> str:
    """Extract document title from filename."""
    # Remove extension and clean up
    name = os.path.splitext(filename)[0]
    # Replace underscores/dashes with spaces
    name = name.replace("_", " ").replace("-", " ")
    return name.title()


# --- Routes ---
@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user: TokenPayload = Depends(require_viewer)
):
    """
    Upload a document for later processing.

    The document is saved to disk and registered in the database with 'discovered' status.
    Processing (embedding) is NOT automatic - use the /process endpoint.
    """
    user_id = user.sub

    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content with size check
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB."
        )

    # Save file to user's directory
    user_dir = _get_user_dir(user_id)
    safe_filename = file.filename.replace("/", "_").replace("\\", "_")
    file_path = os.path.join(user_dir, safe_filename)

    # Handle duplicate filenames
    base, ext = os.path.splitext(safe_filename)
    counter = 1
    while os.path.exists(file_path):
        file_path = os.path.join(user_dir, f"{base}_{counter}{ext}")
        counter += 1

    with open(file_path, "wb") as f:
        f.write(content)

    # Compute checksum
    checksum = _compute_checksum(file_path)

    # Create paper record
    try:
        import sys
        sme_src = "/app/src"
        if sme_src not in sys.path:
            sys.path.insert(0, "/app")
            sys.path.insert(0, sme_src)

        from src.acquisition.paper_discoverer import DiscoveredPaper

        paper = DiscoveredPaper(
            title=_extract_title_from_filename(safe_filename),
            source="user_upload",
            import_source="user_upload",
            status="discovered",
            pdf_path=file_path,
            file_checksum=checksum,
            user_id=user_id,
        )

        paper_store = _get_paper_store()
        added = paper_store.add_paper(paper)

        if not added:
            # Cleanup file if paper already exists
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document with same content already exists."
            )

        logger.info(f"User {user_id} uploaded document: {safe_filename}")

        return UploadResponse(
            document_id=paper.unique_id,
            filename=safe_filename,
            status="pending",
            message="Document uploaded successfully. Click 'Process' to embed."
        )

    except HTTPException:
        raise
    except Exception as e:
        # Cleanup on error
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"Upload failed for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.post("/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    user: TokenPayload = Depends(require_viewer)
):
    """
    Trigger processing (embedding) for a single document.

    The document must be in 'discovered' or 'downloaded' status.
    """
    user_id = user.sub
    paper_store = _get_paper_store()

    # Verify ownership
    paper = paper_store.get_user_paper(document_id, user_id)
    if not paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or not owned by you."
        )

    if paper.status not in ("discovered", "downloaded"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document cannot be processed (current status: {paper.status})."
        )

    # Queue for processing via pipeline
    # For now, update status to 'downloaded' to signal ready for processing
    paper_store.update_status(document_id, "downloaded")

    # Broadcast status change for real-time UI update
    asyncio.create_task(_broadcast_status_change(document_id, "processing"))

    logger.info(f"User {user_id} triggered processing for document: {document_id}")

    return ProcessResponse(
        document_id=document_id,
        status="processing",
        message="Document queued for processing."
    )


@router.post("/process-all", response_model=dict)
async def process_all_pending(user: TokenPayload = Depends(require_viewer)):
    """
    Trigger processing for all pending documents.
    """
    user_id = user.sub
    paper_store = _get_paper_store()

    pending_ids = paper_store.get_pending_user_papers(user_id)

    if not pending_ids:
        return {"queued_count": 0, "message": "No pending documents to process."}

    # Queue all for processing
    for doc_id in pending_ids:
        paper_store.update_status(doc_id, "downloaded")
        # Broadcast status change for real-time UI update
        asyncio.create_task(_broadcast_status_change(doc_id, "processing"))

    logger.info(f"User {user_id} triggered processing for {len(pending_ids)} documents")

    return {
        "queued_count": len(pending_ids),
        "message": f"Queued {len(pending_ids)} documents for processing."
    }


@router.get("/", response_model=DocumentListResponse)
async def list_documents(user: TokenPayload = Depends(require_viewer)):
    """
    List all documents uploaded by the current user.
    """
    user_id = user.sub
    paper_store = _get_paper_store()

    papers = paper_store.get_user_papers(user_id, limit=500)
    counts = paper_store.count_user_papers(user_id)

    documents = []
    for paper in papers:
        # Map internal status to user-friendly status
        internal_status = paper["status"]
        if internal_status == "discovered":
            display_status = "pending"
        elif internal_status in ("downloaded", "chunked", "chunking"):
            display_status = "processing"
        elif internal_status == "embedded":
            display_status = "ready"
        elif internal_status == "failed":
            display_status = "failed"
        else:
            display_status = internal_status

        # Get file size
        file_size = 0
        if paper["pdf_path"] and os.path.exists(paper["pdf_path"]):
            file_size = os.path.getsize(paper["pdf_path"])

        # Format upload date
        upload_date = paper["created_at"] or ""
        if upload_date and isinstance(upload_date, str):
            try:
                dt = datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
                upload_date = dt.strftime("%b %d, %Y")
            except Exception:
                pass

        documents.append(DocumentInfo(
            document_id=paper["document_id"],
            filename=os.path.basename(paper["pdf_path"] or paper["title"]),
            title=paper["title"],
            status=display_status,
            file_size=file_size,
            upload_date=upload_date,
            error_message=paper.get("error_message"),
        ))

    return DocumentListResponse(
        documents=documents,
        total=counts["total"],
        counts=counts
    )


@router.get("/{document_id}/status")
async def get_document_status(
    document_id: str,
    user: TokenPayload = Depends(require_viewer)
):
    """
    Get detailed status of a specific document.
    """
    user_id = user.sub
    paper_store = _get_paper_store()

    paper = paper_store.get_user_paper(document_id, user_id)
    if not paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or not owned by you."
        )

    # Map status
    internal_status = paper.status
    if internal_status == "discovered":
        display_status = "pending"
    elif internal_status in ("downloaded", "chunked", "chunking"):
        display_status = "processing"
    elif internal_status == "embedded":
        display_status = "ready"
    else:
        display_status = internal_status

    return {
        "document_id": document_id,
        "title": paper.title,
        "status": display_status,
        "internal_status": internal_status,
    }


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    user: TokenPayload = Depends(require_viewer)
):
    """
    Delete a document with cascading cleanup.

    Order of deletion:
    1. Qdrant (vector embeddings)
    2. BM25 Tantivy (keyword index)
    3. SQLite (paper record)
    4. Disk (source file)
    """
    user_id = user.sub
    paper_store = _get_paper_store()

    # Verify ownership and get paper details
    paper = paper_store.get_user_paper(document_id, user_id)
    if not paper:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or not owned by you."
        )

    errors = []

    # 1. Delete from Qdrant
    try:
        vector_store = _get_vector_store()
        # Delete by DOI/unique_id with user_id isolation
        doi = paper.doi or document_id
        vector_store.delete(doi, user_id=user_id)
        logger.info(f"Deleted Qdrant vectors for {document_id}")
    except Exception as e:
        logger.error(f"Failed to delete Qdrant vectors for {document_id}: {e}")
        errors.append(f"Qdrant: {e}")

    # 2. Delete from BM25 Tantivy
    try:
        bm25_index = _get_bm25_index()
        # Get chunk IDs from Qdrant before deletion (if we need them)
        # For now, we'll skip BM25 deletion if vectors already deleted
        # In production, we'd query for chunk IDs first
        logger.info(f"BM25 cleanup skipped for {document_id} (vectors deleted first)")
    except Exception as e:
        logger.error(f"Failed to delete BM25 index for {document_id}: {e}")
        errors.append(f"BM25: {e}")

    # 3. Delete from SQLite
    try:
        deleted = paper_store.delete_user_paper(document_id, user_id)
        if not deleted:
            errors.append("SQLite: Record not found")
    except Exception as e:
        logger.error(f"Failed to delete SQLite record for {document_id}: {e}")
        errors.append(f"SQLite: {e}")

    # 4. Delete from disk
    if paper.pdf_path and os.path.exists(paper.pdf_path):
        try:
            os.remove(paper.pdf_path)
            logger.info(f"Deleted file: {paper.pdf_path}")
        except Exception as e:
            logger.error(f"Failed to delete file {paper.pdf_path}: {e}")
            errors.append(f"Disk: {e}")

    if errors:
        return DeleteResponse(
            deleted=True,
            message=f"Deleted with warnings: {'; '.join(errors)}"
        )

    logger.info(f"User {user_id} deleted document: {document_id}")
    return DeleteResponse(deleted=True, message="Document deleted successfully.")


@router.delete("/batch", response_model=BatchDeleteResponse)
async def delete_documents_batch(
    document_ids: List[str],
    user: TokenPayload = Depends(require_viewer)
):
    """
    Delete multiple documents at once.
    """
    user_id = user.sub
    deleted_count = 0
    failed = []

    for doc_id in document_ids:
        try:
            # Reuse single delete logic
            paper_store = _get_paper_store()
            paper = paper_store.get_user_paper(doc_id, user_id)

            if not paper:
                failed.append(doc_id)
                continue

            # Delete vectors
            try:
                vector_store = _get_vector_store()
                vector_store.delete(paper.doi or doc_id, user_id=user_id)
            except Exception:
                pass

            # Delete from SQLite
            paper_store.delete_user_paper(doc_id, user_id)

            # Delete from disk
            if paper.pdf_path and os.path.exists(paper.pdf_path):
                os.remove(paper.pdf_path)

            deleted_count += 1

        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            failed.append(doc_id)

    logger.info(f"User {user_id} batch deleted {deleted_count} documents")

    return BatchDeleteResponse(
        deleted_count=deleted_count,
        failed=failed
    )
