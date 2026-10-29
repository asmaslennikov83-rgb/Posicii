import json
import time

import httpx
from .version import VERSION_LABEL


class TelegramError(Exception):
    pass


KEYBOARD = {'keyboard': [[{'text': 'Сформировать отчёты'}], [{'text': 'Изменить товар'}],
                        [{'text': VERSION_LABEL}]],
            'resize_keyboard': True}


class Telegram:
    def __init__(self, token):
        self.url = f'https://api.telegram.org/bot{token}/'
        self.client = httpx.Client(timeout=100)

    def call(self, method, data, files=None):
        for attempt in range(5):
            if files:
                for _, stream, _ in files.values():
                    stream.seek(0)
            try:
                r = self.client.post(self.url + method, data=data, files=files)
                value = r.json()
            except (httpx.HTTPError, ValueError):
                if attempt == 4:
                    raise TelegramError('Telegram: ошибка соединения') from None
                time.sleep(2 ** attempt)
                continue
            if value.get('ok'):
                return value.get('result')
            if r.status_code == 429:
                time.sleep(max(1, value.get('parameters', {}).get('retry_after', 10)))
                continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise TelegramError(f'Telegram: HTTP {r.status_code}; проверьте токен и чат')
        raise TelegramError('Telegram: исчерпаны повторы')

    def message(self, chat, text, keyboard=True):
        data = {'chat_id': chat, 'text': text[:4000]}
        if keyboard:
            data['reply_markup'] = json.dumps(KEYBOARD, ensure_ascii=False)
        return self.call('sendMessage', data)

    def document(self, chat, file, caption):
        with file.open('rb') as stream:
            return self.call('sendDocument', {'chat_id': chat, 'caption': caption[:1024]},
                             {'document': (file.name, stream,
                              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})

    def close(self):
        self.client.close()
