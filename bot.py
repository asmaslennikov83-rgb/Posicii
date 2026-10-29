if __name__ == '__main__' and not __package__:
    # Hosts may flatten the uploaded folder to /app and launch `python -m bot`.
    # Register this directory as the package before loading the real entry point.
    import importlib.util
    from pathlib import Path
    import sys

    if 'wb_positions' not in sys.modules:
        _root = Path(__file__).resolve().parent
        _spec = importlib.util.spec_from_file_location(
            'wb_positions', _root / '__init__.py', submodule_search_locations=[str(_root)])
        _package = importlib.util.module_from_spec(_spec)
        sys.modules['wb_positions'] = _package
        _spec.loader.exec_module(_package)
    from wb_positions.__main__ import main
    main()
    raise SystemExit(0)

from concurrent.futures import ThreadPoolExecutor
import logging
from queue import Queue, Empty
import threading
import time

from .reports import build_report, period, resolve
from .telegram import Telegram, TelegramError
from .wb import WB, WBError
from .version import VERSION_LABEL

LOG = logging.getLogger('wb_positions')


def authorized(message, allowed):
    user = message.get('from', {}).get('id')
    chat = message.get('chat', {})
    return user in allowed and chat.get('type') == 'private' and chat.get('id') == user


class Bot:
    def __init__(self, config, telegram=None, apis=None):
        self.config = config
        self.telegram = telegram or Telegram(config.telegram_token)
        self.apis = apis or {a.key: WB(a, config.analytics_interval) for a in config.accounts}
        self.selected = {}
        self.busy = set()
        self.lock = threading.Lock()
        self.queue = Queue(maxsize=len(config.allowed))
        self.stopping = threading.Event()

    def handle(self, message):
        if not authorized(message, self.config.allowed):
            return
        chat = message['chat']['id']
        text = message.get('text', '').strip()
        if text.startswith('Версия сборки:') or text == '/version':
            self.telegram.message(chat, VERSION_LABEL)
            return
        if not text:
            self.telegram.message(chat, 'Пришлите ШК или артикул продавца текстом.')
            return
        if text in ('/start', '/help'):
            self.telegram.message(chat, 'Пришлите ШК или артикул продавца, затем нажмите «Сформировать отчёты». '
                'Проверю оба кабинета и все ШК размеров. Период — последние 30 завершённых дней по Москве. '
                'Раздельные позиции требуют дополнительного источника; топ частотности из API ограничен доступной выборкой.')
            return
        if text == 'Изменить товар':
            self.selected.pop(chat, None)
            self.telegram.message(chat, 'Пришлите новый ШК или артикул продавца.')
            return
        if text in ('Сформировать отчёты', '/report'):
            query = self.selected.get(chat)
            if not query:
                self.telegram.message(chat, 'Сначала пришлите ШК или артикул продавца.')
                return
            with self.lock:
                if chat in self.busy:
                    self.telegram.message(chat, 'Ваш отчёт уже в очереди или формируется.')
                    return
                self.busy.add(chat)
                self.queue.put_nowait((chat, query, period()))
            self.telegram.message(chat, 'Запрос принят. Пришлю отдельный файл по каждому кабинету. '
                'При первом обращении загрузка каталога может занять несколько минут.')
            return
        if text.startswith('/') or len(text) > 200 or any(ord(c) < 32 for c in text):
            self.telegram.message(chat, 'Нужен один ШК или артикул продавца длиной до 200 символов.')
            return
        self.selected[chat] = text
        self.telegram.message(chat, f'Товар: {text}\nНажмите «Сформировать отчёты».')

    def safe_message(self, chat, text):
        try:
            self.telegram.message(chat, text)
        except TelegramError:
            LOG.error('Не удалось доставить уведомление; файлы сохранены локально')

    def run_job(self, chat, query, dates):
        start, end = dates
        catalogs, failures = {}, {}
        # Separate account clients and limits; a failed account never prevents the second report.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {a.key: pool.submit(self.apis[a.key].catalog, True) for a in self.config.accounts}
            for account in self.config.accounts:
                try:
                    catalogs[account.key] = futures[account.key].result()
                except WBError as error:
                    failures[account.key] = str(error)
        matched = resolve(catalogs, query)

        def collect(account):
            return build_report(account, query, matched.get(account.key, []), self.apis[account.key],
                                self.config.data_dir, start, end, self.config.query_limit)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {a.key: pool.submit(collect, a) for a in self.config.accounts if a.key not in failures}
            for account in self.config.accounts:
                if account.key in failures:
                    self.safe_message(chat, f'{account.name}: {failures[account.key]}. Отчёт второго кабинета обрабатывается независимо.')
                    continue
                try:
                    file, warnings = futures[account.key].result()
                    caption = f'{account.name}: {start:%d.%m.%Y}–{end:%d.%m.%Y}\n'
                    caption += 'Есть ограничения — смотрите первые строки Excel.' if warnings else 'Отчёт сформирован.'
                    self.telegram.document(chat, file, caption)
                    if warnings:
                        self.safe_message(chat, account.name + ':\n' + '\n'.join(warnings)[:3500])
                except TelegramError:
                    self.safe_message(chat, f'{account.name}: файл создан, но доставка не удалась. Файл сохранён на сервере.')
                except WBError as error:
                    self.safe_message(chat, f'{account.name}: {error}')
                except Exception:
                    # Never output raw HTTP exception URLs or credentials to logs.
                    LOG.error('Ошибка формирования файла кабинета %s', account.key)
                    self.safe_message(chat, f'{account.name}: ошибка формирования файла; проверьте свободное место и настройки.')

    def worker(self):
        while not self.stopping.is_set():
            try:
                chat, query, dates = self.queue.get(timeout=1)
            except Empty:
                continue
            try:
                self.run_job(chat, query, dates)
            except Exception:
                LOG.error('Не удалось завершить задание')
                self.safe_message(chat, 'Не удалось завершить задание. Повторите запрос.')
            finally:
                with self.lock:
                    self.busy.discard(chat)
                self.queue.task_done()

    def run(self):
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        worker = threading.Thread(target=self.worker, daemon=True)
        worker.start()
        # Drop pending updates on start so an old button does not trigger a new report.
        # Only one process may poll a given Telegram token.
        offset = 0
        pending = self.telegram.call('getUpdates', {'offset': -1, 'timeout': 0})
        if pending:
            offset = pending[-1]['update_id'] + 1
        try:
            while True:
                try:
                    updates = self.telegram.call('getUpdates', {'offset': offset, 'timeout': 45,
                                                  'allowed_updates': '["message"]'})
                    for update in updates:
                        offset = update['update_id'] + 1
                        if 'message' in update:
                            self.handle(update['message'])
                except TelegramError:
                    LOG.error('Telegram временно недоступен; повтор через 5 секунд')
                    time.sleep(5)
        finally:
            self.stopping.set()
            worker.join()
            for api in self.apis.values():
                api.close()
            self.telegram.close()


if __name__ == '__main__':
    from .__main__ import main
    main()
