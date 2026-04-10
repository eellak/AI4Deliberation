#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from bs4 import BeautifulSoup

from helpers import load_scraper_modules


def make_comment_page(comment_rows, total_pages):
    pagination = "".join(
        f'<a class="page-numbers">{page_number}</a>'
        for page_number in range(1, total_pages + 1)
    )
    comments = []
    for comment_id, author_name, body in comment_rows:
        comments.append(
            f"""
            <li id="comment-{comment_id}">
              <div class="user">
                <div class="author">
                  <strong>{author_name}</strong>
                  1 Ιανουαρίου 2026, 10:00
                </div>
              </div>
              <p>{body}</p>
            </li>
            """
        )

    html = f"""
    <html>
      <body>
        <div class="nav">{pagination}</div>
        <div id="comments">
          <ul class="comment_list">
            {''.join(comments)}
          </ul>
        </div>
      </body>
    </html>
    """
    return BeautifulSoup(html, "html.parser")


def make_metadata_page(side_spot_text, document_titles=None):
    documents_html = ""
    if document_titles:
        documents_html = """
        <div class="sidespot orange_spot">
          %s
        </div>
        """ % "".join(
            f'<span class="file"><a href="/docs/{index}.pdf">{title}</a></span>'
            for index, title in enumerate(document_titles, start=1)
        )

    html = f"""
    <html>
      <body>
        <div id="headerlogo"><h1><a>Test Ministry</a></h1></div>
        <div class="sidespot red_spot">
          <h4>
            <span>1 Ιανουαρίου 2026, 10:00</span>
            <span>2 Ιανουαρίου 2026, 10:00</span>
          </h4>
        </div>
        {documents_html}
        <div class="sidespot">{side_spot_text}</div>
        <div class="post clearfix">
          <h3>Test Consultation</h3>
          <div class="post_content">Body</div>
        </div>
      </body>
    </html>
    """
    return html.encode("utf-8")


class FakeResponse:
    def __init__(self, content, url):
        self.content = content
        self.url = url

    def raise_for_status(self):
        return None


def seed_consultation(modules, session, ministry_code, title, url, post_id, is_finished=False):
    ministry = modules["db_models"].Ministry(
        code=ministry_code,
        name=ministry_code.upper(),
        url=f"https://www.opengov.gr/{ministry_code}/",
    )
    session.add(ministry)
    session.flush()

    consultation = modules["db_models"].Consultation(
        post_id=post_id,
        title=title,
        start_minister_message="",
        end_minister_message="",
        start_date=None,
        end_date=None,
        is_finished=is_finished,
        url=url,
        total_comments=0,
        accepted_comments=0,
        ministry_id=ministry.id,
    )
    session.add(consultation)
    session.commit()
    return consultation


def test_extract_comments_fetches_cpage1_and_deduplicates(monkeypatch):
    modules = load_scraper_modules()
    scraper = modules["content_scraper"]

    article_url = "https://www.opengov.gr/ministrya/?p=42"
    initial_soup = make_comment_page(
        [
            ("101", "Author A", "Visible on article URL"),
            ("102", "Author B", "Also visible on article URL"),
        ],
        total_pages=2,
    )
    cpage1_url = scraper.set_query_param(article_url, "cpage", 1)
    cpage2_url = scraper.set_query_param(article_url, "cpage", 2)
    fetched_pages = {
        cpage1_url: make_comment_page(
            [
                ("103", "Author C", "Only visible on cpage=1"),
                ("101", "Author A", "Visible on article URL"),
            ],
            total_pages=2,
        ),
        cpage2_url: make_comment_page(
            [
                ("104", "Author D", "Only visible on cpage=2"),
                ("103", "Author C", "Only visible on cpage=1"),
            ],
            total_pages=2,
        ),
    }
    fetched_urls = []

    def fake_fetch_page_soup(url):
        fetched_urls.append(url)
        return fetched_pages[url], url

    monkeypatch.setattr(scraper, "fetch_page_soup", fake_fetch_page_soup)
    monkeypatch.setattr(scraper, "uniform", lambda _low, _high: 0.0)
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)

    comments = scraper.extract_comments(initial_soup, article_url)

    assert fetched_urls == [cpage1_url, cpage2_url]
    assert [comment["comment_id"] for comment in comments] == ["101", "102", "103", "104"]
    assert comments[2]["content"] == "Only visible on cpage=1"
    assert all(comment["username"] == "ANONYMIZED" for comment in comments)


