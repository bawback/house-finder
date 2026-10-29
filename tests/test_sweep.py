import json

from house_finder import main as main_mod
from house_finder.models import Listing
from house_finder.state import State, load_default_prefs
from house_finder.sweep import Search, parse_search_page, run_searches, searches_for


def daft_page(items):
    data = {"props": {"pageProps": {"listings": [{"listing": i} for i in items]}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


DAFT_ITEM = {"seoFriendlyPath": "/for-sale/1-cairnbrook-way-cairnbrook-dublin-18-co-dublin/6673406",
             "title": "1 Cairnbrook Way, Cairnbrook, Dublin 18, Co. Dublin", "price": "€595,000",
             "numBedrooms": "3 Bed", "numBathrooms": "3 Bath", "propertyType": "End of Terrace",
             "ber": {"rating": "C1"}, "seller": {"name": "DNG"}}


def test_parse_daft_search_next_data():
    [l] = parse_search_page(daft_page([DAFT_ITEM]), "daft")
    assert l.url == "https://www.daft.ie/for-sale/1-cairnbrook-way-cairnbrook-dublin-18-co-dublin/6673406"
    assert (l.price, l.bedrooms, l.bathrooms, l.property_type, l.ber) == (595000, 3, 3, "end-of-terrace", "C1")


def test_parse_new_home_url():
    item = dict(DAFT_ITEM, seoFriendlyPath="/new-home-for-sale/the-joyce-macnebury-mews-cherrywood-co-dublin/6660351",
                price="From €425,000", prs={"subUnits": []})
    [l] = parse_search_page(daft_page([item]), "daft")
    assert l.new_build and l.price == 425000


def test_parse_cards_fallback():
    html = """<ul>
      <li><a href="/residential/brochure/5-oak-road-dundrum-dublin-14/5000001">5 Oak Road, Dundrum, Dublin 14</a>
          <span>€650,000</span><span>3 beds</span><span>2 baths</span><span>Semi-Detached House</span>
          <img alt="BER B2" src="x.png"></li>
      <li><a href="/residential/brochure/9-elm-park-blackrock-co-dublin/5000002">9 Elm Park</a>
          <span>€690,000</span> 4 bed 3 bath Detached House BER: A3 SALE AGREED</li>
    </ul>"""
    a, b = parse_search_page(html, "myhome")
    assert (a.price, a.bedrooms, a.bathrooms, a.property_type, a.ber) == (650000, 3, 2, "semi-detached", "B2")
    assert (b.price, b.ber, b.sale_agreed) == (690000, "A3", True)


def test_searches_use_allowed_url_forms():
    prefs = load_default_prefs()
    s = searches_for(prefs)
    daft = [x for x in s if x.source == "daft"]
    myhome = [x for x in s if x.source == "myhome"]
    assert daft[0].url.startswith("https://www.daft.ie/property-for-sale/dublin/houses?salePrice_to=700000")
    assert myhome[0].page_url(2).endswith("/house-for-sale?page=2")    # only bare ?page= is allowed
    assert "?" not in myhome[0].url
    quick = searches_for(prefs, newest_first=True)
    assert all("sort=publishDateDesc" in x.url for x in quick if x.source == "daft")
    assert "https://www.myhome.ie/residential/dublin/property-for-sale-in-dublin-south-county" in [x.url for x in s]


class FakeResponse:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []
        self.headers = {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        return FakeResponse(*self.pages.get(url, ("", 404)))


def test_run_searches_pages_until_no_new(monkeypatch):
    monkeypatch.setattr("house_finder.sweep.PAGE_DELAY_SECONDS", 0)
    s = Search("daft-dublin", "daft", "https://www.daft.ie/property-for-sale/dublin/houses?x=1")
    item2 = dict(DAFT_ITEM, seoFriendlyPath="/for-sale/2-oak-dalkey-co-dublin/2")
    http = FakeHttp({s.url: (daft_page([DAFT_ITEM]),), s.page_url(2): (daft_page([item2]),),
                     s.page_url(3): (daft_page([item2]),)})
    listings, stats = run_searches([s], http)
    assert len(listings) == 2 and stats["daft-dublin"]["pages"] == 3
    assert len(http.calls) == 3


def test_full_run_sends_best_first_and_keeps_rest_pending(tmp_path, monkeypatch):
    for name in ("PAGE_DELAY_SECONDS", "SEND_DELAY_SECONDS"):
        monkeypatch.setattr(main_mod, name, 0)
    monkeypatch.setattr("house_finder.sweep.PAGE_DELAY_SECONDS", 0)
    monkeypatch.setattr(main_mod, "MAX_SEND_PER_RUN", 2)
    good = [dict(DAFT_ITEM, seoFriendlyPath=f"/for-sale/{i}-oak-road-blackrock-co-dublin/{i}",
                 title=f"{i} Oak Road, Blackrock, Co. Dublin", propertyType=t)
            for i, t in ((1, "Terrace"), (2, "Detached"), (3, "Semi-D"))]
    bad = dict(DAFT_ITEM, seoFriendlyPath="/for-sale/9-x-tallaght-dublin-24/9", title="9 X, Tallaght, Dublin 24")
    pages = {}

    class Http(FakeHttp):
        def get(self, url, timeout=None):
            self.calls.append(url)
            if url.startswith("https://www.daft.ie/property-for-sale/dublin/") and "page=" not in url:
                return FakeResponse(daft_page(good + [bad]))
            return FakeResponse("<html>listing</html>") if "/for-sale/" in url else FakeResponse("", 404)

    http = Http(pages)
    monkeypatch.setattr(main_mod.requests, "Session", lambda: http)
    for k in ("TELEGRAM_BOT_TOKEN", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "state.json"
    main_mod.run(path, dry_run=True, force_full_sweep=True)
    st = State.load(path)
    sent_types = [d["property_type"] for d in st.data["sent"].values()]
    assert sorted(sent_types) == ["detached", "semi-detached"]        # best two first
    assert list(st.data["pending"]) == ["https://www.daft.ie/for-sale/1-oak-road-blackrock-co-dublin/1"]
    assert st.is_seen("https://www.daft.ie/for-sale/9-x-tallaght-dublin-24/9")   # rejected from card data
    assert not any("9-x-tallaght" in c for c in http.calls if "/for-sale/9" in c)  # never opened

    # Next run sends the leftover without re-reading search pages.
    main_mod.run(path, dry_run=True)
    st = State.load(path)
    assert st.data["pending"] == {} and len(st.data["sent"]) == 3


def test_blocked_site_is_skipped_for_rest_of_run(monkeypatch):
    monkeypatch.setattr("house_finder.sweep.PAGE_DELAY_SECONDS", 0)
    a = Search("daft-dublin", "daft", "https://www.daft.ie/a")
    b = Search("daft-wicklow", "daft", "https://www.daft.ie/b")
    http = FakeHttp({a.url: ("Security Check", 403)})
    _, stats = run_searches([a, b], http)
    assert stats["daft-dublin"]["error"] == "HTTP 403" and http.calls == [a.url]
    assert stats["daft-wicklow"]["error"].startswith("skipped")


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_real_myhome_search_page():
    ls = parse_search_page((FIXTURES / "myhome_search.html").read_text(), "myhome")
    assert len(ls) == 20
    first = ls[0]
    assert first.address == "39 Ailesbury Grove, Dundrum, Dublin 16"
    assert (first.price, first.bedrooms, first.bathrooms, first.property_type) == (995000, 3, 2, "semi-detached")
    assert first.agent_email and first.viewings and first.viewings[0].startswith("Open viewing")


def test_real_myhome_listing_page():
    from house_finder.parse import parse_listing_page
    l = Listing(url="https://www.myhome.ie/residential/brochure/1-cairnbrook-way-cairnbrook-dublin-18/5028649", source="myhome")
    parse_listing_page(l, (FIXTURES / "myhome_listing.html").read_text())
    assert (l.price, l.bedrooms, l.bathrooms, l.ber, l.property_type) == (595000, 3, 3, "C1", "terraced")
    assert l.agent_phone == "01 493 8969" and l.agent_email == "mel@mkproperty.ie"
    assert l.viewings == ["Open viewing Sat Oct 31, 12pm - 12.25pm"]
    assert "three-bedroom" in l.description
