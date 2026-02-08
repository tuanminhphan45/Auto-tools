"""
Multi-Account Runner with Browser Watchdog
Đảm bảo luôn có 2 Chromium chạy, auto-detect crash và recovery

Usage:
    python run_watchdog.py
"""
import asyncio
import os
import re
from collections import deque
from typing import Dict, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

import config as cfg
from src.account_monitor import AccountMonitor
from src.browser_watchdog import BrowserWatchdog
from src.data_manager import DataManager
from src.kpi_manager import KPIManager
from src.logger_utils import ColoredLogger as log
from src.snorkel_bot import SnorkelBot
from src.task_logger import TaskLogger
from src.work_hours_scheduler import WorkHoursScheduler

# Map action to Status (Platform) value
ACTION_TO_STATUS = {
    "ACCEPT": "Accept",
    "REJECT": "Reject",
    "REVISE": "Needs Revision",  # Fixed: was "REVISION", should be "REVISE"
    "UNSURE": "Unsure",
    "SKIP": "Skip this task"
}


class WatchdogRunner:
    """Runner with continuous browser monitoring"""
    
    def __init__(self, config: dict):
        self.config = config
        self.accounts = config['accounts']
        self.headless = config['headless']
        # Dual-queue system: incomplete accounts have absolute priority
        self.incomplete_queue = deque()  # Priority 1: Accounts that crashed with incomplete quota
        self.normal_queue = deque()      # Priority 2: Normal rotation queue
        self.running_tasks: Dict[str, asyncio.Task] = {}  # email -> task
        self.passwords: Dict[str, str] = {}  # email -> password
        self.account_kpis: Dict[str, int] = {}  # email -> KPI target
        self.data_manager: Optional[DataManager] = None
        self.watchdog: Optional[BrowserWatchdog] = None
        self.monitor: Optional[AccountMonitor] = None
        self.kpi_manager: Optional[KPIManager] = None
        self.work_hours: Optional[WorkHoursScheduler] = None
        self.playwright = None
        self._running = False
        self._lock = asyncio.Lock()
        self.rotation = 1
        
    async def initialize(self):
        """Initialize components"""
        # Store passwords, KPIs, and initialize normal queue
        for acc in self.accounts:
            email = acc['email']
            self.passwords[email] = acc['password']
            self.account_kpis[email] = acc.get('kpi', 100)  # Default 100 if not specified
        
        # Initialize KPI Manager
        self.kpi_manager = KPIManager.get_instance("completed_tasks.xlsx")
        for email, kpi in self.account_kpis.items():
            self.kpi_manager.set_kpi(email, kpi)
        
        # Refresh progress from completed_tasks.xlsx
        self.kpi_manager.refresh_progress()
        
        # Initialize Work Hours Scheduler
        self.work_hours = WorkHoursScheduler.get_instance(
            start_hour=cfg.WORK_HOURS_START,
            end_hour=cfg.WORK_HOURS_END,
            enabled=cfg.ENABLE_WORK_HOURS
        )
        
        # Only add accounts to normal_queue if they haven't met KPI
        for email in self.account_kpis.keys():
            if not self.kpi_manager.has_met_kpi(email):
                self.normal_queue.append(email)
            else:
                log.log(email, f"✅ KPI already met ({self.kpi_manager.get_progress(email)}/{self.kpi_manager.get_kpi(email)}), skipping", 'SUCCESS')
        
        # Initialize monitors
        self.monitor = AccountMonitor.get_instance()
        self.watchdog = BrowserWatchdog.get_instance(
            min_browsers=cfg.WATCHDOG_MIN_BROWSERS,
            check_interval=cfg.WATCHDOG_CHECK_INTERVAL,
            max_restart_attempts=cfg.WATCHDOG_MAX_RESTARTS
        )
        
        # Register callbacks
        self.watchdog.on_crash_detected(self._on_crash)
        self.watchdog.on_need_spawn(self._on_need_spawn)
        
        # Initialize data manager
        sheet_path = self.config['review_sheet']
        google_sheet_id = self.config.get('google_sheet_id')
        google_credentials = self.config.get('google_credentials')
        
        if google_sheet_id:
            log.log_status("Using Google Sheets (realtime)", 'INFO')
            self.data_manager = DataManager(
                file_path=sheet_path,
                google_sheet_id=google_sheet_id,
                credentials_file=google_credentials
            )
        else:
            log.log_status(f"Using local file: {sheet_path}", 'INFO')
            self.data_manager = DataManager(file_path=sheet_path)
        
        # Start playwright
        self.playwright = await async_playwright().start()
        
        log.log_separator("Watchdog Runner Config")
        log.log_status(f"Total accounts: {len(self.accounts)}", 'INFO')
        log.log_status(f"Accounts needing work: {len(self.normal_queue)}", 'INFO')
        log.log_status(f"Min browsers: {cfg.WATCHDOG_MIN_BROWSERS}", 'INFO')
        log.log_status(f"Check interval: {cfg.WATCHDOG_CHECK_INTERVAL}s", 'INFO')
        log.log_status(f"Headless: {self.headless}", 'INFO')
        log.log_status(self.work_hours.get_status_message(), 'INFO')
        log.log_separator("KPI Overview")
        self.kpi_manager.print_status()
    
    async def _on_crash(self, email: str):
        """Callback when browser crash detected"""
        log.log_status(f"💥 CRASH DETECTED: {email}", 'ERROR')
        self.monitor.mark_browser_lost(email, "Watchdog detected browser crash")
        
        # Remove from running tasks
        if email in self.running_tasks:
            task = self.running_tasks.pop(email)
            if not task.done():
                task.cancel()
        
        # Check remaining tasks and add to appropriate queue
        remaining = self.monitor.get_remaining_tasks(email)
        checkpoint = self.monitor.get_checkpoint(email)
        
        if remaining > 0 and self.monitor.should_restart(email, cfg.WATCHDOG_MAX_RESTARTS):
            # Add to INCOMPLETE queue (highest priority)
            self.incomplete_queue.appendleft(email)
            log.log(email, f"🔴 INCOMPLETE: {checkpoint}/{checkpoint+remaining} tasks → Added to INCOMPLETE queue", 'ERROR')
            log.log_incomplete_status(self.monitor.get_incomplete_accounts())
        else:
            if remaining <= 0:
                log.log(email, f"✓ Completed all tasks before crash", 'SUCCESS')
            else:
                log.log(email, f"⚠️ Max restarts exceeded, skipping", 'WARNING')
    
    async def _on_need_spawn(self, count: int):
        """Callback when more browsers needed"""
        log.log_status(f"Need to spawn {count} browser(s)", 'INFO')
        for _ in range(count):
            await self._spawn_next_browser()
    
    async def _spawn_next_browser(self):
        """Spawn browser for next available account - INCOMPLETE queue has absolute priority"""
        # Check work hours FIRST - don't spawn if outside work hours
        if not self.work_hours.can_run_tasks():
            log.log_status(f"⏸️  Cannot spawn browser - outside work hours ({self.work_hours.get_status_message()})", 'WARNING')
            return
        
        async with self._lock:
            # Priority 1: Incomplete accounts MUST complete first
            if self.incomplete_queue:
                email = self.incomplete_queue.popleft()
                queue_type = "INCOMPLETE"
                log.log_queue_status(len(self.incomplete_queue), len(self.normal_queue))
            # Priority 2: Normal rotation
            elif self.normal_queue:
                email = self.normal_queue.popleft()
                queue_type = "NORMAL"
            else:
                log.log_status("⚠️ No accounts available in any queue", 'WARNING')
                return
            
            password = self.passwords.get(email)
            
            if not password:
                log.log(email, f"⚠️ No password found", 'ERROR')
                return
            
            # Check if already running
            if email in self.running_tasks and not self.running_tasks[email].done():
                log.log(email, f"⚠️ Already running, re-queuing", 'WARNING')
                if queue_type == "INCOMPLETE":
                    self.incomplete_queue.append(email)
                else:
                    self.normal_queue.append(email)
                return
            
            # Spawn new task
            task = asyncio.create_task(
                self._run_account(email, password)
            )
            self.running_tasks[email] = task
            
            checkpoint = self.monitor.get_checkpoint(email)
            if checkpoint > 0:
                log.log(email, f"🔄 Spawning from [{queue_type}] queue (checkpoint: {checkpoint} tasks)", 'WARNING')
            else:
                log.log(email, f"🚀 Spawning from [{queue_type}] queue", 'INFO')
    
    async def _run_account(self, email: str, password: str):
        """Run tasks for one account with watchdog integration - KPI-based"""
        # Get KPI and current progress
        kpi_target = self.kpi_manager.get_kpi(email)
        current_progress = self.kpi_manager.get_progress(email)
        remaining_for_kpi = self.kpi_manager.get_remaining(email)
        
        # Determine how many tasks to do this session
        max_tasks = min(remaining_for_kpi, cfg.TASKS_PER_ROTATION)  # Don't exceed rotation limit
        
        if max_tasks <= 0:
            log.log(email, f"✅ KPI already met ({current_progress}/{kpi_target}), skipping", 'SUCCESS')
            return 0
        
        log.log_separator(f"🚀 STARTING: {email}")
        log.log(email, f"KPI: {current_progress}/{kpi_target} | This session: {max_tasks} tasks | Rotation #{self.rotation}", 'INFO')
        
        self.monitor.start_account(email, rotation=self.rotation, max_tasks=max_tasks)
        task_logger = TaskLogger("completed_tasks.xlsx", user_name=email)
        completed = 0
        
        browser = None
        context = None
        page = None
        
        try:
            # Launch browser
            browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context()
            page = await context.new_page()
            
            # Register with watchdog
            await self.watchdog.register_browser(email, page, context, browser)
            
            bot = SnorkelBot(page)
            
            try:
                log.log(email, "Logging in...", 'INFO')
                await bot.login(email, password)
                has_task_id = await bot.navigate_to_review()
                
                # Handle BLANK TASK from the very start
                if has_task_id is False:
                    log.log(email, "BLANK TASK from start - Auto REJECT", 'WARNING')
                    uid = await bot.get_uid()
                    
                    decision = {
                        "action": "REJECT",
                        "rejection_notes": "No Task ID Present.",
                        "notes": "No Task ID Present."
                    }
                    await bot.process_task(decision)
                    task_logger.log_task(
                        task_id="BLANK_TASK",
                        uid=uid,
                        decision_from_sheet="Blank Task",
                        status_platform="Reject",
                        notes="No Task ID Present."
                    )
                    completed += 1
                    self.monitor.update_progress(email, completed)
                    await self.watchdog.update_task_count(email, completed)
                    log.log_task(email, completed, max_tasks, "BLANK_TASK", "REJECT")
                
                while completed < max_tasks:
                    # Check if browser still healthy
                    if not await self.watchdog.health_check(email):
                        log.log(email, "Browser unhealthy, stopping", 'ERROR')
                        break
                    
                    await page.wait_for_timeout(2000)
                    
                    task_id = await bot.get_task_id()
                    if not task_id:
                        log.log(email, "No more tasks available", 'WARNING')
                        break
                    
                    uid = await bot.get_uid()
                    
                    # Handle BLANK TASK
                    if task_id == "BLANK_TASK":
                        decision = {
                            "action": "REJECT",
                            "rejection_notes": "No Task ID Present.",
                            "notes": "No Task ID Present."
                        }
                        await bot.process_task(decision)
                        task_logger.log_task(
                            task_id="BLANK_TASK",
                            uid=uid,
                            decision_from_sheet="Blank Task",
                            status_platform="Reject",
                            notes="No Task ID Present."
                        )
                        completed += 1
                        self.monitor.update_progress(email, completed)
                        await self.watchdog.update_task_count(email, completed)
                        log.log_task(email, completed, max_tasks, "BLANK_TASK", "REJECT")
                        await asyncio.sleep(1)
                        continue
                    
                    decision, row_data = self.data_manager.get_decision(task_id)
                    
                    await bot.process_task(decision)
                    
                    # If row_data is None, it means Task ID not found in Evals
                    if row_data is None and decision['action'] == 'UNSURE':
                        decision_from_sheet = 'No Task ID in the Evals'
                    else:
                        decision_from_sheet = row_data.get('decision', '') if row_data else ''
                    
                    status_platform = ACTION_TO_STATUS.get(decision['action'], 'Unsure')
                    task_logger.log_task(
                        task_id=task_id,
                        uid=uid,
                        decision_from_sheet=decision_from_sheet,
                        status_platform=status_platform,
                        notes=decision.get('notes', '')[:200]
                    )
                    
                    completed += 1
                    self.monitor.update_progress(email, completed)
                    await self.watchdog.update_task_count(email, completed)
                    
                    # Extract scores for logging
                    scores = None
                    if row_data:
                        scores = {
                            'C': row_data.get('overall_score', 0),
                            'E': row_data.get('task_correctness_score', 0),
                            'I': row_data.get('response_accuracy_score', 0)
                        }
                    
                    log.log_task(email, completed, max_tasks, task_id, decision['action'], scores, decision_from_sheet)
                    await asyncio.sleep(1)
                
                # Mark as completed successfully
                self.monitor.mark_completed(email, completed)
                log.log(email, f"Batch complete: {completed}/{max_tasks} tasks", 'SUCCESS')
                
            except Exception as e:
                log.log(email, f"Error: {e}", 'ERROR')
                import traceback
                traceback.print_exc()
                self.monitor.mark_crashed(email, str(e))
                # Add to INCOMPLETE queue if should restart
                if self.monitor.should_restart(email, cfg.WATCHDOG_MAX_RESTARTS):
                    remaining = self.monitor.get_remaining_tasks(email)
                    if remaining > 0:
                        self.monitor.mark_restarting(email)
                        self.incomplete_queue.appendleft(email)
                        log.log(email, f"🔴 Added to INCOMPLETE queue ({remaining} tasks remaining)", 'WARNING')
                
        except Exception as e:
            log.log(email, f"Browser launch error: {e}", 'ERROR')
            self.monitor.mark_crashed(email, str(e))
            # Add to INCOMPLETE queue if should restart
            if self.monitor.should_restart(email, cfg.WATCHDOG_MAX_RESTARTS):
                remaining = self.monitor.get_remaining_tasks(email)
                if remaining > 0:
                    self.monitor.mark_restarting(email)
                    self.incomplete_queue.appendleft(email)
                    log.log(email, f"🔴 Added to INCOMPLETE queue ({remaining} tasks remaining)", 'WARNING')
            
        finally:
            # Unregister from watchdog
            await self.watchdog.unregister_browser(email)
            
            # Clean up
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            
            # Add back to queue based on completion status and KPI
            # Refresh KPI progress
            self.kpi_manager.refresh_progress()
            current_progress = self.kpi_manager.get_progress(email)
            kpi_target = self.kpi_manager.get_kpi(email)
            
            if self.kpi_manager.has_met_kpi(email):
                # KPI met - don't add back to any queue
                log.log(email, f"✅ KPI MET! {current_progress}/{kpi_target} tasks completed", 'SUCCESS')
            elif completed >= max_tasks:
                # Completed this session but KPI not met - add to normal queue
                self.normal_queue.append(email)
                remaining = kpi_target - current_progress
                log.log(email, f"✓ Session complete: {current_progress}/{kpi_target} ({remaining} remaining) - queued to NORMAL", 'SUCCESS')
            elif completed < max_tasks:
                # Stopped early - check if it's incomplete or just no more tasks
                remaining = max_tasks - completed
                if remaining > 0 and email not in self.incomplete_queue and email not in self.normal_queue:
                    # Add to normal queue (not incomplete because it didn't crash)
                    self.normal_queue.append(email)
                    log.log(email, f"Stopped at {completed}/{max_tasks} - queued to NORMAL queue", 'WARNING')
        
        return completed
    
    async def run(self):
        """Main run loop - ensures always min_browsers running"""
        self._running = True
        
        # Start watchdog monitoring
        await self.watchdog.start_monitoring()
        
        log.log_separator("🚀 WATCHDOG RUNNER STARTED")
        log.log_status(f"Ensuring {cfg.WATCHDOG_MIN_BROWSERS} browsers always running", 'INFO')
        
        try:
            # Initial spawn
            for _ in range(cfg.WATCHDOG_MIN_BROWSERS):
                await self._spawn_next_browser()
                await asyncio.sleep(5)  # Stagger start
            
            # Main loop - keep running until all accounts exhausted
            last_status_log = 0  # Track last status log time to reduce spam
            last_work_hours_check = 0  # Track last work hours check
            while self._running:
                await asyncio.sleep(5)
                
                # Check work hours (every 60 seconds)
                import time
                current_time = time.time()
                if current_time - last_work_hours_check >= 60:
                    if not self.work_hours.can_run_tasks():
                        # Outside work hours - pause all browsers
                        log.log_status(self.work_hours.get_status_message(), 'WARNING')
                        
                        # Cancel all running tasks gracefully
                        for email, task in list(self.running_tasks.items()):
                            if not task.done():
                                log.log(email, "⏸️  Pausing due to work hours", 'WARNING')
                                task.cancel()  # Actually cancel the task!
                                # Add back to normal queue
                                if email not in self.normal_queue and email not in self.incomplete_queue:
                                    self.normal_queue.append(email)
                        
                        # Wait until work hours resume
                        seconds_until = self.work_hours.get_time_until_work_starts()
                        if seconds_until:
                            hours_until = seconds_until / 3600
                            log.log_status(f"⏰ Sleeping until {cfg.WORK_HOURS_START:02d}:00 ({hours_until:.1f}h)", 'INFO')
                            # Sleep in chunks to allow for graceful shutdown
                            while seconds_until > 0 and self._running:
                                sleep_time = min(60, seconds_until)  # Sleep max 60s at a time
                                await asyncio.sleep(sleep_time)
                                seconds_until -= sleep_time
                            
                            if self._running:
                                log.log_status("✅ Work hours resumed! Restarting browsers...", 'SUCCESS')
                                # Spawn browsers again
                                for _ in range(min(cfg.WATCHDOG_MIN_BROWSERS, len(self.normal_queue) + len(self.incomplete_queue))):
                                    await self._spawn_next_browser()
                                    await asyncio.sleep(2)
                        
                        last_work_hours_check = time.time()
                        continue
                    
                    last_work_hours_check = current_time
                
                # Check running tasks
                active_count = self.watchdog.get_active_count()
                incomplete_count = len(self.incomplete_queue)
                normal_count = len(self.normal_queue)
                running_count = len([t for t in self.running_tasks.values() if not t.done()])
                
                # Print periodic status (reduced frequency: every 30s instead of 5s)
                import time
                current_time = time.time()
                if current_time - last_status_log >= 30:
                    log.log_status(f"Active: {active_count} | Running: {running_count} | Incomplete: {incomplete_count} | Normal: {normal_count}")
                    last_status_log = current_time
                    
                    # Show incomplete accounts if any
                    if incomplete_count > 0:
                        log.log_incomplete_status(self.monitor.get_incomplete_accounts())
                
                # Clean up completed tasks
                completed_emails = []
                for email, task in list(self.running_tasks.items()):
                    if task.done():
                        completed_emails.append(email)
                        try:
                            task.result()  # Check for exceptions
                        except Exception as e:
                            log.log_status(f"Task for {email} failed: {e}", 'ERROR')
                
                for email in completed_emails:
                    del self.running_tasks[email]
                
                # Check if rotation should happen
                if running_count == 0 and normal_count == 0:
                    # Refresh KPI progress
                    self.kpi_manager.refresh_progress()
                    
                    # Check if ALL KPIs are met
                    if self.kpi_manager.all_kpis_met():
                        log.log_separator("🎉 ALL KPIs MET - STOPPING SYSTEM")
                        self.kpi_manager.print_status()
                        log.log_status("All accounts have completed their KPI targets!", 'SUCCESS')
                        self._running = False
                        break
                    
                    # BLOCK rotation if there are incomplete accounts
                    if incomplete_count > 0:
                        log.log_separator(f"🚫 ROTATION BLOCKED - {incomplete_count} INCOMPLETE ACCOUNT(S)")
                        log.log_incomplete_status(self.monitor.get_incomplete_accounts())
                        log.log_status("Waiting for incomplete accounts to finish before continuing...", 'WARNING')
                        
                        # Spawn incomplete accounts
                        for _ in range(min(cfg.WATCHDOG_MIN_BROWSERS, incomplete_count)):
                            await self._spawn_next_browser()
                            await asyncio.sleep(2)
                    else:
                        # Check which accounts still need work
                        accounts_needing_work = []
                        for email in self.account_kpis.keys():
                            if not self.kpi_manager.has_met_kpi(email):
                                accounts_needing_work.append(email)
                        
                        if not accounts_needing_work:
                            # All KPIs met
                            log.log_separator("🎉 ALL KPIs MET - STOPPING SYSTEM")
                            self.kpi_manager.print_status()
                            self._running = False
                            break
                        
                        # Start new rotation with accounts needing work
                        log.log_separator(f"🔄 ROTATION #{self.rotation} COMPLETE")
                        self.rotation += 1
                        
                        # Refill normal queue with only accounts that need work
                        for email in accounts_needing_work:
                            self.normal_queue.append(email)
                        
                        log.log_separator(f"🔄 STARTING ROTATION #{self.rotation}")
                        log.log_status(f"{len(accounts_needing_work)} account(s) still need work", 'INFO')
                        self.kpi_manager.print_status()
                        
                        # Spawn initial browsers
                        for _ in range(min(cfg.WATCHDOG_MIN_BROWSERS, len(self.normal_queue))):
                            await self._spawn_next_browser()
                            await asyncio.sleep(5)
                
                # Safety: ensure min browsers (prioritize incomplete)
                if active_count < cfg.WATCHDOG_MIN_BROWSERS:
                    total_queued = incomplete_count + normal_count
                    if total_queued > 0:
                        needed = cfg.WATCHDOG_MIN_BROWSERS - active_count
                        for _ in range(needed):
                            if incomplete_count > 0 or normal_count > 0:
                                await self._spawn_next_browser()
                                await asyncio.sleep(2)
                
        except KeyboardInterrupt:
            log.log_status("Interrupted by user", 'WARNING')
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Clean shutdown"""
        log.log_status("Shutting down...", 'INFO')
        self._running = False
        
        # Stop watchdog
        await self.watchdog.stop_monitoring()
        
        # Cancel running tasks
        for email, task in self.running_tasks.items():
            if not task.done():
                task.cancel()
        
        # Wait for tasks to cancel
        if self.running_tasks:
            await asyncio.gather(*self.running_tasks.values(), return_exceptions=True)
        
        # Close playwright
        if self.playwright:
            await self.playwright.stop()
        
        # Final status
        self.monitor.print_status()
        self.watchdog.print_status()
        self.kpi_manager.print_status()
        
        log.log_status("Shutdown complete", 'SUCCESS')


def load_config(config_file="accounts.config"):
    """Load config from file"""
    config = {
        "accounts": [],
        "headless": True,
        "max_concurrent": 2,
        "review_sheet": "nereid-evals.xlsx",
        "google_sheet_id": None,
        "google_credentials": "credentials.json"
    }
    
    if not os.path.exists(config_file):
        log.log_status(f"Config file not found: {config_file}", 'ERROR')
        return config
    
    with open(config_file, 'r') as f:
        content = f.read()
    
    # Parse accounts
    in_accounts = False
    for line in content.split('\n'):
        line = line.strip()
        
        if line.startswith('ACCOUNTS:'):
            in_accounts = True
            continue
        
        if line.startswith('HEADLESS:'):
            config['headless'] = 'true' in line.lower()
            in_accounts = False
            continue
            
        if line.startswith('MAX_CONCURRENT:'):
            match = re.search(r'(\d+)', line)
            if match:
                config['max_concurrent'] = int(match.group(1))
            in_accounts = False
            continue
            
        if line.startswith('REVIEW_SHEET:'):
            config['review_sheet'] = line.split(':', 1)[1].strip()
            in_accounts = False
            continue
        
        if line.startswith('GOOGLE_SHEET_ID:'):
            config['google_sheet_id'] = line.split(':', 1)[1].strip()
            in_accounts = False
            continue
            
        if line.startswith('GOOGLE_CREDENTIALS:'):
            config['google_credentials'] = line.split(':', 1)[1].strip()
            in_accounts = False
            continue
        
        # Parse account line (format: email,password,kpi or email,password)
        if in_accounts and ',' in line and not line.startswith('#'):
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 2:
                email = parts[0]
                password = parts[1]
                kpi = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 100  # Default KPI = 100
                if email and password:
                    config['accounts'].append({
                        'email': email,
                        'password': password,
                        'kpi': kpi
                    })
    
    return config


async def main_async():
    """Async main entry point"""
    # Enable file logging
    log.enable_file_logging("watchdog.log")
    
    log.log_separator("SNORKEL BOT - WATCHDOG MODE")
    log.log_status(f"Always maintains {cfg.WATCHDOG_MIN_BROWSERS} browsers", 'INFO')
    
    config = load_config("accounts.config")
    
    if not config['accounts']:
        log.log_status("No accounts found in accounts.config!", 'ERROR')
        return
    
    runner = WatchdogRunner(config)
    await runner.initialize()
    await runner.run()


def main():
    """Main entry point"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
