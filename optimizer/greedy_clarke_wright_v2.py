"""
Greedy Clarke-Wright V2 solver for the thesis LRP model.

Self-contained file:
    - loads the Option B adapted CSV
    - controls beta, m, and p as Python globals
    - solves with greedy depot selection, nearest feasible assignment, and
      Clarke-Wright-informed one-route construction

Notation:
    V, E, delta[u,v], c[u], l[u], d[u], beta, m, p
"""

import csv
import math
import os
import time
from collections import defaultdict

from dataloader_v2 import (
    BETA,
    M,
    P,
    PROJECT_ROOT,
    ROUTE_COST_TYPE,
    _arc,
    _arc_cost as _distance,
    _euclidean,
    _to_float,
    _to_node_id,
    load_lrp_data,
    validate_dataset,
)


DATA_PATH = os.path.join(PROJECT_ROOT, "data", "lrp_prins_option_b_10_5_1a_derived.csv")


def _depot_score(candidate, open_depots, unassigned, delta, c, l, d, k_nearest=8):
    nearby = sorted(unassigned, key=lambda v: _arc(delta, candidate, v))[:k_nearest]
    covered_demand = sum(d[v] for v in nearby)
    weighted_distance = sum(d[v] * _arc(delta, candidate, v) for v in nearby)
    coverage_bonus = covered_demand / max(sum(d[v] for v in unassigned), 1.0)
    separation_penalty = 0.0
    if open_depots:
        nearest_open = min(_arc(delta, candidate, w) for w in open_depots)
        separation_penalty = 25.0 / max(nearest_open, 1.0)
    return l[candidate] + weighted_distance / max(covered_demand, 1.0) - 50.0 * coverage_bonus + separation_penalty


def select_depots_greedy(V, delta, c, l, d, p=None, m=None):
    open_depots = []
    unassigned = set(V)
    candidates = [u for u in V if c[u] >= d[u]]
    if not candidates:
        raise ValueError("No candidate can serve itself.")

    target = p if p is not None else (m or len(V))
    while len(open_depots) < target:
        remaining = [u for u in candidates if u not in open_depots]
        if not remaining:
            break
        best = min(remaining, key=lambda u: _depot_score(u, open_depots, unassigned, delta, c, l, d))
        open_depots.append(best)
        unassigned.discard(best)
        if p is None and sum(c[w] for w in open_depots) >= sum(d.values()):
            break
    if p is not None and len(open_depots) != p:
        raise ValueError(f"Could not open exactly p={p} depots.")
    return open_depots


def _open_best_extra_depot(V, open_depots, customer, delta, c, l, d):
    candidates = [u for u in V if u not in open_depots and c[u] >= d[u] + (0 if u == customer else d[customer])]
    if not candidates:
        raise ValueError(f"No unopened depot can accept customer {customer}.")
    return min(candidates, key=lambda u: (l[u] + _arc(delta, u, customer), u))


def assign_customers_nearest_feasible(V, open_depots, delta, c, d, l, p=None, m=None):
    open_depots = list(open_depots)
    assignment = {}
    used_capacity = defaultdict(float)
    for w in open_depots:
        assignment[w] = w
        used_capacity[w] = d[w]

    for v in sorted((u for u in V if u not in assignment), key=lambda u: (-d[u], u)):
        feasible = [w for w in open_depots if used_capacity[w] + d[v] <= c[w]]
        if not feasible:
            if p is not None or (m is not None and len(open_depots) >= m):
                raise ValueError(f"No feasible depot for customer {v}.")
            new_depot = _open_best_extra_depot(V, open_depots, v, delta, c, l, d)
            open_depots.append(new_depot)
            assignment[new_depot] = new_depot
            used_capacity[new_depot] = d[new_depot]
            if new_depot == v:
                continue
            feasible = [new_depot]
        best = min(feasible, key=lambda w: (_arc(delta, w, v), used_capacity[w], w))
        assignment[v] = best
        used_capacity[best] += d[v]
    return open_depots, assignment


def _route_distance(depot, sequence, delta):
    if not sequence:
        return 0.0
    path = [depot] + sequence + [depot]
    return sum(_arc(delta, path[i], path[i + 1]) for i in range(len(path) - 1))


def _best_concat(depot, a, b, delta):
    candidates = [a + b, b + a, list(reversed(a)) + b, a + list(reversed(b)), list(reversed(a)) + list(reversed(b))]
    return min(candidates, key=lambda seq: _route_distance(depot, seq, delta))


def _force_single_route(depot, route_sequences, delta):
    sequences = [list(seq) for seq in route_sequences if seq]
    while len(sequences) > 1:
        best = None
        for i in range(len(sequences)):
            for j in range(i + 1, len(sequences)):
                merged = _best_concat(depot, sequences[i], sequences[j], delta)
                score = _route_distance(depot, merged, delta)
                if best is None or score < best[0]:
                    best = (score, i, j, merged)
        _, i, j, merged = best
        sequences[i] = merged
        del sequences[j]
    return sequences[0] if sequences else []


