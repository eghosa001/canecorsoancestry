from collections import Counter, defaultdict
from hashlib import sha256

from django.core.cache import cache
from django.db.models import Q

from registry.models import Dog, HealthRecord


class PedigreeCycleError(ValueError):
    pass


ANALYSIS_CACHE_SECONDS = 60 * 60


def _bounded_generations(generations):
    return max(1, min(int(generations), 10))


def _slot_path(generation, index):
    if generation <= 0:
        return ()
    return tuple(
        "dam" if (index >> shift) & 1 else "sire"
        for shift in range(generation - 1, -1, -1)
    )


def _path_label(path):
    return " → ".join(part.title() for part in path) if path else "Subject"


def _pedigree_snapshot(dog, generations=4, public_only=False):
    """Load a bounded pedigree with at most one parent query per generation."""
    generations = _bounded_generations(generations)
    layers = [[dog]]
    slots = [dog]

    for _ in range(generations):
        parent_ids = {
            parent_id
            for current in slots
            if current is not None
            for parent_id in (current.sire_id, current.dam_id)
            if parent_id
        }
        parents = Dog.objects.select_related("kennel").in_bulk(parent_ids)
        if public_only:
            parents = {
                pk: parent for pk, parent in parents.items() if parent.is_public
            }

        next_slots = []
        for current in slots:
            if current is None:
                next_slots.extend((None, None))
                continue
            next_slots.extend(
                (parents.get(current.sire_id), parents.get(current.dam_id))
            )
        layers.append(next_slots)
        slots = next_slots

    dogs_by_key = {
        str(current.pk): current
        for layer in layers
        for current in layer
        if current is not None
    }
    revision_material = [f"g={generations}", f"public={int(public_only)}"]
    for key in sorted(dogs_by_key):
        current = dogs_by_key[key]
        revision_material.append(
            ":".join(
                (
                    key,
                    current.name,
                    current.sex,
                    current.colour,
                    str(current.sire_id or ""),
                    str(current.dam_id or ""),
                    str(current.kennel_id or ""),
                    str(int(current.is_public)),
                    current.updated_at.isoformat() if current.updated_at else "",
                )
            )
        )
    revision_key = sha256("|".join(revision_material).encode("utf-8")).hexdigest()[:20]

    return {
        "dog": dog,
        "generations": generations,
        "public_only": public_only,
        "layers": layers,
        "dogs_by_key": dogs_by_key,
        "revision_key": revision_key,
    }


def _layers_from_snapshot(snapshot):
    counts = Counter(
        current.pk
        for layer in snapshot["layers"]
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
        for index, layer in enumerate(snapshot["layers"])
    ]


def _occurrences_from_snapshot(snapshot):
    occurrences = []
    for generation, layer in enumerate(snapshot["layers"][1:], start=1):
        for index, current in enumerate(layer):
            if current is None:
                continue
            occurrences.append((current, generation, _slot_path(generation, index)))
    return occurrences


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
    snapshot = _pedigree_snapshot(dog, generations, public_only=public_only)
    return _layers_from_snapshot(snapshot)


def ancestor_occurrences(dog, generations=4, public_only=False):
    """Return every bounded pedigree position without relationship N+1 queries."""
    snapshot = _pedigree_snapshot(dog, generations, public_only=public_only)
    return _occurrences_from_snapshot(snapshot)


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
    return queryset.select_related("kennel", "sire", "dam").distinct().order_by("name")


def mate_relationships(dog, public_only=True):
    """Group mating partners automatically from canonical offspring links."""
    children = list(offspring_for(dog, public_only=public_only))
    groups = {}
    for child in children:
        if child.sire_id == dog.pk:
            mate = child.dam
        else:
            mate = child.sire
        key = str(mate.pk) if mate else "unknown"
        group = groups.setdefault(
            key,
            {"mate": mate, "offspring": [], "offspring_count": 0},
        )
        group["offspring"].append(child)
        group["offspring_count"] += 1
    return sorted(
        groups.values(),
        key=lambda item: (
            item["mate"] is None,
            item["mate"].name.lower() if item["mate"] else "",
        ),
    )


