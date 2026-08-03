"""Initial tracked universe and their sector ETF proxies for the ML sector-trend adjustment."""

TRACKED_STOCKS = {
    # history_since is a fixed calendar date, not a rolling "N years back" window:
    # it marks roughly when each company's current business character took hold,
    # so the data window only grows over time instead of drifting forward and
    # eventually losing the start of the relevant regime.
    "NVDA": {
        "name": "NVIDIA",
        "sector_etf": "SMH",  # Semiconductors / AI
        "history_since": "2020-01-01",  # start of the datacenter/AI pivot, before the 2023+ re-rating
    },
    "NOW": {
        "name": "ServiceNow",
        "sector_etf": "IGV",  # Software
        "history_since": "2018-01-01",  # mature enterprise SaaS scale
    },
    "MSFT": {
        "name": "Microsoft",
        "sector_etf": "XLK",  # Technology
        "history_since": "2016-01-01",  # solidly into the Nadella cloud-era
    },
    "DASH": {
        "name": "DoorDash",
        "sector_etf": "XLY",  # Consumer Discretionary
        "history_since": "2022-01-01",  # excludes the 2020-2021 COVID delivery-demand anomaly
    },
    "MELI": {
        "name": "MercadoLibre",
        "sector_etf": "XLY",  # E-commerce / Consumer Discretionary
        "history_since": "2018-01-01",  # Mercado Pago (fintech) already scaling as a growth engine
    },
    "LOAR": {
        "name": "Loar Holdings",
        "sector_etf": "XLI",  # Industrials / Aerospace
        "history_since": "2024-04-25",  # actual IPO date — no earlier data exists
    },
}
