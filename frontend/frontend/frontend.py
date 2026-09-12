"""Phase 18 (Reflex, ADR-012): page registration only. Business logic
lives in `app/*`, plumbing in `state.py`, this file just wires routes."""

import reflex as rx

from frontend.pages.analyze import analyze
from frontend.pages.dashboard import dashboard
from frontend.pages.symbol_detail import symbol_detail

app = rx.App()
app.add_page(dashboard, route="/", title="Trading Advisor")
app.add_page(symbol_detail, route="/symbols/[symbol]", title="Symbol")
app.add_page(analyze, route="/analyze", title="Analyze")
