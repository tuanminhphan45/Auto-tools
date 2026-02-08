"""
Multi-Account Runner for Snorkel Bot
Chạy nhiều account với rotation: mỗi cặp chạy 15 task rồi đổi
"""
import asyncio
import os
import re
from pathlib import Path

from src.account_monitor import AccountMonitor
from src.browser_manager import BrowserManager
from src.data_manager import DataManager
from src.snorkel_bot import SnorkelBot
from src.task_logger import TaskLogger

# Map action to Status (Platform) value
ACTION_TO_STATUS = {
    "ACCEPT": "Accept",
    "REJECT": "Reject",
    "REVISE": "Needs Revision",  # Fixed: was "REVISION", should be "REVISE"
    "UNSURE": "Unsure",
    "SKIP": "Skip this task"
}

# Configuration
TASKS_PER_ROTATION = 100  # Each pair runs 15 tasks then switch
MAX_RESTART_ATTEMPTS = 3  # Max times to restart a crashed account


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
        print(f"Config file not found: {config_file}")
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
        
        # Parse account line
        if in_accounts and ',' in line and not line.startswith('#'):
            parts = line.split(',', 1)
            if len(parts) == 2:
                email, password = parts[0].strip(), parts[1].strip()
                if email and password:
                    config['accounts'].append({'email': email, 'password': password})
    
    return config


async def run_account_batch(email, password, data_manager, headless, max_tasks, account_label, rotation=1):
    """Run a batch of tasks for one account, returns number of completed tasks"""
    print(f"\n{'='*50}")
    print(f"🚀 [{account_label}] Starting: {email} (max {max_tasks} tasks)")
    print(f"{'='*50}")
    
    # Get monitor instance
    monitor = AccountMonitor.get_instance()
    monitor.start_account(email, rotation=rotation, max_tasks=max_tasks)
    
    task_logger = TaskLogger("completed_tasks.xlsx", user_name=email)
    completed = 0
    
    from playwright.async_api import async_playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context()
            page = await context.new_page()
            
            bot = SnorkelBot(page)
            
            try:
                await bot.login(email, password)
                has_task_id = await bot.navigate_to_review()
                
                # Handle BLANK TASK from the very start (no Task ID when page loaded)
                if has_task_id is False:
                    print(f"[{email}] ⚠️ BLANK TASK from start - Auto REJECT")
                    decision = {
                        "action": "REJECT",
                        "rejection_notes": "No Task ID Present.",
                        "notes": "No Task ID Present."
                    }
                    await bot.process_task(decision)
                    uid = await bot.get_uid()
                    task_logger.log_task(
                        task_id="BLANK_TASK",
                        uid=uid,
                        decision_from_sheet="",
                        status_platform="Reject",
                        notes="No Task ID Present."
                    )
                    completed += 1
                    monitor.update_progress(email, completed)
                    print(f"[{email}] ✓ BLANK TASK rejected from start")
                
                while completed < max_tasks:
                    print(f"\n[{email}] --- Task #{completed + 1}/{max_tasks} ---")
                    await page.wait_for_timeout(2000)
                    
                    task_id = await bot.get_task_id()
                    if not task_id:
                        print(f"[{email}] No more tasks available.")
                        break
                    
                    uid = await bot.get_uid()
                    
                    # Handle BLANK TASK - auto reject
                    if task_id == "BLANK_TASK":
                        print(f"[{email}] ⚠️ BLANK TASK detected - Auto REJECT")
                        decision = {
                            "action": "REJECT",
                            "rejection_notes": "No Task ID Present.",
                            "notes": "No Task ID Present."
                        }
                        await bot.process_task(decision)
                        task_logger.log_task(
                            task_id="BLANK_TASK",
                            uid=uid,
                            decision_from_sheet="",
                            status_platform="Reject",
                            notes="No Task ID Present."
                        )
                        completed += 1
                        monitor.update_progress(email, completed)
                        print(f"[{email}] ✓ BLANK TASK rejected #{completed}/{max_tasks}")
                        await asyncio.sleep(1)
                        continue
                    
                    print(f"[{email}] Task ID: {task_id}")
                    
                    decision, row_data = data_manager.get_decision(task_id)
                    print(f"[{email}] Decision: {decision['action']}")
                    
                    await bot.process_task(decision)
                    
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
                    monitor.update_progress(email, completed)
                    print(f"[{email}] ✓ Task #{completed}/{max_tasks} completed")
                    await asyncio.sleep(1)
                
                # Mark as completed successfully
                monitor.mark_completed(email, completed)
                    
            except Exception as e:
                print(f"[{email}] Error: {e}")
                import traceback
                traceback.print_exc()
                monitor.mark_crashed(email, str(e))
                
            finally:
                print(f"\n[{email}] === Batch Complete: {completed} tasks ===")
                await browser.close()
    
    except Exception as e:
        print(f"[{email}] Browser launch error: {e}")
        monitor.mark_crashed(email, str(e))
    
    return completed