def clarke_wright_routes_for_depot(w, customers, delta, d, beta):
    if not customers:
        return []
    if sum(d[v] for v in customers) > beta:
        raise ValueError(f"Depot {w} route demand exceeds beta.")

    routes = {v: [v] for v in customers}
    route_of = {v: v for v in customers}
    route_demand = {v: d[v] for v in customers}
    savings = sorted(
        ((delta[w, i] + delta[w, j] - delta[i, j], i, j) for i in customers for j in customers if i != j),
        reverse=True,
    )

    for _, i, j in savings:
        ri, rj = route_of[i], route_of[j]
        if ri == rj:
            continue
        route_i, route_j = routes[ri], routes[rj]
        if i not in (route_i[0], route_i[-1]) or j not in (route_j[0], route_j[-1]):
            continue
        if route_demand[ri] + route_demand[rj] > beta:
            continue
        merged = _best_concat(w, route_i, route_j, delta)
        keep, drop = min(ri, rj), max(ri, rj)
        routes[keep] = merged
        route_demand[keep] = route_demand[ri] + route_demand[rj]
        del routes[drop]
        del route_demand[drop]
        for v in merged:
            route_of[v] = keep

    sequence = _force_single_route(w, routes.values(), delta)
    return [{"depot": w, "customers": sequence, "route": [w] + sequence + [w], "demand": sum(d[v] for v in sequence), "distance": _route_distance(w, sequence, delta)}]


def calculate_solution_cost(solution):
    solution["opening_cost"] = sum(solution["l"][w] for w in solution["open_depots"])
    solution["routing_cost"] = sum(route["distance"] for routes in solution["routes_by_depot"].values() for route in routes)
    solution["vehicles_used"] = sum(len(routes) for routes in solution["routes_by_depot"].values())
    solution["total_cost"] = solution["opening_cost"] + solution["routing_cost"]
    return solution


def validate_solution(solution):
    V, d, beta, m = solution["V"], solution["d"], solution["beta"], solution["m"]
    open_depots = set(solution["open_depots"])
    assignment = solution["assignment"]
    errors = []
    if set(assignment) != set(V):
        errors.append("Not every customer is assigned exactly once.")
    if len(open_depots) > m:
        errors.append("Opened depots exceed m.")
    for v, w in assignment.items():
        if w not in open_depots:
            errors.append(f"Customer {v} assigned to unopened depot {w}.")
    for w in open_depots:
        if assignment.get(w) != w:
            errors.append(f"Depot {w} is not self-served.")
        if sum(d[v] for v in V if assignment.get(v) == w) > beta:
            errors.append(f"Depot {w} demand exceeds beta.")
        if len(solution["routes_by_depot"].get(w, [])) > 1:
            errors.append(f"Depot {w} has more than one route.")
    routed = []
    for w, routes in solution["routes_by_depot"].items():
        for route in routes:
            if route["route"][0] != w or route["route"][-1] != w:
                errors.append(f"Route for depot {w} does not start/end at depot.")
            if route["demand"] > beta:
                errors.append(f"Route for depot {w} exceeds beta.")
            routed.extend(route["customers"])
    expected = [v for v in V if assignment.get(v) != v]
    if sorted(routed) != sorted(expected):
        errors.append("Routed customers do not match non-self-service customers.")
    return not errors, errors


def solve_greedy_lrp(data_path=DATA_PATH, print_output=True):
    start = time.perf_counter()
    V, E, coords, delta, d, l, c, beta, m, p = load_lrp_data(data_path)
    open_depots = select_depots_greedy(V, delta, c, l, d, p=p, m=m)
    open_depots, assignment = assign_customers_nearest_feasible(V, open_depots, delta, c, d, l, p=p, m=m)
    routes_by_depot = {}
    for w in open_depots:
        customers = [v for v in V if assignment[v] == w and v != w]
        routes_by_depot[w] = clarke_wright_routes_for_depot(w, customers, delta, d, beta)
    solution = {
        "model_name": "Greedy Clarke-Wright V2",
        "data_path": data_path,
        "V": V,
        "coords": coords,
        "delta": delta,
        "d": d,
        "l": l,
        "c": c,
        "beta": beta,
        "m": m,
        "p": p,
        "open_depots": open_depots,
        "assignment": assignment,
        "self_service_customers": sorted(open_depots),
        "routes_by_depot": routes_by_depot,
        "runtime": time.perf_counter() - start,
    }
    calculate_solution_cost(solution)
    solution["validation_ok"], solution["validation_messages"] = validate_solution(solution)
    if print_output:
        print_solution(solution)
    return solution


def print_solution(solution):
    print("Greedy Clarke-Wright V2 Solution")
    print("=" * 72)
    print(f"dataset       : {solution['data_path']}")
    print(f"nodes         : {len(solution['V'])}")
    print(f"beta, m, p    : {solution['beta']:g}, {solution['m']}, {solution['p']}")
    print(f"opened depots : {solution['open_depots']}")
    print(f"vehicles used : {solution['vehicles_used']}")
    print(f"opening cost  : {solution['opening_cost']:.2f}")
    print(f"routing cost  : {solution['routing_cost']:.2f}")
    print(f"total cost    : {solution['total_cost']:.2f}")
    print(f"runtime       : {solution['runtime']:.4f}s")
    print(f"validation    : {'PASS' if solution['validation_ok'] else 'FAIL'}")
    if not solution["validation_ok"]:
        for message in solution["validation_messages"]:
            print(f"  - {message}")


if __name__ == "__main__":
    solve_greedy_lrp()
