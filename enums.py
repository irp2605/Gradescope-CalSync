from enum import  Enum

class DateStrictness(Enum):
    ALL = 0
    NEVER_PAST_DUE_ALREADY_SUBMITTED = 1
    NEVER_ALREADY_SUBMITTED = 2
    NEVER_PAST_DUE = 3
    NEVER_PAST_DUE_UNLESS_LATE_OPEN = 4
    NEVER_PAST_DUE_UNLESS_LATE_OPEN_AND_NO_SUBMISSION = 5
