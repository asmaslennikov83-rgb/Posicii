import logging
from .bot import Bot
from .config import Config


def main():
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
    # HTTP library logs can include the bot token in request URLs.
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    try:
        config = Config.load()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    try:
        Bot(config).run()
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit('Запуск не удался. Проверьте сеть, токен Telegram и отсутствие второго экземпляра бота.') from None


if __name__ == '__main__':
    main()