def descendant_generations(
    dog,
    generations=4,
    public_only=True,
    per_generation_limit=None,
):
    """Return unique descendant layers while allowing public views to cap breadth."""
    generations = _bounded_generations(generations)
    layers = []
    frontier = {dog.pk}
    seen = {dog.pk}
    for generation in range(1, generations + 1):
        children = Dog.objects.filter(
            Q(sire_id__in=frontier) | Q(dam_id__in=frontier)
        ).select_related("kennel", "sire", "dam")
        if public_only:
            children = children.filter(is_public=True)
        children = children.order_by("name")
        if per_generation_limit:
            fetched = list(children[: per_generation_limit + 1])
            truncated = len(fetched) > per_generation_limit
            fetched = fetched[:per_generation_limit]
        else:
            fetched = list(children)
            truncated = False
        rows = [child for child in fetched if child.pk not in seen]
        if not rows:
            break
        layers.append(
            {
                "number": generation,
                "label": (
                    "Children"
                    if generation == 1
                    else "Grandchildren"
                    if generation == 2
                    else f"Descendant generation {generation}"
                ),
                "dogs": rows,
                "truncated": truncated,
            }
        )
        frontier = {child.pk for child in rows}
        seen.update(frontier)
    return layers


def direct_relative_health(dog, public_only=True):
    """Summarize published health records for parents, siblings and offspring."""
    relatives = {}

    def add(relative, relation):
        if relative is None or (public_only and not relative.is_public):
            return
        row = relatives.setdefault(
            relative.pk,
            {"dog": relative, "relations": [], "records": []},
        )
        if relation not in row["relations"]:
            row["relations"].append(relation)

    add(dog.sire, "Sire")
    add(dog.dam, "Dam")
    for item in sibling_relationships(dog, public_only=public_only):
        add(item["dog"], item["relation"])
    for child in offspring_for(dog, public_only=public_only):
        add(child, "Offspring")

    if not relatives:
        return []

    records = HealthRecord.objects.filter(
        dog_id__in=relatives.keys()
    ).select_related("dog").order_by("dog__name", "test_type", "-tested_on")
    for record in records:
        relatives[record.dog_id]["records"].append(record)

    return sorted(
        relatives.values(),
        key=lambda row: (row["dog"].name.lower(), str(row["dog"].pk)),
    )


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
    """Load all reachable ancestors in breadth-first batches, then topologically order them."""
    nodes = {}
    frontier = []
    for dog in dogs:
        if dog is None or (public_only and not dog.is_public):
            continue
        nodes[dog.pk] = dog
        frontier.append(dog)

    while frontier:
        parent_ids = {
            parent_id
            for current in frontier
            for parent_id in (current.sire_id, current.dam_id)
            if parent_id and parent_id not in nodes
        }
        if not parent_ids:
            break
        parents = Dog.objects.in_bulk(parent_ids)
        if public_only:
            parents = {
                pk: parent for pk, parent in parents.items() if parent.is_public
            }
        frontier = []
        for parent in parents.values():
            if parent.pk not in nodes:
                nodes[parent.pk] = parent
                frontier.append(parent)

    visited = set()
    visiting = set()
    ordered = []

    def visit(dog_id):
        if dog_id in visited:
            return
        if dog_id in visiting:
            raise PedigreeCycleError("Pedigree contains a parent cycle.")
        current = nodes.get(dog_id)
        if current is None:
            return

        visiting.add(dog_id)
        for parent_id in (current.sire_id, current.dam_id):
            if parent_id in nodes:
                visit(parent_id)
        visiting.remove(dog_id)
        visited.add(dog_id)
        ordered.append(current)

    for dog in dogs:
        if dog is not None and dog.pk in nodes:
            visit(dog.pk)
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



