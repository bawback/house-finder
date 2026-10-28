import json

import pytest

from house_finder.alerts import classify, extract_listing_links
from house_finder.commands import handle_command, process_updates
from house_finder.main import address_from_url
from house_finder.matcher import evaluate, garden_score, matches_area
from house_finder.messages import listing_message
from house_finder.models import Listing
from house_finder.parse import normalise_type, parse_listing_page
from house_finder.state import State, load_default_prefs


@pytest.fixture
def prefs():
    return load_default_prefs()


@pytest.fixture
def state(tmp_path):
    return State(tmp_path / "state.json")


def good_listing(**kw):
    base = dict(url="https://www.daft.ie/for-sale/detached-house-1-oak-road-blackrock-co-dublin/5000001",
                source="daft", address="1 Oak Road, Blackrock, Co. Dublin", price=650000, bedrooms=3,
                bathrooms=2, property_type="detached", ber="B2", parking=2,
                description="Large south facing rear garden, not overlooked.")
    base.update(kw)
    return Listing(**base)


# --- email links -----------------------------------------------------------

def test_classify_listing_urls():
    assert classify("https://www.daft.ie/for-sale/semi-detached-house-5-main-st-dalkey-co-dublin/5912345?utm=x") == (
        "daft", "https://www.daft.ie/for-sale/semi-detached-house-5-main-st-dalkey-co-dublin/5912345")
    assert classify("https://www.myhome.ie/residential/brochure/12-the-green-howth-co-dublin/4890123")[0] == "myhome"
    assert classify("https://www.property.ie/property-for-sale/12-The-Green-Malahide-Co-Dublin/4567890/")[0] == "propertyie"
    assert classify("https://www.daft.ie/property-for-sale/dublin") is None


def test_extract_links_from_html_email_with_trackers():
    html = """<html><body>
      <a href="https://click.daft.ie/ls/click?upn=abc&amp;u=https%3A%2F%2Fwww.daft.ie%2Ffor-sale%2Fhouse-killiney%2F5111111">See it</a>
      <a href="https://www.myhome.ie/residential/brochure/apt-dun-laoghaire/4999999?ref=alert">Apt</a>
      <a href="https://www.daft.ie/for-sale/house-killiney/5111111">dup</a>
      <a href="https://www.daft.ie/unsubscribe">unsub</a>
    </body></html>"""
    links = extract_listing_links(html)
    assert links == [("daft", "https://www.daft.ie/for-sale/house-killiney/5111111"),
                     ("myhome", "https://www.myhome.ie/residential/brochure/apt-dun-laoghaire/4999999")]


def test_address_from_url():
    assert address_from_url("https://www.daft.ie/for-sale/semi-detached-house-5-main-st-dalkey-co-dublin/5912345") \
        == "Semi Detached House 5 Main St Dalkey Co Dublin"


# --- page parsing ----------------------------------------------------------

def test_parse_daft_next_data():
    data = {"props": {"pageProps": {"listing": {
        "title": "5 Main Street, Dalkey, Co. Dublin", "price": "€675,000", "numBedrooms": "3 Bed",
        "numBathrooms": "2 Bath", "propertyType": "Semi-D", "ber": {"rating": "B3"},
        "seller": {"name": "Sherry FitzGerald", "phone": "01 234 5678"},
        "media": {"images": [{"size720x480": "https://img.daft.ie/x.jpg"}]},
    }, "listingDetails": {"description": "Viewing strictly by appointment. Off street parking for two cars. Mature rear garden."}}}}
    html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script><body>x</body></html>'
    l = parse_listing_page(Listing(url="https://www.daft.ie/for-sale/x/1", source="daft"), html)
    assert (l.price, l.bedrooms, l.bathrooms, l.property_type, l.ber) == (675000, 3, 2, "semi-detached", "B3")
    assert l.agent_name == "Sherry FitzGerald" and l.image.endswith("x.jpg")
    assert l.parking == 2
    assert any("appointment" in v for v in l.viewings)


def test_parse_jsonld_and_text():
    ld = {"@type": "SingleFamilyResidence", "name": "12 The Green, Howth", "numberOfBedrooms": 4,
          "offers": {"price": 695000}}
    html = f"""<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head>
      <body><h1>12 The Green</h1><p>Detached house. 3 bathrooms. BER: A2. SALE AGREED</p>
      <p>Open viewing Saturday 2nd Nov 11:00 - 11:30</p><p>Contact info@agent.ie</p></body></html>"""
    l = parse_listing_page(Listing(url="https://www.myhome.ie/residential/brochure/x/1", source="myhome"), html)
    assert (l.price, l.bedrooms, l.bathrooms, l.ber, l.property_type) == (695000, 4, 3, "A2", "detached")
    assert l.sale_agreed
    assert l.viewings and "Saturday" in l.viewings[0]
    assert l.agent_email == "info@agent.ie"


def test_normalise_type():
    assert normalise_type("Semi-Detached House") == "semi-detached"
    assert normalise_type("End of Terrace") == "end-of-terrace"
    assert normalise_type("Apartment for sale") == "apartment"
    assert normalise_type("Detached") == "detached"


