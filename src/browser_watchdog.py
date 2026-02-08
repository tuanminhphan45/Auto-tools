"""
Browser Watchdog - Continuous browser health monitoring and auto-recovery
"""
import asyncio
from datetime import datetime
from typing import Callable, Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page


class BrowserSession:
    """Represents a monitored browser session"""

    def __init__(self, email: str, page: Page, context: BrowserContext, browser: Browser):
        self.email = email
        self.page = page
        self.context = context
        self.browser = browser
        self.started_at = datetime.now()
        self.last_check = datetime.now()
        self.is_healthy = True
        self.completed_tasks = 0


class BrowserWatchdog:
    """Background watchdog for browser health monitoring"""
    
    _instance = None
    
    def __init__(self, 
                 min_browsers: int = 2,
                 check_interval: int = 15,
                 max_restart_attempts: int = 3):
        """
        Initialize watchdog.
        
        Args:
            min_browsers: Minimum number of browsers to maintain
            check_interval: Seconds between health checks
            max_restart_attempts: Max restart attempts per account
        """
        self.min_browsers = min_browsers
        self.check_interval = check_interval
        self.max_restart_attempts = max_restart_attempts
        
        self.sessions: Dict[str, BrowserSession] = {}
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_crash_callback: Optional[Callable] = None
        self._on_need_spawn_callback: Optional[Callable] = None
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls, **kwargs) -> 'BrowserWatchdog':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = BrowserWatchdog(**kwargs)
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)"""
        if cls._instance and cls._instance._monitoring:
            cls._instance._monitoring = False
        cls._instance = None
    
    async def register_browser(self, email: str, page: Page, context: BrowserContext, browser: Browser):
        """Register a browser session for monitoring"""
        async with self._lock:
            self.sessions[email] = BrowserSession(email, page, context, browser)
            print(f"👁️ [Watchdog] Registered: {email} (total: {len(self.sessions)})")
    
    async def unregister_browser(self, email: str):
        """Unregister a browser session"""
        async with self._lock:
            if email in self.sessions:
                del self.sessions[email]
                print(f"👁️ [Watchdog] Unregistered: {email} (remaining: {len(self.sessions)})")
    
    async def update_task_count(self, email: str, completed: int):
        """Update completed task count for a session"""
        async with self._lock:
            if email in self.sessions:
                self.sessions[email].completed_tasks = completed
    
    async def health_check(self, email: str) -> bool:
        """
        Check if a browser session is still healthy.
        Returns True if healthy, False if crashed/disconnected.
        """
        async with self._lock:
            if email not in self.sessions:
                return False
            
            session = self.sessions[email]
            
            try:
                # Check 1: Browser still connected
                if not session.browser.is_connected():
                    print(f"💥 [Watchdog] {email} - Browser disconnected")
                    return False
                
                # Check 2: Page not closed
                if session.page.is_closed():
                    print(f"💥 [Watchdog] {email} - Page closed")
                    return False
                
                # Check 3: Context still has pages
                if len(session.context.pages) == 0:
                    print(f"💥 [Watchdog] {email} - Context has no pages")
                    return False
                
                # All checks passed
                session.last_check = datetime.now()
                session.is_healthy = True
                return True
                
            except Exception as e:
                print(f"💥 [Watchdog] {email} - Health check error: {e}")
                session.is_healthy = False
                return False
    
    async def _monitor_loop(self):
        """Background monitoring loop"""
        print(f"👁️ [Watchdog] Started monitoring (interval: {self.check_interval}s, min: {self.min_browsers})")
        
        while self._monitoring:
            try:
                await asyncio.sleep(self.check_interval)
                
                if not self._monitoring:
                    break
                
                # Check all registered sessions
                crashed_emails = []
                async with self._lock:
                    emails = list(self.sessions.keys())
                
                for email in emails:
                    is_healthy = await self.health_check(email)
                    if not is_healthy:
                        crashed_emails.append(email)
                
                # Handle crashed sessions
                for email in crashed_emails:
                    await self.unregister_browser(email)
                    if self._on_crash_callback:
                        try:
                            await self._on_crash_callback(email)
                        except Exception as e:
                            print(f"⚠️ [Watchdog] Crash callback error: {e}")
                
                # Check if we need more browsers
                active_count = self.get_active_count()
                if active_count < self.min_browsers and self._on_need_spawn_callback:
                    needed = self.min_browsers - active_count
                    print(f"👁️ [Watchdog] Need {needed} more browser(s)")
                    try:
                        await self._on_need_spawn_callback(needed)
                    except Exception as e:
                        print(f"⚠️ [Watchdog] Spawn callback error: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Watchdog] Monitor loop error: {e}")
        
        print("👁️ [Watchdog] Stopped monitoring")
    
    async def start_monitoring(self):
        """Start background monitoring"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop_monitoring(self):
        """Stop background monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
    
    def get_active_count(self) -> int:
        """Return number of active (healthy) browser sessions"""
        return len([s for s in self.sessions.values() if s.is_healthy])
    
    def get_active_emails(self) -> list:
        """Return list of emails with active sessions"""
        return [s.email for s in self.sessions.values() if s.is_healthy]
    
    def on_crash_detected(self, callback: Callable):
        """Register callback when crash detected. Callback signature: async def callback(email: str)"""
        self._on_crash_callback = callback
    
    def on_need_spawn(self, callback: Callable):
        """Register callback when more browsers needed. Callback signature: async def callback(count: int)"""
        self._on_need_spawn_callback = callback
    
    def print_status(self):
        """Print current watchdog status"""
        print(f"\n{'='*50}")
        print(f"   👁️ BROWSER WATCHDOG STATUS")
        print(f"{'='*50}")
        print(f"   Active sessions: {self.get_active_count()}/{self.min_browsers}")
        print(f"   Monitoring: {'🟢 ON' if self._monitoring else '🔴 OFF'}")
        for email, session in self.sessions.items():
            status = "🟢" if session.is_healthy else "💥"
            print(f"   {status} {email}: {session.completed_tasks} tasks")
        print(f"{'='*50}\n")
