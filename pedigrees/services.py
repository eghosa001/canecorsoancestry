from collections import Counter, defaultdict

from django.db.models import Q

from registry.models import Dog


class PedigreeCycleError(ValueError):
    pass


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
            dog.sire, generations - 1, seen, public_only=public_only
        ),
        "dam": build_pedigree(
            dog.dam, generations - 1, seen, public_only=public_only
        ),
    }


def pedigree_generations(dog, generations=4, public_only=False):
    """Return ordered pedigree slots using at most one parent query per generation."""
    generations = max(1, min(int(generations), 10))
    layers = []
    slots = [dog]

    for generation in range(generations + 1):
        layers.append(list(slots))
        if generation == generations:
            break

        parent_ids = {
            parent_id
            for current in slots
            if current is not None
            for parent_id in (current.sire_id, current.dam_id)
            if parent_id
        }
        parents = Dog.objects.in_bulk(parent_ids)

        next_slots = []
        for current in slots:
            if current is None:
                next_slots.extend((None, None))
                continue

            sire = parents.get(current.sire_id)
            dam = parents.get(current.dam_id)
            if public_only and sire is not None and not sire.is_public:
                sire = None
            if public_only and dam is not None and not dam.is_public:
                dam = None
            next_slots.extend((sire, dam))
        slots = next_slots

    counts = Counter(
        current.pk
        for layer in layers
        for current in layer
        if current is not None
    )

    labels = {
        0: "Subject",
        1: "Parents",
        2: "Grandparents",
        3: "Great-grandparents",
    }
    return [
        {
            "number": index,
            "label": labels.get(index, f"Generation {index}"),
            "nodes": [
                {
                    "dog": current,
                    "repeated": bool(current and counts[current.pk] > 1),
                }
                for current in layer
            ],
        }
        for index, layer in enumerate(layers)
    ]


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
    occurrences = ancestor_occurrences(dog, generations, public_only=public_only)
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


def sibling_relationships(dog, public_only=True):
    """Return full and half siblings derived from shared parent links."""
    parent_filter = Q()
    if dog.sire_id:
        parent_filter |= Q(sire_id=dog.sire_id)
    if dog.dam_id:
        parent_filter |= Q(dam_id=dog.dam_id)
    if not parent_filter.children:
        return []

    siblings = Dog.objects.filter(parent_filter).exclude(pk=dog.pk)
    if public_only:
        siblings = siblings.filter(is_public=True)
    siblings = siblings.select_related("sire", "dam", "kennel").distinct().order_by("name")

    result = []
    for sibling in siblings:
        shared = []
        if dog.sire_id and sibling.sire_id == dog.sire_id:
            shared.append("sire")
        if dog.dam_id and sibling.dam_id == dog.dam_id:
            shared.append("dam")
        is_full = bool(dog.sire_id and dog.dam_id and len(shared) == 2)
        result.append(
            {
                "dog": sibling,
                "relation": "Full sibling" if is_full else "Half sibling",
                "shared_parents": tuple(shared),
            }
        )
    return result


def offspring_for(dog, public_only=True):
    queryset = Dog.objects.filter(Q(sire_id=dog.pk) | Q(dam_id=dog.pk))
    if public_only:
        queryset = queryset.filter(is_public=True)
    return queryset.select_related("kennel").distinct().order_by("name")


def common_ancestors(dog_a, dog_b, generations=10, public_only=False):
    left = ancestor_occurrences(dog_a, generations, public_only=public_only)
    right = ancestor_occurrences(dog_b, generations, public_only=public_only)

    left_counts = Counter(dog.pk for dog, _, _ in left)
    right_counts = Counter(dog.pk for dog, _, _ in right)
    left_nearest = defaultdict(list)
    right_nearest = defaultdict(list)
    dogs = {}

    for dog, generation, _ in left:
        dogs[dog.pk] = dog
        left_nearest[dog.pk].append(generation)
    for dog, generation, _ in right:
        dogs[dog.pk] = dog
        right_nearest[dog.pk].append(generation)

    rows = []
    for dog_id in left_counts.keys() & right_counts.keys():
        rows.append(
            {
                "dog": dogs[dog_id],
                "left_occurrences": left_counts[dog_id],
                "right_occurrences": right_counts[dog_id],
                "left_generation": min(left_nearest[dog_id]),
                "right_generation": min(right_nearest[dog_id]),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["left_generation"] + row["right_generation"],
            row["dog"].name,
        ),
    )


def _pedigree_order(*dogs, public_only=False):
    visited = set()
    visiting = set()
    ordered = []

    def visit(dog):
        if dog is None or dog.pk in visited:
            return
        if public_only and not dog.is_public:
            return
        if dog.pk in visiting:
            raise PedigreeCycleError("Pedigree contains a parent cycle.")

        visiting.add(dog.pk)
        visit(dog.sire)
        visit(dog.dam)
        visiting.remove(dog.pk)
        visited.add(dog.pk)
        ordered.append(dog)

    for dog in dogs:
        visit(dog)
    return ordered


def _relationship_matrix(*dogs, public_only=False):
    ordered = _pedigree_order(*dogs, public_only=public_only)
    index = {dog.pk: position for position, dog in enumerate(ordered)}
    size = len(ordered)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]

    for i, dog in enumerate(ordered):
        sire_index = index.get(dog.sire_id)
        dam_index = index.get(dog.dam_id)

        for j in range(i):
            value = 0.0
            if sire_index is not None:
                value += 0.5 * matrix[sire_index][j]
            if dam_index is not None:
                value += 0.5 * matrix[dam_index][j]
            matrix[i][j] = value
            matrix[j][i] = value

        parental_relationship = 0.0
        if sire_index is not None and dam_index is not None:
            parental_relationship = matrix[sire_index][dam_index]
        matrix[i][i] = 1.0 + (0.5 * parental_relationship)

    return ordered, index, matrix


def inbreeding_coefficient(dog, public_only=False):
    """Return Wright's inbreeding coefficient as a 0..1 float."""
    _, index, matrix = _relationship_matrix(dog, public_only=public_only)
    dog_index = index[dog.pk]
    return max(0.0, matrix[dog_index][dog_index] - 1.0)


def projected_inbreeding(sire, dam, public_only=False):
    """Return projected offspring COI for a sire/dam pairing as a 0..1 float."""
    if sire is None or dam is None:
        return None
    if sire.pk == dam.pk:
        raise ValueError("Sire and dam must be different dogs.")

    _, index, matrix = _relationship_matrix(
        sire, dam, public_only=public_only
    )
    return max(0.0, 0.5 * matrix[index[sire.pk]][index[dam.pk]])
