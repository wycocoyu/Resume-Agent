"""
PDF 内存 LRU 缓存单元测试
"""
import pytest
from backend.routes.pdf import PDFCache, _pdf_cache


def test_pdf_cache_basic_get_put():
    cache = PDFCache(max_size=3)
    assert cache.get("k1") is None

    cache.put("k1", b"pdf-data-1")
    assert cache.get("k1") == b"pdf-data-1"
    assert len(cache) == 1


def test_pdf_cache_lru_eviction():
    cache = PDFCache(max_size=3)
    cache.put("k1", b"data1")
    cache.put("k2", b"data2")
    cache.put("k3", b"data3")
    assert len(cache) == 3

    # Access k1 so k2 becomes the least recently used
    assert cache.get("k1") == b"data1"

    # Add k4 -> k2 should be evicted
    cache.put("k4", b"data4")
    assert len(cache) == 3
    assert cache.get("k2") is None
    assert cache.get("k1") == b"data1"
    assert cache.get("k3") == b"data3"
    assert cache.get("k4") == b"data4"


def test_pdf_cache_key_generation():
    cache = PDFCache()
    # Different order in dict keys should yield identical cache keys
    resume_a = {"name": "张三", "title": "架构师", "skills": ["Python", "Rust"]}
    resume_b = {"title": "架构师", "skills": ["Python", "Rust"], "name": "张三"}

    key_a = cache.get_cache_key(resume_a, ["basic", "skills"])
    key_b = cache.get_cache_key(resume_b, ["basic", "skills"])
    assert key_a == key_b

    # Different section order should yield different cache keys
    key_c = cache.get_cache_key(resume_a, ["skills", "basic"])
    assert key_a != key_c

    # Different content should yield different cache keys
    resume_diff = {"name": "李四", "title": "架构师", "skills": ["Python", "Rust"]}
    key_diff = cache.get_cache_key(resume_diff, ["basic", "skills"])
    assert key_a != key_diff


def test_pdf_cache_latex_key():
    cache = PDFCache()
    key1 = cache.get_latex_cache_key(r"\documentclass{resume}\begin{document}Hello\end{document}")
    key2 = cache.get_latex_cache_key(r"\documentclass{resume}\begin{document}Hello\end{document}")
    key3 = cache.get_latex_cache_key(r"\documentclass{resume}\begin{document}World\end{document}")
    assert key1 == key2
    assert key1 != key3


def test_pdf_cache_clear():
    cache = PDFCache(max_size=5)
    cache.put("k1", b"1")
    cache.put("k2", b"2")
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert cache.get("k1") is None


def test_pdf_cache_concurrent_access():
    import threading

    cache = PDFCache(max_size=10)
    errors = []

    def worker(worker_id: int):
        try:
            for i in range(50):
                key = f"key-{worker_id}-{i % 5}"
                cache.put(key, f"data-{worker_id}-{i}".encode("utf-8"))
                val = cache.get(key)
                if val is not None and not val.startswith(b"data-"):
                    errors.append(f"Invalid val: {val}")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(cache) <= 10
