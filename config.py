# ==========================================
# SNORKEL BOT - CONFIGURATION FILE
# ==========================================
# Tất cả các thông số có thể điều chỉnh

# ------------------------------------------
# DELAY TIMES (giả lập người thật - in seconds)
# ------------------------------------------
DELAY_ACCEPT_MIN = 10       # Min delay for ACCEPT action
DELAY_ACCEPT_MAX = 15       # Max delay for ACCEPT action

DELAY_REVISION_MIN = 12     # Min delay for REVISION/UNSURE action
DELAY_REVISION_MAX = 25     # Max delay for REVISION/UNSURE action

DELAY_REJECT_MIN = 17       # Min delay for REJECT action
DELAY_REJECT_MAX = 23       # Max delay for REJECT action

# ------------------------------------------
# DECISION LOGIC (overall_score thresholds)
# ------------------------------------------
SCORE_AUTO_ACCEPT = 0.8     # Score > này sẽ auto ACCEPT
SCORE_GRAY_ZONE_MIN = 0.78  # Score từ đây đến SCORE_AUTO_ACCEPT sẽ random Accept/Revise
GRAY_ZONE_ACCEPT_CHANCE = 0.50  # % chance accept trong gray zone (0.0 - 1.0)

# ------------------------------------------
# ROTATION SETTINGS
# ------------------------------------------
TASKS_PER_ROTATION = 100    # Mỗi account làm bao nhiêu task mỗi rotation

# ------------------------------------------
# AUTO-REFRESH (Google Sheets)
# ------------------------------------------
REFRESH_MIN_MINUTES = 3     # Min time before refresh (minutes)
REFRESH_MAX_MINUTES = 7     # Max time before refresh (minutes)

# ------------------------------------------
# PAGE WAIT TIMES (milliseconds/seconds)
# ------------------------------------------
WAIT_AFTER_LOGIN = 2000     # Wait after clicking sign in (ms)
WAIT_AFTER_CLICK = 1000     # Wait after clicking buttons (ms)
WAIT_PAGE_LOAD = 5000       # Wait for page to load (ms)
WAIT_BEFORE_SUBMIT_MIN = 1  # Min wait before submit (seconds)
WAIT_BEFORE_SUBMIT_MAX = 3  # Max wait before submit (seconds)

# ------------------------------------------
# BROWSER WATCHDOG SETTINGS
# ------------------------------------------
WATCHDOG_CHECK_INTERVAL = 45    # Seconds between health checks
WATCHDOG_MIN_BROWSERS = 1       # Always maintain this many browsers
WATCHDOG_MAX_RESTARTS = 3       # Max restart attempts per account

# ------------------------------------------
# WORK HOURS SCHEDULER (Giới hạn giờ làm việc)
# ------------------------------------------
ENABLE_WORK_HOURS = False        # Bật/tắt giới hạn giờ làm việc
WORK_HOURS_START = 19           # Giờ bắt đầu (0-23), 20 = 20:00 (8 giờ tối)
WORK_HOURS_END = 8              # Giờ kết thúc (0-23), 8 = 08:00 (8 giờ sáng)
# Với cấu hình trên: Chạy qua đêm 12 giờ/ngày (20:00 tối → 08:00 sáng hôm sau)
# Hỗ trợ overnight shift: Nếu END < START thì hiểu là qua đêm
# Ví dụ khác: START=22, END=6 → Chạy từ 22:00 tối đến 06:00 sáng (8 giờ)
# Tốc độ: ~1235 tasks/ngày → Hoàn thành 6158 tasks trong ~5 ngày

