"""Bounded API concurrency using the existing atomic request budget."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
from typing import Callable, Any

from quant.data.forecast_text_scores import ScoreCache


def score_parallel(selected: dict[str,str], *, settings: dict, cache_path: Path,
                   max_requests: int, max_usd: float, workers: int,
                   client_factory: Callable[[],Any], development_test: bool = False) -> dict:
    from quant.research.score_forecast_text import score_one
    if type(workers) is not int or not 2 <= workers <= 4:
        raise ValueError('Parallel text scoring requires 2-4 workers')
    stop = threading.Event()
    items = list(selected.items())

    def work(chunk):
        cache = ScoreCache(cache_path)
        client = None
        try:
            client = client_factory()
            result = {}
            for key,reason in chunk:
                if stop.is_set():
                    break
                result[key] = score_one(reason,settings=settings,cache=cache,client=client,
                    max_requests=max_requests,max_usd=max_usd,development_test=development_test)
            return result
        except BaseException:
            stop.set()
            raise
        finally:
            cache.close()
            if client is not None:
                client.close()

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(work,items[i::workers]) for i in range(min(workers,len(items)))]
        for future in as_completed(futures):
            results.update(future.result())
    return results
