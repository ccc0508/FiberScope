"""Answer standalone questions about today's calendar date from the system clock."""

from datetime import datetime
import re
from zoneinfo import ZoneInfo


_TODAY_QUESTION = re.compile(
    r'(?:(?:请问|请告诉我)[，,：:]?)?(?:今天|今日|现在)是?'
    r'(?:星期几|礼拜几|周几|几月几[日号]|几号|什么日期)[呀啊呢吗]?'
)
_WEEKDAYS = '一二三四五六日'


def calendar_run(question: str) -> dict | None:
    query = re.sub(r'\s+', '', question).rstrip('？?。！!')
    if not _TODAY_QUESTION.fullmatch(query):
        return None

    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    answer = f'北京时间今天是{today.year}年{today.month}月{today.day}日，星期{_WEEKDAYS[today.weekday()]}。'
    return dict(question=question, status='completed', answer=answer, draft='',
                review_status='not_required', stop_reason=None, pipeline_version='calendar-direct-v1',
                model_calls=[], tool_calls=[])
