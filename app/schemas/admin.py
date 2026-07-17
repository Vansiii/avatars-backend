from datetime import datetime

from pydantic import BaseModel


class MetricsResponse(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    characters_this_week: int
    spots_this_week: int


class UserLimitsResponse(BaseModel):
    user_id: str
    user_email: str
    user_name: str
    week_start: datetime
    characters_used: int
    characters_limit: int
    characters_remaining: int
    spots_used: int
    spots_limit: int
    spots_remaining: int


class UserLimitsUpdate(BaseModel):
    characters_limit: int | None = None
    spots_limit: int | None = None
