from pathlib import Path
from unittest.mock import patch

import pytest

from backend import company_logos, latex_generator, school_logos


FAKE_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake-png-payload"


@pytest.fixture(autouse=True)
def _reset_caches():
    company_logos.clear_cache()
    school_logos.clear_cache()
    latex_generator.clear_user_photo_cache()
    try:
        yield
    finally:
        company_logos.clear_cache()
        school_logos.clear_cache()
        latex_generator.clear_user_photo_cache()


def test_company_logo_local_first_even_in_production_mode(tmp_path, monkeypatch):
    local_dir = tmp_path / "logo"
    local_dir.mkdir(parents=True)
    (local_dir / "字节跳动.png").write_bytes(FAKE_PNG)

    monkeypatch.setattr(company_logos, "LOCAL_LOGO_DIR", local_dir)
    monkeypatch.setenv("LOG_MODE", "production")

    def fail_network(*_args, **_kwargs):
        raise AssertionError("COS network call should not happen when local logo exists")

    monkeypatch.setattr(company_logos, "_scan_cos_logos", fail_network)
    monkeypatch.setattr(company_logos, "_download_url_to_path", fail_network)

    out_dir = tmp_path / "compile_out"
    logo_map = company_logos.download_logos_to_dir(
        [{"company": "ByteDance", "logo": "bytedance"}],
        str(out_dir),
    )

    assert logo_map == {0: "logo_0.png"}
    assert (out_dir / "logos" / "logo_0.png").read_bytes() == FAKE_PNG


def test_company_logo_cos_miss_persists_then_hits_local(tmp_path, monkeypatch):
    local_dir = tmp_path / "logo"
    local_dir.mkdir(parents=True)

    monkeypatch.setattr(company_logos, "LOCAL_LOGO_DIR", local_dir)
    monkeypatch.setenv("LOG_MODE", "production")

    scan_calls = 0
    download_calls = 0

    def fake_scan_cos():
        nonlocal scan_calls
        scan_calls += 1
        company_logos._cos_key_to_file = {"acme_corp": "company_logo/acme_corp.png"}
        company_logos._key_to_file = dict(company_logos._cos_key_to_file)
        return [{"key": "acme_corp", "name": "acme_corp", "url": "https://cos.example/company_logo/acme_corp.png"}]

    def fake_download(url, local_path, timeout=15.0):
        nonlocal download_calls
        download_calls += 1
        Path(local_path).write_bytes(FAKE_PNG)

    monkeypatch.setattr(company_logos, "_scan_cos_logos", fake_scan_cos)
    monkeypatch.setattr(company_logos, "_download_url_to_path", fake_download)

    out1 = tmp_path / "compile_1"
    map1 = company_logos.download_logos_to_dir([{"logo": "acme_corp"}], str(out1))
    assert map1 == {0: "logo_0.png"}
    assert scan_calls == 1
    assert download_calls == 1
    assert (local_dir / "acme_corp.png").is_file()

    out2 = tmp_path / "compile_2"
    map2 = company_logos.download_logos_to_dir([{"logo": "acme_corp"}], str(out2))
    assert map2 == {0: "logo_0.png"}
    assert (out2 / "logos" / "logo_0.png").read_bytes() == FAKE_PNG
    assert scan_calls == 1
    assert download_calls == 1


