import time
import httpx

HOSTS = {'content': 'https://content-api.wildberries.ru',
         'analytics': 'https://seller-analytics-api.wildberries.ru'}


class WBError(Exception):
    pass


class WB:
    def __init__(self, account, interval=21, client=None, sleep=time.sleep, clock=time.monotonic):
        self.client = client or httpx.Client(timeout=90, follow_redirects=False)
        self.headers = {'Authorization': account.token}
        if account.secret:
            self.headers['X-Client-Secret'] = account.secret
        self.interval = interval
        self.sleep, self.clock = sleep, clock
        self.last = {}
        self.cache = None
        self.cache_time = 0

    def close(self):
        self.client.close()

    def request(self, host, path, body):
        for attempt in range(5):
            interval = self.interval if host == 'analytics' else .7
            wait = interval - (self.clock() - self.last.get(host, -1e10))
            if wait > 0:
                self.sleep(wait)
            self.last[host] = self.clock()
            try:
                r = self.client.post(HOSTS[host] + path, json=body, headers=self.headers)
            except httpx.HTTPError:
                if attempt == 4:
                    raise WBError('WB: соединение не установлено после повторных попыток') from None
                self.sleep(2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == 4:
                    raise WBError(f'WB: HTTP {r.status_code}, повторы исчерпаны')
                try:
                    delay = max(1, float(r.headers.get('X-Ratelimit-Retry', r.headers.get('Retry-After', '30'))))
                except ValueError:
                    delay = 30
                # A long base-token limit should not block all queued reports for an hour.
                if delay > 300:
                    raise WBError('WB: длительный лимит API. Повторите позже; проверьте тип токена и интервал запросов')
                self.sleep(max(delay, 2 ** attempt))
                continue
            if not r.is_success:
                reasons = {401: 'истёк токен или неверная авторизация',
                           402: 'отчёт недоступен на текущем тарифе',
                           403: 'нет прав токена или доступа к отчёту',
                           400: 'WB отклонил параметры отчёта; проверьте тариф и лимит запросов'}
                raise WBError(f'WB: HTTP {r.status_code} — {reasons.get(r.status_code, "метод недоступен")}')
            try:
                value = r.json()
            except ValueError:
                raise WBError('WB вернул ответ неизвестного формата') from None
            if not isinstance(value, dict) or value.get('error'):
                raise WBError('WB вернул ошибку или изменил формат ответа')
            return value
        raise WBError('WB: запрос не завершён')

    def catalog(self, refresh=False):
        if self.cache is not None and not refresh and self.clock() - self.cache_time < 900:
            return self.cache
        cursor, cards, seen = {'limit': 100}, {}, set()
        while True:
            value = self.request('content', '/content/v2/get/cards/list', {
                'settings': {'sort': {'ascending': True}, 'filter': {'withPhoto': -1}, 'cursor': cursor}})
            page, next_cursor = value.get('cards'), value.get('cursor')
            if not isinstance(page, list) or not isinstance(next_cursor, dict):
                raise WBError('Изменился формат каталога WB')
            for card in page:
                if not isinstance(card, dict) or not card.get('nmID'):
                    raise WBError('В каталоге отсутствует артикул WB')
                cards[int(card['nmID'])] = card
            total = next_cursor.get('total')
            if not isinstance(total, int):
                raise WBError('В каталоге отсутствует счётчик страниц')
            if total < 100:
                break
            marker = (next_cursor.get('updatedAt'), next_cursor.get('nmID'))
            if not all(marker) or marker in seen:
                raise WBError('WB повторил страницу каталога; полный поиск не завершён')
            seen.add(marker)
            cursor = {'limit': 100, 'updatedAt': marker[0], 'nmID': marker[1]}
        self.cache, self.cache_time = list(cards.values()), self.clock()
        return self.cache

    def queries(self, nm_id, start, end, limit):
        value = self.request('analytics', '/api/v2/search-report/product/search-texts', {
            'currentPeriod': {'start': start.isoformat(), 'end': end.isoformat()},
            'nmIds': [nm_id], 'topOrderBy': 'openCard',
            'includeSubstitutedSKUs': False, 'includeSearchTexts': True,
            'orderBy': {'field': 'openCard', 'mode': 'desc'}, 'limit': limit})
        items = value.get('data', {}).get('items')
        if not isinstance(items, list):
            raise WBError('Изменился формат поисковой аналитики WB')
        result = []
        for row in items:
            if not isinstance(row, dict) or not isinstance(row.get('text'), str) or row.get('nmId') != nm_id:
                raise WBError('WB вернул некорректные запросы или чужой артикул')
            result.append(row)
        return result
