"""Fictional pedestrian safety exercise with an incident and an assistance response."""
from __future__ import annotations

import math
import numpy as np

from .pedestrian import ContactEvacModel, R_PED


class CrowdResponseModel(ContactEvacModel):
    """虚拟步道演练，计算预定倒地下的局部降速、人群移动与离场。"""

    model_id = "NET121"
    time_unit = "模型秒"
    primary_metric = "evacuated"
    output_units = {
        "evacuated": "人", "alive": "人", "min_separation": "m",
        "moving": "人", "waiting": "人", "fallen": "人", "assisted": "人",
        "aid_completed": "人", "local_conflicts": "对", "yielding": "人",
    }
    delivery_events = {
        "drill_fall": ("fallen", "fallen"),
        "aid_started": ("assisted", "seated"),
        "aid_completed": ("aid_completed", None),
    }

    def __init__(self, n=72, bounds=(0, 0, 22, 16), exit_half=2.0, v_des=1.2,
                 dt=0.05, exercise_time=3.0, response_delay=6.0, assistance_time=4.0):
        if not 2 <= n <= 256:
            raise ValueError("景区演练支持2至256个行人")
        if len(bounds) != 4 or any(not math.isfinite(x) for x in bounds):
            raise ValueError("场地边界须给出四个有限坐标")
        x0, y0, x1, y1 = bounds
        if x1-x0 < 4 or y1-y0 < 4 or not 0 < exit_half < (x1-x0)/2:
            raise ValueError("场地尺寸与通道开口不相容")
        if not 0 < dt <= .2 or not .1 <= v_des <= 3:
            raise ValueError("演练步长须在(0, 0.2]模型秒，步速须在[0.1, 3] m/s")
        if exercise_time < 0 or response_delay <= 0 or assistance_time <= 0:
            raise ValueError("演练时点非负，响应和协助需要正时长")
        super().__init__(n, tuple(bounds), exit_half, v_des, dt)
        self.dt = dt
        self.exercise_time = exercise_time
        self.response_delay = response_delay
        self.assistance_time = assistance_time

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        x0, y0, x1, y1 = self.bounds
        lower, upper = [x0 + 1, y0 + 1], [x1 - 1, y1 - 2]
        for i in range(1, self.n):
            # Keep the initial draw when feasible. Redraw only against already placed agents.
            for _ in range(1024):
                if np.all(np.linalg.norm(self.pos[:i] - self.pos[i], axis=1) >= 2 * R_PED):
                    break
                self.pos[i] = rng.uniform(lower, upper)
            else:
                raise ValueError(f"第 {i+1} 位行人在布点预算内无合法初始位置。请扩大有效区域或明确降低人数。")
        self.events = []
        self.incident_actor = -1
        self.incident_at = None
        self.aid_at = None
        self.aid_completed = 0
        self.yielding = 0
        self.aid_state = ""

    def _event(self, name, at, label):
        i = self.incident_actor
        self.events.append({"etype": name, "sim_t": round(at, 9), "entity_id": f"ped_{i}",
                            "x": float(self.pos[i, 0]), "y": float(self.pos[i, 1]), "label": label})

    def _advance_response(self, t, active):
        if self.incident_at is None and t + 1e-9 >= self.exercise_time and active.any():
            self.incident_actor = int(self.rng.choice(np.flatnonzero(active)))
            self.incident_at = t
            self.aid_state = "fallen"
            self._event("drill_fall", t, "演练倒地事件")
        elif self.aid_state == "fallen" and t + 1e-9 >= self.incident_at + self.response_delay:
            self.aid_state = "assisted"
            self.aid_at = t
            self._event("aid_started", t, "当事人转入受助状态")
        elif self.aid_state == "assisted" and t + 1e-9 >= self.aid_at + self.assistance_time:
            self.aid_state = ""
            self.aid_completed = 1
            self._event("aid_completed", t, "恢复行动")

    def step(self, t, dt):
        active = self.exited_at < 0
        if not active.any():
            self.yielding = 0
            return
        self._advance_response(t + dt, active)
        mobile = active.copy()
        scale = np.ones(self.n)
        if self.aid_state:
            mobile[self.incident_actor] = False
            distance = np.linalg.norm(self.pos - self.pos[self.incident_actor], axis=1)
            scale[mobile] = np.clip(distance[mobile] / 1.5, .25, 1.0)
        direction, _ = self._directions()
        drive = (self.v_des * scale[:, None] * direction - self.vel) / .5
        acceleration = drive + self._step_forces(self.rng)
        self.vel[mobile] += dt * acceleration[mobile]
        self.vel[~mobile] = 0
        speeds = np.linalg.norm(self.vel, axis=1)
        fast = speeds > self.v_des * 1.6
        self.vel[fast] *= (self.v_des * 1.6 / speeds[fast])[:, None]
        self.pos[mobile] += dt * self.vel[mobile]
        x0, y0, x1, y1 = self.bounds
        self.pos[mobile] = np.clip(self.pos[mobile], [x0, y0], [x1, y1])
        at_exit = mobile & (self.pos[:, 1] >= y1 - .4) & (
            np.abs(self.pos[:, 0] - (x0 + x1)/2) <= self.exit_half)
        self.exited_at[at_exit] = round((t + dt) / self.dt)
        self.pos[at_exit] = -100.
        self.vel[at_exit] = 0
        self.yielding = int(np.count_nonzero(mobile & ~at_exit & (scale < 1)))
        self.evacuated = int(np.count_nonzero(self.exited_at >= 0))

    def observe(self):
        values = super().observe()
        active = self.exited_at < 0
        mobile = active.copy()
        if self.aid_state:
            mobile[self.incident_actor] = False
        moving = int(np.count_nonzero(mobile & (np.linalg.norm(self.vel, axis=1) > .04)))
        participants = self.pos[active]
        a, b = np.triu_indices(len(participants), k=1)
        distances = np.linalg.norm(participants[a] - participants[b], axis=1)
        values.update({
            "moving": moving, "waiting": int(np.count_nonzero(mobile))-moving,
            "fallen": int(self.aid_state == "fallen"), "assisted": int(self.aid_state == "assisted"),
            "aid_completed": int(self.aid_completed), "yielding": int(self.yielding),
            "local_conflicts": int(np.count_nonzero(distances < 2*R_PED)),
        })
        return values

    def state_frame(self):
        frame = super().state_frame()
        for i, entity in enumerate(frame["entities"]):
            if entity["state"] == "exited":
                continue
            if self.aid_state and i == self.incident_actor:
                entity["state"] = "fallen" if self.aid_state == "fallen" else "seated"
            else:
                entity["state"] = "walking" if entity["speed"] > .04 else "waiting"
        frame["facilities"][0]["label"] = "景区步道演练区"
        frame["facilities"][0]["role"] = "modeled"
        frame["facilities"][1]["label"] = "引导离场口"
        frame["space"]["time_unit"] = self.time_unit
        return frame
