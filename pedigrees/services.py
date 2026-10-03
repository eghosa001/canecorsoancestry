from collections import Counter, defaultdict
from hashlib import sha256
from time import perf_counter

from django.core.cache import cache
from django.db import connection
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
    layers = []
    for generation, layer in enumerate(snapshot["layers"]):
        nodes = []
        for index, current in enumerate(layer):
            relationship = (
                "Subject"
                if generation == 0
                else _path_label(_slot_path(generation, index))
            )
            nodes.append(
                {
                    "dog": current,
                    "relationship": relationship,
                    "repeated": bool(current and counts[current.pk] > 1),
                }
            )
        layers.append(
            {
                "number": generation,
                "label": labels.get(generation, f"Generation {generation}"),
                "nodes": nodes,
            }
        )
    return layers


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


def sibling_relationships(dog, public_only=True, limit=None):
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
    if limit:
        siblings = siblings[:limit]

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


def mate_relationships(dog, public_only=True, preview_limit=5, children=None):
    """Group mating partners while retaining only a small offspring preview per mate."""
    groups = {}
    if children is None:
        children = offspring_for(dog, public_only=public_only)
    child_rows = (
        children.iterator(chunk_size=500)
        if hasattr(children, "iterator")
        else children
    )
    for child in child_rows:
        if child.sire_id == dog.pk:
            mate = child.dam
        else:
            mate = child.sire
        key = str(mate.pk) if mate else "unknown"
        group = groups.setdefault(
            key,
            {"mate": mate, "offspring": [], "offspring_count": 0},
        )
        if len(group["offspring"]) < preview_limit:
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


def direct_relative_health(
    dog,
    public_only=True,
    sibling_rows=None,
    children=None,
):
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
    if sibling_rows is None:
        sibling_rows = sibling_relationships(
            dog, public_only=public_only, limit=200
        )
    for item in list(sibling_rows)[:200]:
        add(item["dog"], item["relation"])

    if children is None:
        children = list(offspring_for(dog, public_only=public_only)[:200])
    for child in list(children)[:200]:
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


