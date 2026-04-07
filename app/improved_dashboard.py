"""
Professional Email Verification Queue Dashboard
- Real-time progress tracking
- Horizontal full-width progress bars
- Clear file completion indicators
- Professional styling with Streamlit
"""

import streamlit as st
import time
from typing import Dict, Optional, List
from datetime import datetime, timedelta


def format_time(seconds: float) -> str:
    """Format seconds to HH:MM:SS format"""
    if seconds <= 0:
        return "00:00:00"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_duration_short(seconds: float) -> str:
    """Format seconds to Xm Ys or XhYmZs format"""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


def get_color_for_percentage(percentage: float) -> str:
    """Get color gradient based on percentage"""
    if percentage < 25:
        return "#FF6B6B"  # Red
    elif percentage < 50:
        return "#FFA500"  # Orange
    elif percentage < 75:
        return "#FFD700"  # Yellow
    elif percentage < 90:
        return "#87CEEB"  # Light Blue
    else:
        return "#4CAF50"  # Green


def display_professional_metrics(stats: Dict) -> None:
    """Display overall queue statistics with professional styling"""
    
    st.markdown("""
    <style>
        .metric-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 30px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        }
        .metric-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            padding-bottom: 15px;
            border-bottom: 2px solid rgba(255,255,255,0.2);
        }
        .metric-header-title {
            font-size: 20px;
            font-weight: bold;
            color: white;
            margin: 0;
        }
        .metric-header-status {
            font-size: 18px;
            font-weight: bold;
            color: white;
        }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }
        .metric-item {
            background: rgba(255,255,255,0.95);
            padding: 18px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .metric-item:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.15);
        }
        .metric-label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .metric-value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
            margin: 5px 0;
        }
        .metric-delta {
            font-size: 12px;
            color: #4CAF50;
            margin-top: 8px;
            font-weight: 600;
        }
        .metric-subtext {
            font-size: 11px;
            color: #999;
            margin-top: 5px;
        }
    </style>
    """, unsafe_allow_html=True)
    
    total_files = stats.get('total_files', 0)
    completed_files = stats.get('completed_files', 0)
    remaining_files = stats.get('files_in_queue', 0)
    progress_pct = (completed_files / total_files * 100) if total_files > 0 else 0
    
    # Status indicator
    if stats.get('is_processing') and not stats.get('is_paused'):
        status_emoji = "🟢"
        status_text = "PROCESSING"
        status_color = "#4CAF50"
    elif stats.get('is_paused'):
        status_emoji = "🟡"
        status_text = "PAUSED"
        status_color = "#FFA500"
    else:
        status_emoji = "⚪"
        status_text = "IDLE"
        status_color = "#9E9E9E"
    
    # Create container with header
    st.markdown(f"""
    <div class="metric-container">
        <div class="metric-header">
            <h3 class="metric-header-title">📊 Queue Overview - Overall Statistics</h3>
            <span class="metric-header-status" style="color: {status_color};">{status_emoji} {status_text}</span>
        </div>
        <div class="metric-grid">
    """, unsafe_allow_html=True)
    
    # Create columns for metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    
    with m1:
        st.markdown(f"""
        <div class="metric-item">
            <div class="metric-label">📋 Total Files</div>
            <div class="metric-value">{total_files}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with m2:
        delta_str = f"+{completed_files - stats.get('last_completed', 0)}" if completed_files > stats.get('last_completed', 0) else ""
        st.markdown(f"""
        <div class="metric-item">
            <div class="metric-label">✅ Completed</div>
            <div class="metric-value" style="color: #4CAF50;">{completed_files}</div>
            {f'<div class="metric-delta">{delta_str}</div>' if delta_str else ''}
        </div>
        """, unsafe_allow_html=True)
    
    with m3:
        st.markdown(f"""
        <div class="metric-item">
            <div class="metric-label">⏳ Remaining</div>
            <div class="metric-value" style="color: #FF9800;">{remaining_files}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with m4:
        st.markdown(f"""
        <div class="metric-item">
            <div class="metric-label">📈 Progress</div>
            <div class="metric-value" style="color: #2196F3;">{progress_pct:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with m5:
        # Calculate estimated total time and speed
        total_emails = stats.get('total_emails', 0)
        processed_emails = stats.get('processed_emails', 0)
        elapsed = stats.get('elapsed_time', 0)
        avg_speed = processed_emails / max(elapsed, 1) if elapsed > 0 else 0
        
        st.markdown(f"""
        <div class="metric-item">
            <div class="metric-label">⚡ Speed</div>
            <div class="metric-value" style="color: #9C27B0;">{avg_speed:.1f}</div>
            <div class="metric-subtext">emails/sec</div>
        </div>
        """, unsafe_allow_html=True)


def display_professional_progress_bar(current: int, total: int, label: str = "") -> None:
    """Display a professional horizontal progress bar"""
    
    percentage = (current / total * 100) if total > 0 else 0
    bar_color = get_color_for_percentage(percentage)
    
    progress_html = f"""
    <div style="margin: 15px 0;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 14px; color: #333;">{label}</span>
            <span style="font-weight: 600; font-size: 14px; color: {bar_color};">{percentage:.1f}%</span>
        </div>
        <div style="background: #e0e0e0; height: 28px; border-radius: 14px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(90deg, {bar_color} 0%, {bar_color}dd 100%); 
                        height: 100%; width: {percentage}%; 
                        display: flex; align-items: center; justify-content: center;
                        color: white; font-weight: bold; font-size: 12px;
                        transition: width 0.3s ease;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.15);">
                {int(current):,} / {int(total):,}
            </div>
        </div>
    </div>
    """
    
    st.markdown(progress_html, unsafe_allow_html=True)


def display_currently_processing(current_file: Dict, file_number: int, total_files: int) -> None:
    """Display currently processing file with professional styling matching Queue Overview"""
    
    if not current_file:
        st.info("⏳ Waiting for file to process...")
        return
    
    st.markdown("""
    <style>
        .processing-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 12px;
            padding: 25px;
            margin: 20px 0 30px 0;
            box-shadow: 0 8px 20px rgba(0,0,0,0.15);
        }
        .processing-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            padding-bottom: 15px;
            border-bottom: 2px solid rgba(255,255,255,0.2);
        }
        .processing-header-title {
            font-size: 20px;
            font-weight: bold;
            color: white;
        }
        .processing-header-subtitle {
            font-size: 14px;
            color: rgba(255,255,255,0.8);
            margin-bottom: 3px;
        }
        .processing-status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
            color: white;
            background: rgba(255,255,255,0.2);
        }
        .processing-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 15px;
            margin-bottom: 25px;
        }
        .processing-item {
            background: rgba(255,255,255,0.95);
            padding: 18px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .processing-label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .processing-value {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
            margin: 5px 0;
        }
        .processing-subtext {
            font-size: 11px;
            color: #999;
            margin-top: 5px;
        }
        .progress-bar-container {
            background: rgba(255,255,255,0.15);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .progress-label-text {
            color: white;
            font-weight: 600;
            font-size: 14px;
            margin-bottom: 12px;
        }
    </style>
    """, unsafe_allow_html=True)
    
    file_name = current_file.get('file_name', 'Unknown')
    file_size = current_file.get('file_size_kb', 0)
    current_count = current_file.get('current', 0)
    total_count = current_file.get('total', 0)
    percentage = (current_count / total_count * 100) if total_count > 0 else 0
    
    valid_count = current_file.get('valid', 0)
    risky_count = current_file.get('risky', 0)
    invalid_count = current_file.get('invalid', 0)
    elapsed = current_file.get('elapsed', 0)
    speed = current_file.get('speed', 0)
    
    # Calculate ETA
    if speed > 0 and current_count < total_count:
        remaining_emails = total_count - current_count
        eta_seconds = remaining_emails / speed
        eta_formatted = format_duration_short(eta_seconds)
    else:
        eta_formatted = "--:--"
    
    # Get progress bar color
    bar_color = get_color_for_percentage(percentage)
    
    # Create container
    st.markdown(f"""
    <div class="processing-container">
        <div class="processing-header">
            <div>
                <div class="processing-header-title">🏃 CURRENTLY PROCESSING FILE</div>
                <div class="processing-header-subtitle">File {file_number} of {total_files}</div>
            </div>
            <span class="processing-status-badge">🔄 PROCESSING</span>
        </div>
        
        <!-- File Information and Progress Stats Row -->
        <div class="processing-grid">
    """, unsafe_allow_html=True)
    
    # Create columns for file and stats
    p1, p2, p3, p4, p5 = st.columns(5)
    
    with p1:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">📄 File Name</div>
            <div style="font-size: 13px; font-weight: 600; color: #333; word-break: break-word; margin: 8px 0;">
                {file_name[:30]}{'...' if len(file_name) > 30 else ''}
            </div>
            <div class="processing-subtext">📊 {file_size:.2f} KB</div>
        </div>
        """, unsafe_allow_html=True)
    
    with p2:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">🏃 File Progress</div>
            <div class="processing-value" style="color: {bar_color};">{percentage:.1f}%</div>
            <div class="processing-subtext">{current_count:,} / {total_count:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with p3:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">✅ Valid</div>
            <div class="processing-value" style="color: #4CAF50;">{valid_count:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with p4:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">⚠️ Risky</div>
            <div class="processing-value" style="color: #FF9800;">{risky_count:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with p5:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">❌ Invalid</div>
            <div class="processing-value" style="color: #DC3545;">{invalid_count:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Large progress bar
    st.markdown(f"""
    <div class="progress-bar-container">
        <div class="progress-label-text">📊 Email Processing Progress: {percentage:.1f}%</div>
        <div style="background: rgba(255,255,255,0.2); height: 36px; border-radius: 18px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(90deg, {bar_color} 0%, {bar_color}dd 100%); 
                        height: 100%; width: {percentage}%; 
                        display: flex; align-items: center; justify-content: center;
                        color: white; font-weight: bold; font-size: 14px;
                        transition: width 0.3s ease;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.15);">
                {current_count:,} / {total_count:,} emails
            </div>
        </div>
    </div>
    
    <!-- Timing Information Row -->
    <div class="processing-grid">
    """, unsafe_allow_html=True)
    
    # Timing stats (3 boxes in a row, leaving 2 empty)
    t1, t2, t3, t4, t5 = st.columns(5)
    
    elapsed_formatted = format_time(elapsed) if elapsed > 0 else "00:00:00"
    
    with t1:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">⏱️ Elapsed</div>
            <div style="font-size: 18px; font-weight: bold; color: #2196F3; font-family: monospace;">{elapsed_formatted}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with t2:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">⚡ Speed</div>
            <div class="processing-value" style="color: #9C27B0;">{speed:.1f}</div>
            <div class="processing-subtext">emails/sec</div>
        </div>
        """, unsafe_allow_html=True)
    
    with t3:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">⏳ ETA</div>
            <div style="font-size: 22px; font-weight: bold; color: #FF6B6B;">{eta_formatted}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with t4:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">💚 Health</div>
            <div class="processing-value" style="color: #4CAF50;">100%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with t5:
        st.markdown(f"""
        <div class="processing-item">
            <div class="processing-label">📋 Status</div>
            <div style="font-size: 16px; font-weight: bold; color: #667eea;">🟢 Active</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("</div></div>", unsafe_allow_html=True)


def display_completed_files_summary(completed_files: List[Dict]) -> None:
    """Display summary of recently completed files"""
    
    if not completed_files:
        return
    
    st.markdown("---")
    st.markdown(f"#### ✅ RECENTLY COMPLETED FILES ({len(completed_files)})", unsafe_allow_html=True)
    
    # Show last 5 completed files
    for idx, file_data in enumerate(completed_files[-5:], 1):
        file_name = file_data.get('file_name', 'Unknown')
        total = file_data.get('total', 0)
        valid = file_data.get('valid', 0)
        risky = file_data.get('risky', 0)
        invalid = file_data.get('invalid', 0)
        duration = file_data.get('duration', 0)
        
        # Calculate completion time
        completion_time = format_duration_short(duration) if duration > 0 else "--"
        
        st.markdown(f"""
        <div style="background: #f8f9fa; padding: 12px; border-radius: 8px; margin: 10px 0; border-left: 4px solid #4CAF50;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 600; color: #333;">✅ {file_name}</span>
                <span style="font-size: 12px; color: #999;">Completed in {completion_time}</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; font-size: 12px;">
                <div style="text-align: center;"><span style="color: #666;">✅ Valid</span><br><span style="font-weight: bold; color: #4CAF50;">{valid:,}</span></div>
                <div style="text-align: center;"><span style="color: #666;">⚠️ Risky</span><br><span style="font-weight: bold; color: #FF9800;">{risky:,}</span></div>
                <div style="text-align: center;"><span style="color: #666;">❌ Invalid</span><br><span style="font-weight: bold; color: #dc3545;">{invalid:,}</span></div>
                <div style="text-align: center;"><span style="color: #666;">📊 Total</span><br><span style="font-weight: bold; color: #667eea;">{total:,}</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)


def display_queue_controls(processing_active: bool, processing_paused: bool) -> tuple:
    """Display queue control buttons and return user actions"""
    
    st.markdown("---")
    st.markdown("#### ⚙️ Queue Controls")
    
    col1, col2, col3, col4 = st.columns(4)
    
    start_clicked = False
    pause_clicked = False
    stop_clicked = False
    clear_clicked = False
    
    with col1:
        if st.button("▶️ START PROCESSING", use_container_width=True, key="btn_start"):
            start_clicked = True
    
    with col2:
        if st.button("⏸️ PAUSE", use_container_width=True, key="btn_pause", disabled=not processing_active):
            pause_clicked = True
    
    with col3:
        if st.button("⏹️ STOP ALL", use_container_width=True, key="btn_stop", disabled=not processing_active):
            stop_clicked = True
    
    with col4:
        if st.button("🗑️ CLEAR QUEUE", use_container_width=True, key="btn_clear"):
            clear_clicked = True
    
    return start_clicked, pause_clicked, stop_clicked, clear_clicked


def display_real_time_stats(stats: Dict) -> None:
    """Display real-time statistics update"""
    
    total_emails = stats.get('total_emails', 0)
    processed_emails = stats.get('processed_emails', 0)
    elapsed = stats.get('elapsed_time', 0)
    
    if elapsed > 0:
        speed = processed_emails / elapsed
    else:
        speed = 0
    
    if total_emails > 0:
        remaining_emails = total_emails - processed_emails
        if speed > 0:
            remaining_time = remaining_emails / speed
            remaining_time_str = format_duration_short(remaining_time)
        else:
            remaining_time_str = "--:--"
    else:
        remaining_time_str = "--:--"
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("🎯 Total Emails", f"{total_emails:,}")
    
    with col2:
        st.metric("✅ Processed", f"{processed_emails:,}")
    
    with col3:
        st.metric("⚡ Speed", f"{speed:.2f} e/s")
    
    with col4:
        st.metric("⏳ Remaining", remaining_time_str)


def display_comprehensive_status_container(current_file: Dict, stats: Dict) -> None:
    """Display comprehensive status in a single professional container"""
    
    if not current_file:
        st.info("⏳ Waiting for file to process...")
        return
    
    st.markdown("""
    <style>
        .status-container {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 16px;
            padding: 30px;
            margin: 25px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.12);
            border: 1px solid rgba(255,255,255,0.3);
        }
        .status-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            padding-bottom: 15px;
            border-bottom: 2px solid rgba(0,0,0,0.1);
        }
        .status-title {
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: bold;
            color: white;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-stat {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            border-left: 5px solid;
        }
        .status-stat-label {
            font-size: 13px;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 700;
            margin-bottom: 10px;
        }
        .status-stat-value {
            font-size: 28px;
            font-weight: bold;
            margin: 5px 0;
        }
        .status-progress-container {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }
        .status-progress-label {
            font-size: 14px;
            font-weight: 700;
            color: #333;
            margin-bottom: 12px;
        }
        .status-horizontal-stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-top: 20px;
        }
        .horizontal-stat-box {
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            color: white;
            font-weight: bold;
        }
        .valid-box { background: linear-gradient(135deg, #28a745, #20c997); }
        .risky-box { background: linear-gradient(135deg, #ffc107, #ff9800); }
        .invalid-box { background: linear-gradient(135deg, #dc3545, #c82333); }
        .time-box { background: linear-gradient(135deg, #17a2b8, #138496); }
    </style>
    """, unsafe_allow_html=True)
    
    file_name = current_file.get('file_name', 'Unknown')
    file_size = current_file.get('file_size_kb', 0)
    current_count = current_file.get('current', 0)
    total_count = current_file.get('total', 0)
    valid = current_file.get('valid', 0)
    risky = current_file.get('risky', 0)
    invalid = current_file.get('invalid', 0)
    elapsed = current_file.get('elapsed', 0)
    speed = current_file.get('speed', 0)
    
    percentage = (current_count / total_count * 100) if total_count > 0 else 0
    bar_color = get_color_for_percentage(percentage)
    
    # Calculate ETA
    if speed > 0 and current_count < total_count:
        remaining_emails = total_count - current_count
        eta_seconds = remaining_emails / speed
        eta_text = format_duration_short(eta_seconds)
    else:
        eta_text = "--:--"
    
    # Get status badge color
    status_badge_color = {
        'processing': '#4CAF50',
        'completed': '#2196F3',
        'paused': '#FF9800'
    }.get(current_file.get('status', 'processing'), '#9E9E9E')
    
    # Main container
    st.markdown(f"""
    <div class="status-container">
        <div class="status-header">
            <div class="status-title">📄 {file_name[:50]}{'...' if len(file_name) > 50 else ''}</div>
            <div style="font-size: 12px; color: #666;">📊 {file_size:.2f} KB</div>
        </div>
        
        <!-- File Progress Stats -->
        <div class="status-grid">
    """, unsafe_allow_html=True)
    
    # File progress stats row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="status-stat" style="border-left-color: #2196F3;">
            <div class="status-stat-label">📁 Files Processed</div>
            <div class="status-stat-value" style="color: #2196F3;">{stats.get('completed_files', 0)}/{stats.get('total_files', 0)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        pct = (stats.get('completed_files', 0) / stats.get('total_files', 1) * 100) if stats.get('total_files', 0) > 0 else 0
        st.markdown(f"""
        <div class="status-stat" style="border-left-color: #667eea;">
            <div class="status-stat-label">⏳ Overall Progress</div>
            <div class="status-stat-value" style="color: #667eea;">{pct:.1f}%</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        total_processed = stats.get('processed_emails', 0)
        total_all = stats.get('total_emails', 0)
        st.markdown(f"""
        <div class="status-stat" style="border-left-color: #9C27B0;">
            <div class="status-stat-label">📧 Total Processed</div>
            <div class="status-stat-value" style="color: #9C27B0;">{total_processed:,}/{total_all:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        elapsed_time = stats.get('elapsed_time', 0)
        elapsed_formatted = format_time(elapsed_time) if elapsed_time > 0 else "00:00:00"
        st.markdown(f"""
        <div class="status-stat" style="border-left-color: #FF6B6B;">
            <div class="status-stat-label">⏱️ Total Elapsed</div>
            <div class="status-stat-value" style="color: #FF6B6B;">{elapsed_formatted}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Progress bar in container
    st.markdown(f"""
    <div class="status-progress-container">
        <div class="status-progress-label">Current File Progress: {percentage:.1f}%</div>
        <div style="background: #e0e0e0; height: 32px; border-radius: 16px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(90deg, {bar_color} 0%, {bar_color}dd 100%); 
                        height: 100%; width: {percentage}%; 
                        display: flex; align-items: center; justify-content: center;
                        color: white; font-weight: bold; font-size: 13px;
                        transition: width 0.3s ease;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.15);">
                {current_count:,} / {total_count:,} emails
            </div>
        </div>
        
        <!-- Email status breakdown in horizontal layout -->
        <div class="status-horizontal-stats">
            <div class="horizontal-stat-box valid-box">
                <div style="font-size: 12px; opacity: 0.9;">✅ VALID</div>
                <div style="font-size: 24px; margin-top: 8px;">{valid:,}</div>
            </div>
            <div class="horizontal-stat-box risky-box">
                <div style="font-size: 12px; opacity: 0.9;">⚠️ RISKY</div>
                <div style="font-size: 24px; margin-top: 8px;">{risky:,}</div>
            </div>
            <div class="horizontal-stat-box invalid-box">
                <div style="font-size: 12px; opacity: 0.9;">❌ INVALID</div>
                <div style="font-size: 24px; margin-top: 8px;">{invalid:,}</div>
            </div>
            <div class="horizontal-stat-box time-box">
                <div style="font-size: 12px; opacity: 0.9;">⏳ ETA</div>
                <div style="font-size: 24px; margin-top: 8px;">{eta_text}</div>
            </div>
        </div>
        
        <!-- Timing info -->
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-top: 20px;">
            <div style="background: #f0f0f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #666; font-weight: 600;">CURRENT FILE ELAPSED</div>
                <div style="font-size: 18px; font-weight: bold; color: #333; margin-top: 5px; font-family: monospace;">{format_time(elapsed)}</div>
            </div>
            <div style="background: #f0f0f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #666; font-weight: 600;">PROCESSING SPEED</div>
                <div style="font-size: 18px; font-weight: bold; color: #333; margin-top: 5px;">{speed:.2f} e/s</div>
            </div>
            <div style="background: #f0f0f0; padding: 12px; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; color: #666; font-weight: 600;">SYSTEM HEALTH</div>
                <div style="font-size: 18px; font-weight: bold; color: #28a745; margin-top: 5px;">💚 100%</div>
            </div>
        </div>
    </div>
    </div>
    """, unsafe_allow_html=True)
