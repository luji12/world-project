import json
import os
import networkx as nx
import config

_g = None


def get_graph() -> nx.DiGraph:
    global _g
    if _g is None:
        _g = nx.DiGraph()
        graph_file = os.path.join(config.STATE_DIR, "graph.json")
        if os.path.exists(graph_file):
            try:
                with open(graph_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for node in data.get("nodes", []):
                    _g.add_node(node["id"], **node.get("props", {}), type=node.get("type"))
                for edge in data.get("edges", []):
                    _g.add_edge(edge["source"], edge["target"], type=edge["type"])
            except Exception:
                pass
    return _g


def save_graph():
    g = get_graph()
    nodes = [
        {"id": n, "type": g.nodes[n].get("type", "unknown"),
         "props": {k: v for k, v in g.nodes[n].items() if k != "type"}}
        for n in g.nodes()
    ]
    edges = [
        {"source": u, "target": v, "type": d.get("type", "unknown")}
        for u, v, d in g.edges(data=True)
    ]
    graph_file = os.path.join(config.STATE_DIR, "graph.json")
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, ensure_ascii=False, indent=2)


def get_related(node_id: str, relation_types: list = None, depth: int = 2) -> list:
    g = get_graph()
    if node_id not in g:
        return []
    result = []
    try:
        for d in range(1, depth + 1):
            for target in nx.descendants_at_distance(g, node_id, d):
                edge_data = g.get_edge_data(node_id, target)
                if relation_types is None or (edge_data and edge_data.get("type") in relation_types):
                    result.append({
                        "id": target,
                        "type": g.nodes[target].get("type"),
                        "relation": edge_data.get("type") if edge_data else None,
                    })
    except Exception:
        pass
    return result


def get_entities_in_region(region_id: str) -> list:
    g = get_graph()
    result = []
    for node in g.nodes():
        if g.has_edge(node, region_id):
            edge_data = g.get_edge_data(node, region_id)
            if edge_data and edge_data.get("type") == "located_in":
                result.append({"id": node, "type": g.nodes[node].get("type")})
    return result


def add_entity(entity_id: str, entity_type: str, props: dict = None):
    g = get_graph()
    g.add_node(entity_id, type=entity_type, **(props or {}))
    save_graph()


def add_relation(source: str, target: str, rel_type: str):
    g = get_graph()
    g.add_edge(source, target, type=rel_type)
    save_graph()


def build_initial_graph():
    from state import read_json
    from world_shape import regions_of
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        return
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
    except Exception:
        chars = {"characters": []}

    g = get_graph()

    for region in regions_of(world):
        region_id = region.get("id") or region.get("name")
        if not region_id:
            continue
        add_entity(region_id, "location", {"name": region.get("name", ""), "population": region.get("population", 0)})

    for faction in world.get("factions", []):
        if not isinstance(faction, dict):
            continue
        fid = faction.get("id", "")
        if fid:
            add_entity(fid, "faction", {"name": faction.get("name", ""), "power": faction.get("power_level", 0)})

    for c in chars.get("characters", []):
        if not isinstance(c, dict):
            continue
        cid = c.get("id", "")
        if cid:
            add_entity(cid, "character", {"name": c.get("name", ""), "realm": c.get("realm", "凡人")})

    save_graph()
