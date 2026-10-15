"""
MTZ/Gurobi V2 solver for the thesis Location-Routing Problem.

Self-contained file:
    - loads the Option B adapted CSV
    - controls beta, m, and p as Python globals
    - builds the MTZ LRP model directly in this file

Model assumptions:
    - every customer node is also a depot candidate
    - opened depot u self-serves customer u
    - delivery only, not pickup
    - one opened depot has at most one vehicle/route
    - c[u] = beta for every node

Notation:
    V, E, delta[u,v], c[u], l[u], d[u], beta, m, p
Decision variables:
    x[u,v], z[w,u,v], y[w,u,v], s[w,u]
"""

import csv
import math
import os
import time
from collections import defaultdict


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJECT_ROOT, "data", "lrp_prins_option_b_10_5_1a_derived.csv")
BETA = 70.0
M = 5
P = None
ROUTE_COST_TYPE = 0
MAX_NODES_FOR_MTZ = 15
TIME_LIMIT_SECONDS = 300
MIP_GAP = 0.01
OUTPUT_FLAG = 1


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


def load_lrp_data(data_path=DATA_PATH, max_nodes=MAX_NODES_FOR_MTZ, beta=BETA, m=M, p=P):
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


def build_mtz_model(V, E, delta, d, l, beta, m, p):
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as exc:
        raise RuntimeError("gurobipy is not installed or not available in this Python environment.") from exc

    n = len(V)
    model = gp.Model("LRP_MTZ_V2")
    x = model.addVars(((u, v) for u in V for v in V), vtype=GRB.BINARY, name="x")
    z = model.addVars(((w, u, v) for w in V for (u, v) in E), vtype=GRB.BINARY, name="z")
    y = model.addVars(((w, u, v) for w in V for (u, v) in E), lb=0.0, vtype=GRB.CONTINUOUS, name="y")
    s = model.addVars(((w, u) for w in V for u in V if u != w), lb=0.0, ub=n - 1, vtype=GRB.CONTINUOUS, name="s")

    model.setObjective(
        gp.quicksum(l[u] * x[u, u] for u in V)
        + gp.quicksum(delta[u, v] * z[w, u, v] for w in V for (u, v) in E),
        GRB.MINIMIZE,
    )

    for v in V:
        model.addConstr(gp.quicksum(x[u, v] for u in V) == 1, name=f"assign_once[{v}]")
    for u in V:
        for v in V:
            model.addConstr(x[u, v] <= x[u, u], name=f"assign_only_open[{u},{v}]")
    if p is None:
        model.addConstr(gp.quicksum(x[u, u] for u in V) >= 1, name="min_one_depot")
    else:
        model.addConstr(gp.quicksum(x[u, u] for u in V) == p, name="fixed_depot_count")

    for u in V:
        model.addConstr(gp.quicksum(d[v] * x[u, v] for v in V) <= beta * x[u, u], name=f"depot_capacity[{u}]")
    model.addConstr(gp.quicksum(x[u, u] for u in V) <= m, name="open_depots_limit")
    model.addConstr(gp.quicksum(z[w, w, v] for w in V for v in V if v != w) <= m, name="vehicle_limit")

    for w in V:
        model.addConstr(gp.quicksum(z[w, w, v] for v in V if v != w) <= x[w, w], name=f"one_departure[{w}]")
        model.addConstr(
            gp.quicksum(z[w, u, w] for u in V if u != w) == gp.quicksum(z[w, w, v] for v in V if v != w),
            name=f"depot_balance[{w}]",
        )

    for w in V:
        for v in V:
            if v == w:
                continue
            model.addConstr(gp.quicksum(z[w, i, v] for i in V if i != v) == x[w, v], name=f"in_visit[{w},{v}]")
            model.addConstr(gp.quicksum(z[w, v, j] for j in V if j != v) == x[w, v], name=f"out_visit[{w},{v}]")
            model.addConstr(
                gp.quicksum(y[w, i, v] for i in V if i != v) - gp.quicksum(y[w, v, j] for j in V if j != v)
                == d[v] * x[w, v],
                name=f"delivery_flow[{w},{v}]",
            )

    for w in V:
        model.addConstr(
            gp.quicksum(y[w, w, v] for v in V if v != w) == gp.quicksum(d[v] * x[w, v] for v in V if v != w),
            name=f"depot_supply[{w}]",
        )
        for u in V:
            if u != w:
                model.addConstr(y[w, u, w] == 0.0, name=f"empty_return[{w},{u}]")

    for w in V:
        for u, v in E:
            model.addConstr(y[w, u, v] <= beta * z[w, u, v], name=f"arc_capacity[{w},{u},{v}]")

    for w in V:
        for u in V:
            if u == w:
                continue
            model.addConstr(s[w, u] >= x[w, u], name=f"mtz_active_lb[{w},{u}]")
            model.addConstr(s[w, u] <= (n - 1) * x[w, u], name=f"mtz_active_ub[{w},{u}]")
            for v in V:
                if v != w and v != u:
                    model.addConstr(s[w, u] - s[w, v] + n * z[w, u, v] <= n - 1, name=f"mtz_subtour[{w},{u},{v}]")

    model.Params.TimeLimit = TIME_LIMIT_SECONDS
    model.Params.MIPGap = MIP_GAP
    model.Params.OutputFlag = OUTPUT_FLAG
    return model, x, z, y


