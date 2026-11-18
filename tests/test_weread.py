import pytest

from weread2notion.weread import WeReadClient
from weread2notion.weread import WeReadError


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class Session:
    def __init__(self, pages):
        self.headers = {}
        self.pages = iter(pages)
        self.payloads = []

    def post(self, url, json, timeout):
        self.payloads.append(json)
        return Response(next(self.pages))


def test_shelf_request_reports_current_skill_version():
    session = Session([{"errcode": 0, "books": []}])
    client = WeReadClient("test-key", session=session)

    client.shelf()

    assert session.payloads[0]["api_name"] == "/shelf/sync"
    assert session.payloads[0]["skill_version"] == "1.0.6"


@pytest.mark.parametrize("status", [{"errcode": 0}, {}])
def test_upgrade_notice_preserves_shelf_data_without_retry(status, caplog):
    data = {
        **status,
        "books": [{"bookId": "book-1", "title": "test book"}],
        "upgrade_info": {"message": "本次请求已正常处理，后续可升级"},
    }
    session = Session([data, data])
    client = WeReadClient("test-key", session=session)

    assert client.shelf() == data
    assert len(session.payloads) == 1
    assert client.shelf() == data
    assert len(session.payloads) == 2
    assert len(caplog.records) == 1
    assert "升级" in caplog.text


def test_upgrade_notice_does_not_hide_api_error():
    session = Session([{
        "errcode": -1,
        "errmsg": "invalid API key",
        "upgrade_info": {"message": "new version"},
    }])
    client = WeReadClient("test-key", session=session)

    with pytest.raises(WeReadError, match="errcode=-1: invalid API key"):
        client.shelf()
    assert len(session.payloads) == 1


def test_notebook_pagination_is_flat_and_uses_last_sort():
    session = Session(
        [
            {"books": [{"sort": 20}], "hasMore": 1, "totalNoteCount": 3},
            {"books": [{"sort": 10}], "hasMore": 0, "totalNoteCount": 3},
        ]
    )
    client = WeReadClient("key", session=session)
    rows, totals = client.notebooks()
    assert len(rows) == 2
    assert totals["notes"] == 3
    assert session.payloads[1]["lastSort"] == 20
    assert "params" not in session.payloads[1]


def test_reading_days_falls_back_to_monthly_day_buckets():
    session = Session(
        [
            {"totalReadTime": 120},
            {"readTimes": {"1767196800": 120}, "totalReadTime": 120},
            {"readTimes": {"1767283200": 120}},
        ]
    )
    client = WeReadClient("key", session=session)
    days, _ = client.reading_days(2026)
    assert days == [{"timestamp": 1767283200, "duration": 120}]
    assert session.payloads[2]["mode"] == "monthly"


def test_book_bundle_reports_the_failing_stage():
    client = WeReadClient("key")
    responses = {
        "/book/info": {"bookId": "book-1", "title": "导入书"},
        "/book/getprogress": {"book": {"progress": 40}},
    }

    def call(api_name, **params):
        if api_name == "/book/chapterinfo":
            raise WeReadError("/book/chapterinfo 请求失败：499")
        return responses[api_name]

    client.call = call
    try:
        client.book_bundle("book-1")
    except WeReadError as exc:
        assert "阶段=章节目录" in str(exc)
        assert "接口=/book/chapterinfo" in str(exc)
    else:
        raise AssertionError("expected chapter stage failure")


def test_book_bundle_reports_progress_failure_before_chapter_lookup():
    client = WeReadClient("key")

    def call(api_name, **params):
        if api_name == "/book/getprogress":
            raise WeReadError("请求失败：499")
        return {"bookId": "book-2"}

    client.call = call
    try:
        client.book_bundle("book-2")
    except WeReadError as exc:
        assert "阶段=阅读进度" in str(exc)
        assert "接口=/book/getprogress" in str(exc)
    else:
        raise AssertionError("expected progress stage failure")