def test_school_logo_local_first_and_cos_persist_then_hit_local(tmp_path, monkeypatch):
    local_dir = tmp_path / "school_logo"
    local_dir.mkdir(parents=True)
    (local_dir / "tsinghua.png").write_bytes(FAKE_PNG)

    monkeypatch.setattr(school_logos, "LOCAL_SCHOOL_LOGO_DIR", local_dir)
    monkeypatch.setenv("LOG_MODE", "production")

    cos_scan_calls = 0
    download_calls = 0

    def fake_scan_cos():
        nonlocal cos_scan_calls
        cos_scan_calls += 1
        school_logos._cos_key_to_file["mock_univ"] = "school_logo/mock_univ.png"
        return [{"key": "mock_univ", "name": "mock_univ", "url": "https://cos.example/school_logo/mock_univ.png"}], []

    def fake_download(url, local_path, timeout=15.0):
        nonlocal download_calls
        download_calls += 1
        Path(local_path).write_bytes(FAKE_PNG)

    monkeypatch.setattr(school_logos, "_scan_cos_school_logos", fake_scan_cos)
    monkeypatch.setattr(company_logos, "_download_url_to_path", fake_download)

    # Local school logo must resolve and validate LaTeX support with zero COS calls
    assert school_logos.is_school_logo_latex_supported("tsinghua") is True
    assert cos_scan_calls == 0

    out_local = tmp_path / "edu_local"
    map_local = school_logos.download_school_logos_to_dir([{"logo": "tsinghua"}], str(out_local))
    assert map_local == {0: "school_logo_0.png"}
    assert cos_scan_calls == 0
    assert download_calls == 0

    # Local miss fetches once from COS, persists under LOCAL_SCHOOL_LOGO_DIR, and hits local next time
    out_miss_1 = tmp_path / "edu_miss_1"
    map_miss_1 = school_logos.download_school_logos_to_dir([{"logo": "mock_univ"}], str(out_miss_1))
    assert map_miss_1 == {0: "school_logo_0.png"}
    assert cos_scan_calls == 1
    assert download_calls == 1
    assert (local_dir / "mock_univ.png").is_file()

    out_miss_2 = tmp_path / "edu_miss_2"
    map_miss_2 = school_logos.download_school_logos_to_dir([{"logo": "mock_univ"}], str(out_miss_2))
    assert map_miss_2 == {0: "school_logo_0.png"}
    assert cos_scan_calls == 1
    assert download_calls == 1


def test_cos_cache_isolation_and_fallback_prefix(tmp_path, monkeypatch):
    local_dir = tmp_path / "logo"
    local_dir.mkdir(parents=True)
    (local_dir / "字节跳动.png").write_bytes(FAKE_PNG)

    monkeypatch.setattr(company_logos, "LOCAL_LOGO_DIR", local_dir)
    monkeypatch.delenv("LOG_MODE", raising=False)

    with patch("backend.core.cos_client.prefer_local_assets", return_value=True):
        logos = company_logos.get_all_logos_with_urls()

    assert len(logos) == 1
    assert logos[0]["key"] == "bytedance"
    assert company_logos._cos_cache is None
    assert company_logos._cos_cache_time == 0

    fallback = company_logos._fallback_logos()
    bytedance = next(item for item in fallback if item["key"] == "bytedance")
    assert f"/{company_logos.COMPANY_LOGO_PREFIX}" in bytedance["url"]
    assert company_logos._cos_key_to_file["bytedance"].startswith(company_logos.COMPANY_LOGO_PREFIX)


def test_user_photo_ttl_cache_and_security_guards(tmp_path, monkeypatch):
    download_calls = 0

    def fake_download(url, local_path, timeout=15.0):
        nonlocal download_calls
        download_calls += 1
        Path(local_path).write_bytes(FAKE_PNG)

    monkeypatch.setattr(company_logos, "_download_url_to_path", fake_download)

    # Security and offline guards
    assert latex_generator._download_user_photo_to_dir("https://cdn.example.com/a.png", str(tmp_path / "s0"), offline=True) is None
    assert latex_generator._download_user_photo_to_dir("/etc/passwd", str(tmp_path / "s1")) is None
    assert latex_generator._download_user_photo_to_dir("file:///etc/passwd", str(tmp_path / "s2")) is None
    assert latex_generator._download_user_photo_to_dir("", str(tmp_path / "s3")) is None
    assert download_calls == 0

    url = "https://cdn.example.com/avatar.png"
    assert latex_generator._download_user_photo_to_dir(url, str(tmp_path / "c1")) == "photo.png"
    assert latex_generator._download_user_photo_to_dir(url, str(tmp_path / "c2")) == "photo.png"
    assert (tmp_path / "c2" / "logos" / "photo.png").read_bytes() == FAKE_PNG
    assert download_calls == 1

    # Expire TTL and verify re-fetch
    fetched_at, ext, raw = latex_generator._USER_PHOTO_CACHE[url]
    latex_generator._USER_PHOTO_CACHE[url] = (
        fetched_at - latex_generator._USER_PHOTO_CACHE_TTL - 10.0,
        ext,
        raw,
    )
    assert latex_generator._download_user_photo_to_dir(url, str(tmp_path / "c3")) == "photo.png"
    assert download_calls == 2
