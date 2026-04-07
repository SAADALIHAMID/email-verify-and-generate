"""
PROFESSIONAL Email Verification Platform
- Advanced Batch Processing
- Concurrent Verification (360K emails/day)
- Multi-threaded Architecture
- Memory Optimized
- Enterprise Grade
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import asyncio
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from queue import Queue
import gc
from openpyxl import Workbook
import os
import shutil

# Import professional dashboard utilities
from app.improved_dashboard import (
    format_time,
    format_duration_short
)

# Setup logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure Streamlit for max performance
st.set_option('client.toolbarMode', 'minimal')
st.set_option('client.showErrorDetails', False)

# ===== CUSTOM TQDM-STYLE PROGRESS BAR FOR STREAMLIT =====
def display_progress_bar_tqdm_style(current: int, total: int, file_name: str = "", elapsed: float = 0, speed: float = 0):
    """
    Display a tqdm-style progress bar in Streamlit
    Format: |████████░░░░░░░░| 12/100 [00:45<02:15, 3.50it/s]
    """
    if total == 0:
        return
    
    percentage = min(100, int((current / total) * 100))
    bar_length = 30
    filled = int((percentage / 100) * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    # Format elapsed time
    if elapsed > 0:
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins:02d}:{secs:02d}"
    else:
        elapsed_str = "00:00"
    
    # Calculate remaining time
    if speed > 0 and current > 0:
        remaining = (total - current) / speed
        r_mins, r_secs = divmod(int(remaining), 60)
        remaining_str = f"{r_mins:02d}:{r_secs:02d}"
    else:
        remaining_str = "--:--"
    
    # Format speed
    if speed > 0:
        speed_str = f"{speed:.2f}it/s"
    else:
        speed_str = "0.00it/s"
    
    # Create the tqdm-style string
    file_name_short = file_name[:25] + "..." if len(file_name) > 25 else file_name
    progress_str = f"|{bar}| {current}/{total} [{elapsed_str}<{remaining_str}, {speed_str}]"
    
    return progress_str

# ===== CUSTOM HTML PROGRESS BAR =====
def create_html_progress_bar(percentage: float, width: int = 300):
    """Create a custom HTML progress bar"""
    filled = int((percentage / 100) * width)
    bar_html = f"""
    <div style="background-color: #e0e0e0; border-radius: 4px; height: 20px; width: {width}px; overflow: hidden;">
        <div style="background-color: #4CAF50; height: 100%; width: {percentage}%; text-align: center; color: white; line-height: 20px; font-weight: bold;">
            {percentage:.0f}%
        </div>
    </div>
    """
    return bar_html


# MODULE-LEVEL QUEUE SYSTEM (not tied to session state, works in background threads)
_file_queue = []  # List of (file_obj, file_idx) tuples
_file_queue_lock = threading.Lock()
_file_queue_results = {}  # Completed file results
_file_queue_active = False  # Whether processor is running
_file_queue_paused = False  # Whether processor is paused
_file_queue_processing = None  # Current file being processed
_file_queue_progress = {}  # Track per-file progress: {file_key: {'current': x, 'total': y, 'start_time': t}}
_file_queue_thread = None  # Background thread
_queue_start_time = None  # When queue processing started
_domain_mx_cache = {}
_domain_mx_lock = threading.Lock()
_file_queue_stats = {  # Overall queue statistics
    'total_files': 0,
    'completed_files': 0,
    'files_in_queue': 0,
    'total_emails': 0,
    'processed_emails': 0,
    'total_duration': 0.0
}

# Import verification - Use enhanced version with proper SMTP handling
try:
    from app.email_verification_enhanced import (
        verify_email_enhanced as verify_email_improved,
        batch_smtp_verify,
        get_mx_records_reliable
    )
except ImportError:
    from app.improved_verification_system import verify_email_improved
    batch_smtp_verify = None
    get_mx_records_reliable = None

# Page configuration - Professional
st.set_page_config(
    page_title="Email Verification Platform - Professional",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS - Professional
st.markdown("""
<style>
    .metric-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 0.75rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin: 0.5rem 0;
    }
    .success-box {
        background-color: #d4edda;
        border-left: 5px solid #28a745;
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .error-box {
        background-color: #f8d7da;
        border-left: 5px solid #dc3545;
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Session state initialization
if 'verification_stats' not in st.session_state:
    st.session_state.verification_stats = {
        'total_processed': 0,
        'valid_count': 0,
        'invalid_count': 0,
        'processing_time': 0
    }
if 'stats' not in st.session_state:
    st.session_state.stats = {
        'total': 0,
        'valid': 0,
        'invalid': 0
    }
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []
if 'processing_queue' not in st.session_state:
    st.session_state.processing_queue = Queue()
if 'files_queue' not in st.session_state:
    st.session_state.files_queue = []
if 'verification_history' not in st.session_state:
    st.session_state.verification_history = []
if 'batch_processor_queue' not in st.session_state:
    st.session_state.batch_processor_queue = []
if 'batch_processor_status' not in st.session_state:
    st.session_state.batch_processor_status = {}
if 'batch_processor_results' not in st.session_state:
    st.session_state.batch_processor_results = {}
if 'confirm_clear_queue' not in st.session_state:
    st.session_state.confirm_clear_queue = False
if 'app_initialized' not in st.session_state:
    st.session_state.app_initialized = False
if 'startup_message_shown' not in st.session_state:
    st.session_state.startup_message_shown = False


async def verify_email_async(email: str) -> Dict:
    """Verify email with optimized timeout."""
    try:
        result = await asyncio.wait_for(
            verify_email_improved(email, timeout=30),
            timeout=40
        )
        return result
    except asyncio.TimeoutError:
        return {
            'email': email,
            'valid': False,
            'reason': 'TIMEOUT',
            'duration_ms': 40000,
            'has_mx': False
        }
    except Exception as e:
        logger.error(f"Verification error: {email}")
        return {
            'email': email,
            'valid': False,
            'reason': 'ERROR',
            'duration_ms': 0,
            'has_mx': False
        }


def verify_single(email: str) -> Dict:
    """Synchronous wrapper with optimized async handling."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(verify_email_async(email))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Verification failed: {email}")
        return {
            'email': email,
            'valid': False,
            'reason': 'ERROR',
            'duration_ms': 0,
            'has_mx': False
        }


def process_emails_concurrent(emails: List[str], max_workers: int = 10) -> List[Dict]:
    """Process emails concurrently using ThreadPoolExecutor for maximum speed."""
    results = []
    progress_placeholder = st.empty()
    progress_bar = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(verify_single, email): email for email in emails}
        
        completed = 0
        total = len(emails)
        
        for future in as_completed(futures):
            try:
                result = future.result(timeout=50)
                results.append(result)
            except Exception as e:
                email = futures[future]
                logger.error(f"Task error: {email}")
                results.append({
                    'email': email,
                    'valid': False,
                    'reason': 'TASK_ERROR',
                    'duration_ms': 0,
                    'has_mx': False
                })
            
            completed += 1
            progress = completed / total
            progress_bar.progress(min(progress, 0.99))
            progress_placeholder.metric(
                "Processing Speed",
                f"{completed}/{total} ({(completed/total*100):.0f}%) | "
                f"{completed/(time.time() - getattr(process_emails_concurrent, 'start_time', time.time())):.1f} emails/sec"
            )
    
    progress_bar.progress(1.0)
    progress_placeholder.empty()
    return results


async def process_emails_async_batch(emails: List[str], batch_size: int = 15) -> List[Dict]:
    """Process emails asynchronously in batches for optimal performance."""
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i+batch_size]
        
        # Create tasks for concurrent processing
        tasks = [verify_email_async(email) for email in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for email, result in zip(batch, batch_results):
            if isinstance(result, Exception):
                results.append({
                    'email': email,
                    'valid': False,
                    'reason': 'ASYNC_ERROR',
                    'duration_ms': 0,
                    'has_mx': False
                })
            else:
                results.append(result)
        
        progress = (i + len(batch)) / len(emails)
        progress_bar.progress(min(progress, 0.99))
        status_text.metric("Processed", f"{min(i + len(batch), len(emails))}/{len(emails)}")
    
    progress_bar.progress(1.0)
    status_text.empty()
    return results


async def verify_batch_async(emails: List[str]) -> List[Dict]:
    """Verify multiple emails with concurrent processing for speed."""
    results = []
    batch_size = 10  # Process 10 emails concurrently
    
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i+batch_size]
        
        # Run multiple verifications concurrently
        try:
            batch_tasks = [verify_email_improved(email, timeout=30) for email in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            for email, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        'email': email,
                        'valid': False,
                        'reason': f'Error: {str(result)}',
                        'duration_ms': 0
                    })
                else:
                    results.append(result)
            
            logger.info(f"Processed batch: {min(i+batch_size, len(emails))}/{len(emails)}")
            
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            for email in batch:
                results.append({
                    'email': email,
                    'valid': False,
                    'reason': f'Error: {str(e)}',
                    'duration_ms': 0
                })
    
    return results


def verify_batch(emails: List[str]) -> List[Dict]:
    """Synchronous wrapper for batch verification."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(verify_batch_async(emails))
        return results
    except Exception as e:
        logger.error(f"Batch verification error: {e}")
        return []


def display_single_result(result: Dict):
    """Display single verification result."""
    if not result:
        return
    
    is_valid = result.get('valid', False)
    card_class = "email-valid" if is_valid else "email-invalid"
    icon = "✅" if is_valid else "❌"
    status_text = "VALID" if is_valid else "INVALID"
    
    st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([3, 2, 2])
    
    with col1:
        st.markdown(f"### {icon} {status_text}")
        st.markdown(f"**Email:** `{result['email']}`")
        st.markdown(f"**Reason:** {result.get('reason', 'N/A')}")
    
    with col2:
        st.markdown("**Verification Details:**")
        if result.get('has_mx'):
            st.markdown("✅ MX Records Found")
        else:
            st.markdown("❌ No MX Records")
        
        if result.get('smtp_accepted'):
            st.markdown("✅ SMTP Accepted")
        elif result.get('smtp_rejected'):
            st.markdown("❌ SMTP Rejected")
        elif result.get('smtp_timeout'):
            st.markdown("⏱️  SMTP Timeout")
    
    with col3:
        st.markdown("**Performance:**")
        duration = result.get('duration_ms', 0)
        st.metric("Duration", f"{duration}ms")
        
        if result.get('mx_records'):
            st.markdown(f"**MX Records:** {len(result['mx_records'])}")
    
    if result.get('steps'):
        with st.expander("📋 Verification Steps"):
            for step in result['steps']:
                st.text(step)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Update statistics
    st.session_state.stats['total'] += 1
    if is_valid:
        st.session_state.stats['valid'] += 1
    else:
        st.session_state.stats['invalid'] += 1


def display_batch_results(results: List[Dict]):
    """Display batch verification results with analytics."""
    if not results:
        st.warning("No results to display")
        return
    
    st.session_state.batch_results = results
    
    # Metrics
    total = len(results)
    valid = sum(1 for r in results if r.get('valid', False))
    invalid = total - valid
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📧 Total", total)
    with col2:
        valid_pct = (valid / total * 100) if total > 0 else 0
        st.metric("✅ Valid", valid, f"{valid_pct:.1f}%")
    with col3:
        invalid_pct = (invalid / total * 100) if total > 0 else 0
        st.metric("❌ Invalid", invalid, f"{invalid_pct:.1f}%")
    with col4:
        avg_duration = sum(r.get('duration_ms', 0) for r in results) / total if total > 0 else 0
        st.metric("⏱️  Avg Time", f"{avg_duration:.0f}ms")
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.pie(
            values=[valid, invalid],
            names=['Valid', 'Invalid'],
            title="Status Distribution",
            color_discrete_sequence=['#28a745', '#dc3545'],
            hole=0.3
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Reasons distribution
        reasons_count = {}
        for r in results:
            reason = r.get('reason', 'Unknown')[:30]
            reasons_count[reason] = reasons_count.get(reason, 0) + 1
        
        fig = px.bar(
            x=list(reasons_count.keys())[:10],
            y=list(reasons_count.values())[:10],
            title="Top 10 Rejection Reasons",
            labels={'x': 'Reason', 'y': 'Count'},
            color_discrete_sequence=['#ffc107']
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Detailed results table
    st.markdown("### 📋 Detailed Results")
    
    df_results = []
    for r in results:
        # Check for risky reason
        reason = r.get('reason', 'N/A')
        is_risky = 'catch-all' in reason.lower() or 'accepts all' in reason.lower()
        
        status = '❌ INVALID (RISKY)' if is_risky else ('✅ VALID' if r['valid'] else '❌ INVALID')
        display_reason = 'RISKY - Catch-all' if is_risky else reason[:50]
        
        df_results.append({
            'Email': r['email'],
            'Status': status,
            'MX': '✅' if r.get('has_mx') else '❌',
            'SMTP': ('✅' if r.get('smtp_accepted') else '❌ Rejected' if r.get('smtp_rejected') else '⏱️  Timeout' if r.get('smtp_timeout') else '⚠️'),
            'Reason': display_reason,
            'Time (ms)': r.get('duration_ms', 0)
        })
    
    df = pd.DataFrame(df_results)
    st.dataframe(df, use_container_width=True, height=400)
    
    # Download options
    st.markdown("### 💾 Download Results")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📄 Download All Results (CSV)",
            csv,
            f"results_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv"
        )
    
    with col2:
        valid_results = [r['Email'] for r in df_results if r['Status'].startswith('✅')]
        if valid_results:
            valid_text = "\n".join(valid_results)
            st.download_button(
                "✅ Valid Emails Only",
                valid_text,
                f"valid_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                "text/plain"
            )
    
    with col3:
        invalid_results = [r['Email'] for r in df_results if r['Status'].startswith('❌')]
        if invalid_results:
            invalid_text = "\n".join(invalid_results)
            st.download_button(
                "❌ Invalid Emails Only",
                invalid_text,
                f"invalid_emails_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                "text/plain"
            )


def extract_emails_from_file(uploaded_file) -> List[str]:
    """Extract emails from file with multi-encoding support and memory optimization."""
    emails = []
    
    try:
        max_size = 150 * 1024 * 1024  # 150MB limit
        file_size = len(uploaded_file.getvalue()) if hasattr(uploaded_file, 'getvalue') else 0
        
        if file_size > max_size:
            st.error(f"File too large ({file_size/1024/1024:.1f}MB). Maximum: 150MB")
            return []
        
        file_ext = uploaded_file.name.split('.')[-1].lower()
        
        if file_ext == 'csv':
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'gb2312', 'gbk']
            df = None
            
            for encoding in encodings:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=encoding, on_bad_lines='skip', engine='python')
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            if df is None:
                st.error("Failed to read CSV file")
                return []
            
            col_name = None
            for col in ['email', 'Email', 'EMAIL', 'e-mail', 'E-mail', 'mail', 'Mail']:
                if col in df.columns:
                    col_name = col
                    break
            
            if col_name is None and len(df.columns) > 0:
                col_name = df.columns[0]
            
            if col_name:
                emails = df[col_name].dropna().astype(str).str.strip().tolist()
        
        elif file_ext in ['xlsx', 'xls']:
            try:
                df = pd.read_excel(uploaded_file, engine='openpyxl' if file_ext == 'xlsx' else 'xlrd')
                col_name = None
                for col in ['email', 'Email', 'EMAIL', 'e-mail', 'E-mail', 'mail', 'Mail']:
                    if col in df.columns:
                        col_name = col
                        break
                
                if col_name is None and len(df.columns) > 0:
                    col_name = df.columns[0]
                
                if col_name:
                    emails = df[col_name].dropna().astype(str).str.strip().tolist()
            except Exception as e:
                st.error(f"Failed to read Excel file: {str(e)[:100]}")
                return []
        
        else:
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252']
            content = None
            
            for encoding in encodings:
                try:
                    uploaded_file.seek(0)
                    content = uploaded_file.read().decode(encoding)
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            if content is None:
                st.error("Failed to read text file")
                return []
            
            emails = [e.strip() for e in content.split('\n') if e.strip()]
        
        # Validate and deduplicate
        emails = list(set([e for e in emails if '@' in e and len(e) > 3 and '.' in e.split('@')[-1]]))
        
        if len(emails) > 10000:
            st.warning(f"Found {len(emails)} emails. Processing first 10,000 for optimal speed.")
            emails = emails[:10000]
        
        if not emails:
            st.warning("No valid emails found")
        else:
            st.success(f"Loaded {len(emails)} unique valid emails")
        
        return emails
    
    except Exception as e:
        logger.error(f"Error extracting emails: {e}")
        st.error(f"File processing error: {str(e)[:100]}")
        return []


def save_results_to_file(file_name_base: str, df_results: pd.DataFrame, results: List[Dict]) -> Dict:
    """Save results automatically to outputs folder with input file name"""
    try:
        # Create outputs folder if not exists - FULL PATH
        output_dir = Path("D:/email verify/data/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get base name without extension
        base_name = file_name_base.rsplit('.', 1)[0] if '.' in file_name_base else file_name_base
        
        saved_files = {}
        
        # Save 1: CSV with all results
        csv_file = output_dir / f"{base_name}_verified.csv"
        df_results.to_csv(csv_file, index=False, encoding='utf-8')
        saved_files['csv'] = str(csv_file)
        
        # Save 2: TXT with valid emails only
        valid_emails = [r['Email'] for r in df_results.to_dict('records') if r['Status'].startswith('✅')]
        if valid_emails:
            valid_file = output_dir / f"{base_name}_valid.txt"
            with open(valid_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(valid_emails))
            saved_files['valid'] = str(valid_file)
        
        # Save 3: TXT with invalid emails only
        invalid_emails = [r['Email'] for r in df_results.to_dict('records') if r['Status'].startswith('❌')]
        if invalid_emails:
            invalid_file = output_dir / f"{base_name}_invalid.txt"
            with open(invalid_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(invalid_emails))
            saved_files['invalid'] = str(invalid_file)
        
        # Save 4: Excel with formatted results
        try:
            excel_file = output_dir / f"{base_name}_verified.xlsx"
            df_results.to_excel(excel_file, index=False, engine='openpyxl')
            saved_files['excel'] = str(excel_file)
        except:
            pass
        
        return saved_files
    
    except Exception as e:
        logger.error(f"Error saving results: {e}")
        return {}


def format_duration(seconds: float) -> str:
    """Format duration as HH:MM:SS or MM:SS"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"

def format_duration_short(seconds):
    """Format duration in short form: 1h 23m 45s"""
    return format_duration(seconds)


def process_single_file_for_queue(uploaded_file, file_idx: int) -> Dict:
    """Process a single file with detailed progress tracking"""
    global _file_queue_progress, _file_queue_stats, _file_queue_paused
    
    file_name = uploaded_file.name
    file_key = f"{file_name}_{file_idx}"
    
    print(f"\n{'='*70}")
    print(f"📋 FILE PROCESSOR STARTED")
    print(f"{'='*70}")
    print(f"📂 File Name: {file_name}")
    print(f"📍 File Index: {file_idx}")
    print(f"🕐 Started At: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*70}\n")
    
    try:
        # Get file size
        try:
            file_size_kb = len(uploaded_file.getvalue()) / 1024
        except:
            file_size_kb = 0
        
        # Extract emails
        print(f"[STEP 1] 📧 Extracting emails from {file_name}...")
        emails = extract_emails_from_file(uploaded_file)
        print(f"[STEP 1] ✅ SUCCESS: Found {len(emails)} emails\n")
        
        if not emails:
            print(f"[ERROR] ⚠️  No emails found in {file_name}\n")
            return {
                'file_key': file_key,
                'file_name': file_name,
                'status': 'failed',
                'emails_count': 0,
                'valid_count': 0,
                'invalid_count': 0,
                'risky_count': 0,
                'duration': 0,
                'speed': 0,
                'file_size_kb': file_size_kb,
                'results': [],
                'df_export': pd.DataFrame(),
                'saved_files': {}
            }
        
        # Initialize progress tracking
        print(f"[STEP 2] 🔒 Initializing progress tracking...")
        with _file_queue_lock:
            _file_queue_progress[file_key] = {
                'status': 'processing',
                'current': 0,
                'total': len(emails),
                'start_time': time.time(),
                'elapsed': 0,
                'valid': 0,
                'invalid': 0,
                'risky': 0,
                'speed': 0,
                'file_name': file_name,
                'file_size_kb': file_size_kb
            }
            _file_queue_stats['total_emails'] += len(emails)
        print(f"[STEP 2] ✅ Progress tracking initialized\n")
        
        # Verify all emails with progress tracking
        results = []
        start_time = time.time()
        
        print(f"[STEP 3] 🔍 STARTING EMAIL VERIFICATION")
        print(f"         Total emails to verify: {len(emails)}")
        print(f"         Workers: 10 threads")
        print(f"         Timeout: 50 seconds per email\n")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(verify_single, email): email for email in emails}
            
            completed = 0
            total = len(emails)
            
            for future in as_completed(futures):
                # Handle pause
                while _file_queue_paused:
                    time.sleep(0.2)
                
                try:
                    result = future.result(timeout=50)
                    results.append(result)
                    completed += 1
                    
                    reason = result.get('reason', 'N/A').lower()
                    is_risky = 'catch-all' in reason or 'accepts all' in reason
                    
                    # Update progress dict and stats (THREAD-SAFE)
                    with _file_queue_lock:
                        if file_key in _file_queue_progress:
                            prog = _file_queue_progress[file_key]
                            prog['current'] = completed
                            elapsed = time.time() - prog['start_time']
                            prog['elapsed'] = elapsed
                            prog['speed'] = completed / elapsed if elapsed > 0 else 0
                            prog['status'] = 'processing'
                            
                            if result['valid']:
                                if is_risky:
                                    prog['risky'] += 1
                                else:
                                    prog['valid'] += 1
                            else:
                                prog['invalid'] += 1
                        
                        _file_queue_stats['processed_emails'] += 1
                    
                except Exception as e:
                    email = futures[future]
                    logger.error(f"Task error: {email}")
                    results.append({
                        'email': email,
                        'valid': False,
                        'reason': 'ERROR',
                        'duration_ms': 0,
                        'has_mx': False
                    })
                    completed += 1
                    with _file_queue_lock:
                        _file_queue_stats['processed_emails'] += 1
        
        duration = time.time() - start_time
        speed = len(results) / duration if duration > 0 else 0
        
        print(f"\n[STEP 3] ✅ VERIFICATION COMPLETED\n")
        
        # Prepare dataframe with catch-all detection
        print(f"[STEP 4] 📊 Analyzing results...")
        df_results_list = []
        valid_count = 0
        risky_count = 0
        
        for r in results:
            reason = r.get('reason', 'N/A')
            is_risky = 'catch-all' in reason.lower() or 'accepts all' in reason.lower()
            
            if r['valid']:
                if is_risky:
                    status = '⚠️ RISKY'
                    risky_count += 1
                else:
                    status = '✅ VALID'
                    valid_count += 1
            else:
                status = '❌ INVALID'
            
            display_reason = 'Catch-all' if is_risky else reason[:40]
            
            df_results_list.append({
                'Email': r['email'],
                'Status': status,
                'MX': '✅' if r.get('has_mx') else '❌',
                'Reason': display_reason,
                'Time (ms)': r.get('duration_ms', 0)
            })
        
        df_export = pd.DataFrame(df_results_list)
        print(f"[STEP 4] ✅ Results analyzed\n")
        
        # Auto-save
        print(f"[STEP 5] 💾 Saving results to file...")
        file_name_base = file_name.rsplit('.', 1)[0]
        saved_files = save_results_to_file(file_name_base, df_export, results)
        print(f"[STEP 5] ✅ Results saved: {len(saved_files)} files\n")
        
        # Calculate invalid count
        invalid_count = len(results) - valid_count - risky_count
        
        # Print final results
        mins_total, secs_total = divmod(int(duration), 60)
        print(f"{'='*70}")
        print(f"✅ FILE PROCESSING COMPLETE: {file_name}")
        print(f"{'='*70}")
        print(f"📊 Results: {valid_count} Valid | {invalid_count} Invalid | {risky_count} Risky")
        print(f"⏱️ Duration: {mins_total}m {secs_total}s | Speed: {speed:.2f}/s")
        print(f"{'='*70}\n")
        
        # Mark as completed and update stats
        with _file_queue_lock:
            if file_key in _file_queue_progress:
                _file_queue_progress[file_key]['status'] = 'completed'
                _file_queue_progress[file_key]['duration'] = duration
                _file_queue_progress[file_key]['speed'] = speed
            _file_queue_stats['completed_files'] += 1
            _file_queue_stats['total_duration'] += float(duration)
        
        return {
            'file_key': file_key,
            'file_name': file_name,
            'status': 'completed',
            'emails_count': len(results),
            'valid_count': valid_count,
            'invalid_count': len(results) - valid_count - risky_count,
            'risky_count': risky_count,
            'duration': duration,
            'speed': speed,
            'file_size_kb': file_size_kb,
            'results': results,
            'df_export': df_export,
            'saved_files': saved_files
        }
    
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"\n{'='*70}")
        print(f"❌ FILE PROCESSING ERROR")
        print(f"{'='*70}")
        print(f"📂 File: {file_name}")
        print(f"❌ Error Details:")
        print(error_msg)
        print(f"{'='*70}\n")
        logger.error(f"Error processing file {file_name}: {e}")
        with _file_queue_lock:
            if file_key in _file_queue_progress:
                _file_queue_progress[file_key]['status'] = 'error'
        
        return {
            'file_key': file_key,
            'file_name': file_name,
            'status': 'error',
            'emails_count': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'risky_count': 0,
            'duration': 0,
            'speed': 0,
            'file_size_kb': 0,
            'results': [],
            'df_export': pd.DataFrame(),
            'saved_files': {}
        }


def run_file_queue_processor():
    """Background processor that continuously processes queued files sequentially"""
    global _file_queue_active, _file_queue_paused, _file_queue_processing, _file_queue_results, _queue_start_time, _file_queue_stats
    
    print("\n" + "="*70)
    print("🚀 QUEUE PROCESSOR STARTED")
    print("="*70)
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 Mode: Sequential Processing (One file at a time)")
    print("="*70 + "\n")
    
    # Mark queue start time
    _queue_start_time = time.time()
    empty_queue_count = 0
    MAX_EMPTY_CHECKS = 20  # Wait ~10 seconds before auto-stopping (20 * 0.5s)
    
    while _file_queue_active:
        # Check if paused
        if _file_queue_paused:
            print("⏸️  [PROCESSOR] Queue PAUSED - waiting for resume...")
            time.sleep(0.5)
            continue
        
        # Get next file from queue
        with _file_queue_lock:
            if not _file_queue:
                # Queue is empty - wait for new files, don't stop immediately
                empty_queue_count += 1
                if empty_queue_count >= MAX_EMPTY_CHECKS:
                    print("\n✅ [PROCESSOR] Queue has been empty for 10 seconds")
                    print("🛑 [PROCESSOR] Stopping processor...")
                    _file_queue_active = False
                    break
                else:
                    elapsed = empty_queue_count * 0.5
                    remaining_time = (MAX_EMPTY_CHECKS - empty_queue_count) * 0.5
                    
                    if empty_queue_count % 4 == 1:  # Print every 2 seconds
                        print(f"⏳ [PROCESSOR] Waiting for files... ({elapsed:.1f}s / auto-stop in {remaining_time:.1f}s)")
                
                time.sleep(0.5)
                continue
            
            # Files available - reset empty counter
            empty_queue_count = 0
            
            file_obj, file_idx = _file_queue.pop(0)
            _file_queue_stats['files_in_queue'] = len(_file_queue)
            _file_queue_processing = (file_obj.name, file_idx)
        
        # Process the file
        print(f"\n📂 [PROCESSOR] Processing: {file_obj.name}")
        print(f"   Queue remaining: {len(_file_queue)} files")
        
        result = process_single_file_for_queue(file_obj, file_idx)
        
        # Store result and update progress
        with _file_queue_lock:
            _file_queue_results[result['file_key']] = result
            _file_queue_processing = None
            # Update stats - only update completed files count
            _file_queue_stats['completed_files'] = len([r for r in _file_queue_results.values() if r.get('status') == 'completed'])
            # DON'T recalculate processed_emails here - it's updated during file processing
        
        print(f"✅ [PROCESSOR] File completed: {result['file_name']}")
        print(f"   Stats: {result['emails_count']} emails | {result['valid_count']} valid | {result['risky_count']} risky\n")
        
        time.sleep(0.2)  # Small delay to allow UI updates
    
    # Mark as complete
    print("\n" + "="*70)
    print("🛑 QUEUE PROCESSOR STOPPED")
    print("="*70)
    print(f"⏰ End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Final Stats:")
    
    with _file_queue_lock:
        print(f"   • Files Processed: {_file_queue_stats['completed_files']}")
        print(f"   • Total Emails: {_file_queue_stats['processed_emails']}")
        print(f"   • Total Duration: {_file_queue_stats['total_duration']:.2f}s")
        if _file_queue_stats['processed_emails'] > 0 and _file_queue_stats['total_duration'] > 0:
            avg_speed = _file_queue_stats['processed_emails'] / _file_queue_stats['total_duration']
            print(f"   • Average Speed: {avg_speed:.2f} emails/sec")
    
    print("="*70 + "\n")
    
    with _file_queue_lock:
        _file_queue_active = False
        _file_queue_paused = False


def generate_email_patterns(first: str, last: str, domain: str) -> List[str]:
    """
    Generate professional email patterns strictly prioritizing the user's requested order.
    Definition: 'f' = first initial, 'l' = last initial.
    """
    # Clean inputs: remove spaces and convert to lowercase
    first = str(first).strip().lower().replace(" ", "")
    last = str(last).strip().lower().replace(" ", "")
    # Remove @ from domain if present
    domain = str(domain).strip().lower()
    if "@" in domain:
        domain = domain.split("@")[-1]
    
    if not first or not domain:
        return []
    
    # Initials
    f = first[0] if first else ""
    l = last[0] if last else ""
    
    # 1. User's Specific Priority List
    patterns = [
        f"{first}@{domain}",                   # first@domain
        f"{first}.{last}@{domain}",            # first.last@domain
        f"{f}{last}@{domain}",                 # f+last@domain
        f"{f}.{last}@{domain}",                # f.last@domain
        f"{first}{last}@{domain}",             # firstlast@domain
        f"{last}@{domain}",                    # last@domain
        f"{first}{l}@{domain}",                # first+l@domain (first name + last initial)
        f"{first}.{l}@{domain}",  
        f"{first}_{last}@{domain}",            # first_last (Underscore)
        f"{first}-{last}@{domain}",            # first-last (Hyphen)
        f"{f}{l}@{domain}",                    # fl (Initials only)
        f"{f}_{last}@{domain}",                # f_last
        f"{last}.{first}@{domain}",            # last.first
        f"{last}{first}@{domain}", 
    ]
    
    # 2 Corporate Variations
    patterns.extend([
        f"{first}.{last}@corp.{domain}",
        f"{first}{last}@corp.{domain}",
        f"{f}{last}@corp.{domain}",
    ])
    
    # Deduplicate while preserving the priority order
    unique_patterns = []
    seen = set()
    for p in patterns:
        if p and p not in seen:
            unique_patterns.append(p)
            seen.add(p)
    
    return unique_patterns


def initialize_startup_progress():
    """Show startup initialization progress."""
    startup_placeholder = st.empty()
    
    # Progress stages
    stages = [
        ("🔧 System Initialization", 0.1),
        ("📚 Loading Modules", 0.25),
        ("🔐 Configuring SMTP", 0.4),
        ("💾 Database Setup", 0.6),
        ("📊 Loading Dashboard", 0.8),
        ("✅ Ready for Verification!", 1.0)
    ]
    
    for stage_text, progress_val in stages:
        with startup_placeholder.container():
            st.info(stage_text)
            st.progress(progress_val)
        time.sleep(0.3)
    
    startup_placeholder.empty()
    return True


def main():
    """Main application - Direct start, no delays."""
    
    # Initialize on first load only
    if 'app_initialized' not in st.session_state:
        st.session_state.app_initialized = True  # Mark as initialized immediately
    
    # Header
    st.markdown('<h1 class="header">📧 Email Verifier - Batch Processing</h1>', unsafe_allow_html=True)
    st.markdown("**Upload CSV/Excel files → Process → View Results**")
    
    # Status indicator
    col_status = st.columns(1)[0]
    with col_status:
        st.markdown(f"🟢 **System Status:** Ready | {datetime.now().strftime('%H:%M:%S')}")
    
    st.markdown("---")
    
    # Sidebar
    with st.sidebar:
        st.title("⚙️ Dashboard & Settings")
        
        # Live status indicator
        st.markdown("### 📊 Live Status")
        col_s1, col_s2, col_s3 = st.columns(3)
        
        with col_s1:
            st.metric("Total Processed", st.session_state.stats['total'], delta=None)
        
        with col_s2:
            st.metric("✅ Valid", st.session_state.stats['valid'], delta=None)
        
        with col_s3:
            st.metric("❌ Invalid", st.session_state.stats['invalid'], delta=None)
        
        st.divider()
        
        # File queue info
        if st.session_state.files_queue:
            st.warning(f"📁 Files in queue: {len(st.session_state.files_queue)}")
        else:
            st.success("✅ Queue: Empty")
        
        st.divider()
        
        # System info
        st.markdown("### ℹ️ System Info")
        st.write(f"**Version:** 2.1 (Enhanced)")
        st.write(f"**Status:** 🟢 OK")
        st.write(f"**Time:** {datetime.now().strftime('%H:%M:%S')}")
    
    # Main tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔍 Single Verification",
        "📋 Bulk Verification",
        "📁 Batch Files",
        "📊 Analytics",
        "🔎 Email Finder"
    ])
    
    # ===== TAB 1: Single Verification =====
    with tab1:
        st.header("🔍 Single Email Verification")
        st.markdown("Verify a single email address with detailed diagnostics.")
        
        col1, col2 = st.columns([4, 1])
        
        with col1:
            email = st.text_input(
                "Enter email address:",
                placeholder="example@gmail.com",
                key="single_email"
            )
        
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            verify_btn = st.button("🚀 Verify", type="primary", use_container_width=True)
        
        if verify_btn and email:
            if '@' not in email:
                st.error("❌ Please enter a valid email address")
            else:
                with st.spinner("🔍 Verifying email..."):
                    result = verify_single(email.strip())
                    if result:
                        display_single_result(result)
                        st.session_state.verification_history.append(result)
    
    # ===== TAB 2: Bulk Verification =====
    with tab2:
        st.header("📋 Bulk Email Verification")
        st.markdown("Verify multiple emails at once using text input or file upload.")
        
        # Input method selector
        input_method = st.radio(
            "Choose input method:",
            ["📝 Text Input (Paste emails)", "📄 Upload File (CSV/Excel/TXT)"],
            horizontal=True 
        )
        
        emails = []
        
        if input_method == "📝 Text Input (Paste emails)":
            email_text = st.text_area(
                "Paste emails (one per line):",
                height=200,
                placeholder="john@example.com\nneha@gmail.com\nsaad@yahoo.com"
            )
            
            if email_text:
                emails = [
                    e.strip() for e in email_text.split('\n')
                    if e.strip() and '@' in e
                ]
        
        else:  # File upload
            uploaded_files = st.file_uploader(
                "Upload email files:",
                type=['csv', 'xlsx', 'xls', 'txt'],
                accept_multiple_files=True
            )
            
            if uploaded_files:
                for uploaded_file in uploaded_files:
                    file_emails = extract_emails_from_file(uploaded_file)
                    emails.extend(file_emails)
                    st.success(f"✅ Loaded {len(file_emails)} emails from {uploaded_file.name}")
                
                emails = list(set(emails))  # Remove duplicates
        
        # Display loaded emails
        if emails:
            st.info(f"📊 Total emails ready: {len(emails)}")
            
            # Show preview
            with st.expander("👀 Preview Emails"):
                for i, email in enumerate(emails[:20]):
                    st.text(f"{i+1}. {email}")
                if len(emails) > 20:
                    st.text(f"... and {len(emails) - 20} more")
            
            # Verification button
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                if st.button("🚀 Start Verification", type="primary", use_container_width=True):
                    st.markdown("### 🔄 **VERIFICATION IN PROGRESS**")
                    
                    # Progress display placeholders
                    progress_placeholder = st.empty()
                    details_placeholder = st.empty()
                    
                    # Verify emails
                    results = []
                    completed = 0
                    total = len(emails)
                    start_time = time.time()
                    
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        futures = {executor.submit(verify_single, email): email for email in emails}
                        
                        for future in as_completed(futures):
                            try:
                                result = future.result(timeout=50)
                                results.append(result)
                                completed += 1
                                
                                # Calculate progress metrics
                                progress = completed / total
                                elapsed = time.time() - start_time
                                speed = completed / elapsed if elapsed > 0 else 0
                                eta = (total - completed) / speed if speed > 0 else 0
                                
                                # Update UI with progress bar and metrics
                                with progress_placeholder.container():
                                    col_bar, col_count = st.columns([3, 1])
                                    with col_bar:
                                        st.progress(progress)
                                    with col_count:
                                        st.write(f"**{completed}/{total}**")
                                
                                with details_placeholder.container():
                                    met1, met2, met3, met4 = st.columns(4)
                                    with met1:
                                        st.metric("⚡ Speed", f"{speed:.1f}/s")
                                    with met2:
                                        st.metric("⏱️  Elapsed", format_duration(elapsed))
                                    with met3:
                                        st.metric("⏰ ETA", format_duration(eta))
                                    with met4:
                                        st.metric("✅ Complete", f"{progress*100:.1f}%")
                            
                            except Exception as e:
                                logger.error(f"Task error: {e}")
                                completed += 1
                    
                    # Clear placeholders
                    progress_placeholder.empty()
                    details_placeholder.empty()
                    
                    # Display results
                    if results:
                        st.markdown("---")
                        display_batch_results(results)
            
            with col2:
                if st.button("📋 Copy All", use_container_width=True):
                    st.info("📋 Copy these emails:\n\n" + "\n".join(emails))
            
            with col3:
                if st.button("🔄 Clear", use_container_width=True):
                    st.rerun()
    
    # ===== TAB 3: Sequential Batch Processing (QUEUE-BASED, NON-BLOCKING) =====
    with tab3:
        # Declare all global queue variables at tab start to avoid SyntaxError
        global _file_queue, _file_queue_active, _file_queue_paused, _file_queue_processing, _file_queue_thread, _file_queue_progress, _queue_start_time, _file_queue_stats
        
        # Store progress snapshot in session state for reliable updates
        if 'last_progress_snapshot' not in st.session_state:
            st.session_state.last_progress_snapshot = {}
        if 'last_results_snapshot' not in st.session_state:
            st.session_state.last_results_snapshot = {}
        
        # Read current state from global (thread-safe with locks)
        with _file_queue_lock:
            queue_size = len(_file_queue)
            results_count = len(_file_queue_results)
            current_file = _file_queue_processing
            progress_snapshot = dict(_file_queue_progress)  # Copy all progress data
            results_snapshot = dict(_file_queue_results)     # Copy all results
            queue_stats_snapshot = dict(_file_queue_stats)
        
        # Update session state snapshots
        st.session_state.last_progress_snapshot = progress_snapshot
        st.session_state.last_results_snapshot = results_snapshot
        
        # Display the queue status and progress in the UI
        st.markdown("## 📦 Batch File Processing")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📁 Files in Queue", queue_size)
        with col2:
            st.metric("✅ Completed", results_count)
        with col3:
            cf_name = current_file[0].name if current_file else "None"
            st.metric("📂 Current", cf_name)
        
        # Upload area
        st.markdown("### 📤 Upload Files")
        uploaded_files = st.file_uploader(
            "Select CSV files:",
            type=['csv', 'xlsx', 'xls'],
            accept_multiple_files=True,
            key="batch_uploader_files"
        )
        
        files_ready = len(uploaded_files) if uploaded_files else 0
        if files_ready > 0:
            st.info(f"📁 {files_ready} file(s) ready to process")
        
        # Control buttons
        st.markdown("### ⚙️ Controls")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("▶️ START", type="primary", use_container_width=True):
                # First, add any files from uploader to queue
                print(f"\n{'='*70}")
                print(f"🔴 START BUTTON CLICKED")
                print(f"{'='*70}")
                print(f"uploaded_files: {len(uploaded_files) if uploaded_files else 0} files")
                print(f"_file_queue_active BEFORE: {_file_queue_active}")
                
                if uploaded_files and len(uploaded_files) > 0:
                    for f in uploaded_files:
                        with _file_queue_lock:
                            _file_queue.append((f, len(_file_queue)))
                            _file_queue_stats['total_files'] += 1
                            # Initialize total_emails to 0 if not set yet
                            if _file_queue_stats['total_emails'] == 0:
                                _file_queue_stats['total_emails'] = 0  # Will be incremented during processing
                    with _file_queue_lock:
                        qsize = len(_file_queue)
                    print(f"✅ Added {len(uploaded_files)} files to queue")
                else:
                    with _file_queue_lock:
                        qsize = len(_file_queue)
                    print(f"⚠️  No uploaded files, using existing queue: {qsize} items")
                
                print(f"Queue size: {qsize}")
                print(f"_file_queue_active: {_file_queue_active}")
                print(f"Condition: qsize > 0 = {qsize > 0}, not _file_queue_active = {not _file_queue_active}")
                
                # Now check if we can start
                if qsize > 0 and not _file_queue_active:
                    print(f"✅ Starting processor...")
                    _file_queue_active = True
                    _queue_start_time = time.time()
                    # Reset stats for this batch
                    with _file_queue_lock:
                        _file_queue_stats['processed_emails'] = 0
                        # DON'T reset total_emails - it will be set during processing
                        # _file_queue_stats['total_emails'] = 0  
                        _file_queue_stats['completed_files'] = 0
                    thread = threading.Thread(target=run_file_queue_processor, daemon=True)
                    thread.start()
                    print(f"✅ Thread started!")
                    print(f"{'='*70}\n")
                    st.success(f"✅ Processing {qsize} file(s)...")
                    time.sleep(0.5)
                    st.rerun()
                elif _file_queue_active:
                    print(f"❌ Already processing!")
                    print(f"{'='*70}\n")
                    st.warning("⚠️ Already processing!")
                else:
                    print(f"❌ No files in queue!")
                    print(f"{'='*70}\n")
                    st.error("❌ Upload files first!")
        
        
        with col2:
            if st.button("⏹️ STOP", use_container_width=True):
                _file_queue_active = False
                st.warning("⏹️ Stopped")
        
        with col3:
            if st.button("🗑️ CLEAR", use_container_width=True):
                with _file_queue_lock:
                    _file_queue.clear()
                    _file_queue_progress.clear()
                    _file_queue_results.clear()
                    _file_queue_stats['total_files'] = 0
                    _file_queue_stats['completed_files'] = 0
                    _file_queue_stats['processed_emails'] = 0
                    _file_queue_stats['total_emails'] = 0
                _file_queue_active = False
                st.info("🗑️ Cleared all!")
                time.sleep(0.3)
                st.rerun()
        
        st.markdown("---")
        
        # Initialize session state for auto-refresh control
        if 'dashboard_poll_active' not in st.session_state:
            st.session_state.dashboard_poll_active = False
        
        # REAL-TIME STATUS - Re-read globals every render
        current_queue_active = _file_queue_active
        current_queue_start = _queue_start_time
        
        with _file_queue_lock:
            current_total = _file_queue_stats['total_files']
            current_completed = _file_queue_stats['completed_files']
            current_processed = _file_queue_stats['processed_emails']
            current_total_emails = _file_queue_stats['total_emails']
            current_queue_len = len(_file_queue)
            progress_dict = dict(_file_queue_progress)
            results_dict = dict(_file_queue_results)
        
        # DEBUG INFO
        col_d1, col_d2, col_d3, col_d4 = st.columns(4)
        with col_d1:
            st.metric("🔴 Active", "YES" if current_queue_active else "NO")
        with col_d2:
            st.metric("📊 Files", f"{current_total}")
        with col_d3:
            st.metric("📧 Processed", f"{current_processed}/{current_total_emails}")
        with col_d4:
            if current_queue_start:
                speed = current_processed / max(time.time() - current_queue_start, 0.1)
                st.metric("⚡ Speed", f"{speed:.1f}/s")
            else:
                st.metric("⚡ Speed", "0/s")
        
        # Create a container for live updates
        dashboard_container = st.empty()
        
        # Force polling while processing is active
        # FIXED: Check if queue processor is running (not just if we have total_emails yet)
        is_processing = current_queue_active and current_queue_start is not None
        
        if is_processing:
            st.session_state.dashboard_poll_active = True
            
            # Update dashboard immediately
            elapsed = time.time() - current_queue_start if current_queue_start else 0
            
            with dashboard_container.container():
                # Professional dashboard using st.metric and progress bar
                st.markdown("### 📈 Live Progress Dashboard")
                
                # Check if we have emails to process yet
                if current_total_emails > 0:
                    overall_speed = current_processed / max(elapsed, 0.1) if current_processed > 0 else 0
                    overall_pct = (current_processed / max(current_total_emails, 1)) * 100
                    
                    # Progress bar
                    col_progress = st.columns([1])
                    with col_progress[0]:
                        st.progress(min(max(overall_pct / 100, 0), 1.0), text=f"Progress: {overall_pct:.1f}%")
                    
                    # Metrics row
                    mcol1, mcol2, mcol3 = st.columns(3)
                    with mcol1:
                        st.metric("⚡ Speed", f"{overall_speed:.2f} emails/sec")
                    with mcol2:
                        st.metric("⏱️  Elapsed", f"{int(elapsed)}s")
                    with mcol3:
                        eta_sec = (current_total_emails - current_processed) / max(overall_speed, 0.1) if overall_speed > 0 else 0
                        st.metric("⏰ ETA", f"{int(eta_sec)}s")
                    
                    # Results row
                    rcol1, rcol2, rcol3 = st.columns(3)
                    with rcol1:
                        valid = sum(p.get('valid', 0) for p in progress_dict.values())
                        st.metric("✅ Valid", f"{valid}")
                    with rcol2:
                        risky = sum(p.get('risky', 0) for p in progress_dict.values())
                        st.metric("⚠️  Risky", f"{risky}")
                    with rcol3:
                        invalid = sum(p.get('invalid', 0) for p in progress_dict.values())
                        st.metric("❌ Invalid", f"{invalid}")
                else:
                    # Still waiting for first file to be processed
                    st.info(f"⏳ **Starting processor...** (Elapsed: {int(elapsed)}s)")
                    st.progress(0, text="Initializing...")
            
            # Auto-refresh
            time.sleep(0.5)
            st.rerun()
        else:
            st.session_state.dashboard_poll_active = False
        
        # Show completed results even if not processing
        with _file_queue_lock:
            results_dict = dict(_file_queue_results)
        
        # Display one section for completed results
        if results_dict and len(results_dict) > 0:
            st.markdown("---")
            st.subheader("✅ **COMPLETED FILES RESULTS**")
            
            for file_key, result in list(results_dict.items()):
                if result and result.get('status') == 'completed':
                    file_name = result.get('file_name', 'Unknown')
                    total_e = result.get('emails_count', 0)
                    valid = result.get('valid_count', 0)
                    risky = result.get('risky_count', 0)
                    invalid = total_e - valid - risky
                    speed_file = result.get('speed', 0)
                    duration = result.get('duration', 0)
                    
                    # File summary row
                    cols = st.columns([2, 1, 1.2, 1.2, 1.2, 1])
                    
                    with cols[0]:
                        st.write(f"**📄 {file_name}**")
                    with cols[1]:
                        st.write(f"📊 {total_e}")
                    with cols[2]:
                        pv = (valid/total_e*100) if total_e > 0 else 0
                        st.write(f"✅ {valid} ({pv:.0f}%)")
                    with cols[3]:
                        pr = (risky/total_e*100) if total_e > 0 else 0
                        st.write(f"⚠️ {risky} ({pr:.0f}%)")
                    with cols[4]:
                        pi = (invalid/total_e*100) if total_e > 0 else 0
                        st.write(f"❌ {invalid} ({pi:.0f}%)")
                    with cols[5]:
                        st.write(f"⚡ {speed_file:.1f}/s")
                    
                    st.divider()
                    
                    # Expandable results table
                    with st.expander(f"📋 View Detailed Results - {file_name}", expanded=False):
                        if 'df_export' in result and not result['df_export'].empty:
                            st.dataframe(
                                result['df_export'], 
                                use_container_width=True,
                                height=400
                            )
                            
                            # Download button
                            csv_data = result['df_export'].to_csv(index=False).encode('utf-8')
                            st.download_button(
                                "📥 Download CSV",
                                csv_data,
                                f"{file_name.rsplit('.', 1)[0]}_verified.csv",
                                "text/csv",
                                key=f"download_{file_key}"
                            )


    with tab4:
        st.header("📊 Verification Analytics")
        
        if st.session_state.batch_results:
            results = st.session_state.batch_results
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                total = len(results)
                st.metric("Total Verified", total)
            
            with col2:
                valid = sum(1 for r in results if r.get('valid', False))
                valid_pct = (valid / total * 100) if total > 0 else 0
                st.metric("Valid Rate", f"{valid_pct:.1f}%")
            
            with col3:
                durations = [r.get('duration_ms', 0) for r in results]
                avg_duration = sum(durations) / len(durations) if durations else 0
                st.metric("Avg Duration", f"{avg_duration:.0f}ms")
            
            # Domain analysis
            st.markdown("### 🌐 Domain Analysis")
            domains = {}
            for r in results:
                domain = r['email'].split('@')[1].lower() if '@' in r['email'] else 'unknown'
                if domain not in domains:
                    domains[domain] = {'total': 0, 'valid': 0}
                domains[domain]['total'] += 1
                if r.get('valid', False):
                    domains[domain]['valid'] += 1
            
            domain_stats = []
            for domain, stats in sorted(domains.items(), key=lambda x: x[1]['total'], reverse=True):
                valid_pct = (stats['valid'] / stats['total'] * 100) if stats['total'] > 0 else 0
                domain_stats.append({
                    'Domain': domain,
                    'Total': stats['total'],
                    'Valid': stats['valid'],
                    'Valid %': valid_pct
                })
            
            df_domains = pd.DataFrame(domain_stats)
            st.dataframe(df_domains, use_container_width=True)
        else:
            st.info("👉 Run some verifications first to see analytics")

    # ===== TAB 5: Email Finder (Pattern Generation & Verification) =====
    with tab5:
        st.markdown("<h1 style='text-align: center;'>🔎 Professional Email Finder</h1>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; color: #666; margin-bottom: 2rem;'>Generate and verify professional emails using name and domain data.</div>", unsafe_allow_html=True)
        
        # --- SHARED HELPERS ---
        # Using global _domain_mx_cache and _domain_mx_lock for thread safety

        def _get_mx_sync(domain: str) -> List[str]:
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                _, mx, _ = loop.run_until_complete(get_mx_records_reliable(domain))
                return mx
            except Exception:
                return []

        def _verify_batch_sync(emails: List[str], mx: str) -> Dict:
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                return loop.run_until_complete(batch_smtp_verify(emails, mx))
            except Exception:
                return {}

        # --- SINGLE FINDER SECTION ---
        st.markdown("### 👤 Single Finder")
        with st.container():
            sf_col1, sf_col2 = st.columns([1, 1])
            with sf_col1:
                sf_name_input = st.text_input("Person's Full Name", placeholder="e.g. Dayna Santana", key="sf_name_field")
            with sf_col2:
                sf_domain_input = st.text_input("Website / Domain", placeholder="e.g. aviditybio.com", key="sf_domain_field")
            
            sf_submit = st.button("🚀 Find Email (Single)", type="primary", use_container_width=True)
            
            if sf_submit:
                if not sf_name_input or not sf_domain_input:
                    st.error("⚠️ Please provide a Name and Domain.")
                else:
                    sf_domain_input = sf_domain_input.strip().lstrip("@")
                    name_parts = sf_name_input.strip().split(maxsplit=1)
                    sf_fname = name_parts[0]
                    sf_lname = name_parts[1] if len(name_parts) > 1 else ""
                    
                    with st.spinner(f"🔍 Searching for {sf_name_input} @ {sf_domain_input}..."):
                        p_list = generate_email_patterns(sf_fname, sf_lname, sf_domain_input)
                        with _domain_mx_lock:
                            info = _domain_mx_cache.get(sf_domain_input)
                        
                        if not info:
                            mx_list = _get_mx_sync(sf_domain_input)
                            if mx_list:
                                test_email = f"chk.{int(time.time())}@{sf_domain_input}"
                                b_res = _verify_batch_sync([test_email], mx_list[0])
                                is_ca = b_res.get(test_email, {}).get('accepted', False)
                                info = {'mx': mx_list, 'is_catch_all': is_ca}
                                with _domain_mx_lock:
                                    _domain_mx_cache[sf_domain_input] = info
                        
                        if info and info['mx']:
                            if info['is_catch_all']:
                                st.warning("⚠️ Domain is Catch-all (Accepts everything). Showing likely patterns.")
                            
                            # Use parallel verify_single for maximum reliability
                            results = {}
                            is_ca = info.get('is_catch_all', False)
                            
                            with ThreadPoolExecutor(max_workers=5) as p_exe:
                                fut_map = {p_exe.submit(verify_single, p): p for p in p_list}
                                for fobj in as_completed(fut_map):
                                    p_item = fut_map[fobj]
                                    v_out = fobj.result()
                                    results[p_item] = {
                                        'accepted': v_out.get('valid', False),
                                        'text': v_out.get('reason', 'OK')
                                    }
                            
                            output_res = []
                            any_found = False
                            for p in p_list:
                                r = results.get(p, {})
                                is_ok = r.get('accepted', False)
                                
                                if is_ca:
                                    status_text = '⚠️ Catch-all (Risky)'
                                    response_text = 'Server accepts all emails'
                                    any_found = True
                                else:
                                    status_text = '✅ Valid' if is_ok else '❌ Invalid'
                                    response_text = r.get('text', 'No response')
                                    if is_ok: any_found = True
                                    
                                output_res.append({
                                    'Email Pattern': p,
                                    'Result': status_text,
                                    'Server Response': response_text
                                })
                            
                            if is_ca:
                                st.warning("⚠️ This domain is a Catch-all. All patterns will accept mail, but only one might be the real person.")
                            elif any_found: 
                                st.success(f"🎊 Found valid email(s) for {sf_name_input}!")
                            else: 
                                st.info("ℹ️ No valid patterns discovered.")
                            
                            df_sf = pd.DataFrame(output_res)
                            def style_results(val):
                                if 'Valid' in str(val): return 'color: #28a745; font-weight: bold; background-color: #f8fff9'
                                if 'Invalid' in str(val): return 'color: #dc3545; opacity: 0.8'
                                return ''
                            st.dataframe(df_sf.style.applymap(style_results, subset=['Result']), use_container_width=True)
                        else:
                            st.error(f"❌ Could not resolve MX records for {sf_domain_input}")

        st.markdown("<br><hr>", unsafe_allow_html=True)

        # --- BULK FINDER SECTION ---
        st.markdown("### 📂 Bulk Finder (Multiple Files)")
        uploaded_files = st.file_uploader("Upload CSV/Excel:", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True, key="bulk_email_up")
        
        if uploaded_files:
            # Use the first file to determine columns
            first_file = uploaded_files[0]
            f_ext = first_file.name.split('.')[-1].lower()
            try:
                # Read sample from first file for column mapping
                df_prev = pd.read_csv(first_file, nrows=5) if f_ext == 'csv' else pd.read_excel(first_file, nrows=5)
                st.write("### ⚙️ Column Mapping")
                st.info(f"📁 {len(uploaded_files)} files selected. Mapping will be applied to all files.")
                
                c1, c2, c3, c4 = st.columns(4)
                with c1: f_col = st.selectbox("First Name Column", df_prev.columns)
                with c2: l_col = st.selectbox("Last Name Column", [None] + list(df_prev.columns))
                with c3: d_col = st.selectbox("Domain Column", df_prev.columns)
                with c4: 
                    st.markdown("<br>", unsafe_allow_html=True)
                    start_bulk = st.button("🚀 Start Bulk Finder", type="primary", use_container_width=True)
                
                if start_bulk:
                    # Overall Batch Progress
                    batch_total = len(uploaded_files)
                    batch_completed = 0
                    
                    st.markdown("---")
                    st.markdown("## 📊 Batch Progress")
                    batch_col1, batch_col2, batch_col3 = st.columns(3)
                    batch_files_met = batch_col1.empty()
                    batch_completed_met = batch_col2.empty()
                    batch_remaining_met = batch_col3.empty()
                    
                    batch_pb = st.progress(0)
                    batch_status = st.empty()
                    
                    # Current File Progress
                    st.markdown("### 📄 Current File Progress")
                    file_name_txt = st.empty()
                    pb = st.progress(0)
                    st_txt = st.empty()
                    ra = st.empty()
                    
                    all_found_arr = []
                    batch_start_time = time.time()
                    
                    def bulk_worker_fn(item):
                        fname = str(item.get(f_col, "")).strip()
                        lname = str(item.get(l_col, "")).strip() if l_col else ""
                        domain = str(item.get(d_col, "")).strip().lstrip("@")
                        if not fname or not domain: return {'First Name': fname, 'Last Name': lname, 'Domain': domain, 'Valid Email': 'N/A', 'Status': 'Missing Data'}
                        
                        patterns = generate_email_patterns(fname, lname, domain)
                        with _domain_mx_lock: info = _domain_mx_cache.get(domain)
                        
                        if not info:
                            mx = _get_mx_sync(domain)
                            if not mx: return {'First Name': fname, 'Last Name': lname, 'Domain': domain, 'Valid Email': 'NOT FOUND', 'Status': '❌ INVALID DOMAIN'}
                            test_v = f"chk.{int(time.time())}@{domain}"
                            svr_res = _verify_batch_sync([test_v], mx[0])
                            is_ca_val = svr_res.get(test_v, {}).get('accepted', False)
                            info = {'mx': mx, 'is_catch_all': is_ca_val}
                            with _domain_mx_lock: _domain_mx_cache[domain] = info
                        
                        if info['is_catch_all']:
                            g = f"{fname}.{lname}@{domain}".lower().replace(" ", "") if lname else f"{fname}@{domain}".lower()
                            return {'First Name': fname, 'Last Name': lname, 'Domain': domain, 'Valid Email': g, 'Status': '⚠️ RISKY (CATCH-ALL)'}
                        
                        v_res = _verify_batch_sync(patterns, info['mx'][0])
                        found_v = [p for p in patterns if v_res.get(p, {}).get('accepted')]
                        if found_v:
                            return {
                                'First Name': fname, 'Last Name': lname, 'Domain': domain, 
                                'Valid Email': ", ".join(found_v), 
                                'Status': f'✅ FOUND ({len(found_v)})'
                            }
                        return {'First Name': fname, 'Last Name': lname, 'Domain': domain, 'Valid Email': 'NOT FOUND', 'Status': '❌ NOT FOUND'}

                    for flow_idx, current_file in enumerate(uploaded_files):
                        file_name = current_file.name
                        file_f_ext = file_name.split('.')[-1].lower()
                        
                        # Update Batch UI
                        batch_files_met.metric("Total Files", batch_total)
                        batch_completed_met.metric("Completed", batch_completed)
                        batch_remaining_met.metric("Remaining", batch_total - batch_completed)
                        batch_pb.progress(batch_completed / batch_total)
                        batch_status.markdown(f"🔍 **Processing:** `{file_name}` ({batch_completed + 1}/{batch_total})")
                        
                        file_name_txt.info(f"📂 **File:** {file_name}")
                        
                        # Process Current File
                        current_file.seek(0)
                        df_full = pd.read_csv(current_file) if file_f_ext == 'csv' else pd.read_excel(current_file)
                        total_r = len(df_full)
                        found_arr = []
                        start_time_val = time.time()
                        
                        with ThreadPoolExecutor(max_workers=5) as p_exe:
                            futures_list = [p_exe.submit(bulk_worker_fn, r) for _, r in df_full.iterrows()]
                            for idx, fobj in enumerate(as_completed(futures_list)):
                                res = fobj.result()
                                res['Source File'] = file_name # Track source
                                found_arr.append(res)
                                all_found_arr.append(res)
                                
                                # UI Updates
                                pb.progress((idx + 1) / total_r)
                                elapsed_val = time.time() - start_time_val
                                cur_speed = (idx + 1) / elapsed_val if elapsed_val > 0 else 0
                                st_txt.markdown(f"**Progress:** {idx+1}/{total_r} | **Speed:** {cur_speed:.1f} rows/s")
                                if idx % 10 == 0:
                                    with ra.container():
                                        st.dataframe(pd.DataFrame(found_arr).tail(5), use_container_width=True)
                        
                        batch_completed += 1
                        st.toast(f"✅ Completed: {file_name}")
                    
                    # Final Completion UI
                    batch_pb.progress(1.0)
                    batch_completed_met.metric("Completed", batch_completed)
                    batch_remaining_met.metric("Remaining", 0)
                    batch_status.success(f"🎊 Batch discovery complete! All {batch_total} files processed.")
                    
                    st.markdown("---")
                    st.subheader("🏁 All Results Summary")
                    df_final_res = pd.DataFrame(all_found_arr)
                    st.dataframe(df_final_res, use_container_width=True)
                    
                    col_dl1, col_dl2 = st.columns(2)
                    with col_dl1:
                        csv_bytes = df_final_res.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Download Combined Results (CSV)", csv_bytes, "email_finder_batch_output.csv", "text/csv")
                    with col_dl2:
                        if st.button("🔄 Clear All", use_container_width=True):
                            st.rerun()

            except Exception as error_msg:
                import traceback
                st.error(f"Error processing upload: {error_msg}")
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()