"""
PSO V2 solver for the thesis Location-Routing Problem.

Self-contained file:
    - loads the Option B adapted CSV
    - controls beta, m, and p as Python globals
    - uses relative depot attractiveness plus particle priority weights

Notation:
    V, E, delta[u,v], c[u], l[u], d[u], beta, m, p
"""

import csv
import math
import os
import random
import time
from copy import deepcopy


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJECT_ROOT, "data", "lrp_prins_option_b_20_5_1a_nodes.csv")
BETA = 70.0
M = 5
P = None
ROUTE_COST_TYPE = 0

NUM_PARTICLES = 35
MAX_ITERATIONS = 80
INERTIA = 0.72
C1 = 1.45
C2 = 1.45
ALPHA = 0.55
SEED = 42
POSITION_BOUNDS = (0.0, 1.0)
VELOCITY_BOUNDS = (-0.25, 0.25)
BIG_PENALTY = 1_000_000.0


def _to_float(value, field_name, node_id):
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing {field_name} for node {node_id}.")
    return float(value)


def _to_node_id(value, fallback):
    if value is None or str(value).strip() == "":
        return fallback
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number.is_integer() else text


def _distance(a, b):
    euclidean = math.hypot(a[0] - b[0], a[1] - b[1])
    return float(int(euclidean * 100.0)) if ROUTE_COST_TYPE == 0 else euclidean


def load_lrp_data(data_path=DATA_PATH, max_nodes=None, beta=BETA, m=M, p=P):
    with open(data_path, "r", newline="", encoding="utf-8-sig") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if max_nodes is not None:
        rows = rows[:max_nodes]
    if not rows:
        raise ValueError(f"No rows found in {data_path}")

    V, coords, d, l = [], {}, {}, {}
    for index, row in enumerate(rows):
        node_id = _to_node_id(row.get("node_id"), index)
        V.append(node_id)
        coords[node_id] = (_to_float(row.get("x"), "x", node_id), _to_float(row.get("y"), "y", node_id))
        d[node_id] = _to_float(row.get("demand"), "demand", node_id)
        l[node_id] = _to_float(row.get("opening_cost"), "opening_cost", node_id)

    beta = float(beta)
    m = int(m)
    c = {u: beta for u in V}
    E = [(u, v) for u in V for v in V if u != v]
    delta = {(u, v): _distance(coords[u], coords[v]) for u, v in E}
    validate_dataset(V, coords, d, l, c, beta, m)
    return V, E, coords, delta, d, l, c, beta, m, p


def validate_dataset(V, coords, d, l, c, beta, m):
    if beta <= 0 or m <= 0:
        raise ValueError("beta and m must be positive.")
    if beta * m < sum(d.values()):
        raise ValueError("Fleet capacity beta*m is insufficient.")
    for u in V:
        if u not in coords:
            raise ValueError(f"Missing coordinates for node {u}.")
        if d[u] < 0:
            raise ValueError(f"Negative demand for node {u}.")
        if l[u] < 0:
            raise ValueError(f"Negative opening cost for node {u}.")
        if abs(c[u] - beta) > 1e-9:
            raise ValueError(f"Depot capacity for node {u} must equal beta.")


def _arc(delta, u, v):
    return 0.0 if u == v else delta[u, v]


def normalize_values(values):
    lo, hi = min(values.values()), max(values.values())
    if abs(hi - lo) < 1e-12:
        return {key: 0.0 for key in values}
    return {key: (value - lo) / (hi - lo) for key, value in values.items()}


def compute_relative_depot_weights(V, delta, d, l):
    scores = {}
    for u in V:
        scores[u] = l[u] + sum(d[v] * _arc(delta, u, v) for v in V if v != u)
    return normalize_values(scores)


def initialize_particles(num_particles, V, seed):
    rng = random.Random(seed)
    particles = []
    for _ in range(num_particles):
        position = {u: rng.random() for u in V}
        velocity = {u: rng.uniform(VELOCITY_BOUNDS[0], VELOCITY_BOUNDS[1]) for u in V}
        particles.append(
            {
                "position": position,
                "velocity": velocity,
                "personal_best_position": dict(position),
                "personal_best_fitness": float("inf"),
            }
        )
    return particles


