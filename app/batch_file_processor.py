"""
Streamlit Batch File Processor Integration
Handles UI and file processing for multi-file queue system
"""

import streamlit as st
import asyncio
import uuid
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def initialize_batch_processor():
    """Initialize batch processor in session state"""
    if 'file_queue_manager' not in st.session_state:
        from app.file_queue_manager import FileQueueManager
        st.session_state.file_queue_manager = FileQueueManager(output_dir="data/queue_results")
    
    if 'batch_processing_progress' not in st.session_state:
        st.session_state.batch_processing_progress = None


def extract_emails_from_uploaded_file(filename: str, file_content: bytes, file_type: str) -> List[str]:
    """Extract emails from uploaded file content"""
    import csv
    
    emails = []
    
    try:
        if file_type == 'csv':
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'gb2312', 'gbk']
            df = None
            
            for encoding in encodings:
                try:
                    df = pd.read_csv(io.BytesIO(file_content), encoding=encoding, on_bad_lines='skip', engine='python')
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            if df is None:
                logger.error(f"Failed to read CSV: {filename}")
                return []
            
            # Find email column
            col_name = None
            for col in ['email', 'Email', 'EMAIL', 'e-mail', 'E-mail', 'mail', 'Mail']:
                if col in df.columns:
                    col_name = col
                    break
            
            if col_name is None and len(df.columns) > 0:
                col_name = df.columns[0]
            
            if col_name:
                emails = df[col_name].dropna().astype(str).str.strip().tolist()
        
        elif file_type in ['xlsx', 'xls']:
            try:
                df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl' if file_type == 'xlsx' else 'xlrd')
                
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
                logger.error(f"Failed to read Excel file: {e}")
                return []
        
        else:  # TXT
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252']
            content = None
            
            for encoding in encodings:
                try:
                    content = file_content.decode(encoding)
                    break
                except (UnicodeDecodeError, Exception):
                    continue
            
            if content is None:
                logger.error(f"Failed to read text file: {filename}")
                return []
            
            emails = [e.strip() for e in content.split('\n') if e.strip()]
        
        # Validate and deduplicate
        emails = list(set([e for e in emails if '@' in e and len(e) > 3 and '.' in e.split('@')[-1]]))
        
        if len(emails) > 10000:
            logger.warning(f"Found {len(emails)} emails. Limiting to 10,000 for performance.")
            emails = emails[:10000]
        
        return emails
    
    except Exception as e:
        logger.error(f"Error extracting emails from {filename}: {e}")
        return []


async def verify_emails_sequential(emails: List[str]) -> List[Dict[str, Any]]:
    """Verify emails sequentially - ONE AT A TIME (NO CONCURRENCY)"""
    from app.improved_verification_system import verify_email_improved
    
    results = []
    total_emails = len(emails)
    
    try:
        for idx, email in enumerate(emails, 1):
            logger.info(f"Verifying email {idx}/{total_emails}: {email}")
            
            try:
                # Verify ONE email at a time - NO CONCURRENT PROCESSING
                result = await verify_email_improved(email, timeout=30)
                results.append(result)
                
                # Log progress
                if idx % 10 == 0:
                    logger.info(f"Progress: {idx}/{total_emails} emails verified")
            
            except Exception as e:
                logger.error(f"Error verifying {email}: {e}")
                results.append({
                    'email': email,
                    'valid': False,
                    'reason': f'Error: {str(e)}',
                    'duration_ms': 0
                })
        
        return results
    
    except Exception as e:
        logger.error(f"Error in sequential verification: {e}")
        return []


