"""
Account Monitor - Track account status and handle crashes
"""
import json
import os
import threading
from datetime import datetime
from enum import Enum


class AccountStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CRASHED = "crashed"
    RESTARTING = "restarting"


class AccountMonitor:
    """Monitor and track account status - Thread-safe"""
    
    _lock = threading.Lock()
    _instance = None
    
    def __init__(self, status_file="account_status.json"):
        self.status_file = status_file
        self.accounts = {}
        self._load_status()
    
    @classmethod
    def get_instance(cls, status_file="account_status.json"):
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = AccountMonitor(status_file)
        return cls._instance
    
    def _load_status(self):
        """Load status from file"""
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r') as f:
                    self.accounts = json.load(f)
            except Exception:
                self.accounts = {}
    
    def _save_status(self):
        """Save status to file"""
        with open(self.status_file, 'w') as f:
            json.dump(self.accounts, f, indent=2, default=str)
    
    def start_account(self, email, rotation=1, max_tasks=100):
        """Mark account as starting"""
        with self._lock:
            self.accounts[email] = {
                "status": AccountStatus.RUNNING.value,
                "rotation": rotation,
                "max_tasks": max_tasks,
                "completed_tasks": 0,
                "started_at": datetime.now().isoformat(),
                "last_update": datetime.now().isoformat(),
                "error": None,
                "restart_count": self.accounts.get(email, {}).get("restart_count", 0)
            }
            self._save_status()
            print(f"📊 [Monitor] {email} - STARTED (rotation {rotation})")
    
    def update_progress(self, email, completed_tasks):
        """Update task progress"""
        with self._lock:
            if email in self.accounts:
                self.accounts[email]["completed_tasks"] = completed_tasks
                self.accounts[email]["last_update"] = datetime.now().isoformat()
                self._save_status()
    
    def mark_completed(self, email, completed_tasks):
        """Mark account as completed successfully"""
        with self._lock:
            if email in self.accounts:
                self.accounts[email]["status"] = AccountStatus.COMPLETED.value
                self.accounts[email]["completed_tasks"] = completed_tasks
                self.accounts[email]["completed_at"] = datetime.now().isoformat()
                self._save_status()
            print(f"✅ [Monitor] {email} - COMPLETED ({completed_tasks} tasks)")
    
    def mark_crashed(self, email, error_msg):
        """Mark account as crashed"""
        with self._lock:
            if email in self.accounts:
                self.accounts[email]["status"] = AccountStatus.CRASHED.value
                self.accounts[email]["error"] = str(error_msg)[:500]
                self.accounts[email]["crashed_at"] = datetime.now().isoformat()
                self._save_status()
            print(f"💥 [Monitor] {email} - CRASHED: {str(error_msg)[:100]}")
    
    def mark_restarting(self, email):
        """Mark account as restarting"""
        with self._lock:
            if email in self.accounts:
                self.accounts[email]["status"] = AccountStatus.RESTARTING.value
                self.accounts[email]["restart_count"] = self.accounts[email].get("restart_count", 0) + 1
                self._save_status()
            print(f"🔄 [Monitor] {email} - RESTARTING (attempt #{self.accounts[email].get('restart_count', 1)})")
    
    def get_crashed_accounts(self):
        """Get list of crashed accounts"""
        with self._lock:
            crashed = []
            for email, data in self.accounts.items():
                if data.get("status") == AccountStatus.CRASHED.value:
                    crashed.append({
                        "email": email,
                        "error": data.get("error"),
                        "completed_tasks": data.get("completed_tasks", 0),
                        "max_tasks": data.get("max_tasks", 100),
                        "restart_count": data.get("restart_count", 0)
                    })
            return crashed
    
    def mark_browser_lost(self, email, reason="Browser connection lost"):
        """Mark account as crashed due to browser loss"""
        with self._lock:
            if email in self.accounts:
                self.accounts[email]["status"] = AccountStatus.CRASHED.value
                self.accounts[email]["error"] = reason
                self.accounts[email]["browser_lost_at"] = datetime.now().isoformat()
                self._save_status()
            print(f"💔 [Monitor] {email} - BROWSER LOST: {reason}")
    
    def get_accounts_by_status(self, status: AccountStatus):
        """Get list of accounts with specific status"""
        with self._lock:
            return [email for email, data in self.accounts.items() 
                    if data.get("status") == status.value]
    
    def get_running_accounts(self):
        """Get list of running accounts"""
        with self._lock:
            running = []
            for email, data in self.accounts.items():
                if data.get("status") == AccountStatus.RUNNING.value:
                    running.append({
                        "email": email,
                        "completed_tasks": data.get("completed_tasks", 0),
                        "max_tasks": data.get("max_tasks", 100),
                        "started_at": data.get("started_at")
                    })
            return running
    
    def should_restart(self, email, max_restarts=3):
        """Check if account should be restarted"""
        with self._lock:
            if email not in self.accounts:
                return False
            data = self.accounts[email]
            if data.get("status") != AccountStatus.CRASHED.value:
                return False
            if data.get("restart_count", 0) >= max_restarts:
                print(f"⚠️ [Monitor] {email} - Max restarts ({max_restarts}) reached")
                return False
            return True
    
    def get_remaining_tasks(self, email):
        """Get remaining tasks for an account"""
        with self._lock:
            if email not in self.accounts:
                return 0
            data = self.accounts[email]
            return max(0, data.get("max_tasks", 100) - data.get("completed_tasks", 0))
    
    def get_incomplete_accounts(self):
        """Get list of accounts that haven't completed their quota"""
        with self._lock:
            incomplete = []
            for email, data in self.accounts.items():
                status = data.get("status")
                # Account is incomplete if crashed or restarting and has remaining tasks
                if status in [AccountStatus.CRASHED.value, AccountStatus.RESTARTING.value]:
                    remaining = data.get("max_tasks", 100) - data.get("completed_tasks", 0)
                    if remaining > 0:
                        incomplete.append({
                            "email": email,
                            "completed_tasks": data.get("completed_tasks", 0),
                            "max_tasks": data.get("max_tasks", 100),
                            "remaining_tasks": remaining,
                            "restart_count": data.get("restart_count", 0),
                            "error": data.get("error", "")
                        })
            return incomplete
    
    def is_account_incomplete(self, email):
        """Check if account is incomplete (crashed/restarting with remaining tasks)"""
        with self._lock:
            if email not in self.accounts:
                return False
            data = self.accounts[email]
            status = data.get("status")
            if status not in [AccountStatus.CRASHED.value, AccountStatus.RESTARTING.value]:
                return False
            remaining = data.get("max_tasks", 100) - data.get("completed_tasks", 0)
            return remaining > 0
    
    def get_checkpoint(self, email):
        """Get checkpoint (completed tasks count) for an account"""
        with self._lock:
            if email not in self.accounts:
                return 0
            return self.accounts[email].get("completed_tasks", 0)
    
    def print_status(self):
        """Print current status of all accounts"""
        with self._lock:
            print("\n" + "="*60)
            print("   📊 ACCOUNT STATUS MONITOR")
            print("="*60)
            for email, data in self.accounts.items():
                status = data.get("status", "unknown")
                completed = data.get("completed_tasks", 0)
                max_tasks = data.get("max_tasks", 100)
                
                status_icon = {
                    "running": "🟢",
                    "completed": "✅",
                    "crashed": "💥",
                    "restarting": "🔄",
                    "pending": "⏳"
                }.get(status, "❓")
                
                print(f"   {status_icon} {email}: {status.upper()} ({completed}/{max_tasks} tasks)")
                if data.get("error"):
                    print(f"      └── Error: {data['error'][:80]}...")
            print("="*60 + "\n")
    
    def reset_all(self):
        """Reset all account statuses"""
        with self._lock:
            self.accounts = {}
            self._save_status()
            print("🔄 [Monitor] All accounts reset")
