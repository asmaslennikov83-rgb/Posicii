"""Error diagnostics without exception values, URLs, locals or source lines."""
import errno
from pathlib import Path
import traceback
from uuid import uuid4

from .wb import WBError


def failure(log, stage, error):
    code = uuid4().hex[:8]
    frames = ' > '.join(f'{Path(f.filename).name}:{f.lineno} ({f.name})'
                        for f in traceback.extract_tb(error.__traceback__))
    log.error('Ошибка %s; этап=%s; тип=%s; стек=%s', code, stage, type(error).__name__, frames or '-')
    if isinstance(error, WBError):
        reason = str(error)
    elif isinstance(error, PermissionError):
        reason = 'нет прав на запись файлов; проверьте доступ к папке данных и временной папке сервера'
    elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
        reason = 'на сервере закончилось свободное место'
    elif isinstance(error, OSError):
        reason = 'системная ошибка чтения или записи файлов'
    elif isinstance(error, (TypeError, ValueError, KeyError, AttributeError)):
        reason = 'неожиданный формат данных; место сбоя записано в журнал сервера'
    else:
        reason = 'внутренняя ошибка; место сбоя записано в журнал сервера'
    return f'{reason}. Код ошибки: {code}'