def test_metadata_prefers_consultation_comment_count_over_all_comments(monkeypatch):
    modules = load_scraper_modules()
    scraper = modules["metadata_scraper"]
    url = "https://www.opengov.gr/consultations/?p=4038"

    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            make_metadata_page(
                "316 Σχόλια επι της Διαβούλευσης 2220 - Όλα τα Σχόλια",
                document_titles=["Doc A", "Doc B"],
            ),
            url,
        ),
    )

    result = scraper.scrape_consultation_metadata(url)

    assert result["consultation"]["total_comments"] == 316
    assert len(result["documents"]) == 2


def test_metadata_falls_back_to_all_comments_when_consultation_count_missing(monkeypatch):
    modules = load_scraper_modules()
    scraper = modules["metadata_scraper"]
    url = "https://www.opengov.gr/ministrya/?p=100"

    monkeypatch.setattr(
        scraper.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            make_metadata_page("800 - Όλα τα Σχόλια"),
            url,
        ),
    )

    result = scraper.scrape_consultation_metadata(url)

    assert result["consultation"]["total_comments"] == 800


def test_scrape_and_store_treats_cross_ministry_post_id_as_new_consultation(monkeypatch, tmp_path):
    modules = load_scraper_modules()
    db_url = f"sqlite:///{tmp_path / 'single.sqlite'}"
    _engine, session_factory = modules["db_models"].init_db(db_url)
    session = session_factory()

    existing = seed_consultation(
        modules,
        session,
        ministry_code="ministrya",
        title="Existing A",
        url="https://www.opengov.gr/ministrya/?p=900",
        post_id="900",
    )

    monkeypatch.setattr(
        modules["scrape_single_consultation"],
        "scrape_consultation_metadata",
        lambda url: {
            "consultation": {
                "post_id": "900",
                "title": "Incoming B",
                "start_minister_message": "",
                "end_minister_message": "",
                "start_date": None,
                "end_date": None,
                "is_finished": False,
                "url": url,
                "total_comments": 0,
            },
            "ministry": {
                "code": "ministryb",
                "name": "MINISTRYB",
                "url": "https://www.opengov.gr/ministryb/",
            },
            "documents": [],
        },
    )
    monkeypatch.setattr(
        modules["scrape_single_consultation"],
        "scrape_consultation_content",
        lambda url: [],
    )

    result, consultation_id = modules["scrape_single_consultation"].scrape_and_store(
        "https://www.opengov.gr/ministryb/?p=900",
        session,
    )

    consultations = session.query(modules["db_models"].Consultation).all()
    consultation_by_url = {
        consultation.url: consultation
        for consultation in consultations
    }

    assert result is True
    assert len(consultations) == 2
    assert consultation_id != existing.id
    assert consultation_by_url["https://www.opengov.gr/ministryb/?p=900"].title == "Incoming B"


def test_batch_scraper_does_not_selectively_update_different_ministry_post_id(monkeypatch, tmp_path):
    modules = load_scraper_modules()
    db_url = f"sqlite:///{tmp_path / 'batch.sqlite'}"
    _engine, session_factory = modules["db_models"].init_db(db_url)
    session = session_factory()

    seed_consultation(
        modules,
        session,
        ministry_code="ministrya",
        title="Existing A",
        url="https://www.opengov.gr/ministrya/?p=700",
        post_id="700",
    )
    session.close()

    calls = []

    def fake_scrape_and_store(url, session, selective_update=False, existing_cons=None):
        calls.append(
            {
                "url": url,
                "selective_update": selective_update,
                "existing_cons_url": getattr(existing_cons, "url", None),
            }
        )
        return True

    monkeypatch.setattr(modules["scrape_all_consultations"], "scrape_and_store", fake_scrape_and_store)

    success_count = modules["scrape_all_consultations"].scrape_consultations_to_db(
        [
            {
                "url": "https://www.opengov.gr/ministryb/?p=700",
                "title": "Incoming B",
                "date": "",
            }
        ],
        db_url,
    )

    assert success_count == 1
    assert calls == [
        {
            "url": "https://www.opengov.gr/ministryb/?p=700",
            "selective_update": False,
            "existing_cons_url": None,
        }
    ]