def assign_customers_for_pso(sorted_depots, V, delta, d, beta, m, p):
    assignment = {}
    open_depots = []
    used_capacity = {}
    penalties = []
    max_open = p if p is not None else m

    if p is not None and p > m:
        return [], {}, [f"p={p} exceeds m={m}."]

    for w in sorted_depots:
        if len(open_depots) >= max_open:
            break
        if all(v in assignment for v in V):
            break
        if w in assignment or d[w] > beta:
            continue

        open_depots.append(w)
        assignment[w] = w
        used_capacity[w] = d[w]

        while True:
            feasible = [v for v in V if v not in assignment and used_capacity[w] + d[v] <= beta]
            if not feasible:
                break
            nxt = min(feasible, key=lambda v: (_arc(delta, w, v), -d[v], v))
            assignment[nxt] = w
            used_capacity[w] += d[nxt]

        if p is not None and len(open_depots) == p:
            break

    if p is not None:
        for v in sorted((u for u in V if u not in assignment), key=lambda u: (-d[u], u)):
            feasible = [w for w in open_depots if used_capacity[w] + d[v] <= beta]
            if not feasible:
                penalties.append(f"Customer {v} cannot be assigned within fixed p.")
                continue
            best = min(feasible, key=lambda w: (_arc(delta, w, v), used_capacity[w], w))
            assignment[v] = best
            used_capacity[best] += d[v]

    missing = sorted(set(V) - set(assignment))
    if missing:
        penalties.append(f"Unassigned customers remain: {missing}")
    return open_depots, assignment, penalties


def build_single_route_for_depot(w, assigned_customers, delta, d, beta):
    customers = [v for v in assigned_customers if v != w]
    route_demand = sum(d[v] for v in customers)
    if route_demand > beta:
        return {"depot": w, "customers": customers, "route": [w] + customers + [w], "demand": route_demand, "distance": 0.0, "feasible": False}

    unvisited = set(customers)
    current = w
    sequence = []
    while unvisited:
        nxt = min(unvisited, key=lambda v: (_arc(delta, current, v), v))
        sequence.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    path = [w] + sequence + [w]
    return {
        "depot": w,
        "customers": sequence,
        "route": path,
        "demand": route_demand,
        "distance": sum(_arc(delta, path[i], path[i + 1]) for i in range(len(path) - 1)),
        "feasible": True,
    }


def decode_particle(position, relative_weights, V, delta, d, l, beta, m, p, alpha=ALPHA):
    normalized_position = normalize_values(position)
    combined = {u: alpha * normalized_position[u] + (1.0 - alpha) * relative_weights[u] for u in V}
    sorted_depots = sorted(V, key=lambda u: (combined[u], relative_weights[u], u))
    open_depots, assignment, penalties = assign_customers_for_pso(sorted_depots, V, delta, d, beta, m, p)

    routes_by_depot = {}
    for w in open_depots:
        assigned = [v for v in V if assignment.get(v) == w]
        route = build_single_route_for_depot(w, assigned, delta, d, beta)
        routes_by_depot[w] = [] if not route["customers"] else [route]
        if not route["feasible"]:
            penalties.append(f"Route for depot {w} exceeds beta.")

    solution = {
        "model_name": "PSO V2",
        "data_path": DATA_PATH,
        "V": V,
        "delta": delta,
        "d": d,
        "l": l,
        "c": {u: beta for u in V},
        "beta": beta,
        "m": m,
        "p": p,
        "open_depots": open_depots,
        "assignment": assignment,
        "self_service_customers": sorted(open_depots),
        "routes_by_depot": routes_by_depot,
        "penalty_messages": penalties,
    }
    calculate_cost(solution)
    solution["validation_ok"], solution["validation_messages"] = validate_solution(solution)
    return solution


def calculate_cost(solution):
    solution["opening_cost"] = sum(solution["l"][w] for w in solution["open_depots"])
    solution["routing_cost"] = sum(route["distance"] for routes in solution["routes_by_depot"].values() for route in routes)
    solution["vehicles_used"] = sum(len(routes) for routes in solution["routes_by_depot"].values())
    solution["total_cost"] = solution["opening_cost"] + solution["routing_cost"]
    return solution


