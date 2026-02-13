import random
import re

from playwright.async_api import Page


class SnorkelBot:
    def __init__(self, page: Page):
        self.page = page
        self.base_url = "https://experts.snorkel-ai.com"

    async def login(self, email, password):
        await self.page.goto(f"{self.base_url}/home")
        
        # Wait for login page to fully load
        await self.page.wait_for_load_state('networkidle')
        await self.page.wait_for_timeout(2000)
        
        # Check if on login page (Cognito)
        if "login" in self.page.url or "cognito" in self.page.url or "auth" in self.page.url:
            # Wait for login form to be visible
            await self.page.wait_for_selector('input[placeholder="name@host.com"]', timeout=10000)
            
            # Fill email field using placeholder
            email_input = self.page.locator('input[placeholder="name@host.com"]')
            await email_input.fill(email)
            
            # Fill password field using placeholder
            password_input = self.page.locator('input[placeholder="Enter password"]')
            await password_input.fill(password)
            
            # Click Sign In button
            await self.page.click('button:has-text("Sign in")')
            
            # Wait for redirect to home page (longer timeout for auth)
            await self.page.wait_for_url("**/home", timeout=60000)

    async def navigate_to_review(self):
        """
        Navigate to review page.
        Returns True if Task ID found, False if blank task (no Task ID)
        """
        # Wait for dashboard to load with retry
        for attempt in range(3):
            try:
                await self.page.wait_for_selector('text=My projects', timeout=20000)
                break
            except:
                if attempt < 2:
                    await self.page.wait_for_timeout(3000)
                else:
                    raise
        
        await self.page.wait_for_timeout(3000)
        
        # Use the exact data-testid for the Review Start button
        await self.page.click('[data-testid="Review-Nereid"]')
        
        # Wait for review page to load
        await self.page.wait_for_timeout(5000)
        
        # Check if left panel is empty (blank task) - no retry needed
        left_panel = self.page.locator('[data-testid="document-review-left-panel"]')
        left_panel_html = await left_panel.inner_html()
        
        # If left panel is empty (no Task ID info), it's a blank task
        if 'Task ID' not in left_panel_html:
            return False
        
        return True

    async def get_task_id(self):
        """Extract Task ID from the review page. Returns 'BLANK_TASK' if task is blank."""
        try:
            # First check if left panel has Task ID (fast check)
            left_panel = self.page.locator('[data-testid="document-review-left-panel"]')
            left_panel_html = await left_panel.inner_html()
            
            if 'Task ID' not in left_panel_html:
                return "BLANK_TASK"
            
            # Get the text content after "Task ID" header
            task_id_element = self.page.locator('h3:has-text("Task ID")').locator('..').locator('span')
            task_id = await task_id_element.first.text_content()
            
            if task_id:
                task_id = task_id.strip()
                if not task_id or task_id == "" or task_id.lower() == "none":
                    return "BLANK_TASK"
                return task_id
            
            return "BLANK_TASK"
        except Exception as e:
            return None

    async def get_uid(self):
        """Extract UID from the review page (e.g. 6dd9f981-aa73-4d06-9bef-9990e0de6b0b)"""
        try:
            # UID is displayed next to "UID:" label
            uid_element = self.page.locator('div:has-text("UID:")').locator('div').filter(has_text=re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'))
            uid = await uid_element.first.text_content()
            
            if uid:
                uid = uid.strip()
                return uid
            
            return ""
        except Exception:
            return ""

    def _get_human_delay(self, action):
        """
        Get random delay to simulate human behavior
        Uses values from config.py
        """
        from config import (
            DELAY_ACCEPT_MAX,
            DELAY_ACCEPT_MIN,
            DELAY_REJECT_MAX,
            DELAY_REJECT_MIN,
            DELAY_REVISION_MAX,
            DELAY_REVISION_MIN,
        )
        
        if action == "ACCEPT":
            delay = random.uniform(DELAY_ACCEPT_MIN, DELAY_ACCEPT_MAX)
        elif action in ["REVISE", "UNSURE"]:
            delay = random.uniform(DELAY_REVISION_MIN, DELAY_REVISION_MAX)
        else:  # REJECT
            delay = random.uniform(DELAY_REJECT_MIN, DELAY_REJECT_MAX)
        
        return delay

    async def process_task(self, decision):
        """
        Process a task based on decision from DataManager.
        
        decision = {
            "action": "ACCEPT" | "REJECT" | "REVISION" | "UNSURE",
            "notes": str,           # Column K -> #evaluator_reason
            "revision_notes": str   # Column L -> #Revision Notes (only for REVISION)
        }
        """
        action = decision['action']
        
        # Get human-like delay for this action
        delay_seconds = self._get_human_delay(action)
        
        # Wait before interacting (simulating reading/reviewing)
        await self.page.wait_for_timeout(delay_seconds * 1000)
        
        # Click the appropriate radio button using data-cy attribute
        if action == "ACCEPT":
            await self.page.click('[data-cy="yes"]')
            await self.page.wait_for_timeout(1000)
            
            # Fill Notes (Column K) -> #evaluator_reason
            if decision.get('notes'):
                await self.page.fill('#evaluator_reason', decision['notes'])
            
        elif action == "REJECT":
            await self.page.click('[data-cy="no"]')
            await self.page.wait_for_timeout(1000)
            
            # Fill Rejection Notes -> id="Rejection Notes"
            rejection_reason = decision.get('rejection_notes', decision.get('notes', ''))
            if rejection_reason:
                await self.page.fill('[id="Rejection Notes"]', rejection_reason)
            
            # Fill Notes
            if decision.get('notes'):
                await self.page.fill('#evaluator_reason', decision['notes'])
            
        elif action == "REVISE":
            await self.page.click('[data-cy="needs_revision"]')
            await self.page.wait_for_timeout(1000)
            
            # Fill Revision Notes for Feedback to Submitter (Column L) -> id="Revision Notes"
            if decision.get('revision_notes'):
                await self.page.fill('[id="Revision Notes"]', decision['revision_notes'])
            
            # Điền Additional Notes for Snorkel (#evaluator_reason) với step_evaluations (Column K)
            if decision.get('notes'):
                await self.page.fill('#evaluator_reason', decision['notes'])
                    
        elif action == "UNSURE":
            await self.page.click('[data-cy="unsure"]')
            await self.page.wait_for_timeout(1000)
            
            # Fill Notes (Column K) -> #evaluator_reason
            if decision.get('notes'):
                await self.page.fill('#evaluator_reason', decision['notes'])

        # Wait before submit (random 1-3s)
        await self.page.wait_for_timeout(random.randint(1000, 3000))
        
        # Click Submit button
        await self.page.click('button:has-text("Submit")')
        
        # Wait for next task or "Continue" button
        await self.page.wait_for_timeout(3000)
        
        # Check if there's a "Continue to next task" button
        try:
            continue_btn = self.page.locator('button:has-text("Continue")')
            if await continue_btn.count() > 0:
                await continue_btn.click()
        except:
            pass
        
        # Wait for next task to load
        await self.page.wait_for_timeout(3000)
