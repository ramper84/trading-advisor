"""Symbol detail page: current status, a real candlestick chart from
`daily_bars`, and analysis history."""

import reflex as rx
import reflex_components_plotly as rcp

from frontend.state import SymbolState


def _stat(label: str, value) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color="gray"),
        rx.text(value, size="3", weight="bold"),
        align_items="start",
        spacing="1",
    )


def _range_stat(label: str, low, high) -> rx.Component:
    # Separate text nodes, not string concatenation on Vars: plain `+`
    # between two dict-subscripted Vars raised a real TypeError
    # (`ObjectItemOperation` + `str`) in this Reflex version — caught by
    # actually compiling the app, not assumed to work from memory.
    return rx.vstack(
        rx.text(label, size="1", color="gray"),
        rx.hstack(
            rx.text(low, size="3", weight="bold"),
            rx.text(" – ", size="3", color="gray"),
            rx.text(high, size="3", weight="bold"),
            spacing="1",
        ),
        align_items="start",
        spacing="1",
    )


def _analysis_row(analysis: dict) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(analysis["stance"]),
                rx.badge(analysis["quality_status"], variant="outline"),
                rx.spacer(),
                rx.text(analysis["confidence_display"], size="2", color="gray"),
                width="100%",
            ),
            rx.text(analysis["rationale"], size="2"),
            rx.text(analysis["requested_at"], size="1", color="gray"),
            align_items="start",
            spacing="2",
        ),
        width="100%",
    )


def symbol_detail() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.link(rx.button("← Dashboard", variant="soft"), href="/"),
                rx.spacer(),
                rx.button(
                    rx.cond(SymbolState.is_monitored, "Remove from monitor", "Add to monitor"),
                    on_click=SymbolState.toggle_monitor,
                ),
                width="100%",
            ),
            rx.cond(
                SymbolState.error != "",
                rx.callout(SymbolState.error, color_scheme="red"),
            ),
            rx.cond(
                SymbolState.is_loading,
                rx.center(rx.spinner(), padding_y="4em"),
                rx.vstack(
                    rx.heading(SymbolState.instrument["name"], size="7"),
                    rx.hstack(
                        rx.text(SymbolState.instrument["exchange"], size="2", color="gray"),
                        rx.text(" · ", size="2", color="gray"),
                        rx.text(SymbolState.instrument["sector"], size="2", color="gray"),
                        rx.text(" · ", size="2", color="gray"),
                        rx.text(SymbolState.instrument["industry"], size="2", color="gray"),
                        spacing="1",
                    ),
                    rx.hstack(
                        _stat("Price", SymbolState.observation["price_display"]),
                        _stat("Change", SymbolState.observation["change_display"]),
                        _range_stat("Day range", SymbolState.observation["day_low_display"], SymbolState.observation["day_high_display"]),
                        _range_stat("52w range", SymbolState.observation["year_low_display"], SymbolState.observation["year_high_display"]),
                        spacing="6",
                        wrap="wrap",
                        padding_y="1em",
                    ),
                    rx.cond(
                        SymbolState.bars.length() > 0,
                        rcp.Plotly.create(
                            data=SymbolState.candlestick_figure,
                            width="100%",
                        ),
                        rx.callout("No daily bars yet for this symbol.", color_scheme="gray"),
                    ),
                    rx.heading("Analysis history", size="5", margin_top="1em"),
                    rx.cond(
                        SymbolState.analyses.length() > 0,
                        rx.vstack(
                            rx.foreach(SymbolState.analyses, _analysis_row),
                            width="100%",
                            spacing="3",
                        ),
                        rx.callout("No analyses yet — run one from the analyze form.", color_scheme="gray"),
                    ),
                    width="100%",
                    align_items="start",
                    spacing="3",
                ),
            ),
            spacing="4",
            width="100%",
            padding_y="2em",
        ),
        max_width="900px",
    )