def fitness(solution):
    penalty_count = len(solution.get("penalty_messages", []))
    if not solution.get("validation_ok", False):
        penalty_count += max(1, len(solution.get("validation_messages", [])))
    if solution["vehicles_used"] > solution["m"]:
        penalty_count += solution["vehicles_used"] - solution["m"]
    return solution["total_cost"] + BIG_PENALTY * penalty_count


def update_particles(particles, global_best_position, rng, inertia=INERTIA, c1=C1, c2=C2):
    lo, hi = POSITION_BOUNDS
    vlo, vhi = VELOCITY_BOUNDS
    for particle in particles:
        for u in particle["position"]:
            r1, r2 = rng.random(), rng.random()
            velocity = (
                inertia * particle["velocity"][u]
                + c1 * r1 * (particle["personal_best_position"][u] - particle["position"][u])
                + c2 * r2 * (global_best_position[u] - particle["position"][u])
            )
            velocity = max(vlo, min(vhi, velocity))
            particle["velocity"][u] = velocity
            particle["position"][u] = max(lo, min(hi, particle["position"][u] + velocity))


def validate_solution(solution):
    V, d, beta, m = solution["V"], solution["d"], solution["beta"], solution["m"]
    open_depots = set(solution["open_depots"])
    assignment = solution["assignment"]
    errors = []
    if set(assignment) != set(V):
        errors.append("Not every customer is assigned.")
    if len(open_depots) > m or solution["vehicles_used"] > m:
        errors.append("Vehicle/depot count exceeds m.")
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


def solve_pso_lrp(data_path=DATA_PATH, print_output=True):
    start = time.perf_counter()
    rng = random.Random(SEED)
    V, E, coords, delta, d, l, c, beta, m, p = load_lrp_data(data_path)
    relative_weights = compute_relative_depot_weights(V, delta, d, l)
    particles = initialize_particles(NUM_PARTICLES, V, SEED)

    global_best_position = dict(particles[0]["position"])
    global_best_solution = None
    global_best_fitness = float("inf")
    history = []

    for _ in range(MAX_ITERATIONS):
        for particle in particles:
            solution = decode_particle(particle["position"], relative_weights, V, delta, d, l, beta, m, p)
            solution["data_path"] = data_path
            fit = fitness(solution)
            if fit < particle["personal_best_fitness"]:
                particle["personal_best_fitness"] = fit
                particle["personal_best_position"] = dict(particle["position"])
            if fit < global_best_fitness:
                global_best_fitness = fit
                global_best_position = dict(particle["position"])
                global_best_solution = deepcopy(solution)
        history.append(global_best_fitness)
        update_particles(particles, global_best_position, rng)

    global_best_solution["runtime"] = time.perf_counter() - start
    global_best_solution["convergence_history"] = history
    global_best_solution["best_fitness"] = global_best_fitness
    if print_output:
        print_solution(global_best_solution)
    return global_best_solution


def print_solution(solution):
    print("PSO V2 Solution")
    print("=" * 72)
    print(f"dataset       : {solution['data_path']}")
    print(f"settings      : particles={NUM_PARTICLES}, iterations={MAX_ITERATIONS}, inertia={INERTIA}, c1={C1}, c2={C2}, alpha={ALPHA}, seed={SEED}")
    print(f"nodes         : {len(solution['V'])}")
    print(f"beta, m, p    : {solution['beta']:g}, {solution['m']}, {solution['p']}")
    print(f"opened depots : {solution['open_depots']}")
    print(f"vehicles used : {solution['vehicles_used']}")
    print(f"opening cost  : {solution['opening_cost']:.2f}")
    print(f"routing cost  : {solution['routing_cost']:.2f}")
    print(f"total cost    : {solution['total_cost']:.2f}")
    print(f"best fitness  : {solution['best_fitness']:.2f}")
    print(f"runtime       : {solution['runtime']:.4f}s")
    print(f"validation    : {'PASS' if solution['validation_ok'] else 'FAIL'}")
    print("convergence   : " + ", ".join(f"{value:.2f}" for value in solution["convergence_history"][:10]) + (" ..." if len(solution["convergence_history"]) > 10 else ""))
    if not solution["validation_ok"]:
        for message in solution["validation_messages"]:
            print(f"  - {message}")


if __name__ == "__main__":
    solve_pso_lrp()
