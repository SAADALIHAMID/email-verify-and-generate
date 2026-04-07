"""Export functionality for verification results - CSV/JSON with deliverable/invalid splits."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, IO
from io import StringIO
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Job, EmailVerification, VerificationStatus
from app.schemas import VerificationResult

logger = logging.getLogger(__name__)


class ResultExporter:
    """Export verification results in various formats."""
    
    def __init__(self):
        self.csv_headers = [
            'email', 'status', 'reason_code', 'reasons', 'mx_records',
            'has_mx', 'smtp_accepted', 'is_catch_all', 'is_role_based',
            'is_disposable', 'verification_duration_ms', 'timestamp'
        ]
    
    async def export_job_results(
        self, 
        session: AsyncSession,
        job_id: str, 
        format_type: str = 'csv',
        filter_status: Optional[str] = None
    ) -> Optional[str]:
        """
        Export job results to string format.
        
        Args:
            session: Database session
            job_id: Job ID to export
            format_type: 'csv' or 'json'
            filter_status: Optional status filter ('deliverable', 'invalid', etc.)
            
        Returns:
            Exported data as string or None if error
        """
        try:
            # Get job
            job = await session.get(Job, job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return None
            
            # Build query
            query = select(EmailVerification).where(EmailVerification.job_id == job_id)
            
            # Apply status filter
            if filter_status:
                status_mapping = {
                    'deliverable': [VerificationStatus.DELIVERABLE],
                    'invalid': [VerificationStatus.INVALID],
                    'risky': [VerificationStatus.RISKY_CATCH_ALL, VerificationStatus.RISKY_ROLE_BASED],
                    'unknown': [VerificationStatus.UNKNOWN_TEMPFAIL],
                    'disposable': [VerificationStatus.DISPOSABLE]
                }
                
                if filter_status in status_mapping:
                    query = query.where(EmailVerification.status.in_(status_mapping[filter_status]))
            
            # Execute query
            result = await session.execute(query.order_by(EmailVerification.created_at))
            verifications = result.scalars().all()
            
            if format_type.lower() == 'json':
                return self._export_json(verifications)
            elif format_type.lower() == 'csv':
                return self._export_csv(verifications)
            else:
                logger.error(f"Unsupported format: {format_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error exporting job {job_id}: {e}")
            return None
    
    def _export_csv(self, verifications) -> str:
        """Export verifications to CSV format."""
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(self.csv_headers)
        
        # Write data
        for verification in verifications:
            reasons_list = verification.reasons if isinstance(verification.reasons, list) else []
            mx_list = verification.mx_records if isinstance(verification.mx_records, list) else []
            # Safely join reasons
            reasons_str = '; '.join(str(r) for r in reasons_list) if reasons_list else ''
            # Safely join MX records
            mx_str = '; '.join(str(m) for m in mx_list) if mx_list else ''
            row = [
                verification.email,
                verification.status.value,
                verification.reason_code.value,
                reasons_str,
                mx_str,
                verification.has_mx,
                verification.smtp_accepted,
                verification.is_catch_all,
                verification.is_role_based,
                verification.is_disposable,
                verification.verification_duration_ms,
                verification.created_at.isoformat() if verification.created_at else ''
            ]
            writer.writerow(row)
        
        return output.getvalue()
    
    def _export_json(self, verifications) -> str:
        """Export verifications to JSON format."""
        data = []
        
        for verification in verifications:
            item = {
                'email': verification.email,
                'status': verification.status.value,
                'reason_code': verification.reason_code.value,
                'reasons': verification.reasons,
                'mx_records': verification.mx_records,
                'has_mx': verification.has_mx,
                'smtp_accepted': verification.smtp_accepted,
                'is_catch_all': verification.is_catch_all,
                'is_role_based': verification.is_role_based,
                'is_disposable': verification.is_disposable,
                'verification_duration_ms': verification.verification_duration_ms,
                'timestamp': verification.created_at.isoformat() if verification.created_at else None
            }
            data.append(item)
        
        return json.dumps(data, indent=2)
    
    def export_email_list(
        self, 
        verifications: List[EmailVerification],
        status_filter: Optional[List[VerificationStatus]] = None
    ) -> str:
        """
        Export just email addresses as plain text list.
        
        Args:
            verifications: List of verification records
            status_filter: Optional list of statuses to include
            
        Returns:
            Plain text list of email addresses
        """
        emails = []
        
        for verification in verifications:
            if status_filter is None or verification.status in status_filter:
                emails.append(verification.email)
        
        return '\n'.join(emails)
    
    async def export_deliverable_emails(
        self, 
        session: AsyncSession,
        job_id: str
    ) -> Optional[str]:
        """Export only deliverable email addresses."""
        try:
            query = select(EmailVerification).where(
                EmailVerification.job_id == job_id,
                EmailVerification.status == VerificationStatus.DELIVERABLE
            ).order_by(EmailVerification.created_at)
            
            result = await session.execute(query)
            verifications = list(result.scalars().all())
            
            return self.export_email_list(verifications)
            
        except Exception as e:
            logger.error(f"Error exporting deliverable emails for job {job_id}: {e}")
            return None
    
    async def export_invalid_emails(
        self, 
        session: AsyncSession,
        job_id: str
    ) -> Optional[str]:
        """Export invalid email addresses with reasons."""
        try:
            query = select(EmailVerification).where(
                EmailVerification.job_id == job_id,
                EmailVerification.status == VerificationStatus.INVALID
            ).order_by(EmailVerification.created_at)
            
            result = await session.execute(query)
            verifications = result.scalars().all()
            
            # Export as CSV with email and reason
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['email', 'reason_code', 'reasons'])
            
            for verification in verifications:
                # Check if reasons exist and is a list
                if isinstance(verification.reasons, list):
                    reasons_str = '; '.join(str(r) for r in verification.reasons)
                else:
                    reasons_str = ''
                writer.writerow([
                    verification.email,
                    verification.reason_code.value,
                    reasons_str
                ])
            
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"Error exporting invalid emails for job {job_id}: {e}")
            return None
    
    def export_results_to_files(
        self, 
        results: List[VerificationResult],
        output_dir: Path,
        job_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Export results to multiple files.
        
        Args:
            results: List of verification results
            output_dir: Directory to save files
            job_id: Optional job ID for filename prefix
            
        Returns:
            Dictionary mapping file type to file path
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"job_{job_id}_" if job_id else f"verification_{timestamp}_"
        
        file_paths = {}
        
        try:
            # All results CSV
            all_csv_path = output_dir / f"{prefix}all.csv"
            with open(all_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.csv_headers)
                
                for result in results:
                    row = [
                        result.email,
                        result.status.value,
                        result.reason_code.value,
                        '; '.join(result.reasons),
                        '; '.join(result.mx_records),
                        result.has_mx,
                        result.smtp_accepted,
                        result.is_catch_all,
                        result.is_role_based,
                        result.is_disposable,
                        result.verification_duration_ms,
                        result.timestamp.isoformat()
                    ]
                    writer.writerow(row)
            
            file_paths['all_csv'] = str(all_csv_path)
            
            # Deliverable emails only
            deliverable_path = output_dir / f"{prefix}deliverable.txt"
            deliverable_emails = [
                r.email for r in results 
                if r.status == VerificationStatus.DELIVERABLE
            ]
            
            with open(deliverable_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(deliverable_emails))
            
            file_paths['deliverable_txt'] = str(deliverable_path)
            
            # Invalid emails with reasons
            invalid_path = output_dir / f"{prefix}invalid.csv"
            with open(invalid_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['email', 'reason_code', 'reasons'])
                
                for result in results:
                    if result.status == VerificationStatus.INVALID:
                        writer.writerow([
                            result.email,
                            result.reason_code.value,
                            '; '.join(result.reasons)
                        ])
            
            file_paths['invalid_csv'] = str(invalid_path)
            
            # Risky emails
            risky_path = output_dir / f"{prefix}risky.csv"
            with open(risky_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['email', 'status', 'reason_code', 'reasons'])
                
                for result in results:
                    if result.status in [VerificationStatus.RISKY_CATCH_ALL, VerificationStatus.RISKY_ROLE_BASED]:
                        writer.writerow([
                            result.email,
                            result.status.value,
                            result.reason_code.value,
                            '; '.join(result.reasons)
                        ])
            
            file_paths['risky_csv'] = str(risky_path)
            
            # Summary statistics
            summary_path = output_dir / f"{prefix}summary.json"
            stats = self._calculate_summary_stats(results)
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2)
            
            file_paths['summary_json'] = str(summary_path)
            
            logger.info(f"Exported {len(results)} results to {len(file_paths)} files")
            return file_paths
            
        except Exception as e:
            logger.error(f"Error exporting results to files: {e}")
            return {}
    
    def _calculate_summary_stats(self, results: List[VerificationResult]) -> Dict[str, Any]:
        """Calculate summary statistics for results."""
        if not results:
            return {}
        
        stats = {
            'total_emails': len(results),
            'deliverable': 0,
            'invalid': 0,
            'risky_catch_all': 0,
            'risky_role_based': 0,
            'unknown_tempfail': 0,
            'disposable': 0,
            'domains': set(),
            'avg_duration_ms': 0,
            'export_timestamp': datetime.utcnow().isoformat()
        }
        
        total_duration = 0
        
        for result in results:
            # Count by status
            if result.status == VerificationStatus.DELIVERABLE:
                stats['deliverable'] += 1
            elif result.status == VerificationStatus.INVALID:
                stats['invalid'] += 1
            elif result.status == VerificationStatus.RISKY_CATCH_ALL:
                stats['risky_catch_all'] += 1
            elif result.status == VerificationStatus.RISKY_ROLE_BASED:
                stats['risky_role_based'] += 1
            elif result.status == VerificationStatus.UNKNOWN_TEMPFAIL:
                stats['unknown_tempfail'] += 1
            elif result.status == VerificationStatus.DISPOSABLE:
                stats['disposable'] += 1
            
            # Track duration
            if result.verification_duration_ms:
                total_duration += result.verification_duration_ms
            
            # Track domains
            if '@' in result.email:
                domain = result.email.split('@')[1].lower()
                stats['domains'].add(domain)
        
        # Calculate percentages and averages
        if stats['total_emails'] > 0:
            stats['deliverable_rate'] = (stats['deliverable'] / stats['total_emails']) * 100
            stats['invalid_rate'] = (stats['invalid'] / stats['total_emails']) * 100
            stats['risky_rate'] = ((stats['risky_catch_all'] + stats['risky_role_based']) / stats['total_emails']) * 100
        
        if total_duration > 0:
            stats['avg_duration_ms'] = total_duration // len(results)
        
        stats['unique_domains'] = len(stats['domains'])
        stats['domains'] = list(stats['domains'])  # Convert set to list for JSON serialization
        
        return stats


# Global exporter instance
exporter = ResultExporter()


async def export_job_to_csv(session: AsyncSession, job_id: str, filter_status: Optional[str] = None) -> Optional[str]:
    """Export job results to CSV (convenience function)."""
    return await exporter.export_job_results(session, job_id, 'csv', filter_status)


async def export_job_to_json(session: AsyncSession, job_id: str, filter_status: Optional[str] = None) -> Optional[str]:
    """Export job results to JSON (convenience function)."""
    return await exporter.export_job_results(session, job_id, 'json', filter_status)


def export_results_to_directory(
    results: List[VerificationResult],
    output_dir: str,
    job_id: Optional[str] = None
) -> Dict[str, str]:
    """Export results to directory (convenience function)."""
    return exporter.export_results_to_files(results, Path(output_dir), job_id)