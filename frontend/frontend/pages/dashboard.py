"""The dashboard/index page: trending, ranked by movement, over the
monitor list (README §2's "what's trending among the stuff I'm
watching?")."""

import reflex as rx

from frontend.state import DashboardState


def _entry_row(entry: dict) -> rx.Component:
    return rx.link(
        rx.card(
            rx.hstack(
                rx.vstack(
                    rx.heading(entry["symbol"], size="4"),
                    rx.text(entry["thesis"], size="1", color="gray"),
                    align_items="start",
                    spacing="1",
                ),
                rx.spacer(),
                rx.vstack(
                    rx.text(entry["price_display"], size="5", weight="bold"),
                    rx.badge(entry["change_display"], color_scheme=entry["change_color"]),
                    align_items="end",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("Volume", size="1", color="gray"),
                    rx.text(entry["volume_display"], size="2"),
                    align_items="end",
                    spacing="1",
                ),
                width="100%",
                align="center",
            ),
            width="100%",
            _hover={"background": rx.color("gray", 3)},
        ),
        href=f"/symbols/{entry['symbol']}",
        text_decoration="none",
        width="100%",
    )


def dashboard() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.heading("Trading Advisor", size="7"),
                rx.spacer(),
                rx.link(rx.button("Analyze a company"), href="/analyze"),
                width="100%",
                align="center",
            ),
            rx.text("Trending among what you're watching", size="3", color="gray"),
            rx.cond(
                DashboardState.error != "",
                rx.callout(DashboardState.error, color_scheme="red"),
            ),
            rx.cond(
                DashboardState.is_loading,
                rx.center(rx.spinner(), padding_y="4em"),
                rx.cond(
                    DashboardState.entries.length() > 0,
                    rx.vstack(
                        rx.foreach(DashboardState.entries, _entry_row),
                        width="100%",
                        spacing="3",
                    ),
                    rx.callout(
                        "Nothing on your watchlist yet — analyze a company and add it to monitor.",
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
