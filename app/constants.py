from enum import StrEnum


class GroupState(StrEnum):
    UNKNOWN = 'UNKNOWN'
    FOUND = 'FOUND'
    NOT_FOUND = 'NOTFOUND'
