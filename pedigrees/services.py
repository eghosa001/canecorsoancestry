from collections import Counter, defaultdict


def build_pedigree(dog, generations=4, _seen=None, public_only=False):
    """Return a bounded pedigree tree while safely stopping accidental cycles."""
    if dog is None or generations < 0:
        return None
    if public_only and not dog.is_public:
        return None

    seen = set() if _seen is None else set(_seen)
    if dog.pk in seen:
        return {"dog": dog, "cycle": True, "sire": None, "dam": None}

    seen.add(dog.pk)
    if generations == 0:
        return {"dog": dog, "cycle": False, "sire": None, "dam": None}

    return {
        "dog": dog,
        "cycle": False,
        "sire": build_pedigree(
            dog.sire,
            generations - 1,
            seen,
            public_only=public_only,
        ),
        "dam": build_pedigree(
            dog.dam,
            generations - 1,
            seen,
            public_only=public_only,
        ),
    }


def ancestor_occurrences(dog, generations=4, public_only=False):
    """Return every pedigree position; repeated ancestors intentionally repeat."""
    occurrences = []
    frontier = [(dog, 0, ())]

    while frontier:
        current, generation, path = frontier.pop()
        if current is None or generation >= generations:
            continue
        for relation in ("sire", "dam"):
            parent = getattr(current, relation)
            if parent is None or (public_only and not parent.is_public):
                continue
            next_path = path + (relation,)
            next_generation = generation + 1
            occurrences.append((parent, next_generation, next_path))
            frontier.append((parent, next_generation, next_path))

    return occurrences


def repeated_ancestors(dog, generations=4, public_only=False):
    occurrences = ancestor_occurrences(
        dog,
        generations,
        public_only=public_only,
    )
    counts = Counter(ancestor.pk for ancestor, _, _ in occurrences)
    generations_by_id = defaultdict(list)
    dogs_by_id = {}

    for ancestor, generation, _ in occurrences:
        dogs_by_id[ancestor.pk] = ancestor
        generations_by_id[ancestor.pk].append(generation)

    result = [
        {
            "dog": dogs_by_id[dog_id],
            "occurrences": count,
            "nearest_generation": min(generations_by_id[dog_id]),
        }
        for dog_id, count in counts.items()
        if count > 1
    ]
    return sorted(result, key=lambda item: (-item["occurrences"], item["dog"].name))