def _selected(var, tol=0.5):
    return float(var.X) > tol


def extract_routes_for_depot(w, V, E, z, d, delta):
    selected_arcs = [(u, v) for (u, v) in E if _selected(z[w, u, v])]
    next_nodes = defaultdict(list)
    for u, v in selected_arcs:
        next_nodes[u].append(v)
    routes = []
    used = set()
    for first in sorted(next_nodes.get(w, []), key=str):
        route = [w]
        u, v = w, first
        while (u, v) not in used:
            used.add((u, v))
            route.append(v)
            if v == w:
                break
            candidates = [node for node in next_nodes.get(v, []) if (v, node) not in used]
            if not candidates:
                break
            u, v = v, sorted(candidates, key=str)[0]
        customers = [node for node in route if node != w]
        routes.append({"depot": w, "customers": customers, "route": route, "demand": sum(d[node] for node in customers), "distance": sum(delta[route[i], route[i + 1]] for i in range(len(route) - 1))})
    return routes


def extract_solution(model, V, E, coords, delta, d, l, beta, m, p, x, z):
    open_depots = [u for u in V if _selected(x[u, u])]
    assignment = {v: next((u for u in V if _selected(x[u, v])), None) for v in V}
    routes_by_depot = {w: extract_routes_for_depot(w, V, E, z, d, delta) for w in open_depots}
    solution = {
        "model_name": "MTZ Gurobi V2",
        "V": V,
        "coords": coords,
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
        "opening_cost": sum(l[w] for w in open_depots),
        "routing_cost": sum(route["distance"] for routes in routes_by_depot.values() for route in routes),
        "vehicles_used": sum(len(routes) for routes in routes_by_depot.values()),
        "objective_value": float(model.ObjVal),
    }
    solution["total_cost"] = solution["opening_cost"] + solution["routing_cost"]
    solution["validation_ok"], solution["validation_messages"] = validate_solution(solution)
    return solution


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


def solve_mtz_lrp(data_path=DATA_PATH, max_nodes=MAX_NODES_FOR_MTZ, print_output=True):
    start = time.perf_counter()
    V, E, coords, delta, d, l, c, beta, m, p = load_lrp_data(data_path, max_nodes=max_nodes)
    try:
        model, x, z, y = build_mtz_model(V, E, delta, d, l, beta, m, p)
    except RuntimeError as exc:
        result = {
            "model_name": "MTZ Gurobi V2",
            "data_path": data_path,
            "status": "GUROBI_UNAVAILABLE",
            "nodes": len(V),
            "beta": beta,
            "m": m,
            "p": p,
            "validation_ok": False,
            "runtime": time.perf_counter() - start,
            "message": str(exc),
        }
        if print_output:
            print(f"MTZ Gurobi V2 unavailable: {exc}")
        return result
    model.optimize()

    import gurobipy as gp
    from gurobipy import GRB

    status_name = {GRB.OPTIMAL: "OPTIMAL", GRB.TIME_LIMIT: "TIME_LIMIT", GRB.INFEASIBLE: "INFEASIBLE"}.get(model.Status, str(model.Status))
    if model.SolCount == 0:
        result = {"model_name": "MTZ Gurobi V2", "status": status_name, "validation_ok": False, "runtime": time.perf_counter() - start}
        if print_output:
            print(f"MTZ Gurobi V2 status: {status_name}; no feasible incumbent.")
        return result

    solution = extract_solution(model, V, E, coords, delta, d, l, beta, m, p, x, z)
    solution["status"] = status_name
    solution["runtime"] = time.perf_counter() - start
    if print_output:
        print_solution(solution)
    return solution


def print_solution(solution):
    print("MTZ Gurobi V2 Solution")
    print("=" * 72)
    print(f"status        : {solution['status']}")
    print(f"nodes         : {len(solution['V'])}")
    print(f"beta, m, p    : {solution['beta']:g}, {solution['m']}, {solution['p']}")
    print(f"opened depots : {solution['open_depots']}")
    print(f"vehicles used : {solution['vehicles_used']}")
    print(f"opening cost  : {solution['opening_cost']:.2f}")
    print(f"routing cost  : {solution['routing_cost']:.2f}")
    print(f"total cost    : {solution['total_cost']:.2f}")
    print(f"objective     : {solution['objective_value']:.2f}")
    print(f"runtime       : {solution['runtime']:.4f}s")
    print(f"validation    : {'PASS' if solution['validation_ok'] else 'FAIL'}")
    if not solution["validation_ok"]:
        for message in solution["validation_messages"]:
            print(f"  - {message}")


if __name__ == "__main__":
    solve_mtz_lrp()
