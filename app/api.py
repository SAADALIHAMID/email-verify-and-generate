import logging
import uuid
import time
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import io
import csv

# Essential Internal Imports
from app.config import settings
from app.models import Base, Job, JobStatus, EmailVerification
from app.schemas import (
    VerifyEmailRequest, VerifyEmailResponse, BulkVerifyRequest,
    JobCreateResponse, JobResponse, JobResultsResponse, HealthResponse,
    JobStats, MetricsResponse
)
from app.verify_service import verify_single_email
from app.metrics import MetricsMiddleware, get_system_metrics

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Email Verification System", version="1.0.0")

# CORS Setup - Very important for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)

# Database Engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker # async_sessionmaker zaroori hai

# 1. Engine setup (theek hai)
engine = create_async_engine(
    settings.database_url, 
    echo=False,
    pool_pre_ping=True
)

# 2. FIXED: async_sessionmaker ka istemal karein taake 'AsyncSession' mile
SessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# 3. FIXED: Dependency mein 'async with' ab kaam karega
async def get_db():
    """Dependency to get database session."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            # async with khud hi close kar deta hai, 
            # par safety ke liye yahan extra logic rakh sakte hain
            await session.close()

# --- FIXED VERIFY ENDPOINT ---
@app.post("/verify", response_model=VerifyEmailResponse)
async def verify_email(request: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    start_time = time.time()
    print(f"\n[📥] Incoming Request: {request.email}")
    
    try:
        # Business logic call
        result = await verify_single_email(request.email)
        
        duration = (time.time() - start_time) * 1000
        print(f"[✅] Finished: {request.email} | Status: {result.status.value} | Time: {duration:.0f}ms")
        
        return VerifyEmailResponse(result=result)
    except Exception as e:
        print(f"[❌] Error: {str(e)}")
        logger.error(f"Verification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.get("/")
async def root():
    return {"message": "Server is up"}

if __name__ == "__main__":
    import uvicorn
    # 8000 ki jagah 8005 kar dein (ya koi bhi random number)
    uvicorn.run(app, host="127.0.0.1", port=8005)