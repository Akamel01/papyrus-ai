"""
Helper utilities for injecting complex UI components like streaming local video.
"""
import base64
import os
import streamlit as st

def get_base64_video(video_path: str) -> str | None:
    """Reads a local video file and returns its base64 string, or None if failed."""
    if not os.path.exists(video_path):
        return None
    try:
        with open(video_path, "rb") as video_file:
            video_bytes = video_file.read()
        return base64.b64encode(video_bytes).decode('utf-8')
    except Exception as e:
        print(f"Failed to read/encode video {video_path}: {e}")
        return None

def inject_animated_video(video_path: str, width: str = "100%", max_height: str = "auto", loop: bool = True) -> str:
    """
    Returns HTML for a transparent/clean WebM or MP4 looping video.
    Intended for seamless Streamlit injection via st.markdown(..., unsafe_allow_html=True)
    """
    b64_video = get_base64_video(video_path)
    if not b64_video:
        # Fallback empty div if video is missing
        return '<div style="display:none;">Video not found</div>'
    
    html_string = f'''
        <div style="display: flex; justify-content: center; align-items: center; width: 100%;">
            <video preload="auto" autoplay {"loop " if loop else ""}muted playsinline 
                   style="mix-blend-mode: screen; width: {width}; max-height: {max_height}; border-radius: 12px; pointer-events: none;">
                <source src="data:video/mp4;base64,{b64_video}" type="video/mp4">
                Your browser does not support the video tag.
            </video>
        </div>
    '''
    return html_string