def render_batch_files_tab():
    """Render the Batch Files queue management UI"""
    initialize_batch_processor()
    queue_manager = st.session_state.file_queue_manager
    
    st.header("📁 Batch Files - Sequential Processing")
    st.markdown("""
    **Upload multiple files (20-30+) and process them automatically:**
    1. Upload files (CSV, XLSX, TXT)
    2. Add them to the queue
    3. System processes each file sequentially
    4. Results saved automatically after each file
    5. Move to next file automatically
    """)
    
    st.divider()
    
    # ===== FILE UPLOAD SECTION =====
    st.subheader("📤 Step 1: Upload Files")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        uploaded_files = st.file_uploader(
            "Upload email files (CSV, XLSX, TXT):",
            type=['csv', 'xlsx', 'xls', 'txt'],
            accept_multiple_files=True,
            key="batch_file_uploader"
        )
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📥 Add to Queue", type="primary", use_container_width=True):
            if uploaded_files:
                for uploaded_file in uploaded_files:
                    file_id = str(uuid.uuid4())
                    file_content = uploaded_file.getvalue()
                    file_type = uploaded_file.name.split('.')[-1].lower()
                    
                    result = queue_manager.add_file_to_queue(
                        file_id=file_id,
                        filename=uploaded_file.name,
                        file_content=file_content,
                        file_type=file_type
                    )
                    
                    st.success(result['message'])
                
                st.rerun()
            else:
                st.warning("Please select files to upload")
    
    st.divider()
    
    # ===== QUEUE STATUS =====
    st.subheader("📊 Step 2: Queue Status")
    
    queue_status = queue_manager.get_queue_status()
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📁 Total Files", queue_status['queue_size'])
    with col2:
        st.metric("⏳ Pending", queue_status['pending'])
    with col3:
        st.metric("⚙️  Processing", queue_status['processing'])
    with col4:
        st.metric("✅ Completed", queue_status['completed'])
    with col5:
        st.metric("❌ Failed", queue_status['failed'])
    
    # Current file info
    if queue_status['current_file']:
        st.info(f"⚙️  Currently Processing: **{queue_status['current_file']['filename']}**")
    
    st.divider()
    
    # ===== QUEUE DETAILS TABLE =====
    if queue_status['queue']:
        st.subheader("📋 Queue Details")
        
        queue_df = []
        for idx, f in enumerate(queue_status['queue'], 1):
            queue_df.append({
                'No.': idx,
                'Filename': f['filename'],
                'Status': f['status'],
                'Uploaded': f['uploaded_at'][:10],
                'Emails': f['total_emails'],
                'Valid': f['valid_emails'],
                'Invalid': f['invalid_emails']
            })
        
        df_queue = pd.DataFrame(queue_df)
        st.dataframe(df_queue, use_container_width=True, hide_index=True)
    else:
        st.info("Queue is empty. Upload files to get started.")
    
    st.divider()
    
    # ===== PROCESSING CONTROLS =====
    st.subheader("🎮 Step 3: Start Processing")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🚀 START PROCESSING QUEUE", type="primary", use_container_width=True, 
                    disabled=queue_status['is_processing'] or queue_status['queue_size'] == 0):
            
            # Confirmation
            if queue_status['queue_size'] > 0:
                st.warning(f"⚠️  Will process {queue_status['queue_size']} files sequentially. This may take a while...")
                st.info("Processing started. Monitor progress below.")
                
                # Progress containers
                progress_container = st.container()
                status_container = st.container()
                results_container = st.container()
                
                async def process_queue_with_progress():
                    """Process queue with progress updates"""
                    
                    # Create async functions for queue manager
                    async def extract_fn(filename, content, ftype):
                        return extract_emails_from_uploaded_file(filename, content, ftype)
                    
                    async def verify_fn(emails):
                        # Use SEQUENTIAL verification instead of batch
                        return await verify_emails_sequential(emails)
                    
                    async def progress_fn(update):
                        """Callback for progress updates"""
                        st.session_state.batch_processing_progress = update
                    
                    # Process queue
                    result = await queue_manager.process_queue(
                        extract_emails_fn=extract_fn,
                        verify_emails_fn=verify_fn,
                        progress_callback=progress_fn
                    )
                    
                    return result
                
                # Run async processing
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                result = loop.run_until_complete(process_queue_with_progress())
                
                # Display results
                with status_container:
                    if result['success']:
                        st.success("✅ Queue processing completed!")
                        
                        # Summary metrics
                        summary = result.get('summary', {})
                        
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.metric("📂 Files Processed", summary.get('completed_files', 0))
                        with col2:
                            st.metric("📧 Total Emails", summary.get('total_emails_processed', 0))
                        with col3:
                            st.metric("✅ Valid", summary.get('total_valid_emails', 0))
                        with col4:
                            st.metric("❌ Invalid", summary.get('total_invalid_emails', 0))
                        
                        # Overall stats
                        if summary.get('total_emails_processed', 0) > 0:
                            valid_pct = summary.get('overall_valid_percentage', 0)
                            st.metric("📊 Valid %", f"{valid_pct:.1f}%")
                        
                        st.info(f"📁 Results saved to: `{summary.get('output_directory', 'data/queue_results')}`")
                    else:
                        st.error(f"❌ Processing failed: {result.get('message', 'Unknown error')}")
                
                # Display detailed file results
                with results_container:
                    st.subheader("📋 Detailed Results")
                    
                    summary = result.get('summary', {})
                    files_processed = summary.get('files_processed', [])
                    
                    if files_processed:
                        results_df = []
                        for f in files_processed:
                            status_icon = "✅" if f['status'] == 'completed' else "❌" if f['status'] == 'failed' else "⏳"
                            results_df.append({
                                'Status': status_icon,
                                'Filename': f['filename'],
                                'Total': f['total'],
                                'Valid': f['valid'],
                                'Invalid': f['invalid'],
                                'Error': f['error'] if f['error'] else '-'
                            })
                        
                        df_results = pd.DataFrame(results_df)
                        st.dataframe(df_results, use_container_width=True, hide_index=True)
                    
                    # Charts
                    if files_processed:
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            # Status pie chart
                            statuses = [f['status'] for f in files_processed]
                            status_counts = {
                                'Completed': statuses.count('completed'),
                                'Failed': statuses.count('failed')
                            }
                            
                            fig = px.pie(
                                values=list(status_counts.values()),
                                names=list(status_counts.keys()),
                                title="Files Processing Status",
                                color_discrete_sequence=['#10b981', '#ef4444']
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        
                        with col2:
                            # Valid vs Invalid pie chart
                            total_valid = summary.get('total_valid_emails', 0)
                            total_invalid = summary.get('total_invalid_emails', 0)
                            
                            fig = px.pie(
                                values=[total_valid, total_invalid],
                                names=['Valid', 'Invalid'],
                                title="Overall Email Status",
                                color_discrete_sequence=['#10b981', '#ef4444']
                            )
                            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        if st.button("⏹️  CANCEL QUEUE", use_container_width=True):
            if queue_manager.is_processing:
                st.warning("Cannot cancel while processing. Please wait...")
            else:
                st.info("No active processing to cancel.")
    
    with col3:
        if st.button("🗑️  CLEAR QUEUE", use_container_width=True, type="secondary"):
            result = queue_manager.clear_queue()
            st.success(result['message'])
            st.rerun()
    
    st.divider()
    
    # ===== DOWNLOAD SECTION =====
    if queue_manager.processing_history:
        st.subheader("💾 Download Results")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Combine all results CSV
            all_results = []
            for processed_file in queue_manager.processing_history:
                for result in processed_file.results:
                    all_results.append({
                        'File': processed_file.filename,
                        'Email': result.get('email', ''),
                        'Status': '✅ VALID' if result.get('valid', False) else '❌ INVALID',
                        'MX': '✅' if result.get('has_mx', False) else '❌',
                        'SMTP': ('✅' if result.get('smtp_accepted', False) 
                                else '❌ Rejected' if result.get('smtp_rejected', False) 
                                else '⏱️  Timeout'),
                        'Reason': result.get('reason', 'N/A')[:50]
                    })
            
            if all_results:
                df_all = pd.DataFrame(all_results)
                csv = df_all.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "📥 Download All Results (CSV)",
                    csv,
                    f"batch_results_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv",
                    use_container_width=True
                )
        
        with col2:
            # Combine all valid emails
            all_valid = []
            for processed_file in queue_manager.processing_history:
                for result in processed_file.results:
                    if result.get('valid', False):
                        all_valid.append(result.get('email', ''))
            
            if all_valid:
                valid_text = '\n'.join(all_valid)
                st.download_button(
                    "✅ Download Valid Emails (TXT)",
                    valid_text,
                    f"valid_emails_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    "text/plain",
                    use_container_width=True
                )
