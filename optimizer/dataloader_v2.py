"""
V2 dataset loader for the thesis Location-Routing Problem.

The CSV stores instance data only:
    node_id, x, y, demand, opening_cost, ...

Notation aligned with the PDF:
    V          : set of nodes
    E          : set of directed arcs
    delta[u,v] : distance / travel cost
    c[u]       : depot capacity at node u
    l[u]       : depot opening cost at node u
    d[u]       : demand at node u
    beta       : vehicle capacity
    m          : maximum number of vehicles
    p          : optional fixed number of depots

Global model settings live in this Python file:
    BETA = vehicle capacity
    M = maximum number of vehicles
    P = optional fixed number of depots

This keeps beta, m, and p out of the Excel/CSV data layer.
"""

import csv
import math
import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJECT_ROOT, "data", "lrp_prins_option_b_20_5_1a_nodes.csv")
BETA = 70.0
M = 5
P = None
ROUTE_COST_TYPE = 0


def _to_float(value, field_name, node_id):
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing {field_name} for node {node_id}.")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric {field_name} for node {node_id}: {value!r}") from exc


def _to_node_id(value, fallback):
    if value is None or str(value).strip() == "":
        return fallback
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else text


def _euclidean(coord_u, coord_v):
    return math.hypot(coord_u[0] - coord_v[0], coord_u[1] - coord_v[1])


def _arc_cost(coord_u, coord_v):
    distance = _euclidean(coord_u, coord_v)
    if ROUTE_COST_TYPE == 0:
        return float(int(distance * 100.0))
    return distance


def _read_rows(data_path):
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Dataset not found: {data_path}")
    with open(data_path, "r", newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)
    if not rows:
        raise ValueError(f"Dataset has no rows: {data_path}")
    return rows


def validate_lrp_data(V, coords, d, l, c, beta, m):
    errors = []
    for u in V:
        if u not in coords or coords[u] is None:
            errors.append(f"Missing coordinates for node {u}.")
        if u not in d:
            errors.append(f"Missing demand for node {u}.")
        elif d[u] < 0:
            errors.append(f"Negative demand for node {u}: {d[u]}.")
        if u not in l:
            errors.append(f"Missing opening cost for node {u}.")
        elif l[u] < 0:
            errors.append(f"Negative opening cost for node {u}: {l[u]}.")
        if u not in c:
            errors.append(f"Missing depot capacity for node {u}.")
        elif abs(c[u] - beta) > 1e-9:
            errors.append(f"Depot capacity must equal beta for node {u}: c={c[u]}, beta={beta}.")

    total_demand = sum(d.values())
    if beta <= 0:
        errors.append(f"beta must be positive, got {beta}.")
    if m <= 0:
        errors.append(f"m must be positive, got {m}.")
    if sum(c.values()) < total_demand:
        errors.append(f"Total possible depot capacity is insufficient for demand {total_demand:.2f}.")
    if beta * m < total_demand:
        errors.append(f"Fleet capacity beta*m={beta * m:.2f} is less than demand {total_demand:.2f}.")

    if errors:
        raise ValueError("LRP data validation failed:\n- " + "\n- ".join(errors))


def load_lrp_data(data_path=DATA_PATH, max_nodes=None, beta=BETA, m=M, p=P):
    """
    Return V, E, coords, delta, d, l, c, beta, m, p.

    beta, m, and p are controlled here, not by the CSV.
    """
    rows = _read_rows(data_path)
    if max_nodes is not None:
        rows = rows[:max_nodes]

    V = []
    coords = {}
    d = {}
    l = {}

    for index, row in enumerate(rows):
        node_id = _to_node_id(row.get("node_id"), index)
        V.append(node_id)
        coords[node_id] = (
            _to_float(row.get("x"), "x", node_id),
            _to_float(row.get("y"), "y", node_id),
        )
        d[node_id] = _to_float(row.get("demand"), "demand", node_id)
        l[node_id] = _to_float(row.get("opening_cost"), "opening_cost", node_id)

    beta = float(beta)
    m = int(m)
    if p is not None:
        p = int(p)
        if p > m:
            raise ValueError(f"p={p} cannot exceed m={m}.")

    c = {u: beta for u in V}
    E = [(u, v) for u in V for v in V if u != v]
    delta = {(u, v): _arc_cost(coords[u], coords[v]) for u, v in E}

    validate_lrp_data(V, coords, d, l, c, beta, m)
    return V, E, coords, delta, d, l, c, beta, m, p


def print_dataset_summary(data_path=DATA_PATH):
    V, E, coords, delta, d, l, c, beta, m, p = load_lrp_data(data_path)
    print("V2 LRP dataset loaded")
    print("=" * 72)
    print(f"path             : {data_path}")
    print(f"nodes            : {len(V)}")
    print(f"direct CSV fields: node_id, x, y, demand, opening_cost")
    print(f"global beta      : {beta:g}")
    print(f"global m         : {m}")
    print(f"global p         : {p}")
    print(f"capacity rule    : c[u] = beta for every node")
    print(f"distance rule    : int(100 * Euclidean distance)" if ROUTE_COST_TYPE == 0 else "distance rule    : Euclidean")
    print(f"total demand     : {sum(d.values()):.2f}")
    print(f"opening cost min : {min(l.values()):.2f}")
    print(f"opening cost max : {max(l.values()):.2f}")


if __name__ == "__main__":
    print_dataset_summary()
