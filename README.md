# house-finder

A personal bot that sends new Irish property listings matching our preferences to a Telegram group.

Setup instructions (Persian): [SETUP.md](SETUP.md)

## How it works

Every 30 minutes a GitHub Actions job:

1. Reads Telegram commands sent to the bot (preference changes, viewing requests).
2. Reads new listing-alert emails (Daft.ie, MyHome.ie, Property.ie, or any email that links to them)
   from the bot's Gmail inbox over IMAP.
3. Reads the newest page of each Daft search. Once a day (or after `/all`) it reads every page of
   the Daft and MyHome searches, so all current listings are covered, not only new ones.
4. Skips listings whose search card already rules them out, then opens each remaining listing page once, a few seconds apart, and extracts price, beds, baths, type, BER,
   parking, garden hints, viewing times and agent contact.
5. Filters and scores it against the preferences, and posts matches to the paired Telegram chat,
   best first, at most 40 per run (the rest follow in the next runs).

The bot's memory (seen listings, preferences changed from Telegram, paired chats) is a JSON file
on the `state` branch. Starting preferences are in [config/preferences.yaml](config/preferences.yaml).

### Staying within the sites' robots.txt

- Daft.ie's robots.txt blocks the old `/searchsale.daft` search, `/api`, and some parameters
  (`offset=`, `sort_by=`, `from_search`); the bot uses only `/property-for-sale/<county>/houses`
  with filter and `page` parameters.
- MyHome.ie's robots.txt blocks every query string on `/residential/` except a bare `?page=N`, so
  the bot reads `/residential/<area>/house-for-sale?page=N` and filters locally.
- Pages are read one at a time, a few seconds apart. Search pages that could not be parsed are
  saved under `debug/` on the `state` branch, and per-search counts go in `sweep_stats` in `state.json`.

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