# --- matching --------------------------------------------------------------

def test_good_listing_matches(prefs):
    v = evaluate(good_listing(), prefs)
    assert v.ok and v.score > 15
    assert any("حیاط" in n for n in v.notes)


@pytest.mark.parametrize("change,reason", [
    (dict(price=750000), "budget"),
    (dict(bedrooms=1), "bedrooms"),
    (dict(bathrooms=1), "bathrooms"),
    (dict(ber="C1"), "BER"),
    (dict(sale_agreed=True), "sale agreed"),
    (dict(address="5 Main St, Tallaght, Dublin 24"), "area"),
    (dict(property_type="apartment", bedrooms=1), "apartment"),
    (dict(parking=0), "parking"),
])
def test_rejections(prefs, change, reason):
    v = evaluate(good_listing(**change), prefs)
    assert not v.ok and any(reason in r for r in v.reasons)


def test_unknown_fields_do_not_reject(prefs):
    v = evaluate(good_listing(ber=None, bathrooms=None, parking=None), prefs)
    assert v.ok and any("نامشخص" in n for n in v.notes)


def test_help_to_buy_flag(prefs):
    v = evaluate(good_listing(price=480000, new_build=True), prefs)
    assert v.htb


def test_area_matching():
    assert matches_area("Apt 4, Sandyford, Dublin 18", ["Dublin 18"]) == "Dublin 18"
    assert matches_area("12 Road, D18 X123", ["Dublin 18"]) == "Dublin 18"
    assert matches_area("Main St, Dublin 14", ["Dublin 1"]) is None
    assert matches_area("Dún Laoghaire, Co. Dublin", ["Dun Laoghaire"]) == "Dun Laoghaire"


def test_garden_score():
    assert garden_score("Rear garden approx 25m in length, south facing garden") >= 6
    assert garden_score("communal gardens and courtyard") < 0


def test_message_renders(prefs):
    l = good_listing(viewings=["Open viewing Sat 11-12"], agent_name="DNG", agent_phone="01 555 1234")
    text = listing_message(l, evaluate(l, prefs))
    assert "€650,000" in text and "DNG" in text and l.url in text


# --- commands --------------------------------------------------------------

def test_commands_change_prefs(state):
    handle_command("/budget 600k", state)
    handle_command("/beds 3 4 3", state)
    handle_command("/ber a3", state)
    handle_command("/types detached semi", state)
    handle_command("/addarea Skerries", state)
    handle_command("/removearea Bray", state)
    p = state.prefs
    assert p["budget"]["max"] == 600000
    assert p["bedrooms"] == {"min": 3, "max": 4, "ideal": 3}
    assert p["min_ber"] == "A3"
    assert p["property_types"] == ["detached", "semi-detached"]
    assert "Skerries" in p["areas"] and "Bray" not in p["areas"]
    assert "❌" in handle_command("/ber Z9", state)
    assert "❌" in handle_command("/budget lots", state)


def test_state_roundtrip(state):
    handle_command("/pause", state)
    state.mark_seen("https://x")
    state.save()
    again = State.load(state.path)
    assert again.data["paused"] and again.is_seen("https://x")


def test_viewing_request_emails_agent_when_known(state):
    l = good_listing(agent_email="sales@agent.ie")
    state.data["sent"][l.id] = l.to_dict()
    handle_command("/contact Babak | 0870000000 | b@example.org", state)
    sent = []
    reply = handle_command(f"/viewing {l.id}", state, lambda *a: sent.append(a))
    assert sent and sent[0][0] == "sales@agent.ie" and sent[0][3] == "b@example.org"
    assert "Babak" in sent[0][2] and "✅" in reply


def test_viewing_request_without_agent_email(state):
    l = good_listing(agent_phone="01 555 1234")
    state.data["sent"][l.id] = l.to_dict()
    reply = handle_command(f"/viewing {l.id}", state, lambda *a: pytest.fail("should not email"))
    assert "01 555 1234" in reply and "Hello" in reply


class FakeTelegram:
    def __init__(self, updates):
        self.updates, self.sent = updates, []

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def send(self, chat_id, text, buttons=None, photo=None):
        self.sent.append((chat_id, text))

    def answer_callback(self, *a, **k):
        pass


def test_pairing_and_private(state):
    tg = FakeTelegram([
        {"update_id": 1, "message": {"chat": {"id": 99}, "text": "/start wrong"}},
        {"update_id": 2, "message": {"chat": {"id": 42}, "text": "/start secret"}},
        {"update_id": 3, "message": {"chat": {"id": 42}, "text": "/baths 3"}},
        {"update_id": 4, "message": {"chat": {"id": 99}, "text": "/budget 1"}},
    ])
    process_updates(tg, state, "secret")
    assert state.data["chats"] == [42]
    assert state.prefs["bathrooms"]["min"] == 3
    assert state.prefs["budget"]["max"] == 700000
    assert state.data["telegram_offset"] == 5
    assert ("private" in tg.sent[0][1] or "خصوصی" in tg.sent[0][1])
