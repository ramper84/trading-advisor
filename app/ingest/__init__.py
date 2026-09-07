"""OFFLINE pipeline (articles/s06-01's split): catalog.py (this phase),
loaders/ + parsers/ + normalizers/ (Phase 3-4), chunking.py + embedding.py
(Phase 7-8), refresh_worker.py (Phase 9). Never called from a request path
— retrieval/ reads what this writes, it never triggers a fetch itself."""