def _analysis_payload(snapshot):
    occurrences = _occurrences_from_snapshot(snapshot)
    rows = {}
    known_by_generation = Counter()

    for ancestor, generation, path in occurrences:
        known_by_generation[generation] += 1
        key = str(ancestor.pk)
        row = rows.setdefault(
            key,
            {
                "dog_key": key,
                "name": ancestor.name,
                "occurrences": 0,
                "nearest_generation": generation,
                "percentage": 0.0,
                "paths": [],
            },
        )
        path_percent = 100.0 / (2 ** generation)
        row["occurrences"] += 1
        row["nearest_generation"] = min(row["nearest_generation"], generation)
        row["percentage"] += path_percent
        row["paths"].append(
            {
                "generation": generation,
                "path": list(path),
                "label": _path_label(path),
                "percentage": path_percent,
                "side": path[0] if path else "subject",
            }
        )

    contributions = []
    linebreeding = []
    for row in rows.values():
        row["percentage"] = min(100.0, row["percentage"])
        row["paths"].sort(key=lambda item: (item["generation"], item["label"]))
        contributions.append(row)
        if row["occurrences"] > 1:
            sides = {item["side"] for item in row["paths"]}
            if {"sire", "dam"}.issubset(sides):
                pattern = "Sire + dam lines"
            elif "sire" in sides:
                pattern = "Sire-side concentration"
            else:
                pattern = "Dam-side concentration"
            linebreeding.append(
                {
                    **row,
                    "pattern": pattern,
                    "crosses_both_sides": {"sire", "dam"}.issubset(sides),
                    "path_pair_count": row["occurrences"] * (row["occurrences"] - 1) // 2,
                    "paths": row["paths"][:8],
                }
            )

    contributions.sort(
        key=lambda row: (-row["percentage"], row["nearest_generation"], row["name"])
    )
    linebreeding.sort(
        key=lambda row: (
            not row["crosses_both_sides"],
            -row["percentage"],
            row["nearest_generation"],
            row["name"],
        )
    )

    generations = snapshot["generations"]
    total_slots = sum(2 ** generation for generation in range(1, generations + 1))
    known_slots = len(occurrences)
    deepest_known = max(known_by_generation, default=0)

    try:
        coi_percent = inbreeding_coefficient(
            snapshot["dog"], public_only=snapshot["public_only"]
        ) * 100
        cycle_error = ""
    except PedigreeCycleError:
        coi_percent = None
        cycle_error = "This pedigree contains a parent cycle and cannot be analysed safely."

    unique_ancestor_count = len(rows)
    ancestor_retention_percent = (
        unique_ancestor_count / known_slots * 100 if known_slots else 100.0
    )
    ancestor_loss_percent = max(0.0, 100.0 - ancestor_retention_percent)

    return {
        "coi_percent": coi_percent,
        "cycle_error": cycle_error,
        "coverage_percent": (known_slots / total_slots * 100) if total_slots else 0.0,
        "known_slots": known_slots,
        "total_slots": total_slots,
        "unique_ancestor_count": unique_ancestor_count,
        "ancestor_retention_percent": ancestor_retention_percent,
        "ancestor_loss_percent": ancestor_loss_percent,
        "deepest_known_generation": deepest_known,
        "contributions": contributions,
        "linebreeding": linebreeding,
        "generation_coverage": [
            {
                "generation": generation,
                "known": known_by_generation[generation],
                "total": 2 ** generation,
            }
            for generation in range(1, generations + 1)
        ],
    }


def pedigree_analysis(dog, generations=4, public_only=False):
    """Return the board and cached advanced metrics under a pedigree revision key."""
    snapshot = _pedigree_snapshot(dog, generations, public_only=public_only)
    cache_key = (
        f"cca:pedigree-analysis:v2:{dog.pk}:{snapshot['generations']}:"
        f"{int(public_only)}:{snapshot['revision_key']}"
    )
    payload = cache.get(cache_key)
    cache_hit = payload is not None
    if payload is None:
        payload = _analysis_payload(snapshot)
        cache.set(cache_key, payload, ANALYSIS_CACHE_SECONDS)

    dogs_by_key = snapshot["dogs_by_key"]
    contributions = [
        {**row, "dog": dogs_by_key[row["dog_key"]]}
        for row in payload["contributions"]
        if row["dog_key"] in dogs_by_key
    ]
    linebreeding = [
        {**row, "dog": dogs_by_key[row["dog_key"]]}
        for row in payload["linebreeding"]
        if row["dog_key"] in dogs_by_key
    ]
    repeated = [
        {
            "dog": row["dog"],
            "occurrences": row["occurrences"],
            "nearest_generation": row["nearest_generation"],
        }
        for row in linebreeding
    ]

    return {
        **payload,
        "layers": _layers_from_snapshot(snapshot),
        "contributions": contributions,
        "linebreeding": linebreeding,
        "repeated": repeated,
        "revision_key": snapshot["revision_key"],
        "cache_hit": cache_hit,
        "generations": snapshot["generations"],
    }


def pedigree_export_rows(dog, generations=4, public_only=False):
    """Return stable CSV-ready pedigree positions for the selected depth."""
    snapshot = _pedigree_snapshot(dog, generations, public_only=public_only)
    counts = Counter(
        current.pk
        for layer in snapshot["layers"][1:]
        for current in layer
        if current is not None
    )
    rows = []
    for generation, layer in enumerate(snapshot["layers"]):
        for index, current in enumerate(layer):
            if current is None:
                continue
            path = _slot_path(generation, index)
            rows.append(
                {
                    "generation": generation,
                    "path": _path_label(path),
                    "dog_id": str(current.pk),
                    "name": current.name,
                    "sex": current.get_sex_display(),
                    "date_of_birth": current.date_of_birth.isoformat()
                    if current.date_of_birth
                    else "",
                    "colour": current.colour,
                    "country": current.country,
                    "kennel": current.kennel.name if current.kennel_id else "",
                    "repeated": "yes" if generation and counts[current.pk] > 1 else "no",
                    "path_contribution_percent": 100.0 / (2 ** generation)
                    if generation
                    else 100.0,
                }
            )
    return rows
