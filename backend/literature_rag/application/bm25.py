"""BM25 over the existing source chunks with English terms and Chinese bigrams."""

from collections import Counter
from heapq import nsmallest
from html import unescape
from math import log1p
import re
from unicodedata import normalize


TOKEN = re.compile(r"[a-z][a-z0-9]*|\d+(?:\.\d+)?|[\u3400-\u9fff]+")
HAN = re.compile(r"[\u3400-\u9fff]")
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
STRUCTURE_MARKER = re.compile(r"\[章节标签（程序整理，非原文）\]|\[原文(?:片段不连续)?\]")


def terms(text):
    text = STRUCTURE_MARKER.sub(" ", text)
    cleaned = normalize("NFKC", unescape(HTML_TAG.sub(" ", text))).casefold()
    for token in TOKEN.findall(cleaned):
        if HAN.match(token) and len(token) > 1:
            yield from (token[i:i + 2] for i in range(len(token) - 1))
        else:
            yield token


def rank_bm25(query, chunks, limit):
    """Return (chunk ID, BM25 score) pairs. Zero-overlap chunks stay out."""
    query_terms = set(terms(query))
    if not query_terms:
        return []
    document_frequency = Counter()
    matched = []
    corpus_size = total_length = 0
    for chunk_id, text in chunks:
        frequencies = Counter(terms(text))
        length = frequencies.total()
        if not length:
            continue
        corpus_size += 1
        total_length += length
        shared = frequencies.keys() & query_terms
        if shared:
            document_frequency.update(shared)
            matched.append((chunk_id, length, sorted((term, frequencies[term]) for term in shared)))

    if not matched:
        return []
    mean_length = total_length / corpus_size
    inverse_frequency = {
        term: log1p((corpus_size - freq + .5) / (freq + .5))
        for term, freq in document_frequency.items()
    }
    k1, b = 1.2, .75

    def score(chunk):
        chunk_id, length, frequencies = chunk
        normalization = k1 * (1 - b + b * length / mean_length)
        value = sum(inverse_frequency[term] * freq * (k1 + 1) / (freq + normalization)
                    for term, freq in frequencies)
        return chunk_id, value

    return nsmallest(limit, map(score, matched), key=lambda row: (-row[1], row[0]))
