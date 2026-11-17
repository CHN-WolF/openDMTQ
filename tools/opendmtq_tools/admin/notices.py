"""The Notices page: what the server tells people, one card each. The site's notice (notice.py), the in-game maintenance
notice (song_pages.py) and the messages to Discord and Slack (webhooks.py). The page keeps the address it had when it held
the maintenance notice alone (/opendmtq/admin/maintenance, song_pages.maintenance_page), which bookmarks and scripts know.

Each card's module gives the values its part of the page needs (card()), under its own name, and the page is drawn with
all of them (render()). A card's template is included by name (maintenance.html): one that is not there yet is left out."""

from flask import render_template

# The values of each card, by its name: the function of its module that gives them, called each time the page is drawn.
CARDS = {}


def card(name):
    """Registers the decorated function (no arguments, a dict back) as what the card name shows."""
    def register(fn):
        # One function per card: a second registration replaces the first (a module imported again in a test).
        CARDS[name] = fn
        return fn
    return register


def render(status=200, **typed):
    """The page with every card's values; typed, by card name, goes over them (what a refused form had typed, drawn again
    with why). Returns (page, status) for a view to return."""
    # Each card's own values, then what its form had typed in their place.
    values = {name: {**fn(), **typed.get(name, {})} for name, fn in CARDS.items()}
    return render_template("maintenance.html", **values), status
