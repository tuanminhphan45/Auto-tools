"""
Logging utilities for better readability with multiple concurrent accounts
"""
import logging
import re
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler


class ColoredLogger:
    """Thread-safe colored logger with account prefixes"""
    
    # ANSI color codes
    COLORS = {
        'RESET': '\033[0m',
        'RED': '\033[91m',
        'GREEN': '\033[92m',
        'YELLOW': '\033[93m',
        'BLUE': '\033[94m',
        'MAGENTA': '\033[95m',
        'CYAN': '\033[96m',
        'WHITE': '\033[97m',
        'GRAY': '\033[90m',
    }
    
    # Account color mapping (rotates through colors)
    ACCOUNT_COLORS = ['CYAN', 'MAGENTA', 'YELLOW', 'BLUE', 'GREEN']
    
    _lock = threading.Lock()
    _account_color_map = {}
    _color_index = 0
    _file_logger = None
    _file_logging_enabled = False
    
    @classmethod
    def enable_file_logging(cls, log_file="watchdog.log", max_bytes=10*1024*1024, backup_count=5):
        """Enable logging to file with rotation"""
        if cls._file_logger is None:
            cls._file_logger = logging.getLogger('WatchdogLogger')
            cls._file_logger.setLevel(logging.INFO)
            
            # Rotating file handler (10MB per file, keep 5 backups)
            handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            handler.setLevel(logging.INFO)
            
            # Simple format for file (no colors)
            formatter = logging.Formatter(
                '%(asctime)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            
            cls._file_logger.addHandler(handler)
            cls._file_logging_enabled = True
    
    @classmethod
    def _strip_ansi(cls, text):
        """Remove ANSI color codes from text"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)
    
    @classmethod
    def _log_to_file(cls, message):
        """Log message to file (without colors)"""
        if cls._file_logging_enabled and cls._file_logger:
            clean_message = cls._strip_ansi(message)
            cls._file_logger.info(clean_message)
    
    @classmethod
    def _get_account_color(cls, email):
        """Get consistent color for an account"""
        if email not in cls._account_color_map:
            cls._account_color_map[email] = cls.ACCOUNT_COLORS[cls._color_index % len(cls.ACCOUNT_COLORS)]
            cls._color_index += 1
        return cls._account_color_map[email]
    
    @classmethod
    def _colorize(cls, text, color):
        """Add color to text"""
        return f"{cls.COLORS.get(color, '')}{text}{cls.COLORS['RESET']}"
    
    @classmethod
    def _get_short_email(cls, email):
        """Get short version of email (first part before @)"""
        return email.split('@')[0][:8].upper()
    
    @classmethod
    def log(cls, email, message, level='INFO'):
        """
        Thread-safe logging with account prefix
        
        Args:
            email: Account email
            message: Log message
            level: INFO, SUCCESS, WARNING, ERROR, DEBUG
        """
        with cls._lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            short_email = cls._get_short_email(email)
            account_color = cls._get_account_color(email)
            
            # Level colors
            level_colors = {
                'INFO': 'WHITE',
                'SUCCESS': 'GREEN',
                'WARNING': 'YELLOW',
                'ERROR': 'RED',
                'DEBUG': 'GRAY'
            }
            level_color = level_colors.get(level, 'WHITE')
            
            # Format: [HH:MM:SS] [ACCOUNT] message
            timestamp_str = cls._colorize(f"[{timestamp}]", 'GRAY')
            account_str = cls._colorize(f"[{short_email:8}]", account_color)
            message_str = cls._colorize(message, level_color)
            
            output = f"{timestamp_str} {account_str} {message_str}"
            print(output)
            cls._log_to_file(output)
    
    @classmethod
    def log_task(cls, email, task_num, total, task_id, decision, scores=None, sheet_decision=None):
        """
        Log task completion in compact format with optional scores
        
        Args:
            email: Account email
            task_num: Current task number
            total: Total tasks
            task_id: Task ID
            decision: Final decision action (ACCEPT, REVISE, etc.)
            scores: Optional dict with 'C', 'E', 'I' scores
            sheet_decision: Optional original decision from sheet (column B)
        """
        with cls._lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            short_email = cls._get_short_email(email)
            account_color = cls._get_account_color(email)
            
            # Decision colors
            decision_colors = {
                'ACCEPT': 'GREEN',
                'REVISE': 'YELLOW',
                'UNSURE': 'MAGENTA',
                'REJECT': 'RED',
                'REVIEW': 'CYAN'
            }
            decision_color = decision_colors.get(decision, 'WHITE')
            
            timestamp_str = cls._colorize(f"[{timestamp}]", 'GRAY')
            account_str = cls._colorize(f"[{short_email:8}]", account_color)
            progress_str = cls._colorize(f"Task {task_num:3}/{total}", 'CYAN')
            
            # Add sheet decision if provided
            sheet_decision_str = ""
            if sheet_decision:
                sheet_color = decision_colors.get(sheet_decision.upper(), 'WHITE')
                sheet_decision_str = cls._colorize(f"{sheet_decision.upper():6} ", sheet_color)
            
            decision_str = cls._colorize(f"{decision:6}", decision_color)
            task_id_short = task_id[-30:] if len(task_id) > 30 else task_id
            
            # Add scores if provided
            scores_str = ""
            if scores:
                c = scores.get('C', 0)
                e = scores.get('E', 0)
                i = scores.get('I', 0)
                scores_str = cls._colorize(f" [C:{c:.2f} E:{e:.2f} I:{i:.2f}]", 'GRAY')
            
            output = f"{timestamp_str} {account_str} {progress_str} {sheet_decision_str}→ {decision_str}{scores_str} | {task_id_short}"
            print(output)
            cls._log_to_file(output)
    
    @classmethod
    def log_status(cls, message, level='INFO'):
        """Log system-wide status (no account prefix)"""
        with cls._lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            level_colors = {
                'INFO': 'CYAN',
                'SUCCESS': 'GREEN',
                'WARNING': 'YELLOW',
                'ERROR': 'RED'
            }
            level_color = level_colors.get(level, 'CYAN')
            
            timestamp_str = cls._colorize(f"[{timestamp}]", 'GRAY')
            message_str = cls._colorize(f"👁️  {message}", level_color)
            
            output = f"{timestamp_str} {message_str}"
            print(output)
            cls._log_to_file(output)
    
    @classmethod
    def log_separator(cls, title=None):
        """Print a separator line"""
        with cls._lock:
            if title:
                separator = f"\n{'='*60}\n  {title}\n{'='*60}"
                print(separator)
                cls._log_to_file(separator)
            else:
                separator = f"{'─'*60}"
                print(separator)
                cls._log_to_file(separator)
    
    @classmethod
    def log_incomplete_status(cls, incomplete_accounts):
        """Log status of incomplete accounts"""
        with cls._lock:
            if not incomplete_accounts:
                return
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            timestamp_str = cls._colorize(f"[{timestamp}]", 'GRAY')
            header = cls._colorize(f"⚠️  INCOMPLETE ACCOUNTS: {len(incomplete_accounts)}", 'RED')
            print(f"{timestamp_str} {header}")
            
            for acc in incomplete_accounts:
                email = acc['email']
                short_email = cls._get_short_email(email)
                account_color = cls._get_account_color(email)
                account_str = cls._colorize(f"   [{short_email:8}]", account_color)
                progress = f"{acc['completed_tasks']}/{acc['max_tasks']} tasks"
                remaining = cls._colorize(f"({acc['remaining_tasks']} remaining)", 'YELLOW')
                restart = cls._colorize(f"[Restart #{acc['restart_count']}]", 'MAGENTA')
                output = f"{account_str} {progress} {remaining} {restart}"
                print(output)
                cls._log_to_file(output)
    
    @classmethod
    def log_queue_status(cls, incomplete_count, normal_count):
        """Log queue status"""
        with cls._lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            timestamp_str = cls._colorize(f"[{timestamp}]", 'GRAY')
            
            incomplete_str = cls._colorize(f"INCOMPLETE: {incomplete_count}", 'RED' if incomplete_count > 0 else 'GREEN')
            normal_str = cls._colorize(f"NORMAL: {normal_count}", 'GREEN')
            
            output = f"{timestamp_str} 📋 Queue Status | {incomplete_str} | {normal_str}"
            print(output)
            cls._log_to_file(output)
