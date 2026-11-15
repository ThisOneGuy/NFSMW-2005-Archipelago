from difflib import SequenceMatcher
import re
import unicodedata


def normalized(value):
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def match_score(query, value):
    query = normalized(query)
    value = normalized(value)
    if not query:
        return 0
    if query == value:
        return 0
    if value.startswith(query):
        return 1
    if query in value:
        return 2
    words = value.split()
    terms = query.split()
    if all(any(term in word for word in words) for term in terms):
        return 3
    if query.replace(" ", "") in value.replace(" ", ""):
        return 4
    scores = []
    for term in terms:
        score = max(
            (
                (
                    1.0
                    if term in word
                    else SequenceMatcher(None, term, word).ratio() if len(term) >= 4 else 0.0
                )
                for word in words
            ),
            default=0.0,
        )
        if score < 0.74:
            return None
        scores.append(score)
    return 5 + 1 - sum(scores) / len(scores)


def matching_names(query, names, limit=40):
    if not normalized(query):
        return [], 0
    matches = []
    for name in set(names):
        score = match_score(query, name)
        if score is not None:
            matches.append((score, len(normalized(name)), name.casefold(), name))
    matches.sort()
    return [row[3] for row in matches[:limit]], len(matches)


def filter_hints(query, hints, location_name=None):
    key = normalized(query)
    if not key:
        return list(hints)
    result = []
    for hint in hints:
        if key in ("found", "not found"):
            if bool(hint.get("found")) == (key == "found"):
                result.append(hint)
            continue
        location = location_name(hint) if location_name else hint.get("location_name", "")
        value = " ".join(
            str(hint.get(k, "")) for k in ("item_name", "recipient_name", "finder_name", "entrance")
        )
        score = match_score(
            key, value + " " + str(location) + " " + ("Found" if hint.get("found") else "Not found")
        )
        if score is not None:
            result.append(hint)
    return result
