"""Pluggable source adapters that feed the ingest queue.

Each adapter normalizes its upstream into records of the shape consumed by the
wiki pipeline:

    {"title", "authors": [..], "arxiv_id", "doi", "url", "fetch_ref", "source", ...}

`fetch_ref` is the single strongest identifier (arXiv id > DOI > url) to hand to
`fetch_paper`.
"""
