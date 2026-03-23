"""
Quick Upload Component for Chat UI.

Allows users to upload temporary documents (PDF, MD, TXT, DOCX) that are:
- Stored in session state only (cleared on page refresh)
- Immediately available for use in chat responses
- Not embedded or indexed (direct text extraction)

Limits:
- 10MB max per file
- 3 files max per session
"""

import logging
import time
from typing import Optional

import streamlit as st

from app.components.theme import GOLD, TEXT_GREY, MUTED_TEXT

logger = logging.getLogger(__name__)

# Configuration
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 3
ALLOWED_EXTENSIONS = [".pdf", ".md", ".txt", ".docx"]


def extract_text_from_file(uploaded_file) -> Optional[str]:
    """
    Extract text content from an uploaded file.

    Args:
        uploaded_file: Streamlit UploadedFile object

    Returns:
        Extracted text content, or None if extraction fails
    """
    filename = uploaded_file.name.lower()

    try:
        if filename.endswith(".pdf"):
            return _extract_text_from_pdf(uploaded_file)
        elif filename.endswith(".md") or filename.endswith(".txt"):
            return uploaded_file.read().decode("utf-8")
        elif filename.endswith(".docx"):
            return _extract_text_from_docx(uploaded_file)
        else:
            logger.warning(f"Unsupported file type: {filename}")
            return None
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}")
        return None


def _extract_text_from_pdf(uploaded_file) -> Optional[str]:
    """Extract text from PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF

        # Read file bytes and open with fitz
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        text_parts = []
        for page_num, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                text_parts.append(f"--- Page {page_num + 1} ---\n{text}")

        doc.close()
        return "\n\n".join(text_parts) if text_parts else None

    except ImportError:
        logger.error("PyMuPDF (fitz) not installed. Cannot extract PDF text.")
        return None
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return None


def _extract_text_from_docx(uploaded_file) -> Optional[str]:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document

        doc = Document(uploaded_file)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs) if paragraphs else None

    except ImportError:
        logger.error("python-docx not installed. Cannot extract DOCX text.")
        return None
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        return None


def render_quick_upload():
    """
    Render the Quick Upload component in the sidebar.

    Displays:
    - File uploader (if under max files)
    - List of uploaded files with remove buttons
    - Usage hints
    """
    # Initialize quick_uploads in session state if not present
    if "quick_uploads" not in st.session_state:
        st.session_state.quick_uploads = []

    current_count = len(st.session_state.quick_uploads)

    # Header
    st.markdown(f'''
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="color: {TEXT_GREY}; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">
            QUICK UPLOAD
        </span>
        <span style="color: {MUTED_TEXT}; font-size: 11px;">
            {current_count}/{MAX_FILES}
        </span>
    </div>
    ''', unsafe_allow_html=True)

    # File uploader (only show if under max)
    if current_count < MAX_FILES:
        uploaded_file = st.file_uploader(
            "Drop file here",
            type=["pdf", "md", "txt", "docx"],
            key=f"quick_upload_widget_{time.time()}",  # Unique key to reset after upload
            label_visibility="collapsed",
            help=f"PDF, MD, TXT, DOCX (max {MAX_FILE_SIZE_MB}MB)"
        )

        if uploaded_file is not None:
            # Check file size
            if uploaded_file.size > MAX_FILE_SIZE_BYTES:
                st.error(f"File too large. Max size is {MAX_FILE_SIZE_MB}MB.")
            else:
                # Check if already uploaded (by name)
                existing_names = [f["filename"] for f in st.session_state.quick_uploads]
                if uploaded_file.name in existing_names:
                    st.warning(f"'{uploaded_file.name}' already uploaded.")
                else:
                    # Extract text
                    with st.spinner("Extracting text..."):
                        content = extract_text_from_file(uploaded_file)

                    if content:
                        st.session_state.quick_uploads.append({
                            "filename": uploaded_file.name,
                            "content": content,
                            "uploaded_at": time.time(),
                            "file_size": uploaded_file.size
                        })
                        st.success(f"Added '{uploaded_file.name}'")
                        st.rerun()
                    else:
                        st.error(f"Could not extract text from '{uploaded_file.name}'")
    else:
        st.caption(f"Max {MAX_FILES} files reached. Remove one to add more.")

    # Display uploaded files
    if st.session_state.quick_uploads:
        st.markdown(f'<div style="margin-top: 8px;"></div>', unsafe_allow_html=True)

        for i, doc in enumerate(st.session_state.quick_uploads):
            col1, col2 = st.columns([4, 1])
            with col1:
                # Truncate filename if too long
                display_name = doc["filename"]
                if len(display_name) > 20:
                    display_name = display_name[:17] + "..."

                # File size display
                size_kb = doc["file_size"] / 1024
                size_str = f"{size_kb:.0f}KB" if size_kb < 1024 else f"{size_kb/1024:.1f}MB"

                st.markdown(f'''
                <div style="font-size: 12px; color: {TEXT_GREY};" title="{doc["filename"]}">
                    {display_name}
                    <span style="color: {MUTED_TEXT}; font-size: 10px;">({size_str})</span>
                </div>
                ''', unsafe_allow_html=True)

            with col2:
                if st.button("X", key=f"remove_quick_{i}", help="Remove file"):
                    st.session_state.quick_uploads.pop(i)
                    st.rerun()

        # Clear all button
        if len(st.session_state.quick_uploads) > 1:
            if st.button("Clear All", key="clear_all_quick_uploads", use_container_width=True):
                st.session_state.quick_uploads = []
                st.rerun()

    # Usage hint
    st.markdown(f'''
    <div style="font-size: 10px; color: {MUTED_TEXT}; margin-top: 8px; line-height: 1.4;">
        Session-only. Cleared on refresh.
    </div>
    ''', unsafe_allow_html=True)


def get_quick_upload_context() -> Optional[str]:
    """
    Get the combined text content from all quick uploads.

    Returns:
        Combined text with source markers, or None if no uploads
    """
    if not st.session_state.get("quick_uploads"):
        return None

    context_parts = []
    for doc in st.session_state.quick_uploads:
        # Limit content to prevent context overflow (5000 chars per doc)
        content = doc["content"][:5000]
        if len(doc["content"]) > 5000:
            content += "\n[... content truncated ...]"

        context_parts.append(
            f"[Quick Upload: {doc['filename']}]\n{content}"
        )

    return "\n\n---\n\n".join(context_parts)
