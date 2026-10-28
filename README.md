# house-finder

A personal bot that sends new Irish property listings matching our preferences to a Telegram group.

Setup instructions (Persian): [SETUP.md](SETUP.md)

## How it works

Every 30 minutes a GitHub Actions job:

1. Reads Telegram commands sent to the bot (preference changes, viewing requests).
2. Reads new listing-alert emails (Daft.ie, MyHome.ie, Property.ie, or any email that links to them)
   from the bot's Gmail inbox over IMAP.
3. Opens each new listing page once, a few seconds apart, and extracts price, beds, baths, type, BER,
   parking, garden hints, viewing times and agent contact.
4. Filters and scores it against the preferences, and posts matches to the paired Telegram chat.

The bot's memory (seen listings, preferences changed from Telegram, paired chats) is a JSON file
on the `state` branch. Starting preferences are in [config/preferences.yaml](config/preferences.yaml).

### Why email alerts instead of scraping search pages

Daft.ie and MyHome.ie block automated access to their search pages in robots.txt. The sites' own
instant email alerts are the permitted way to hear about new listings quickly; the bot then only
opens individual listing pages, which robots.txt allows.

### Viewings

The bot shows any viewing times it finds in the listing. The "درخواست بازدید" button (or
`/viewing <id>`) emails the agent a viewing request from the bot's Gmail with your email as
Reply-To and CC when the listing shows an agent email; otherwise it gives the agent's phone
number and a ready-to-paste message for the site's contact form. It never books on its own.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest
.venv/bin/python -m house_finder --state data/state.json --dry-run
```
