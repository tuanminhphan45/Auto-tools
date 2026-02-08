import asyncio
import os

from dotenv import load_dotenv

from src.browser_manager import BrowserManager
from src.data_manager import DataManager
from src.snorkel_bot import SnorkelBot
from src.task_logger import TaskLogger

# Load environment variables
load_dotenv()

BACKGROUND_MODE = False  # Set True to run headless (no browser UI)

# Map action to Status (Platform) value
ACTION_TO_STATUS = {
    "ACCEPT": "Accept",
    "REJECT": "Reject",
    "REVISE": "Needs Revision",  # Fixed: was "REVISION", should be "REVISE"
    "UNSURE": "Unsure",
    "SKIP": "Skip this task"
}


async def main():
    # 1. Setup
    email = os.getenv("SNORKEL_EMAIL")
    password = os.getenv("SNORKEL_PASSWORD")
    sheet_path = os.getenv("REVIEW_SHEET_PATH", "nereid-evals.xlsx")
    
    if not email or not password:
        print("Error: Please set SNORKEL_EMAIL and SNORKEL_PASSWORD in .env file")
        return

    print(f"Loading data from {sheet_path}...")
    data_manager = DataManager(sheet_path)
    
    # Initialize task logger with user email
    task_logger = TaskLogger("completed_tasks.xlsx", user_name=email)
    
    # 2. Launch Browser
    browser = await BrowserManager.get_browser(headless=BACKGROUND_MODE)
    context = await browser.new_context()
    page = await context.new_page()
    
    bot = SnorkelBot(page)
    
    try:
        # 3. Login & Navigate
        await bot.login(email, password)
        await bot.navigate_to_review()
        
        # 4. Processing Loop
        task_count = 0
        while True:
            print(f"\n--- Task #{task_count + 1} ---")
            # Wait a bit for UI to settle
            await page.wait_for_timeout(2000)
            
            task_id = await bot.get_task_id()
            if not task_id:
                print("Could not find Task ID. Stopping or Manual Check required.")
                break
            
            # Get UID from page
            uid = await bot.get_uid()
                
            print(f"Current Task ID: {task_id}")
            print(f"Current UID: {uid}")
            
            # Get decision and raw row data
            decision, row_data = data_manager.get_decision(task_id)
            print(f"Decision: {decision}")
            
            # Process the task
            await bot.process_task(decision)
            
            # Log the completed task
            decision_from_sheet = row_data.get('decision', '') if row_data else ''
            status_platform = ACTION_TO_STATUS.get(decision['action'], 'Unsure')
            task_logger.log_task(
                task_id=task_id,
                uid=uid,
                decision_from_sheet=decision_from_sheet,
                status_platform=status_platform,
                notes=decision.get('notes', '')[:200]
            )
            
            task_count += 1
            print(f"✓ Task logged. Total completed: {task_count}")
            
            # Rate limit / Safety pause
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        # Keep browser open for debugging if not headless
        print("Browser will stay open for 5 minutes for debugging...")
        await asyncio.sleep(300)
        
    finally:
        print(f"\n=== Session Complete ===")
        print(f"Total tasks completed: {task_logger.get_completed_count()}")
        await BrowserManager.close()

if __name__ == "__main__":
    asyncio.run(main())
