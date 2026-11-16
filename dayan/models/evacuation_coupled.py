"""CPL001: explicit road evacuation, elderly mobility, information and bus coupling.

Roads/population can be real inputs. Response, flood and bus rules are declared
scenario assumptions, not a calibrated Wuhan prediction or actual GPS tracks.
"""
from __future__ import annotations

import copy
import heapq
import math
import numpy as np

from ..datasets import load


class RoadEvacuationModel:
    model_id = "CPL001"
    clock_type = "fixed_step"
    time_unit = "minute"
    requires_external = True  # Do not run catalog probes without explicit dataset IDs.
    declared_observables = ["n_agents", "represented_population", "evacuated", "remaining", "elderly_remaining", "bus_queue", "on_bus", "rumor_mean", "exposure", "evacuated_fraction"]
    implementation_note = ("真实输入路网上的加权抽样主体机制实验；时间分钟、坐标米、公交容量为人/车次。每个抽样主体不可拆分，车次装载会留下不足一个主体权重的余量。安置点/接驳站位置、行为、积水影响和公交调度是显式情景假设，未做武汉实证校准；轨迹是模型计算轨迹。")

    def __init__(self, roads_dataset_id="", population_dataset_id="", n=200,
                 elderly_fraction=.2, elderly_speed_factor=.5, walk_speed=72.,
                 initial_rumor_fraction=.3, rumor_rate=.4, rumor_effect=.8,
                 information_rate=.05, flood_severity=.5, preparation_delay=1.,
                 bus_capacity=20, bus_count=2, bus_speed=300.):
        if any(isinstance(v, bool) or int(v) != v for v in (n, bus_capacity, bus_count)):
            raise ValueError("主体数、公交容量和车辆数必须为整数")
        if not 1 <= n <= 2000 or not 0 <= bus_capacity <= 500 or not 1 <= bus_count <= 20:
            raise ValueError("主体1–2000、容量0–500、车辆1–20")
        for v in (elderly_fraction, elderly_speed_factor, initial_rumor_fraction, rumor_effect, flood_severity):
            if not math.isfinite(v) or not 0 <= v <= 1:
                raise ValueError("比例与减速因子须在0–1内")
        if any(not math.isfinite(v) or v < 0 for v in (rumor_rate, information_rate, preparation_delay)) or walk_speed <= 0 or bus_speed <= 0:
            raise ValueError("速率/延迟须非负，速度须为正")
        self.roads_dataset_id, self.population_dataset_id = roads_dataset_id, population_dataset_id
        self.n, self.elderly_fraction, self.elderly_speed_factor = int(n), elderly_fraction, elderly_speed_factor
        self.walk_speed, self.initial_rumor_fraction = walk_speed, initial_rumor_fraction
        self.rumor_rate, self.rumor_effect, self.information_rate = rumor_rate, rumor_effect, information_rate
        self.flood_severity, self.preparation_delay = flood_severity, preparation_delay
        self.bus_capacity, self.bus_count, self.bus_speed = int(bus_capacity), int(bus_count), bus_speed

    def _load_roads(self):
        if not self.roads_dataset_id:
            raise ValueError("CPL001必须先采集/导入道路数据，并指定roads_dataset_id；不会生成假路网替代")
        record = load(self.roads_dataset_id)
        if record["format"] == "osm":
            lines = [[(p["lon"], p["lat"]) for p in way["geometry"]] for way in record["data"]["elements"]
                     if way.get("type") == "way" and way.get("tags", {}).get("highway") and way.get("geometry")]
        elif record["format"] == "geojson":
            lines = []
            for f in record["data"]["features"]:
                geom = f.get("geometry") or {}
                if geom.get("type") == "LineString":
                    lines.append(geom["coordinates"])
                elif geom.get("type") == "MultiLineString":
                    lines += geom["coordinates"]
        else:
            raise ValueError("道路输入须为OSM JSON或WGS84 GeoJSON线要素")
        coordinates = sorted({(round(float(p[0]), 7), round(float(p[1]), 7)) for line in lines for p in line})
        if not 2 <= len(coordinates) <= 10000 or any(not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in coordinates):
            raise ValueError("道路坐标非法、为空或超过10000节点；要求WGS84经纬度")
        lon0 = sum(p[0] for p in coordinates)/len(coordinates)
        lat0 = sum(p[1] for p in coordinates)/len(coordinates)
        self.origin = (lon0, lat0)
        self.points = [self._project(*p) for p in coordinates]
        lookup = {p: i for i, p in enumerate(coordinates)}
        self.adjacency = {i: {} for i in range(len(coordinates))}
        for line in lines:
            ids = [lookup[(round(float(p[0]), 7), round(float(p[1]), 7))] for p in line]
            for a, b in zip(ids, ids[1:]):
                length = math.dist(self.points[a], self.points[b])
                if a != b and length > 1e-6:
                    self.adjacency[a][b] = self.adjacency[b][a] = length
        remaining, groups = set(self.adjacency), []
        while remaining:
            stack, component = [remaining.pop()], set()
            while stack:
                node = stack.pop()
                component.add(node)
                for other in self.adjacency[node]:
                    if other in remaining:
                        remaining.remove(other)
                        stack.append(other)
            groups.append(component)
        self.nodes = sorted(max(groups, key=len))
        if len(self.nodes) < 2:
            raise ValueError("道路数据没有可通行连通边")
        self.pickup = min(self.nodes, key=lambda i: self.points[i][0])
        self.shelter = max(self.nodes, key=lambda i: self.points[i][0])
        self.routes_pickup = self._routes(self.pickup)
        self.routes_shelter = self._routes(self.shelter)
        self.input_datasets = [{k: record[k] for k in ("dataset_id", "source", "sha256", "license", "role")}]
        self.events = [{"sim_t": 0., "etype": "assumption", "message": f"使用最大连通分量{len(self.nodes)}/{len(self.points)}节点；最西/最东路网节点假设为接驳站/安置点，非已验证设施位置"}]

    def _project(self, lon, lat):
        lon0, lat0 = self.origin
        return ((lon-lon0)*111320*math.cos(math.radians(lat0)), (lat-lat0)*111320)

    def _routes(self, target):
        distance, next_node, queue = {target: 0.}, {}, [(0., target)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost != distance[node]:
                continue
            for other, length in self.adjacency[node].items():
                if cost+length < distance.get(other, float("inf")):
                    distance[other], next_node[other] = cost+length, node
                    heapq.heappush(queue, (cost+length, other))
        return next_node

    def _path(self, source, target, table):
        route = [source]
        while route[-1] != target:
            route.append(table[route[-1]])
        return route

    def _route_entity(self, entity, route):
        entity["route"], entity["route_index"] = route, 1

    def _move(self, entity, distance):
        route = entity["route"]
        while entity["route_index"] < len(route):
            x, y = self.points[route[entity["route_index"]]]
            remaining = math.hypot(x-entity["x"], y-entity["y"])
            if distance+1e-9 < remaining:
                entity["x"] += (x-entity["x"])/remaining*distance
                entity["y"] += (y-entity["y"])/remaining*distance
                return False
            entity["x"], entity["y"] = x, y
            distance -= remaining
            entity["route_index"] += 1
        return True

    def initialize(self, context=None, parameters=None, population=None, topology=None, rng=None):
        self.rng = rng if rng is not None else np.random.default_rng(0)
        self._load_roads()
        origins, weights, elderly = self.nodes, np.ones(len(self.nodes)), [self.elderly_fraction]*len(self.nodes)
        self.represented_population = float(self.n)
        if self.population_dataset_id:
            record = load(self.population_dataset_id)
            rows = record["data"]
            if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) and {"lon", "lat", "population"} <= row.keys() for row in rows):
                raise ValueError("人口数据须为CSV/JSON记录列表，字段lon、lat、population，可选elderly_fraction")
            origins, weights, elderly = [], [], []
            for row in rows:
                point = self._project(float(row["lon"]), float(row["lat"]))
                nearest = min(self.nodes, key=lambda i: math.dist(point, self.points[i]))
                count, elder = float(row["population"]), float(row.get("elderly_fraction", self.elderly_fraction))
                if not math.isfinite(count) or count <= 0 or not 0 <= elder <= 1 or math.dist(point, self.points[nearest]) > 2000:
                    raise ValueError("人口值/老年比例非法或人口点距离有效路网超过2km")
                origins.append(nearest)
                weights.append(count)
                elderly.append(elder)
            self.represented_population = float(sum(weights))
            self.input_datasets.append({k: record[k] for k in ("dataset_id", "source", "sha256", "license", "role")})
        else:
            self.events.append({"sim_t": 0., "etype": "assumption", "message": "未绑定真实人口；n个主体及年龄比例为明确情景假设，不是地区人口观测"})
        probabilities = np.asarray(weights, dtype=float)/sum(weights)
        self.agents = []
        if 0 < self.bus_capacity < self.represented_population/self.n:
            raise ValueError("每个抽样主体权重大于单车人数容量，无法保真装载；须提高n或缩小研究人口范围，不会把一组人假装成一名乘客")
        for i in range(self.n):
            row = int(self.rng.choice(len(origins), p=probabilities))
            source = origins[row]
            elder = bool(self.rng.random() < elderly[row])
            bus = elder or self.rng.random() < .3
            target = self.pickup if bus else self.shelter
            self.agents.append({"id": i, "x": self.points[source][0], "y": self.points[source][1],
                                "elderly": elder, "belief": float(self.rng.random() < self.initial_rumor_fraction),
                                "mode": "preparing", "use_bus": bus, "weight": self.represented_population/self.n,
                                "exposure": 0., "route": self._path(source, target, self.routes_pickup if bus else self.routes_shelter), "route_index": 1})
        self.bus_route = self._path(self.pickup, self.shelter, self.routes_shelter)
        self.buses = [{"id": i, "x": self.points[self.pickup][0], "y": self.points[self.pickup][1], "phase": "pickup", "passengers": [], "route": [], "route_index": 0} for i in range(self.bus_count)]
        self.t = 0.

    def step(self, t, dt):
        mean_belief = float(np.mean([a["belief"] for a in self.agents]))
        for a in self.agents:
            if a["mode"] == "evacuated":
                continue
            a["belief"] = min(1., max(0., a["belief"] + dt*(self.rumor_rate*mean_belief*(1-a["belief"])-self.information_rate*a["belief"])))
            a["exposure"] += dt*self.flood_severity
            motivation = max(.05, .8+.2*self.flood_severity-self.rumor_effect*a["belief"])
            if a["mode"] == "preparing" and t+dt >= self.preparation_delay*(1+.5*a["elderly"])/motivation:
                a["mode"] = "walking"
            if a["mode"] == "walking":
                speed = self.walk_speed*(self.elderly_speed_factor if a["elderly"] else 1)*(1-.4*self.flood_severity)
                if self._move(a, speed*dt):
                    a["mode"] = "queue" if a["use_bus"] else "evacuated"
        for bus in self.buses:
            if bus["phase"] == "pickup":
                waiting = [a for a in self.agents if a["mode"] == "queue"]
                if self.bus_capacity and waiting:
                    seats = float(self.bus_capacity)
                    bus["passengers"] = []
                    for agent in waiting:
                        if agent["weight"] <= seats + 1e-9:
                            bus["passengers"].append(agent["id"])
                            seats -= agent["weight"]
                    if not bus["passengers"]:
                        continue
                    for aid in bus["passengers"]:
                        self.agents[aid]["mode"] = "on_bus"
                    self._route_entity(bus, self.bus_route)
                    bus["phase"] = "outbound"
                    self.events.append({"sim_t": round(t, 9), "etype": "bus_departure", "bus_id": bus["id"], "boarded_agents": len(bus["passengers"]), "boarded_people": self.bus_capacity-seats, "capacity": self.bus_capacity})
            if bus["phase"] in ("outbound", "return"):
                complete = self._move(bus, self.bus_speed*dt*(1-.3*self.flood_severity))
                for aid in bus["passengers"]:
                    self.agents[aid]["x"], self.agents[aid]["y"] = bus["x"], bus["y"]
                if complete:
                    if bus["phase"] == "outbound":
                        for aid in bus["passengers"]:
                            self.agents[aid]["mode"] = "evacuated"
                        self.events.append({"sim_t": round(t+dt, 9), "etype": "bus_arrival", "bus_id": bus["id"], "evacuated": len(bus["passengers"])})
                        bus["passengers"] = []
                        self._route_entity(bus, list(reversed(self.bus_route)))
                        bus["phase"] = "return"
                    else:
                        bus["phase"] = "pickup"
        self.t = float(t+dt)

    def observe(self):
        remaining = [a for a in self.agents if a["mode"] != "evacuated"]
        return {"n_agents": self.n, "represented_population": self.represented_population,
                "evacuated": self.n-len(remaining), "remaining": len(remaining),
                "elderly_remaining": sum(a["elderly"] for a in remaining),
                "bus_queue": sum(a["mode"] == "queue" for a in self.agents),
                "on_bus": sum(a["mode"] == "on_bus" for a in self.agents),
                "rumor_mean": float(np.mean([a["belief"] for a in self.agents])),
                "exposure": float(sum(a["exposure"]*a["weight"] for a in self.agents)),
                "evacuated_fraction": 1-len(remaining)/self.n}

    def state_frame(self):
        xs, ys = zip(*(self.points[i] for i in self.nodes))
        segments = [[list(self.points[a]), list(self.points[b])] for a in self.nodes for b in self.adjacency[a] if a < b]
        return {"entities": [{"id": a["id"], "type": "pedestrian", "x": a["x"], "y": a["y"], "state": a["mode"], "elderly": a["elderly"], "weight": a["weight"], "rumor": a["belief"]} for a in self.agents] +
                            [{"id": "bus-"+str(b["id"]), "type": "bus", "x": b["x"], "y": b["y"], "state": b["phase"], "passengers": len(b["passengers"])} for b in self.buses],
                "aggregates": self.observe(), "relations": [],
                "space": {"bounds": [min(xs), min(ys), max(xs), max(ys)], "unit": "m", "time_unit": "minute"},
                "facilities": [{"id": "roads", "type": "road_network", "segments": segments, "source_dataset": self.roads_dataset_id},
                               {"id": "shelter", "type": "assumed_shelter", "x": self.points[self.shelter][0], "y": self.points[self.shelter][1], "assumed": True}]}

    def snapshot(self):
        import inspect
        keys = [k for k in inspect.signature(self.__init__).parameters if k != "self"]
        return {"parameters": {k: getattr(self, k) for k in keys}, "agents": self.agents, "buses": self.buses,
                "events": self.events, "t": self.t, "rng_state": self.rng.bit_generator.state}

    def restore(self, snapshot):
        self.__init__(**snapshot["parameters"])
        self.initialize()
        for key in ("agents", "buses", "events", "t"):
            setattr(self, key, copy.deepcopy(snapshot[key]))
        self.rng.bit_generator.state = snapshot["rng_state"]

    def validate_state(self):
        return []
