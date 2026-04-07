"""
File Queue Manager - Sequential Processing of Multiple Files
Handles queuing, processing, and result saving for batch email verification
"""

import asyncio
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, asdict, field
from datetime import datetime
import csv

logger = logging.getLogger(__name__)


@dataclass
class QueuedFile:
    """Represents a file in the processing queue"""
    file_id: str
    filename: str
    file_content: bytes
    file_type: str  # 'csv', 'xlsx', 'txt'
    status: str  # 'pending', 'processing', 'completed', 'failed'
    uploaded_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_emails: int = 0
    processed_emails: int = 0
    valid_emails: int = 0
    invalid_emails: int = 0
    error_message: Optional[str] = None
    results: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'file_id': self.file_id,
            'filename': self.filename,
            'file_type': self.file_type,
            'status': self.status,
            'uploaded_at': self.uploaded_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'total_emails': self.total_emails,
            'processed_emails': self.processed_emails,
            'valid_emails': self.valid_emails,
            'invalid_emails': self.invalid_emails,
            'error_message': self.error_message,
            'results_count': len(self.results)
        }


class FileQueueManager:
    """
    Manages a queue of files for sequential email verification.
    
    Features:
    - Queue 20-30+ files
    - Process sequentially (one at a time)
    - Auto-save results after each file (CSV + JSON)
    - Real-time progress tracking
    - Individual file statistics
    """
    
    def __init__(self, output_dir: str = "data/queue_results"):
        self.queue: List[QueuedFile] = []
        self.processing_history: List[QueuedFile] = []
        self.current_file: Optional[QueuedFile] = None
        self.is_processing = False
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.stats = {
            'total_files': 0,
            'completed_files': 0,
            'failed_files': 0,
            'total_emails': 0,
            'total_valid': 0,
            'total_invalid': 0,
            'start_time': None,
            'end_time': None
        }
        
        logger.info(f"FileQueueManager initialized: {self.output_dir}")
    
    def add_file_to_queue(self, file_id: str, filename: str, file_content: bytes, 
                          file_type: str) -> Dict[str, Any]:
        """Add file to processing queue"""
        queued_file = QueuedFile(
            file_id=file_id,
            filename=filename,
            file_content=file_content,
            file_type=file_type,
            status='pending',
            uploaded_at=datetime.now().isoformat()
        )
        
        self.queue.append(queued_file)
        self.stats['total_files'] += 1
        
        logger.info(f"✅ Added '{filename}' to queue. Queue size: {len(self.queue)}")
        
        return {
            'success': True,
            'file_id': file_id,
            'queue_position': len(self.queue),
            'message': f"File '{filename}' added to queue (Position: {len(self.queue)})"
        }
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        pending = sum(1 for f in self.queue if f.status == 'pending')
        processing = sum(1 for f in self.queue if f.status == 'processing')
        completed = sum(1 for f in self.queue if f.status == 'completed')
        failed = sum(1 for f in self.queue if f.status == 'failed')
        
        return {
            'is_processing': self.is_processing,
            'current_file': self.current_file.to_dict() if self.current_file else None,
            'queue_size': len(self.queue),
            'pending': pending,
            'processing': processing,
            'completed': completed,
            'failed': failed,
            'statistics': self.stats,
            'queue': [f.to_dict() for f in self.queue]
        }
    
    async def process_queue(self, 
                           extract_emails_fn: Callable,
                           verify_emails_fn: Callable,
                           progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Process all files in queue sequentially.
        
        Process Flow:
        1. Take first file from queue
        2. Extract emails from file
        3. Verify all emails (in batches)
        4. Save results to CSV + JSON
        5. Move to next file
        6. Repeat until all files processed
        """
        if self.is_processing:
            return {'success': False, 'message': 'Already processing queue'}
        
        if not self.queue:
            return {'success': False, 'message': 'Queue is empty'}
        
        self.is_processing = True
        self.stats['start_time'] = datetime.now().isoformat()
        
        logger.info(f"🚀 Starting queue processing. Files: {len(self.queue)}")
        
        try:
            for idx, queued_file in enumerate(self.queue, 1):
                if queued_file.status in ['completed', 'failed']:
                    logger.info(f"⏭️  Skipping {queued_file.filename} (already {queued_file.status})")
                    continue
                
                logger.info(f"\n{'='*80}")
                logger.info(f"📂 FILE {idx}/{len(self.queue)}: {queued_file.filename}")
                logger.info(f"{'='*80}\n")
                
                self.current_file = queued_file
                queued_file.status = 'processing'
                queued_file.started_at = datetime.now().isoformat()
                
                if progress_callback:
                    await progress_callback({
                        'current_file_idx': idx,
                        'total_files': len(self.queue),
                        'current_filename': queued_file.filename,
                        'status': 'processing'
                    })
                
                try:
                    # Step 1: Extract emails from file
                    logger.info(f"📧 Extracting emails from {queued_file.filename}...")
                    emails = await extract_emails_fn(
                        queued_file.filename,
                        queued_file.file_content,
                        queued_file.file_type
                    )
                    
                    if not emails:
                        queued_file.status = 'failed'
                        queued_file.error_message = 'No valid emails found in file'
                        queued_file.completed_at = datetime.now().isoformat()
                        self.stats['failed_files'] += 1
                        logger.error(f"❌ No emails found in {queued_file.filename}")
                        
                        if progress_callback:
                            await progress_callback({
                                'current_file_idx': idx,
                                'total_files': len(self.queue),
                                'current_filename': queued_file.filename,
                                'status': 'failed',
                                'error': 'No emails found'
                            })
                        continue
                    
                    queued_file.total_emails = len(emails)
                    logger.info(f"✅ Extracted {len(emails)} emails from {queued_file.filename}")
                    
                    if progress_callback:
                        await progress_callback({
                            'current_file_idx': idx,
                            'total_files': len(self.queue),
                            'current_filename': queued_file.filename,
                            'emails_extracted': len(emails),
                            'status': 'extracting_complete'
                        })
                    
                    # Step 2: Verify emails SEQUENTIALLY (ONE AT A TIME - NO CONCURRENCY)
                    logger.info(f"🔍 SEQUENTIAL VERIFICATION: {len(emails)} emails (one at a time)...")
                    logger.info(f"📝 Starting verification process...")
                    results = await verify_emails_fn(emails)

                    
                    if not results:
                        queued_file.status = 'failed'
                        queued_file.error_message = 'Verification failed'
                        queued_file.completed_at = datetime.now().isoformat()
                        self.stats['failed_files'] += 1
                        logger.error(f"❌ Verification failed for {queued_file.filename}")
                        
                        if progress_callback:
                            await progress_callback({
                                'current_file_idx': idx,
                                'total_files': len(self.queue),
                                'current_filename': queued_file.filename,
                                'status': 'failed',
                                'error': 'Verification failed'
                            })
                        continue
                    
                    # Step 3: Process results
                    queued_file.results = results
                    queued_file.processed_emails = len(results)
                    queued_file.valid_emails = sum(1 for r in results if r.get('valid', False))
                    queued_file.invalid_emails = queued_file.processed_emails - queued_file.valid_emails
                    
                    # Update global statistics
                    self.stats['total_emails'] += queued_file.total_emails
                    self.stats['total_valid'] += queued_file.valid_emails
                    self.stats['total_invalid'] += queued_file.invalid_emails
                    
                    logger.info(f"✅ Verification Complete: {queued_file.valid_emails} valid, {queued_file.invalid_emails} invalid")
                    
                    # Step 4: Save results to file
                    logger.info(f"💾 Saving results for {queued_file.filename}...")
                    await self._save_results(queued_file)
                    
                    queued_file.status = 'completed'
                    queued_file.completed_at = datetime.now().isoformat()
                    self.stats['completed_files'] += 1
                    
                    logger.info(f"✅ COMPLETED: {queued_file.filename}")
                    logger.info(f"   Valid emails: {queued_file.valid_emails}")
                    logger.info(f"   Invalid emails: {queued_file.invalid_emails}")
                    logger.info(f"   Results saved to: {self.output_dir}")
                    
                    if progress_callback:
                        await progress_callback({
                            'current_file_idx': idx,
                            'total_files': len(self.queue),
                            'current_filename': queued_file.filename,
                            'status': 'completed',
                            'valid': queued_file.valid_emails,
                            'invalid': queued_file.invalid_emails
                        })
                    
                except Exception as e:
                    logger.error(f"❌ Error processing {queued_file.filename}: {e}", exc_info=True)
                    queued_file.status = 'failed'
                    queued_file.error_message = str(e)
                    queued_file.completed_at = datetime.now().isoformat()
                    self.stats['failed_files'] += 1
                    
                    if progress_callback:
                        await progress_callback({
                            'current_file_idx': idx,
                            'total_files': len(self.queue),
                            'current_filename': queued_file.filename,
                            'status': 'failed',
                            'error': str(e)[:100]
                        })
                
                finally:
                    self.processing_history.append(queued_file)
            
            self.stats['end_time'] = datetime.now().isoformat()
            self.is_processing = False
            
            summary = self._generate_summary()
            logger.info(f"\n{'='*80}")
            logger.info(f"✅ QUEUE PROCESSING COMPLETED")
            logger.info(f"{'='*80}")
            logger.info(f"Total Files: {self.stats['total_files']}")
            logger.info(f"Completed: {self.stats['completed_files']}")
            logger.info(f"Failed: {self.stats['failed_files']}")
            logger.info(f"Total Emails: {self.stats['total_emails']}")
            logger.info(f"Valid: {self.stats['total_valid']}")
            logger.info(f"Invalid: {self.stats['total_invalid']}")
            
            return {
                'success': True,
                'message': 'Queue processing completed',
                'summary': summary
            }
        
        except Exception as e:
            logger.error(f"❌ Fatal error in queue processing: {e}", exc_info=True)
            self.is_processing = False
            self.stats['end_time'] = datetime.now().isoformat()
            
            return {
                'success': False,
                'message': f'Queue processing failed: {str(e)}',
                'summary': self._generate_summary()
            }
    
    async def _save_results(self, queued_file: QueuedFile) -> Dict[str, str]:
        """
        Save results for a single file to CSV and JSON.
        This is called after each file is completed.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_filename = Path(queued_file.filename).stem
        
        saved_files = {}
        
        # CSV file - All results
        csv_filename = f"{base_filename}_{timestamp}_results.csv"
        csv_path = self.output_dir / csv_filename
        
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                if queued_file.results:
                    fieldnames = ['Email', 'Status', 'MX', 'SMTP', 'Reason', 'Duration (ms)']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for result in queued_file.results:
                        writer.writerow({
                            'Email': result.get('email', ''),
                            'Status': '✅ VALID' if result.get('valid', False) else '❌ INVALID',
                            'MX': '✅' if result.get('has_mx', False) else '❌',
                            'SMTP': ('✅' if result.get('smtp_accepted', False) 
                                    else '❌ Rejected' if result.get('smtp_rejected', False) 
                                    else '⏱️  Timeout' if result.get('smtp_timeout', False) 
                                    else '⚠️'),
                            'Reason': result.get('reason', 'N/A')[:100],
                            'Duration (ms)': result.get('duration_ms', 0)
                        })
            
            saved_files['csv'] = str(csv_path)
            logger.info(f"✅ Saved CSV: {csv_filename}")
        
        except Exception as e:
            logger.error(f"Error saving CSV: {e}")
        
        # JSON file - Detailed results
        json_filename = f"{base_filename}_{timestamp}_results.json"
        json_path = self.output_dir / json_filename
        
        try:
            json_data = {
                'file_info': {
                    'filename': queued_file.filename,
                    'file_type': queued_file.file_type,
                    'uploaded_at': queued_file.uploaded_at,
                    'started_at': queued_file.started_at,
                    'completed_at': queued_file.completed_at
                },
                'summary': {
                    'total_emails': queued_file.total_emails,
                    'valid_emails': queued_file.valid_emails,
                    'invalid_emails': queued_file.invalid_emails,
                    'valid_percentage': (queued_file.valid_emails / queued_file.total_emails * 100) 
                                       if queued_file.total_emails > 0 else 0
                },
                'results': queued_file.results
            }
            
            with open(json_path, 'w', encoding='utf-8') as jsonfile:
                json.dump(json_data, jsonfile, indent=2, ensure_ascii=False)
            
            saved_files['json'] = str(json_path)
            logger.info(f"✅ Saved JSON: {json_filename}")
        
        except Exception as e:
            logger.error(f"Error saving JSON: {e}")
        
        # Save valid emails only
        if queued_file.valid_emails > 0:
            valid_filename = f"{base_filename}_{timestamp}_valid.txt"
            valid_path = self.output_dir / valid_filename
            
            try:
                valid_emails = [r['email'] for r in queued_file.results if r.get('valid', False)]
                with open(valid_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(valid_emails))
                
                saved_files['valid'] = str(valid_path)
                logger.info(f"✅ Saved valid emails: {valid_filename}")
            except Exception as e:
                logger.error(f"Error saving valid emails: {e}")
        
        # Save invalid emails only
        if queued_file.invalid_emails > 0:
            invalid_filename = f"{base_filename}_{timestamp}_invalid.txt"
            invalid_path = self.output_dir / invalid_filename
            
            try:
                invalid_emails = [r['email'] for r in queued_file.results if not r.get('valid', False)]
                with open(invalid_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(invalid_emails))
                
                saved_files['invalid'] = str(invalid_path)
                logger.info(f"✅ Saved invalid emails: {invalid_filename}")
            except Exception as e:
                logger.error(f"Error saving invalid emails: {e}")
        
        return saved_files
    
    def _generate_summary(self) -> Dict[str, Any]:
        """Generate processing summary"""
        return {
            'total_files': self.stats['total_files'],
            'completed_files': self.stats['completed_files'],
            'failed_files': self.stats['failed_files'],
            'total_emails_processed': self.stats['total_emails'],
            'total_valid_emails': self.stats['total_valid'],
            'total_invalid_emails': self.stats['total_invalid'],
            'overall_valid_percentage': (self.stats['total_valid'] / self.stats['total_emails'] * 100)
                                        if self.stats['total_emails'] > 0 else 0,
            'output_directory': str(self.output_dir),
            'files_processed': [
                {
                    'filename': f.filename,
                    'status': f.status,
                    'valid': f.valid_emails,
                    'invalid': f.invalid_emails,
                    'total': f.total_emails,
                    'error': f.error_message
                }
                for f in self.processing_history
            ]
        }
    
    def clear_queue(self) -> Dict[str, Any]:
        """Clear the queue"""
        cleared_count = len(self.queue)
        self.queue.clear()
        logger.info(f"🗑️  Cleared {cleared_count} files from queue")
        return {
            'success': True,
            'cleared_files': cleared_count,
            'message': f"Cleared {cleared_count} files from queue"
        }
