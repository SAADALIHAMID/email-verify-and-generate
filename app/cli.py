"""Command-line interface for email verification system."""

import asyncio
import csv
import io
import json
from pathlib import Path
from typing import List, Optional, Tuple, Any
import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

from app.config import settings
from app.verify_service import verify_single_email, verify_email_list
from app.export import export_results_to_directory
from app.pipeline.disposable import update_disposable_domains
from app.models import Base
from app.log_config import setup_logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import select, delete, text

# Setup
setup_logging()
console = Console()
app = typer.Typer(help="Email Verification System CLI")


async def get_async_session(engine: AsyncEngine) -> AsyncSession:
    """Create and return an async session."""
    async_session_factory = sessionmaker(
        class_=AsyncSession,
        expire_on_commit=False
    )
    return async_session_factory(bind=engine)  # type: ignore


@app.command()
def verify(
    email: str = typer.Argument(..., help="Email address to verify"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output")
) -> None:
    """Verify a single email address."""
    
    async def _verify() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(f"Verifying {email}...", total=None)
                result = await verify_single_email(email)
                progress.remove_task(task)
            
            if json_output:
                output = {
                    "email": result.email,
                    "status": result.status.value,
                    "reason_code": result.reason_code.value,
                    "reasons": result.reasons,
                    "mx_records": result.mx_records,
                    "has_mx": result.has_mx,
                    "smtp_accepted": result.smtp_accepted,
                    "is_catch_all": result.is_catch_all,
                    "is_role_based": result.is_role_based,
                    "is_disposable": result.is_disposable,
                    "verification_duration_ms": result.verification_duration_ms,
                    "timestamp": result.timestamp.isoformat()
                }
                console.print_json(json.dumps(output, indent=2))
            else:
                status_color = {
                    "DELIVERABLE": "green",
                    "INVALID": "red",
                    "RISKY_CATCH_ALL": "yellow",
                    "RISKY_ROLE_BASED": "yellow",
                    "UNKNOWN_TEMPFAIL": "blue",
                    "DISPOSABLE": "magenta"
                }.get(result.status.value, "white")
                
                table = Table(title=f"Verification Result for {email}")
                table.add_column("Property", style="cyan")
                table.add_column("Value")
                
                table.add_row("Status", f"[{status_color}]{result.status.value}[/{status_color}]")
                table.add_row("Reason Code", result.reason_code.value)
                table.add_row("Reasons", "\n".join(result.reasons))
                table.add_row("MX Records", "\n".join(result.mx_records))
                table.add_row("SMTP Accepted", "✓" if result.smtp_accepted else "✗")
                table.add_row("Catch-all", "✓" if result.is_catch_all else "✗")
                table.add_row("Role-based", "✓" if result.is_role_based else "✗")
                table.add_row("Disposable", "✓" if result.is_disposable else "✗")
                table.add_row("Duration", f"{result.verification_duration_ms}ms")
                
                console.print(table)
                
                if verbose and result.smtp_transcript:
                    console.print("\n[bold]SMTP Transcript:[/bold]")
                    for line in result.smtp_transcript:
                        console.print(f"  {line}")
        
        except Exception as e:
            console.print(f"[red]Error verifying {email}: {e}[/red]")
            raise typer.Exit(1)
    
    asyncio.run(_verify())


@app.command()
def verify_file(
    file_path: str = typer.Argument(..., help="Path to file with email addresses"),
    export_dir: str = typer.Option("./results", "--export-dir", help="Directory to save results"),
    max_concurrency: Optional[int] = typer.Option(None, "--concurrency", help="Maximum concurrent verifications"),
    json_output: bool = typer.Option(False, "--json", help="Also output JSON summary")
) -> None:
    """Verify email addresses from a file."""
    
    async def _verify_file() -> None:
        try:
            if not file_path:
                console.print("[red]File path is required[/red]")
                raise typer.Exit(1)
            
            file_path_obj: Path = Path(file_path)
            
            if not file_path_obj.exists():
                console.print(f"[red]File not found: {file_path}[/red]")
                raise typer.Exit(1)
            
            emails: List[str] = []
            # Try multiple encodings
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'gb2312', 'gbk']
            file_content = None
            
            for encoding in encodings:
                try:
                    with open(file_path_obj, 'r', encoding=encoding) as f:
                        file_content = f.read()
                    console.print(f"[green]✓ File read successfully with encoding: {encoding}[/green]")
                    break
                except (UnicodeDecodeError, Exception) as e:
                    continue
            
            if file_content is None:
                console.print("[red]❌ Could not read file with any supported encoding[/red]")
                raise typer.Exit(1)
            
            if file_path.endswith('.csv'):
                # Parse CSV
                import io
                csv_file = io.StringIO(file_content)
                reader = csv.DictReader(csv_file)
                
                if reader.fieldnames is None:
                    console.print("[red]CSV file has no headers[/red]")
                    raise typer.Exit(1)
                
                if 'email' in reader.fieldnames:
                    emails = [row['email'].strip() for row in reader if row.get('email', '').strip()]
                else:
                    # Try first column
                    csv_file.seek(0)
                    csv_reader = csv.reader(csv_file)
                    emails = [row[0].strip() for row in csv_reader if row and row[0].strip() and '@' in row[0]]
            else:
                # Parse text file
                emails = [line.strip() for line in file_content.split('\n') if line.strip() and '@' in line]
            
            # Remove duplicates and validate
            emails = list(set([e for e in emails if '@' in e and len(e) > 3 and '.' in e.split('@')[-1]]))
            
            if not emails:
                console.print("[yellow]⚠️ No valid emails found in file[/yellow]")
                raise typer.Exit(1)
            
            console.print(f"Found {len(emails)} emails to verify")
            
            original_concurrency: Optional[int] = None
            if max_concurrency:
                original_concurrency = settings.max_concurrency
                settings.max_concurrency = max_concurrency
            
            with Progress(console=console) as progress:
                task = progress.add_task("Verifying emails...", total=len(emails))
                
                results = []
                batch_size = 50
                
                for i in range(0, len(emails), batch_size):
                    batch = emails[i : i + batch_size]
                    batch_results = await verify_email_list(batch)
                    results.extend(batch_results)
                    progress.update(task, advance=len(batch))
            
            if original_concurrency is not None:
                settings.max_concurrency = original_concurrency
            
            export_dir_path: str = str(Path(export_dir))
            file_paths = export_results_to_directory(results, export_dir_path)
            
            stats = {
                'total': len(results),
                'deliverable': sum(1 for r in results if r.status.value == 'DELIVERABLE'),
                'invalid': sum(1 for r in results if r.status.value == 'INVALID'),
                'risky': sum(1 for r in results if r.status.value in ['RISKY_CATCH_ALL', 'RISKY_ROLE_BASED']),
                'unknown': sum(1 for r in results if r.status.value == 'UNKNOWN_TEMPFAIL'),
                'disposable': sum(1 for r in results if r.status.value == 'DISPOSABLE')
            }
            
            table = Table(title="Verification Summary")
            table.add_column("Status", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Percentage", justify="right")
            
            for status, count in stats.items():
                if status == 'total':
                    continue
                percentage = (count / stats['total'] * 100) if stats['total'] > 0 else 0
                
                color = {
                    'deliverable': 'green',
                    'invalid': 'red',
                    'risky': 'yellow',
                    'unknown': 'blue',
                    'disposable': 'magenta'
                }.get(status, 'white')
                
                table.add_row(
                    status.title(),
                    f"[{color}]{count}[/{color}]",
                    f"{percentage:.1f}%"
                )
            
            table.add_row("Total", str(stats['total']), "100.0%", style="bold")
            console.print(table)
            
            console.print(f"\n[green]Results exported to {export_dir}:[/green]")
            for file_type, file_path_result in file_paths.items():
                console.print(f"  {file_type}: {file_path_result}")
            
            if json_output:
                console.print("\n[bold]JSON Summary:[/bold]")
                console.print_json(json.dumps(stats, indent=2))
        
        except FileNotFoundError:
            console.print(f"[red]Error: File not found - {file_path}[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Error processing file: {e}[/red]")
            raise typer.Exit(1)
    
    asyncio.run(_verify_file())


@app.command()
def refresh_disposable(
    url: Optional[str] = typer.Option(None, "--url", help="URL to fetch disposable domains from"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Create backup of current list")
) -> None:
    """Refresh the disposable domains list."""
    
    async def _refresh() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Updating disposable domains...", total=None)
                success = await update_disposable_domains(url)
                progress.remove_task(task)
            
            if success:
                console.print("[green]✓ Disposable domains updated successfully[/green]")
            else:
                console.print("[red]✗ Failed to update disposable domains[/red]")
                raise typer.Exit(1)
        
        except Exception as e:
            console.print(f"[red]Error updating disposable domains: {e}[/red]")
            raise typer.Exit(1)
    
    asyncio.run(_refresh())


@app.command()
def init_db() -> None:
    """Initialize the database (create tables)."""
    
    async def _init_db() -> None:
        try:
            engine = create_async_engine(settings.database_url)
            
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            await engine.dispose()
            console.print("[green]✓ Database initialized successfully[/green]")
        
        except Exception as e:
            console.print(f"[red]Error initializing database: {e}[/red]")
            raise typer.Exit(1)
    
    asyncio.run(_init_db())


@app.command()
def config() -> None:
    """Show current configuration."""
    
    table = Table(title="Email Verification System Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    
    config_items = [
        ("App Environment", settings.app_env),
        ("Log Level", settings.log_level),
        ("Database URL", settings.database_url),
        ("Redis URL", settings.redis_url),
        ("Cache TTL", f"{settings.cache_ttl_seconds}s"),
        ("SMTP Connect Timeout", f"{settings.smtp_connect_timeout}s"),
        ("SMTP Operation Timeout", f"{settings.smtp_op_timeout}s"),
        ("DNS Timeout", f"{settings.dns_resolve_timeout}s"),
        ("Max Concurrency", str(settings.max_concurrency)),
        ("Rate Limit per Domain", f"{settings.rate_limit_per_domain_per_min}/min"),
        ("Fake Local Domain", settings.fake_local_domain),
        ("Role-based Check", "Enabled" if settings.role_based_check else "Disabled"),
        ("Retry Backoff", settings.retry_backoff_seconds),
    ]
    
    for setting, value in config_items:
        if "password" in setting.lower() or "secret" in setting.lower():
            value = "***"
        elif len(str(value)) > 50:
            value = str(value)[:47] + "..."
        
        table.add_row(setting, str(value))
    
    console.print(table)


@app.command()
def test_connection() -> None:
    """Test connections to external services."""
    
    async def _test() -> None:
        console.print("[bold]Testing connections...[/bold]\n")
        
        try:
            engine = create_async_engine(settings.database_url)
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            console.print("[green]✓ Database connection successful[/green]")
        except Exception as e:
            console.print(f"[red]✗ Database connection failed: {e}[/red]")
        
        try:
            import redis.asyncio as redis_async
            r = redis_async.from_url(settings.redis_url)
            await r.ping()
            await r.close()
            console.print("[green]✓ Redis connection successful[/green]")
        except Exception as e:
            console.print(f"[red]✗ Redis connection failed: {e}[/red]")
        
        try:
            import socket
            socket.gethostbyname("gmail.com")
            console.print("[green]✓ DNS resolution working[/green]")
        except (socket.gaierror, OSError) as e:
            console.print(f"[yellow]⚠ DNS resolution may have issues: {e}[/yellow]")
    
    asyncio.run(_test())


@app.command("create-api-key")
def create_api_key(
    name: str = typer.Argument(..., help="Name for the API key"),
    description: str = typer.Option("", help="Optional description"),
    rate_limit: int = typer.Option(1000, help="Requests per hour limit"),
    admin: bool = typer.Option(False, help="Grant admin permissions"),
    expires_days: Optional[int] = typer.Option(None, help="Expire after N days")
) -> None:
    """Create a new API key."""
    
    async def _create() -> None:
        from app.models import APIKey
        from app.auth import api_auth
        from datetime import datetime, timedelta
        
        engine = create_async_engine(settings.database_url)
        
        try:
            db = await get_async_session(engine)
            
            api_key, key_hash = api_auth.generate_api_key()
            key_prefix = api_auth.get_key_prefix(api_key)
            
            permissions = ["*"] if admin else [
                "POST:/verify", "POST:/verify-bulk", "GET:/health"
            ]
            
            expires_at = None
            if expires_days:
                expires_at = datetime.utcnow() + timedelta(days=expires_days)
            
            api_key_obj = APIKey(
                key_hash=key_hash,
                key_prefix=key_prefix,
                name=name,
                description=description,
                rate_limit_per_hour=rate_limit,
                expires_at=expires_at,
                permissions=permissions,
                is_active=True
            )
            
            db.add(api_key_obj)
            await db.commit()
            await db.refresh(api_key_obj)
            
            console.print(Panel.fit(
                f"[green]✓ API Key Created Successfully![/green]\n\n"
                f"[bold]API Key:[/bold] {api_key}\n"
                f"[bold]Name:[/bold] {name}\n"
                f"[bold]ID:[/bold] {api_key_obj.id}\n"
                f"[bold]Rate Limit:[/bold] {rate_limit} requests/hour\n"
                f"[bold]Permissions:[/bold] {', '.join(permissions)}\n"
                f"[bold]Expires:[/bold] {expires_at.isoformat() if expires_at else 'Never'}\n\n"
                f"[yellow]⚠️  Save this API key securely. It won't be shown again![/yellow]",
                title="API Key Created"
            ))
            
            console.print("\n[bold]Usage Example:[/bold]")
            console.print(f"curl -H 'X-API-Key: {api_key}' \\")
            console.print(f"     -X POST http://localhost:8000/verify \\")
            console.print(f"     -d '{{\"email\": \"test@example.com\"}}'")
        
        finally:
            await engine.dispose()
    
    asyncio.run(_create())


@app.command("list-api-keys")
def list_api_keys() -> None:
    """List all API keys."""
    
    async def _list() -> None:
        from app.models import APIKey
        
        engine = create_async_engine(settings.database_url)
        
        try:
            db = await get_async_session(engine)
            
            result = await db.execute(select(APIKey).order_by(APIKey.created_at.desc()))
            api_keys = result.scalars().all()
            
            if not api_keys:
                console.print("[yellow]No API keys found.[/yellow]")
                return
            
            table = Table(title="API Keys")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Key Prefix", style="blue")
            table.add_column("Requests", style="yellow")
            table.add_column("Status", style="red")
            table.add_column("Created", style="magenta")
            table.add_column("Last Used", style="white")
            
            for key in api_keys:
                # Use is_() for SQLAlchemy Column boolean checks
                is_active: bool = key.is_active is True
                status: str = "✓ Active" if is_active else "✗ Inactive"
                
                # Check if last_used_at is not None
                has_last_used: bool = key.last_used_at is not None
                last_used: str = key.last_used_at.strftime("%Y-%m-%d %H:%M") if has_last_used else "Never"
                
                table.add_row(
                    str(key.id),
                    str(key.name),
                    str(key.key_prefix),
                    str(key.requests_count),
                    status,
                    key.created_at.strftime("%Y-%m-%d"),
                    last_used
                )
            
            console.print(table)
        
        finally:
            await engine.dispose()
    
    asyncio.run(_list())


@app.command("delete-api-key")
def delete_api_key(
    key_id: int = typer.Argument(..., help="API key ID to delete"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation")
) -> None:
    """Delete an API key."""
    
    async def _delete() -> None:
        from app.models import APIKey
        
        engine = create_async_engine(settings.database_url)
        
        try:
            db = await get_async_session(engine)
            
            result = await db.execute(select(APIKey).where(APIKey.id == key_id))
            api_key = result.scalar_one_or_none()
            
            if not api_key:
                console.print(f"[red]API key with ID {key_id} not found.[/red]")
                return
            
            if not confirm:
                confirm_delete = typer.confirm(f"Delete API key '{api_key.name}' ({api_key.key_prefix})?")
                if not confirm_delete:
                    console.print("Deletion cancelled.")
                    return
            
            await db.execute(delete(APIKey).where(APIKey.id == key_id))
            await db.commit()
            
            console.print(f"[green]✓ API key '{api_key.name}' deleted successfully.[/green]")
        
        finally:
            await engine.dispose()
    
    asyncio.run(_delete())


if __name__ == "__main__":
    app()