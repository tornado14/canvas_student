
DOMAIN = "canvas_student"

CONF_BASE_URL = "base_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_SCHOOL_NAME = "school_name"
CONF_STUDENT_NAME = "student_name"

OPT_HIDE_EMPTY = "hide_empty"
DEFAULT_HIDE_EMPTY = False

OPT_DAYS_AHEAD = "days_ahead"
OPT_ANN_DAYS = "announcement_days"
OPT_MISS_LOOKBACK = "missing_lookback"
OPT_UPDATE_MINUTES = "update_interval_minutes"

OPT_ENABLE_GPA = "enable_gpa"
OPT_GPA_SCALE = "gpa_scale"
OPT_CREDITS_MAP = "credits_by_course"

DEFAULT_DAYS_AHEAD = 42
DEFAULT_ANNOUNCEMENT_DAYS = 14
DEFAULT_MISSING_LOOKBACK = 180
DEFAULT_UPDATE_MINUTES = 10

DEFAULT_ENABLE_GPA = False
DEFAULT_GPA_SCALE = "us_4_0_plusminus"

API_PREFIX = "/api/v1"
PATH_USERS_SELF = API_PREFIX + "/users/self"
PATH_COURSES = API_PREFIX + "/courses"
PATH_ASSIGNMENTS = API_PREFIX + "/courses/{course_id}/assignments"
PATH_SUBMISSIONS_SELF = API_PREFIX + "/courses/{course_id}/assignments/{assignment_id}/submissions/self"
PATH_ANNOUNCEMENTS = API_PREFIX + "/announcements"
PATH_ENROLLMENTS = API_PREFIX + "/courses/{course_id}/enrollments"
