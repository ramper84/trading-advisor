"""The analyze form: look up any company/symbol, monitored or not, and
run an on-demand analysis grounded in retrieved data, with per-claim
citations and an "add to monitor" button on the result."""

import reflex as rx

from frontend.state import AnalyzeState


def _citation_row(citation: dict) -> rx.Component:
    # citation["chunk_id"] is passed straight to rx.badge without a
    # .to_string()/.length()-style method call — those raised a real
    # UntypedVarError on a subscripted dict var elsewhere on this page
    # (see state.py's comment); a bare value renders fine as text.
    return rx.hstack(
        rx.badge(citation["chunk_id"]),
        rx.text(citation["claim"], size="2"),
        align="center",
        spacing="2",
    )


def _result_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(AnalyzeState.result_stance, size="6"),
                rx.badge(
                    AnalyzeState.result_quality_status,
                    color_scheme=rx.match(
                        AnalyzeState.result_quality_status,
                        ("grounded", "green"),
                        ("degraded", "amber"),
                        ("insufficient", "red"),
                        "gray",
                    ),
                ),
                rx.spacer(),
                rx.hstack(
                    rx.text("Confidence:", size="2", color="gray"),
                    rx.text(AnalyzeState.result_confidence_display, size="2", color="gray"),
                    spacing="1",
                ),
                width="100%",
                align="center",
            ),
            rx.cond(
                AnalyzeState.result_low_confidence,
                rx.callout(
                    "Retrieval found nothing close enough to this query to fully trust — treat this as a thin-evidence read.",
                    color_scheme="amber",
                ),
            ),
            rx.text(AnalyzeState.result_rationale, size="3"),
            rx.cond(
                AnalyzeState.result_citations.length() > 0,
                rx.vstack(
                    rx.text("Citations", size="2", weight="bold"),
                    rx.foreach(AnalyzeState.result_citations, _citation_row),
                    align_items="start",
                    spacing="2",
                    padding_top="0.5em",
                ),
            ),
            rx.cond(
                ~AnalyzeState.result_reliability_rule_passed,
                rx.callout(
                    "No sufficiently reliable citation backs a directional stance — forced to NEUTRAL.",
                    color_scheme="red",
                ),
            ),
            rx.button(
                "Add to monitor",
                on_click=AnalyzeState.add_result_to_monitor,
                disabled=AnalyzeState.is_monitored,
                margin_top="0.5em",
            ),
            align_items="start",
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def analyze() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.link(rx.button("← Dashboard", variant="soft"), href="/"),
                width="100%",
            ),
            rx.heading("Analyze a company", size="7"),
            rx.text(
                "Not investment advice — a plain-language read of retrieved data, always persisted.",
                size="2",
                color="gray",
            ),
            rx.vstack(
                rx.input(
                    placeholder="Symbol (e.g. AAPL, WALMEX.MX)",
                    value=AnalyzeState.symbol_input,
                    on_change=AnalyzeState.set_symbol,
                    width="100%",
                ),
                rx.text_area(
                    placeholder="What do you want to know? (e.g. why did it move, any risk factors or earnings news)",
                    value=AnalyzeState.query,
                    on_change=AnalyzeState.set_query,
                    width="100%",
                    rows="3",
                ),
                rx.button(
                    "Run analysis",
                    on_click=AnalyzeState.run_analysis,
                    loading=AnalyzeState.is_loading,
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            rx.cond(
                AnalyzeState.error != "",
                rx.callout(AnalyzeState.error, color_scheme="red"),
            ),
            rx.cond(
                AnalyzeState.out_of_scope_reason != "",
                rx.callout(AnalyzeState.out_of_scope_reason, color_scheme="amber"),
            ),
            rx.cond(
                AnalyzeState.has_result,
                _result_card(),
            ),
            spacing="4",
            width="100%",
            padding_y="2em",
        ),
        max_width="700px",
    )