async def run_pair(pair, data_manager, headless, tasks_per_account, pair_index, rotation=1):
    """Run a pair of accounts concurrently"""
    print(f"\n{'#'*60}")
    print(f"# PAIR {pair_index}: {[acc['email'] for acc in pair]}")
    print(f"# Each account will do {tasks_per_account} tasks")
    print(f"{'#'*60}")
    
    tasks = []
    for i, acc in enumerate(pair):
        # Stagger start by 5 seconds
        await asyncio.sleep(i * 5)
        task = asyncio.create_task(
            run_account_batch(
                acc['email'], acc['password'], 
                data_manager, headless, 
                tasks_per_account,
                f"Pair{pair_index}-Acc{i+1}",
                rotation=rotation
            )
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    total = sum(results)
    print(f"\n✅ Pair {pair_index} completed: {total} total tasks")
    return total


async def restart_crashed_accounts(accounts, data_manager, headless, rotation):
    """Check for crashed accounts and restart them"""
    monitor = AccountMonitor.get_instance()
    crashed = monitor.get_crashed_accounts()
    
    if not crashed:
        return 0
    
    print(f"\n{'!'*60}")
    print(f"! RESTARTING {len(crashed)} CRASHED ACCOUNT(S)")
    print(f"{'!'*60}")
    
    total_restarted = 0
    for acc_info in crashed:
        email = acc_info['email']
        
        # Check if should restart
        if not monitor.should_restart(email, MAX_RESTART_ATTEMPTS):
            continue
        
        # Find password from accounts list
        password = None
        for acc in accounts:
            if acc['email'] == email:
                password = acc['password']
                break
        
        if not password:
            print(f"⚠️ Password not found for {email}, skipping restart")
            continue
        
        # Calculate remaining tasks
        remaining = monitor.get_remaining_tasks(email)
        if remaining <= 0:
            print(f"⚠️ {email} has no remaining tasks, skipping restart")
            continue
        
        monitor.mark_restarting(email)
        
        print(f"\n🔄 Restarting {email} with {remaining} remaining tasks...")
        completed = await run_account_batch(
            email, password,
            data_manager, headless,
            remaining,
            f"Restart-{acc_info['restart_count']+1}",
            rotation=rotation
        )
        total_restarted += completed
    
    return total_restarted


async def run_rotation(config):
    """Run accounts with rotation: each pair does 15 tasks then switch"""
    accounts = config['accounts']
    headless = config['headless']
    sheet_path = config['review_sheet']
    google_sheet_id = config.get('google_sheet_id')
    google_credentials = config.get('google_credentials')
    
    if not accounts:
        print("❌ No accounts found!")
        return
    
    # Initialize AccountMonitor
    monitor = AccountMonitor.get_instance()
    
    # Initialize DataManager
    if google_sheet_id:
        print(f"\n📊 Using Google Sheets (realtime)")
        data_manager = DataManager(
            file_path=sheet_path,
            google_sheet_id=google_sheet_id,
            credentials_file=google_credentials
        )
    else:
        print(f"\n📊 Using local file: {sheet_path}")
        data_manager = DataManager(file_path=sheet_path)
    
    # Create pairs (2 accounts per pair)
    pairs = [accounts[i:i+2] for i in range(0, len(accounts), 2)]
    
    print(f"\n📋 Rotation Config:")
    print(f"   - Total accounts: {len(accounts)}")
    print(f"   - Pairs: {len(pairs)}")
    print(f"   - Tasks per rotation: {TASKS_PER_ROTATION} per account")
    print(f"   - Max restart attempts: {MAX_RESTART_ATTEMPTS}")
    print(f"   - Headless: {headless}")
    
    # Run rotation loop
    rotation = 0
    max_rotations = 100  # Safety limit
    
    while rotation < max_rotations:
        rotation += 1
        print(f"\n{'='*60}")
        print(f"   ROTATION #{rotation}")
        print(f"{'='*60}")
        
        total_tasks = 0
        for pair_idx, pair in enumerate(pairs, 1):
            tasks_done = await run_pair(pair, data_manager, headless, TASKS_PER_ROTATION, pair_idx, rotation=rotation)
            total_tasks += tasks_done
            
            if tasks_done == 0:
                print(f"⚠️ Pair {pair_idx} completed 0 tasks - may be no more tasks available")
        
        # Check and restart crashed accounts
        restarted_tasks = await restart_crashed_accounts(accounts, data_manager, headless, rotation)
        total_tasks += restarted_tasks
        
        # Print status summary
        monitor.print_status()
        
        print(f"\n🔄 Rotation #{rotation} complete: {total_tasks} total tasks")
        
        if total_tasks == 0:
            print("🛑 No tasks completed in this rotation. Stopping.")
            break
        
        # Brief pause between rotations
        print("⏳ Pausing 10s before next rotation...")
        await asyncio.sleep(10)
    
    # Final status
    monitor.print_status()
    print("\n🎉 All rotations completed!")


def main():
    print("="*60)
    print("   SNORKEL MULTI-ACCOUNT BOT (ROTATION MODE)")
    print(f"   Each pair runs {TASKS_PER_ROTATION} tasks then switch")
    print("="*60)
    
    config = load_config("accounts.config")
    asyncio.run(run_rotation(config))


if __name__ == "__main__":
    main()