def _pedigree_graph(*dogs, public_only=False):
    """Return ancestry links and display-ready dogs from one recursive DB load."""
    roots = [
        dog
        for dog in dogs
        if dog is not None and (not public_only or dog.is_public)
    ]
    if not roots:
        return {}, {}

    if connection.vendor == "postgresql":
        table = connection.ops.quote_name(Dog._meta.db_table)
        placeholders = ", ".join(["%s"] * len(roots))
        public_root = " AND is_public" if public_only else ""
        public_parent = "WHERE parent.is_public" if public_only else ""
        sql = f"""
            WITH RECURSIVE pedigree AS (
                SELECT id, sire_id, dam_id, is_public, name, slug
                FROM {table}
                WHERE id IN ({placeholders}){public_root}
                UNION
                SELECT
                    parent.id,
                    parent.sire_id,
                    parent.dam_id,
                    parent.is_public,
                    parent.name,
                    parent.slug
                FROM {table} parent
                JOIN pedigree child
                  ON parent.id = child.sire_id OR parent.id = child.dam_id
                {public_parent}
            )
            SELECT id, sire_id, dam_id, is_public, name, slug
            FROM pedigree
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [dog.pk for dog in roots])
            rows = cursor.fetchall()

        links = {}
        nodes = {}
        for dog_id, sire_id, dam_id, is_public, name, slug in rows:
            links[dog_id] = (sire_id, dam_id)
            nodes[dog_id] = Dog(
                id=dog_id,
                sire_id=sire_id,
                dam_id=dam_id,
                is_public=is_public,
                name=name,
                slug=slug,
            )
        return links, nodes

    links = {
        dog.pk: (dog.sire_id, dog.dam_id)
        for dog in roots
    }
    nodes = {dog.pk: dog for dog in roots}
    frontier = list(roots)
    while frontier:
        parent_ids = {
            parent_id
            for current in frontier
            for parent_id in (current.sire_id, current.dam_id)
            if parent_id and parent_id not in links
        }
        if not parent_ids:
            break
        parents = Dog.objects.only(
            "id", "sire_id", "dam_id", "is_public", "name", "slug"
        ).in_bulk(parent_ids)
        if public_only:
            parents = {
                pk: parent
                for pk, parent in parents.items()
                if parent.is_public
            }
        frontier = list(parents.values())
        nodes.update(parents)
        for parent in frontier:
            links[parent.pk] = (parent.sire_id, parent.dam_id)
    return links, nodes


def _pedigree_links(*dogs, public_only=False):
    """Return all reachable parent links."""
    links, _ = _pedigree_graph(*dogs, public_only=public_only)
    return links


def _ordered_from_links(root_ids, links):
    """Topologically order a preloaded pedigree graph and reject parent cycles."""
    visited = set()
    visiting = set()
    ordered = []

    def visit(dog_id):
        if dog_id in visited:
            return
        if dog_id in visiting:
            raise PedigreeCycleError("Pedigree contains a parent cycle.")
        if dog_id not in links:
            return

        visiting.add(dog_id)
        for parent_id in links[dog_id]:
            if parent_id in links:
                visit(parent_id)
        visiting.remove(dog_id)
        visited.add(dog_id)
        ordered.append(dog_id)

    for dog_id in root_ids:
        if dog_id in links:
            visit(dog_id)
    return ordered


def _pedigree_order(*dogs, public_only=False):
    """Topologically order all reachable pedigree IDs after one ancestry load."""
    links = _pedigree_links(*dogs, public_only=public_only)
    ordered = _ordered_from_links(
        [dog.pk for dog in dogs if dog is not None],
        links,
    )
    return ordered, links


def _relationship_matrix(*dogs, public_only=False):
    ordered, links = _pedigree_order(*dogs, public_only=public_only)
    index = {dog_id: position for position, dog_id in enumerate(ordered)}
    size = len(ordered)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]

    for i, dog_id in enumerate(ordered):
        sire_id, dam_id = links[dog_id]
        sire_index = index.get(sire_id)
        dam_index = index.get(dam_id)

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


def _kinship_calculator(ordered, links):
    """Return a memoized kinship calculator for an already ordered pedigree graph."""
    order = {dog_id: position for position, dog_id in enumerate(ordered)}
    memo = {}

    def kinship(a_id, b_id):
        if not a_id or not b_id or a_id not in links or b_id not in links:
            return 0.0

        if order[a_id] < order[b_id]:
            a_id, b_id = b_id, a_id
        key = (a_id, b_id)
        if key in memo:
            return memo[key]

        if a_id == b_id:
            sire_id, dam_id = links[a_id]
            if sire_id in links and dam_id in links:
                value = 0.5 * (1.0 + kinship(sire_id, dam_id))
            else:
                value = 0.5
        else:
            sire_id, dam_id = links[a_id]
            value = 0.5 * kinship(sire_id, b_id) + 0.5 * kinship(dam_id, b_id)

        memo[key] = value
        return value

    return kinship


def _kinship_from_links(left_id, right_id, ordered, links):
    """Return the kinship coefficient for two dogs without allocating an NxN matrix."""
    return _kinship_calculator(ordered, links)(left_id, right_id)


def projected_inbreeding(sire, dam, public_only=False):
    """Return projected offspring COI for a sire/dam pairing as a 0..1 float."""
    if sire is None or dam is None:
        return None
    if sire.pk == dam.pk:
        raise ValueError("Sire and dam must be different dogs.")

    ordered, links = _pedigree_order(sire, dam, public_only=public_only)
    return max(
        0.0,
        _kinship_from_links(sire.pk, dam.pk, ordered, links),
    )


def _ancestry_occurrence_paths(root_id, links, generations=10):
    """Return every bounded ancestry path, including the selected dog at generation 0."""
    generations = _bounded_generations(generations)
    occurrences = defaultdict(list)
    if root_id not in links:
        return occurrences

    occurrences[root_id].append(
        {
            "generation": 0,
            "directions": (),
            "dog_ids": (root_id,),
        }
    )
    frontier = [(root_id, (), (root_id,))]

    for generation in range(1, generations + 1):
        next_frontier = []
        for dog_id, directions, dog_ids in frontier:
            parent_ids = links.get(dog_id)
            if not parent_ids:
                continue
            for relation, parent_id in zip(("sire", "dam"), parent_ids):
                if parent_id not in links:
                    continue
                path = directions + (relation,)
                route = dog_ids + (parent_id,)
                occurrences[parent_id].append(
                    {
                        "generation": generation,
                        "directions": path,
                        "dog_ids": route,
                    }
                )
                next_frontier.append((parent_id, path, route))
        if not next_frontier:
            break
        frontier = next_frontier

    return occurrences


def _projected_pedigree_layers(
    sire_id,
    dam_id,
    links,
    graph_dogs,
    generations=4,
    common_keys=None,
):
    """Build hypothetical offspring ancestry layers and pedigree completeness metrics."""
    generations = _bounded_generations(generations)
    common_keys = common_keys or set()
    raw_layers = []
    slots = [sire_id, dam_id]

    for _generation in range(1, generations + 1):
        visible_slots = [
            dog_id if dog_id in links else None
            for dog_id in slots
        ]
        raw_layers.append(visible_slots)

        next_slots = []
        for dog_id in visible_slots:
            if dog_id is None:
                next_slots.extend((None, None))
                continue
            sire_parent_id, dam_parent_id = links.get(dog_id, (None, None))
            next_slots.extend(
                (
                    sire_parent_id if sire_parent_id in links else None,
                    dam_parent_id if dam_parent_id in links else None,
                )
            )
        slots = next_slots

    all_known = [
        dog_id
        for layer in raw_layers
        for dog_id in layer
        if dog_id is not None
    ]
    counts = Counter(all_known)
    layers = []
    generation_coverage = []

    labels = {
        1: "Parents",
        2: "Grandparents",
        3: "Great-grandparents",
    }
    for generation, layer in enumerate(raw_layers, start=1):
        nodes = []
        known = 0
        for index, dog_id in enumerate(layer):
            dog = graph_dogs.get(dog_id) if dog_id else None
            if dog is not None:
                known += 1
            nodes.append(
                {
                    "dog": dog,
                    "relationship": _path_label(_slot_path(generation, index)),
                    "repeated": bool(dog_id and counts[dog_id] > 1),
                    "common": bool(dog_id and str(dog_id) in common_keys),
                }
            )
        layers.append(
            {
                "number": generation,
                "label": labels.get(generation, f"Generation {generation}"),
                "nodes": nodes,
            }
        )
        generation_coverage.append(
            {
                "generation": generation,
                "known": known,
                "total": 2 ** generation,
            }
        )

    known_slots = len(all_known)
    total_slots = sum(2 ** generation for generation in range(1, generations + 1))
    unique_ids = set(all_known)
    deepest_known = max(
        (
            generation
            for generation, layer in enumerate(raw_layers, start=1)
            if any(dog_id is not None for dog_id in layer)
        ),
        default=0,
    )

    return layers, {
        "known_slots": known_slots,
        "total_slots": total_slots,
        "coverage_percent": (known_slots / total_slots * 100) if total_slots else 0.0,
        "unique_ancestor_count": len(unique_ids),
        "deepest_known_generation": deepest_known,
        "generation_coverage": generation_coverage,
    }


def _independent_path_pair(left_path, right_path):
    """Wright path pairs may only meet at their nominated common ancestor."""
    return not (
        set(left_path["dog_ids"][:-1])
        & set(right_path["dog_ids"][:-1])
    )


def _pedigree_links_revision(links):
    material = [
        f"{dog_id}:{sire_id or ''}:{dam_id or ''}"
        for dog_id, (sire_id, dam_id) in sorted(
            links.items(),
            key=lambda item: str(item[0]),
        )
    ]
    return sha256("|".join(material).encode("utf-8")).hexdigest()[:20]


def virtual_mating_analysis(sire, dam, generations=8, public_only=True):
    """Return a complete, bounded analysis for a hypothetical sire/dam pairing."""
    if sire is None or dam is None:
        return {
            "projected_inbreeding": None,
            "relationship": None,
            "sire_inbreeding": None,
            "dam_inbreeding": None,
            "common": [],
            "contributions": [],
            "pedigree_nodes": 0,
            "completeness": {
                "known_slots": 0,
                "total_slots": 0,
                "coverage_percent": 0.0,
                "unique_ancestor_count": 0,
                "deepest_known_generation": 0,
                "generation_coverage": [],
            },
            "projected_layers": [],
            "generations": _bounded_generations(generations),
            "cache_hit": False,
        }
    if sire.pk == dam.pk:
        raise ValueError("Sire and dam must be different dogs.")

    generations = _bounded_generations(generations)
    links, graph_dogs = _pedigree_graph(sire, dam, public_only=public_only)
    ordered = _ordered_from_links((sire.pk, dam.pk), links)
    revision = _pedigree_links_revision(links)
    cache_key = (
        f"cca:virtual-mating:v2:{sire.pk}:{dam.pk}:{generations}:"
        f"{int(public_only)}:{revision}"
    )
    payload = cache.get(cache_key)
    cache_hit = payload is not None

    if payload is None:
        kinship = _kinship_calculator(ordered, links)
        projected = max(0.0, kinship(sire.pk, dam.pk))
        sire_inbreeding = max(0.0, (2.0 * kinship(sire.pk, sire.pk)) - 1.0)
        dam_inbreeding = max(0.0, (2.0 * kinship(dam.pk, dam.pk)) - 1.0)

        left_paths = _ancestry_occurrence_paths(
            sire.pk,
            links,
            generations=generations,
        )
        right_paths = _ancestry_occurrence_paths(
            dam.pk,
            links,
            generations=generations,
        )
        common_ids = left_paths.keys() & right_paths.keys()
        common_rows = []

        for dog_id in common_ids:
            ancestor_inbreeding = max(
                0.0,
                (2.0 * kinship(dog_id, dog_id)) - 1.0,
            )
            contribution = 0.0
            valid_path_pairs = 0
            for left_path in left_paths[dog_id]:
                for right_path in right_paths[dog_id]:
                    if not _independent_path_pair(left_path, right_path):
                        continue
                    contribution += (
                        0.5
                        ** (
                            left_path["generation"]
                            + right_path["generation"]
                            + 1
                        )
                    ) * (1.0 + ancestor_inbreeding)
                    valid_path_pairs += 1

            left_labels = [
                "Selected sire"
                if path["generation"] == 0
                else _path_label(path["directions"])
                for path in left_paths[dog_id]
            ]
            right_labels = [
                "Selected dam"
                if path["generation"] == 0
                else _path_label(path["directions"])
                for path in right_paths[dog_id]
            ]
            common_rows.append(
                {
                    "dog_id": str(dog_id),
                    "left_occurrences": len(left_paths[dog_id]),
                    "right_occurrences": len(right_paths[dog_id]),
                    "left_generation": min(
                        path["generation"] for path in left_paths[dog_id]
                    ),
                    "right_generation": min(
                        path["generation"] for path in right_paths[dog_id]
                    ),
                    "left_paths": left_labels[:6],
                    "right_paths": right_labels[:6],
                    "contribution": contribution,
                    "valid_path_pairs": valid_path_pairs,
                    "ancestor_inbreeding": ancestor_inbreeding,
                }
            )

        _unused_layers, completeness = _projected_pedigree_layers(
            sire.pk,
            dam.pk,
            links,
            graph_dogs,
            generations=generations,
            common_keys={row["dog_id"] for row in common_rows},
        )
        payload = {
            "projected_inbreeding": projected,
            "relationship": projected * 2.0,
            "sire_inbreeding": sire_inbreeding,
            "dam_inbreeding": dam_inbreeding,
            "common": common_rows,
            "pedigree_nodes": len(links),
            "completeness": completeness,
        }
        cache.set(cache_key, payload, 5 * 60)

    graph_dogs_by_key = {
        str(dog_id): dog
        for dog_id, dog in graph_dogs.items()
    }
    common = [
        {
            **row,
            "dog": graph_dogs_by_key[row["dog_id"]],
            "contribution_percent": row["contribution"] * 100.0,
            "ancestor_inbreeding_percent": row["ancestor_inbreeding"] * 100.0,
        }
        for row in payload["common"]
        if row["dog_id"] in graph_dogs_by_key
    ]
    common.sort(
        key=lambda row: (
            row["left_generation"] + row["right_generation"],
            -row["contribution"],
            row["dog"].name,
        )
    )
    contributions = sorted(
        common,
        key=lambda row: (
            -row["contribution"],
            row["left_generation"] + row["right_generation"],
            row["dog"].name,
        ),
    )

    common_keys = {row["dog_id"] for row in common}
    projected_layers, _projected_summary = _projected_pedigree_layers(
        sire.pk,
        dam.pk,
        links,
        graph_dogs,
        generations=min(4, generations),
        common_keys=common_keys,
    )

    return {
        "projected_inbreeding": payload["projected_inbreeding"],
        "relationship": payload["relationship"],
        "sire_inbreeding": payload["sire_inbreeding"],
        "dam_inbreeding": payload["dam_inbreeding"],
        "common": common,
        "contributions": contributions,
        "contribution_total": sum(row["contribution"] for row in common),
        "pedigree_nodes": payload["pedigree_nodes"],
        "completeness": payload["completeness"],
        "projected_layers": projected_layers,
        "generations": generations,
        "cache_hit": cache_hit,
    }


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
