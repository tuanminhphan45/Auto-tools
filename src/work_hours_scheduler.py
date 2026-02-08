"""
Work Hours Scheduler - Giới hạn giờ làm việc mỗi ngày
Đảm bảo hệ thống chỉ chạy trong khung giờ quy định (mặc định: 08:00 - 18:00)
"""
import threading
from datetime import datetime, time
from typing import Optional


class WorkHoursScheduler:
    """Quản lý giờ làm việc - chỉ cho phép chạy tasks trong khung giờ quy định"""
    
    _lock = threading.Lock()
    _instance = None
    
    def __init__(self, start_hour: int = 8, end_hour: int = 18, enabled: bool = True):
        """
        Args:
            start_hour: Giờ bắt đầu (0-23), mặc định 8 (08:00)
            end_hour: Giờ kết thúc (0-23), mặc định 18 (18:00)
                      Nếu end_hour < start_hour, sẽ hiểu là overnight shift (qua đêm)
                      Ví dụ: start=20, end=8 nghĩa là 20:00 tối → 08:00 sáng hôm sau
            enabled: Bật/tắt giới hạn giờ làm việc
        """
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.enabled = enabled
        self.start_time = time(start_hour, 0)
        self.end_time = time(end_hour, 0)
        
    @classmethod
    def get_instance(cls, start_hour: int = 8, end_hour: int = 18, enabled: bool = True):
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = WorkHoursScheduler(start_hour, end_hour, enabled)
        return cls._instance
    
    def _is_overnight_shift(self) -> bool:
        """
        Kiểm tra xem có phải ca đêm (qua 0h) không
        
        Returns:
            True nếu là ca đêm (start_hour > end_hour), False nếu ca ngày
        """
        return self.start_hour > self.end_hour
    
    def is_within_work_hours(self, check_time: Optional[datetime] = None) -> bool:
        """
        Kiểm tra xem thời điểm hiện tại có trong giờ làm việc không
        
        Args:
            check_time: Thời điểm cần kiểm tra (None = hiện tại)
            
        Returns:
            True nếu trong giờ làm việc, False nếu ngoài giờ
        """
        if not self.enabled:
            return True  # Nếu tắt giới hạn, luôn cho phép chạy
            
        if check_time is None:
            check_time = datetime.now()
            
        current_time = check_time.time()
        
        # Kiểm tra xem có trong khoảng thời gian làm việc không
        if self._is_overnight_shift():
            # Ca đêm (ví dụ: 20:00 → 08:00): trong giờ nếu >= start HOẶC < end
            return current_time >= self.start_time or current_time < self.end_time
        else:
            # Ca ngày (ví dụ: 08:00 → 18:00): trong giờ nếu >= start VÀ < end
            return self.start_time <= current_time < self.end_time
    
    def can_run_tasks(self) -> bool:
        """
        Kiểm tra xem hiện tại có được phép chạy tasks không
        
        Returns:
            True nếu được phép chạy, False nếu cần pause
        """
        return self.is_within_work_hours()
    
    def get_time_until_work_starts(self) -> Optional[float]:
        """
        Tính số giây còn lại cho đến khi bắt đầu giờ làm việc
        
        Returns:
            Số giây, hoặc None nếu đang trong giờ làm việc
        """
        if not self.enabled or self.is_within_work_hours():
            return None
            
        now = datetime.now()
        current_time = now.time()
        
        if self._is_overnight_shift():
            # Ca đêm: nếu ngoài giờ làm việc, nghĩa là đang trong khoảng end → start
            # Ví dụ: 20:00 → 08:00, ngoài giờ là 08:00 → 20:00
            # Chỉ cần tính đến start_hour hôm nay
            work_start = now.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
            return (work_start - now).total_seconds()
        else:
            # Ca ngày: logic cũ
            # Nếu chưa đến giờ làm việc hôm nay
            if current_time < self.start_time:
                work_start = now.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
                return (work_start - now).total_seconds()
            
            # Nếu đã qua giờ làm việc hôm nay, tính đến ngày mai
            from datetime import timedelta
            tomorrow = now + timedelta(days=1)
            work_start = tomorrow.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
            return (work_start - now).total_seconds()
    
    def get_time_until_work_ends(self) -> Optional[float]:
        """
        Tính số giây còn lại cho đến khi kết thúc giờ làm việc
        
        Returns:
            Số giây, hoặc None nếu ngoài giờ làm việc
        """
        if not self.enabled or not self.is_within_work_hours():
            return None
            
        now = datetime.now()
        current_time = now.time()
        
        if self._is_overnight_shift():
            # Ca đêm: nếu đang >= start_hour (phần tối), kết thúc vào sáng mai
            if current_time >= self.start_time:
                from datetime import timedelta
                tomorrow = now + timedelta(days=1)
                work_end = tomorrow.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
                return (work_end - now).total_seconds()
            else:
                # Đang < end_hour (phần sáng), kết thúc hôm nay
                work_end = now.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
                return (work_end - now).total_seconds()
        else:
            # Ca ngày: logic cũ
            work_end = now.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
            return (work_end - now).total_seconds()
    
    def get_status_message(self) -> str:
        """
        Lấy thông báo trạng thái hiện tại
        
        Returns:
            Chuỗi mô tả trạng thái
        """
        if not self.enabled:
            return "⏰ Work hours: DISABLED (24/7 mode)"
        
        if self.is_within_work_hours():
            seconds_left = self.get_time_until_work_ends()
            if seconds_left:
                hours_left = seconds_left / 3600
                return f"✅ Work hours: ACTIVE (ends at {self.end_hour:02d}:00, {hours_left:.1f}h left)"
            return f"✅ Work hours: ACTIVE"
        else:
            seconds_until = self.get_time_until_work_starts()
            if seconds_until:
                hours_until = seconds_until / 3600
                return f"⏸️  Work hours: PAUSED (resumes at {self.start_hour:02d}:00, {hours_until:.1f}h until)"
            return f"⏸️  Work hours: PAUSED"
    
    def get_work_hours_string(self) -> str:
        """
        Lấy chuỗi mô tả giờ làm việc
        
        Returns:
            Ví dụ: "08:00 - 18:00"
        """
        return f"{self.start_hour:02d}:00 - {self.end_hour:02d}:00"
    
    def get_daily_work_hours(self) -> int:
        """
        Lấy số giờ làm việc mỗi ngày
        
        Returns:
            Số giờ
        """
        if self._is_overnight_shift():
            # Ca đêm: (24 - start) + end
            # Ví dụ: 20:00 → 08:00 = (24 - 20) + 8 = 12 giờ
            return (24 - self.start_hour) + self.end_hour
        else:
            # Ca ngày: end - start
            return self.end_hour - self.start_hour
    
    def should_pause_system(self) -> bool:
        """
        Kiểm tra xem có nên pause toàn bộ hệ thống không
        
        Returns:
            True nếu nên pause, False nếu tiếp tục
        """
        return not self.can_run_tasks()
    
    def __str__(self) -> str:
        """String representation"""
        if self.enabled:
            return f"WorkHoursScheduler({self.get_work_hours_string()}, {self.get_daily_work_hours()}h/day)"
        return "WorkHoursScheduler(DISABLED)"
    
    def __repr__(self) -> str:
        """Repr"""
        return self.__str__()
