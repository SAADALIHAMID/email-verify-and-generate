"""Configuration management using Pydantic settings."""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_env: str = Field(default="dev", description="Application environment")
    log_level: str = Field(default="info", description="Logging level")
    
    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="Database connection URL"
    )
    
    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )
    
    # Caching
    cache_ttl_seconds: int = Field(
        default=604800,  # 7 days
        description="Cache TTL in seconds"
    )
    
    # SMTP Settings
    smtp_connect_timeout: int = Field(
        default=30,  # Increased to 30s for very slow servers
        description="SMTP connection timeout in seconds"
    )
    smtp_op_timeout: int = Field(
        default=30,  # Increased to 30s to handle network delays
        description="SMTP operation timeout in seconds"
    )
    fake_local_domain: str = Field(
        default="verify.example.com",
        description="Domain to use for HELO/MAIL FROM"
    )
    
    # DNS Settings
    dns_resolve_timeout: int = Field(
        default=10,  # Increased to 10 seconds for slow nameservers
        description="DNS resolution timeout in seconds"
    )
    
    # Concurrency & Rate Limiting
    max_concurrency: int = Field(
        default=50,  # Reduced for better stability
        description="Maximum concurrent operations"
    )
    rate_limit_per_domain_per_min: int = Field(
        default=5,
        description="Rate limit per domain per minute"
    )
    
    # Retry Settings
    retry_backoff_seconds: str = Field(
        default="15,60,300",
        description="Comma-separated backoff seconds for retries"
    )
    
    @property
    def retry_backoff_list(self) -> List[int]:
        """Parse retry backoff seconds into list of integers."""
        return [int(x.strip()) for x in self.retry_backoff_seconds.split(",")]
    
    # Catch-all Detection
    catch_all_random_localpart_len: int = Field(
        default=16,
        description="Length of random localpart for catch-all detection"
    )
    
    # Feature Toggles
    role_based_check: bool = Field(
        default=True,
        description="Enable role-based email detection"
    )
    
    # Disposable Domains
    disposable_auto_update_url: str = Field(
        default="",
        description="URL to fetch updated disposable domains list"
    )
    
    # API Settings
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    
    # Worker Settings
    worker_concurrency: int = Field(
        default=4,
        description="Number of worker processes"
    )
    
    # Streamlit Settings
    streamlit_port: int = Field(default=8501, description="Streamlit port")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()