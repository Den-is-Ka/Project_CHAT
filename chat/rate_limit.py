import time

from django.core.cache import cache


def rate_limit_allows(*, key_prefix, limit, window_seconds):
    """Атомарно учитывает действие и возвращает, укладывается ли оно в лимит.

    Для одного фиксированного временного окна используется отдельный ключ.
    add() атомарно создаёт первый счётчик, incr() атомарно увеличивает
    существующий. Это исключает гонку get() -> set() при параллельных запросах.
    """

    window = int(time.time()) // window_seconds
    key = f"{key_prefix}:{window}"
    timeout = window_seconds + 10

    if cache.add(key, 1, timeout=timeout):
        return True

    try:
        count = cache.incr(key)
    except ValueError:
        # Ключ мог истечь между add() и incr(). Повторяем создание один раз.
        if cache.add(key, 1, timeout=timeout):
            return True

        try:
            count = cache.incr(key)
        except ValueError:
            # Не разрешаем обход лимита при нестабильном состоянии кэша.
            return False

    return count <= limit
