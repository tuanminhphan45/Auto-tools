import os
import random
import time

import pandas as pd

from src.logger_utils import ColoredLogger as log

# Google Sheets support
try:
    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False


class DataManager:
    def __init__(self, file_path=None, google_sheet_id=None, credentials_file=None):
        """
        Initialize DataManager with either local file or Google Sheet
        
        Args:
            file_path: Path to local Excel/CSV file
            google_sheet_id: Google Sheet ID (from URL)
            credentials_file: Path to Google OAuth credentials JSON file
        """
        self.file_path = file_path
        self.google_sheet_id = google_sheet_id
        self.credentials_file = credentials_file or os.getenv("GOOGLE_CREDENTIALS_FILE", "oauth_credentials.json")
        self.df = None
        self.gc = None  # Google Sheets client
        self.sheet = None
        
        # Auto-accept whitelist from ok.xlsx
        self.whitelist_uids = set()
        self.whitelist_task_links = set()
        self._load_whitelist()
        
        # Auto-refresh settings
        self.last_refresh_time = 0
        self.next_refresh_interval = self._get_random_refresh_interval()
        
        if google_sheet_id:
            self.load_from_google_sheets()
        elif file_path:
            self.load_data()
    
    def _load_whitelist(self):
        """Load auto-accept whitelist from ok.xlsx"""
        whitelist_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ok.xlsx')
        if os.path.exists(whitelist_file):
            try:
                df_whitelist = pd.read_excel(whitelist_file, sheet_name=0)
                if 'UID' in df_whitelist.columns:
                    self.whitelist_uids = set(df_whitelist['UID'].dropna().astype(str).str.strip())
                if 'Task Link' in df_whitelist.columns:
                    self.whitelist_task_links = set(df_whitelist['Task Link'].dropna().astype(str).str.strip())
                log.log_status(f"Loaded whitelist: {len(self.whitelist_uids)} UIDs, {len(self.whitelist_task_links)} Task Links", 'INFO')
            except Exception as e:
                log.log_status(f"Error loading whitelist from ok.xlsx: {e}", 'WARNING')
    
    def _is_in_whitelist(self, task_id):
        """Check if task_id or task_link is in whitelist"""
        # Check if task_id matches any UID in whitelist
        if task_id in self.whitelist_uids:
            return True
        # Check if task_id is contained in any Task Link
        for link in self.whitelist_task_links:
            if task_id in link:
                return True
        return False
    
    def _get_random_refresh_interval(self):
        """Get random refresh interval from config"""
        from config import REFRESH_MAX_MINUTES, REFRESH_MIN_MINUTES
        return random.randint(REFRESH_MIN_MINUTES * 60, REFRESH_MAX_MINUTES * 60)
    
    def _should_refresh(self):
        """Check if we should refresh data"""
        if not self.sheet:
            return False
        elapsed = time.time() - self.last_refresh_time
        return elapsed >= self.next_refresh_interval
    
    def auto_refresh_if_needed(self):
        """Auto-refresh data from Google Sheets if needed"""
        if self._should_refresh():
            self.refresh_from_google_sheets()
            self.next_refresh_interval = self._get_random_refresh_interval()
            log.log_status(f"Next refresh in {self.next_refresh_interval // 60} minutes", 'INFO')

    def load_from_google_sheets(self):
        """Load data from Google Sheets (realtime) using OAuth"""
        if not GSPREAD_AVAILABLE:
            log.log_status("gspread not installed. Run: pip install gspread google-auth-oauthlib", 'ERROR')
            return
        
        if not os.path.exists(self.credentials_file):
            log.log_status(f"Credentials file not found: {self.credentials_file}", 'ERROR')
            return
        
        try:
            SCOPES = [
                'https://www.googleapis.com/auth/spreadsheets.readonly',
                'https://www.googleapis.com/auth/drive.readonly'
            ]
            
            creds = None
            token_file = 'token.json'
            
            # Check if we have saved credentials
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            
            # If no valid credentials, do OAuth flow
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    log.log_status("Opening browser for Google authentication...", 'INFO')
                    flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Save credentials for next run
                with open(token_file, 'w') as token:
                    token.write(creds.to_json())
                log.log_status("Google authentication successful!", 'SUCCESS')
            
            # Connect to Google Sheets
            log.log_status("Connecting to Google Sheets...", 'INFO')
            self.gc = gspread.authorize(creds)
            
            # Open the sheet
            log.log_status("Opening spreadsheet...", 'INFO')
            spreadsheet = self.gc.open_by_key(self.google_sheet_id)
            self.sheet = spreadsheet.worksheet('FULL_BATCH')
            
            # Get all data as DataFrame (handle duplicate headers)
            log.log_status("Downloading data (this may take a moment)...", 'INFO')
            try:
                data = self.sheet.get_all_records()
            except Exception:
                # If headers have duplicates, get as list of lists
                all_values = self.sheet.get_all_values()
                if len(all_values) > 0:
                    # Use first row as headers, make unique if duplicates
                    headers = all_values[0]
                    seen = {}
                    unique_headers = []
                    for h in headers:
                        if h in seen:
                            seen[h] += 1
                            unique_headers.append(f"{h}_{seen[h]}")
                        else:
                            seen[h] = 0
                            unique_headers.append(h)
                    data = [dict(zip(unique_headers, row)) for row in all_values[1:]]
                else:
                    data = []
            
            self.df = pd.DataFrame(data)
            self.last_refresh_time = time.time()
            
            log.log_status(f"Loaded {len(self.df)} rows from Google Sheets (realtime)", 'SUCCESS')
            log.log_status(f"Next refresh in {self.next_refresh_interval // 60} minutes", 'INFO')
            
        except Exception as e:
            log.log_status(f"Error loading Google Sheet: {e}", 'ERROR')
            log.log_status("Falling back to local file...", 'WARNING')
            if self.file_path:
                self.load_data()

    def refresh_from_google_sheets(self):
        """Refresh data from Google Sheets"""
        if self.sheet:
            try:
                data = self.sheet.get_all_records()
            except Exception:
                # Handle duplicate headers
                all_values = self.sheet.get_all_values()
                if len(all_values) > 0:
                    headers = all_values[0]
                    seen = {}
                    unique_headers = []
                    for h in headers:
                        if h in seen:
                            seen[h] += 1
                            unique_headers.append(f"{h}_{seen[h]}")
                        else:
                            seen[h] = 0
                            unique_headers.append(h)
                    data = [dict(zip(unique_headers, row)) for row in all_values[1:]]
                else:
                    data = []
            
            self.df = pd.DataFrame(data)
            self.last_refresh_time = time.time()
            log.log_status(f"Refreshed {len(self.df)} rows from Google Sheets", 'SUCCESS')

    def load_data(self):
        """Load data from local file"""
        if not self.file_path or not os.path.exists(self.file_path):
            log.log_status(f"File not found: {self.file_path}", 'ERROR')
            return
        
        if self.file_path.endswith('.csv'):
            self.df = pd.read_csv(self.file_path)
        elif self.file_path.endswith('.xlsx'):
            self.df = pd.read_excel(self.file_path, sheet_name='FULL_BATCH')
        else:
            raise ValueError("Unsupported file format. Use .csv or .xlsx")
        
        log.log_status(f"Loaded {len(self.df)} rows from {self.file_path}", 'SUCCESS')
    
    def get_record_count(self):
        """Get the number of records loaded"""
        return len(self.df) if self.df is not None else 0

    def get_decision(self, task_id):
        """
        Returns a decision dict based on nereid-evals.xlsx structure.
        Also returns raw row data for logging purposes.
        
        Returns tuple: (decision_dict, row_data_dict)
        """
        # Auto-refresh if needed
        self.auto_refresh_if_needed()
        
        # Check whitelist first - if task_id is in ok.xlsx, auto ACCEPT
        if self._is_in_whitelist(task_id):
            print(f"  ✅ Task {task_id} found in whitelist (ok.xlsx) -> AUTO ACCEPT")
            return {"action": "ACCEPT", "notes": "Auto-accepted from whitelist (ok.xlsx)"}, None
        
        if self.df is None:
            return {"action": "UNSURE", "notes": "Data file not loaded"}, None

        # Search for task_id in 'trace_id' column
        row_df = self.df[self.df['trace_id'].astype(str).str.contains(task_id, case=False, na=False)]
        
        if row_df.empty:
            # Task ID not found in sheet -> UNSURE
            return {"action": "UNSURE", "notes": "Task ID not found in Evals sheet"}, None
        
        row_data = row_df.iloc[0]
        
        # Extract row data for logging
        raw_row_data = {
            'decision': str(row_data.get('decision', '')) if pd.notna(row_data.get('decision')) else '',
            'overall_score': float(row_data.get('overall_score', 0)) if pd.notna(row_data.get('overall_score')) else 0,
            'confidence': float(row_data.get('confidence', 0)) if pd.notna(row_data.get('confidence')) else 0,
            'task_correctness_score': float(row_data.get('task_correctness_score', 0)) if pd.notna(row_data.get('task_correctness_score')) else 0,
            'causal_explainability_score': float(row_data.get('causal_explainability_score', 0)) if pd.notna(row_data.get('causal_explainability_score')) else 0,
            'response_accuracy_score': float(row_data.get('response_accuracy_score', 0)) if pd.notna(row_data.get('response_accuracy_score')) else 0,
        }
        
        # Extract values
        overall_score = raw_row_data['overall_score']              # Column C
        confidence = raw_row_data['confidence']                     # Column D
        task_correctness = raw_row_data['task_correctness_score']   # Column E
        causal_score = raw_row_data['causal_explainability_score']  # Column G
        response_accuracy = raw_row_data['response_accuracy_score'] # Column I
        
        # Column K = step_evaluations -> For "Notes" box
        column_k = str(row_data.get('step_evaluations', '')) if pd.notna(row_data.get('step_evaluations')) else ""
        
        # Column L = notes -> For "Revision Notes" box  
        column_l = str(row_data.get('notes', '')) if pd.notna(row_data.get('notes')) else ""

        # --- DECISION LOGIC ---
        
        decision_col = raw_row_data['decision'].upper().strip()
        
        # Rule 1: If Column B = "REVIEW" -> Check based on reviewer analysis
        if decision_col == "REVIEW":
            # Based on actual reviewer behavior analysis:
            # Rule 1a: LOW SCORES (C < 0.5 OR E < 0.5 OR I < 0.5) -> REVISE
            # Rule 1b: HIGH SCORE (C >= 0.73) -> Always ACCEPT
            # Rule 1c: MEDIUM SCORE (0.57 <= C < 0.73) -> Random 59% ACCEPT / 41% REVISE
            # Rule 1d: LOW-MEDIUM (0.5 <= C < 0.57) -> REVISE
            
            # Rule 1a: Low score threshold - any score below 0.5 = REVISE
            if overall_score < 0.5 or task_correctness < 0.5 or response_accuracy < 0.5:
                print(f"  📋 B='REVIEW', C={overall_score}, E={task_correctness}, I={response_accuracy} -> LOW SCORE: REVISE")
                return {
                    "action": "REVISE",
                    "notes": column_k,
                    "revision_notes": column_l
                }, raw_row_data
            
            # Rule 1b: High score (C >= 0.73) -> Always ACCEPT
            elif overall_score >= 0.73:
                print(f"  📋 B='REVIEW', C={overall_score} >= 0.73 -> ACCEPT")
                return {
                    "action": "ACCEPT",
                    "notes": column_k
                }, raw_row_data
            
            # Rule 1c: Medium score (0.57 <= C < 0.73) -> Random 53% ACCEPT / 41% REVISE / 6% UNSURE
            elif overall_score >= 0.57:
                rand_val = random.random()
                if rand_val < 0.53:
                    print(f"  📋 B='REVIEW', C={overall_score} (0.57-0.73) -> Random: ACCEPT")
                    return {
                        "action": "ACCEPT",
                        "notes": column_k
                    }, raw_row_data
                elif rand_val < 0.96:  # 0.55 to 0.96 = 41%
                    print(f"  📋 B='REVIEW', C={overall_score} (0.57-0.73) -> Random: REVISE")
                    return {
                        "action": "REVISE",
                        "notes": column_k,
                        "revision_notes": column_l
                    }, raw_row_data
                else:  # 0.96 to 1.0 = 4%
                    print(f"  📋 B='REVIEW', C={overall_score} (0.57-0.73) -> Random: UNSURE")
                    return {
                        "action": "UNSURE",
                        "notes": column_k
                    }, raw_row_data
            
            # Rule 1d: Low-medium (0.5 <= C < 0.57) -> REVISE
            else:
                print(f"  📋 B='REVIEW', C={overall_score} (0.5-0.57) -> REVISE")
                return {
                    "action": "REVISE",
                    "notes": column_k,
                    "revision_notes": column_l
                }, raw_row_data
        
        # Rule: If Column B = "ACCEPT" -> Trust it and ACCEPT (no random revision)
        if decision_col == "ACCEPT":
            return {
                "action": "ACCEPT",
                "notes": column_k
            }, raw_row_data
        
        # Rule: If Column B = "REVISE" -> Trust it and REVISE
        if decision_col == "REVISE":
            return {
                "action": "REVISE",
                "notes": column_k,
                "revision_notes": column_l
            }, raw_row_data
        
        # Import config values
        from config import (
            GRAY_ZONE_ACCEPT_CHANCE,
            SCORE_AUTO_ACCEPT,
            SCORE_GRAY_ZONE_MIN,
        )

        # Rule 1: Accept if overall_score >= SCORE_AUTO_ACCEPT (0.8)
        if overall_score >= SCORE_AUTO_ACCEPT:
            return {
                "action": "ACCEPT",
                "notes": column_k
            }, raw_row_data
        
        # Rule 2: Random Accept or Revise if in gray zone (0.78 <= score < 0.8)
        if SCORE_GRAY_ZONE_MIN <= overall_score < SCORE_AUTO_ACCEPT:
            if random.random() < GRAY_ZONE_ACCEPT_CHANCE:
                return {
                    "action": "ACCEPT",
                    "notes": column_k
                }, raw_row_data
            else:
                return {
                    "action": "REVISE",
                    "notes": column_k,
                    "revision_notes": column_l
                }, raw_row_data
        
        # Rule 3: If score is low but exists -> Needs Revision
        if overall_score > 0 and overall_score < SCORE_GRAY_ZONE_MIN:
            return {
                "action": "REVISE",
                "notes": column_k,
                "revision_notes": column_l
            }, raw_row_data
        
        # Fallback: UNSURE
        return {
            "action": "UNSURE",
            "notes": column_k
        }, raw_row_data
