"""
KPI Manager - Track account progress against KPI targets
Reads completed_tasks.xlsx to check how many tasks each account has completed
"""
import os
import threading
from typing import Dict, Optional

import pandas as pd


class KPIManager:
    """Manage KPI tracking for accounts - Thread-safe"""
    
    _lock = threading.Lock()
    _instance = None
    
    def __init__(self, completed_tasks_file="completed_tasks.xlsx"):
        self.completed_tasks_file = completed_tasks_file
        self.account_kpis: Dict[str, int] = {}  # email -> target KPI
        self.account_progress: Dict[str, int] = {}  # email -> completed count
        
    @classmethod
    def get_instance(cls, completed_tasks_file="completed_tasks.xlsx"):
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = KPIManager(completed_tasks_file)
        return cls._instance
    
    def set_kpi(self, email: str, kpi: int):
        """Set KPI target for an account"""
        with self._lock:
            self.account_kpis[email] = kpi
    
    def get_kpi(self, email: str) -> int:
        """Get KPI target for an account"""
        with self._lock:
            return self.account_kpis.get(email, 0)
    
    def _get_sheet_name(self, email: str) -> str:
        """Get sheet name from email (same logic as TaskLogger)"""
        if not email:
            return "Unknown"
        sheet_name = email.split('@')[0]
        invalid_chars = ['\\', '/', '*', '?', ':', '[', ']']
        for char in invalid_chars:
            sheet_name = sheet_name.replace(char, '_')
        return sheet_name[:31]
    
    def refresh_progress(self):
        """Refresh progress by reading completed_tasks.xlsx"""
        with self._lock:
            if not os.path.exists(self.completed_tasks_file):
                # No file yet, all accounts at 0
                for email in self.account_kpis.keys():
                    self.account_progress[email] = 0
                return
            
            try:
                # Read all sheets
                all_sheets = pd.read_excel(self.completed_tasks_file, sheet_name=None)
                
                # Count tasks for each account
                for email in self.account_kpis.keys():
                    sheet_name = self._get_sheet_name(email)
                    if sheet_name in all_sheets:
                        df = all_sheets[sheet_name]
                        self.account_progress[email] = len(df)
                    else:
                        self.account_progress[email] = 0
                        
            except Exception as e:
                print(f"⚠️ [KPIManager] Error reading completed_tasks.xlsx: {e}")
                # Default to 0 if error
                for email in self.account_kpis.keys():
                    self.account_progress[email] = 0
    
    def get_progress(self, email: str) -> int:
        """Get current progress for an account"""
        with self._lock:
            return self.account_progress.get(email, 0)
    
    def get_remaining(self, email: str) -> int:
        """Get remaining tasks to reach KPI"""
        with self._lock:
            kpi = self.account_kpis.get(email, 0)
            progress = self.account_progress.get(email, 0)
            return max(0, kpi - progress)
    
    def has_met_kpi(self, email: str) -> bool:
        """Check if account has met KPI"""
        with self._lock:
            kpi = self.account_kpis.get(email, 0)
            progress = self.account_progress.get(email, 0)
            return progress >= kpi
    
    def get_incomplete_accounts(self) -> list:
        """Get list of accounts that haven't met KPI"""
        with self._lock:
            incomplete = []
            for email, kpi in self.account_kpis.items():
                progress = self.account_progress.get(email, 0)
                if progress < kpi:
                    incomplete.append({
                        'email': email,
                        'kpi': kpi,
                        'progress': progress,
                        'remaining': kpi - progress
                    })
            return incomplete
    
    def all_kpis_met(self) -> bool:
        """Check if all accounts have met their KPI"""
        with self._lock:
            for email, kpi in self.account_kpis.items():
                progress = self.account_progress.get(email, 0)
                if progress < kpi:
                    return False
            return True
    
    def print_status(self):
        """Print KPI status for all accounts"""
        with self._lock:
            print("\n" + "="*60)
            print("   📊 KPI STATUS")
            print("="*60)
            for email, kpi in self.account_kpis.items():
                progress = self.account_progress.get(email, 0)
                remaining = max(0, kpi - progress)
                percentage = (progress / kpi * 100) if kpi > 0 else 0
                
                status_icon = "✅" if progress >= kpi else "🔴"
                print(f"   {status_icon} {email}")
                print(f"      Progress: {progress}/{kpi} tasks ({percentage:.1f}%) | Remaining: {remaining}")
            print("="*60 + "\n")
