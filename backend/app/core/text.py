"""Tiny, dependency-free keyword extraction shared by competitors/trends.

Deliberately not an NLP library: this only needs to find recurring nouns in
video titles for deterministic gap/trend detection, not full text analysis.
"""

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "how", "what", "why", "you", "your", "this", "that", "with", "i", "my",
}


def extract_keywords(title: str) -> set[str]:
    words = "".join(c.lower() if c.isalnum() else " " for c in title).split()
    return {w for w in words if len(w) > 3 and w not in STOPWORDS}
