"""`/feeds` (D6, CLAUDE.md's "Extension — Discovery"): the latest
scheduled discovery batch — companies the Actor-Critic-Boss pipeline
suggested from general news, each routed into `/analyze` (pre-filled)
rather than straight to monitor, since a suggestion is a lead, not a
grounded analysis."""

import reflex as rx

from frontend.state import FeedsState


def _suggestion_card(entry: dict) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading(entry["symbol"], size="5"),
                    rx.text(entry["company_name"], size="2", color="gray"),
                    align_items="start",
                    spacing="1",
                ),
                rx.spacer(),
                rx.link(
                    rx.button("Analyze", variant="soft"),
                    href=f"/analyze?symbol={entry['symbol']}",
                ),
                width="100%",
                align="center",
            ),
            rx.text(entry["reasoning"], size="3"),
            rx.cond(
                entry["sources_markdown"] != "",
                rx.vstack(
                    rx.text("Sources", size="2", weight="bold"),
                    rx.markdown(entry["sources_markdown"]),
                    align_items="start",
                    spacing="1",
                    padding_top="0.25em",
                ),
            ),
            align_items="start",
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def feeds() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.link(rx.button("← Dashboard", variant="soft"), href="/"),
                width="100%",
            ),
            rx.heading("Feeds", size="7"),
            rx.text(
                "Companies an experienced-trader-persona pipeline flagged from today's general "
                "news — reviewed for citation integrity and symbol identity before landing here. "
                "Scanned once daily; not a live search.",
                size="2",
                color="gray",
            ),
            rx.cond(
                FeedsState.error != "",
                rx.callout(FeedsState.error, color_scheme="red"),
            ),
            rx.cond(
                FeedsState.is_loading,
                rx.center(rx.spinner(), padding_y="4em"),
                rx.cond(
                    FeedsState.suggestions.length() > 0,
                    rx.vstack(
                        rx.foreach(FeedsState.suggestions, _suggestion_card),
                        width="100%",
                        spacing="3",
                    ),
                    rx.callout(
                        "No suggestions yet — the daily scan hasn't found anything worth "
                        "flagging, or hasn't run yet.",
                        color_scheme="gray",
                    ),
                ),
            ),
            spacing="4",
            width="100%",
            padding_y="2em",
        ),
        max_width="900px",
    )
