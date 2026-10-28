def normalize_city(value: str) -> str:
    """'  New   Delhi ' → 'new delhi'"""
    return " ".join(value.split()).casefold()