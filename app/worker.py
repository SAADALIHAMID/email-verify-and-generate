"""Background worker for processing bulk email verification jobs."""

import asyncio
import logging
import sys
import signal
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
import redis
from rq import Worker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Job, JobStatus, EmailVerification, Base
from app.verify_service import verification_service
from app.job_queue import JobProgressTracker
from app.log_config import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


class EmailVerificationWorker:
    """Worker for processing email verification jobs."""
    
    def __init__(self):
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[Callable] = None
        self.redis_conn: Optional[redis.Redis] = None
        self.progress_tracker: Optional[JobProgressTracker] = None
        self.should_stop = False
    
    async def initialize(self):
        """Initialize database and Redis connections."""
        try:
            # Initialize database
            self.engine = create_async_engine(
                settings.database_url,
                echo=False,
                pool_pre_ping=True
            )
            
            # Create tables if they don't exist
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            self.session_factory = sessionmaker(  # type: ignore[arg-type]
                self.engine,  # type: ignore[arg-type]
                class_=AsyncSession, 
                expire_on_commit=False
            )
            
            # Initialize Redis
            self.redis_conn = redis.from_url(settings.redis_url)
            self.progress_tracker = JobProgressTracker(self.redis_conn)
            
            logger.info("Worker initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize worker: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup connections."""
        if self.engine:
            await self.engine.dispose()
        if self.redis_conn:
            self.redis_conn.close()
        logger.info("Worker cleanup completed")
    
    async def process_bulk_verification(
        self, 
        job_id: str, 
        emails: List[str], 
        job_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process bulk email verification job.
        
        Args:
            job_id: Unique job identifier
            emails: List of email addresses to verify
            job_config: Job configuration parameters
            
        Returns:
            Job completion summary
        """
        logger.info(f"Starting bulk verification job {job_id} with {len(emails)} emails")
        
        try:
            # Ensure connections are initialized
            assert self.session_factory is not None, "Session factory not initialized"
            assert self.progress_tracker is not None, "Progress tracker not initialized"
            
            # Create job record
            async with self.session_factory() as session:
                job = Job(
                    id=job_id,
                    status=JobStatus.PROCESSING,
                    total_count=len(emails),
                    started_at=datetime.utcnow(),
                    config_snapshot=job_config
                )
                session.add(job)
                await session.commit()
            
            # Remove duplicates while preserving order
            unique_emails = []
            seen = set()
            for email in emails:
                email_lower = email.lower().strip()
                if email_lower not in seen:
                    seen.add(email_lower)
                    unique_emails.append(email)
            
            logger.info(f"Processing {len(unique_emails)} unique emails (from {len(emails)} total)")
            
            # Process emails in batches
            batch_size = min(100, settings.max_concurrency)
            processed_count = 0
            stats = {
                'deliverable_count': 0,
                'invalid_count': 0,
                'risky_count': 0,
                'unknown_count': 0,
                'disposable_count': 0
            }
            
            for i in range(0, len(unique_emails), batch_size):
                if self.should_stop:
                    logger.info(f"Job {job_id} stopped by signal")
                    break
                
                batch = unique_emails[i:i + batch_size]
                
                # Verify batch
                results = await verification_service.verify_bulk(batch)
                
                # Store results and update stats
                async with self.session_factory() as session:  # type: ignore[misc]
                    for result in results:
                        # Create verification record
                        verification = EmailVerification(
                            job_id=job_id,
                            email=result.email,
                            email_hash=self._hash_email(result.email),
                            domain=self._extract_domain(result.email),
                            status=result.status,
                            reason_code=result.reason_code,
                            reasons=result.reasons,
                            mx_records=result.mx_records,
                            has_mx=result.has_mx,
                            smtp_transcript=result.smtp_transcript,
                            smtp_accepted=result.smtp_accepted,
                            is_catch_all=result.is_catch_all,
                            is_role_based=result.is_role_based,
                            is_disposable=result.is_disposable,
                            verification_duration_ms=result.verification_duration_ms
                        )
                        session.add(verification)
                        
                        # Update stats
                        if result.status.value == 'DELIVERABLE':
                            stats['deliverable_count'] += 1
                        elif result.status.value == 'INVALID':
                            stats['invalid_count'] += 1
                        elif result.status.value in ['RISKY_CATCH_ALL', 'RISKY_ROLE_BASED']:
                            stats['risky_count'] += 1
                        elif result.status.value == 'UNKNOWN_TEMPFAIL':
                            stats['unknown_count'] += 1
                        elif result.status.value == 'DISPOSABLE':
                            stats['disposable_count'] += 1
                        
                        # Store in Redis for real-time access
                        self.progress_tracker.store_result(job_id, result.email, result)
                    
                    await session.commit()
                
                processed_count += len(results)
                
                # Update progress
                self.progress_tracker.update_progress(
                    job_id, processed_count, len(unique_emails), stats
                )
                
                # Update job record
                async with self.session_factory() as session:  # type: ignore[misc]
                    job = await session.get(Job, job_id)
                    if job:
                        job.processed_count = processed_count
                        job.deliverable_count = stats['deliverable_count']
                        job.invalid_count = stats['invalid_count']
                        job.risky_count = stats['risky_count']
                        job.unknown_count = stats['unknown_count']
                        job.disposable_count = stats['disposable_count']
                        await session.commit()
                
                logger.info(f"Job {job_id}: processed {processed_count}/{len(unique_emails)} emails")
            
            # Mark job as completed
            async with self.session_factory() as session:  # type: ignore[misc]
                job = await session.get(Job, job_id)
                if job:
                    job.status = JobStatus.COMPLETED if not self.should_stop else JobStatus.FAILED
                    job.finished_at = datetime.utcnow()
                    if self.should_stop:
                        job.error_message = "Job stopped by signal"
                    await session.commit()
            
            summary = {
                'job_id': job_id,
                'total_emails': len(emails),
                'unique_emails': len(unique_emails),
                'processed_count': processed_count,
                'completed': not self.should_stop,
                **stats
            }
            
            logger.info(f"Completed job {job_id}: {summary}")
            return summary
            
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            
            # Mark job as failed
            try:
                async with self.session_factory() as session:  # type: ignore[misc]
                    job = await session.get(Job, job_id)
                    if job:
                        job.status = JobStatus.FAILED
                        job.finished_at = datetime.utcnow()
                        job.error_message = str(e)
                        await session.commit()
            except Exception as db_error:
                logger.error(f"Failed to update job status: {db_error}")
            
            raise
    
    def _hash_email(self, email: str) -> str:
        """Create hash of email for privacy in logs."""
        import hashlib
        return hashlib.sha256(email.encode()).hexdigest()[:16]
    
    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address."""
        if '@' in email:
            return email.split('@')[1].lower()
        return ''
    
    def handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, stopping worker...")
        self.should_stop = True


# Global worker instance
worker_instance = EmailVerificationWorker()


async def process_bulk_verification(job_id: str, emails: List[str], job_config: Dict[str, Any]):
    """
    RQ job function for bulk email verification.
    
    This function is called by RQ workers and must be importable.
    """
    return await worker_instance.process_bulk_verification(job_id, emails, job_config)


def run_worker():
    """Run the RQ worker."""
    async def main():
        try:
            # Initialize worker
            await worker_instance.initialize()
            
            # Setup signal handlers
            signal.signal(signal.SIGTERM, worker_instance.handle_signal)
            signal.signal(signal.SIGINT, worker_instance.handle_signal)
            
            # Connect to Redis and start worker
            redis_conn = redis.from_url(settings.redis_url)
            
            # Create worker
            worker = Worker(['email_verification'], connection=redis_conn, name=f'worker-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}')
            logger.info("Starting RQ worker...")
            worker.work()
            
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            await worker_instance.cleanup()
    
    # Run the async main function
    asyncio.run(main())


if __name__ == '__main__':
    run_worker()