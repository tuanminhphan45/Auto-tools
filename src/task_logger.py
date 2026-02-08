import os
import threading
from datetime import datetime

import pandas as pd

# Account mapping for display names
ACCOUNT_NAMES = {
    'g007@gdsonline.tech': 'Nguyễn Ngọc Hân',
    'g008@gdsonline.tech': 'Nguyễn Hữu Đại',
    'g009@gdsonline.tech': 'Đỗ Mạnh Tùng',
    'g010@gdsonline.tech': 'Nguyễn Xuân Công',
    'g011@gdsonline.tech': 'Phan Nguyễn Tuấn Minh',
    'g012@gdsonline.tech': '',
    'g013@gdsonline.tech': ''
}


class TaskLogger:
    """Log completed tasks to an Excel file - Thread-safe version"""
    
    _lock = threading.Lock()  # Class-level lock for file access
    
    def __init__(self, log_file="completed_tasks.xlsx", user_name=""):
        self.log_file = log_file
        self.user_name = user_name
        self.completed_tasks = []
        
    def log_task(self, task_id, uid, decision_from_sheet, status_platform, notes=""):
        """
        Log a completed task - Thread-safe
        New structure: Account | Email | Code | Ngày | UID | Task ID | Decision | Status | Notes | Completed At
        """
        today = datetime.now()
        
        # Get account name from mapping
        account_name = ACCOUNT_NAMES.get(self.user_name.lower(), '')
        
        task_data = {
            "Account": account_name,
            "Email": self.user_name,
            "Code": "SN02",
            "Ngày": today.strftime("%d/%m"),
            "UID (Platform)": uid,
            "Task ID": task_id,
            "Decision (B)": decision_from_sheet.title() if decision_from_sheet else "",
            "Status (Platform)": status_platform.title() if status_platform else "",
            "Notes": notes[:200] if notes else "",
            "Completed At": today.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        self.completed_tasks.append(task_data)
        
        # Save immediately with lock to prevent concurrent write conflicts
        self._save_task(task_data)
        
    def _get_sheet_name(self):
        """Get sheet name from user email (sanitized for Excel)"""
        if not self.user_name:
            return "Unknown"
        # Extract username part before @ and limit to 31 chars (Excel limit)
        sheet_name = self.user_name.split('@')[0]
        # Remove invalid characters for Excel sheet names
        invalid_chars = ['\\', '/', '*', '?', ':', '[', ']']
        for char in invalid_chars:
            sheet_name = sheet_name.replace(char, '_')
        return sheet_name[:31].upper()  # Return uppercase to match existing sheets (G007, G008, etc.)
    
    def _save_task(self, task_data):
        """Save a single task to Excel - Thread-safe, each account to separate sheet"""
        with TaskLogger._lock:
            try:
                sheet_name = self._get_sheet_name()
                
                # Read existing file with all sheets
                if os.path.exists(self.log_file):
                    # Load all existing sheets
                    all_sheets = pd.read_excel(self.log_file, sheet_name=None)
                else:
                    all_sheets = {}
                
                # Get existing data for this sheet or create empty
                if sheet_name in all_sheets:
                    existing_df = all_sheets[sheet_name]
                else:
                    existing_df = pd.DataFrame()
                
                # Append new task
                new_df = pd.DataFrame([task_data])
                
                if existing_df.empty:
                    combined_df = new_df
                else:
                    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
                
                # Update this sheet in all_sheets
                all_sheets[sheet_name] = combined_df
                
                # Save all sheets to file
                with pd.ExcelWriter(self.log_file, engine='openpyxl') as writer:
                    for sname, sdata in all_sheets.items():
                        sdata.to_excel(writer, sheet_name=sname, index=False)
                
            except Exception as e:
                print(f"⚠️ Error saving task: {e}")
        
    def get_completed_count(self):
        return len(self.completed_tasks)
