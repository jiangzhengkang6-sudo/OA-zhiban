from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MeetingCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    reason: str = Field(default='', max_length=1000)


class MeetingTranscriptionStart(MeetingCommand):
    consent: Literal[True]


class MeetingFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    agenda: str = Field(min_length=1, max_length=20000)
    starts_at: datetime
    ends_at: datetime
    host_id: str = Field(min_length=1, max_length=64)
    recorder_id: str = Field(min_length=1, max_length=64)
    attendee_ids: list[str] = Field(min_length=1, max_length=100)
    location: str = Field(default='', max_length=255)
    online_url: str = Field(default='', max_length=2000)
    video_enabled: bool = False

    @field_validator('starts_at', 'ends_at')
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('会议时间必须包含时区')
        return value

    @field_validator('online_url')
    @classmethod
    def safe_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('请填写有效的 HTTP 或 HTTPS 会议链接')
        return value

    @model_validator(mode='after')
    def time_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError('结束时间必须晚于开始时间')
        if not self.location and not self.online_url and not self.video_enabled:
            raise ValueError('请填写会议地点、在线会议链接或启用视频会议')
        if any(not value.strip() or len(value) > 64 for value in self.attendee_ids):
            raise ValueError('参会人员无效')
        self.attendee_ids = sorted(set(self.attendee_ids))
        return self


class MeetingCreate(MeetingFields):
    operation_id: str = Field(min_length=1, max_length=64)


class MeetingUpdate(MeetingCreate):
    expected_revision: int = Field(ge=1)


class MeetingReply(MeetingCommand):
    invitation_version: int = Field(ge=1)
    response: Literal['ACCEPTED', 'DECLINED', 'TENTATIVE']
    note: str = Field(default='', max_length=500)


class MeetingMinutes(MeetingCommand):
    content: str = Field(min_length=1, max_length=100000)
