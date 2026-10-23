import unicodedata


def _norm(s: str) -> str:
    """Mayusculas, sin tildes, sin saltos de linea y con un solo espacio entre palabras."""
    s = unicodedata.normalize("NFD", str(s)).upper()
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.replace("\n", " ").split()).strip()
