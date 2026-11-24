"""Tkinter beam analysis application for educational, preliminary screening."""

from __future__ import annotations

import csv
import json
import math
import textwrap
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Polygon

STEEL_E_KSI = 29_000.0
CSV_SAMPLE_INTERVALS = 500
FILE_FORMAT = "beam-designer"
FILE_VERSION = 1


@dataclass(frozen=True)
class Section:
    name: str
    ix_in4: float
    sx_in3: float


SECTIONS = (
    Section("W8x10", 30.8, 7.81),
    Section("W10x12", 53.8, 10.9),
    Section("W12x26", 204.0, 33.4),
    Section("W14x22", 199.0, 29.0),
    Section("W16x26", 301.0, 38.4),
    Section("W18x35", 510.0, 57.6),
)
SECTIONS_BY_NAME = {section.name: section for section in SECTIONS}


@dataclass(frozen=True)
class PointLoad:
    magnitude_kip: float
    position_ft: float
    direction: str = "down"


@dataclass(frozen=True)
class UniformLoad:
    magnitude_kip_per_ft: float
    start_ft: float
    end_ft: float
    direction: str = "down"


@dataclass(frozen=True)
class BeamInput:
    support: str
    span_ft: float
    section_name: str
    allowable_bending_stress_ksi: float | None = None
    point_loads: tuple[PointLoad, ...] = ()
    uniform_loads: tuple[UniformLoad, ...] = ()


@dataclass(frozen=True)
class AnalysisResult:
    reaction_a_kip: float
    reaction_b_kip: float
    fixed_end_moment_kip_in: float
    max_shear_kip: float
    max_moment_kip_in: float
    max_deflection_in: float
    deflection_limit_in: float
    max_bending_stress_ksi: float
    # Each row is x (ft), shear (kip), moment (kip-in), deflection (in).
    samples: tuple[tuple[float, float, float, float], ...]


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def validate_design(design: BeamInput) -> None:
    """Raise ValueError when a beam input is outside the documented scope."""
    if not isinstance(design.support, str) or design.support not in {"simple", "cantilever"}:
        raise ValueError("Choose simply supported or cantilever support.")
    span_ft = _finite_number(design.span_ft, "Span")
    if span_ft <= 0:
        raise ValueError("Span must be greater than zero.")
    if not math.isfinite(span_ft * 12.0):
        raise ValueError("Span is outside the supported numerical range.")
    if not isinstance(design.section_name, str) or design.section_name not in SECTIONS_BY_NAME:
        raise ValueError("Choose a valid steel W-shape.")
    allowable = design.allowable_bending_stress_ksi
    if allowable is not None:
        allowable = _finite_number(allowable, "Allowable bending stress")
        if allowable <= 0:
            raise ValueError("Allowable bending stress must be greater than zero.")

    for index, load in enumerate(design.point_loads, start=1):
        magnitude = _finite_number(load.magnitude_kip, f"Point load {index} magnitude")
        position = _finite_number(load.position_ft, f"Point load {index} position")
        if magnitude < 0:
            raise ValueError(f"Point load {index} magnitude cannot be negative.")
        if not 0 <= position <= span_ft:
            raise ValueError(f"Point load {index} must be located within the beam span.")
        if not isinstance(load.direction, str) or load.direction not in {"down", "up"}:
            raise ValueError(f"Point load {index} has an invalid direction.")

    for index, load in enumerate(design.uniform_loads, start=1):
        magnitude = _finite_number(load.magnitude_kip_per_ft, f"Uniform load {index} magnitude")
        start = _finite_number(load.start_ft, f"Uniform load {index} start")
        end = _finite_number(load.end_ft, f"Uniform load {index} end")
        if magnitude < 0:
            raise ValueError(f"Uniform load {index} magnitude cannot be negative.")
        if not 0 <= start < end <= span_ft:
            raise ValueError(f"Uniform load {index} must satisfy 0 <= start < end <= span.")
        if not isinstance(load.direction, str) or load.direction not in {"down", "up"}:
            raise ValueError(f"Uniform load {index} has an invalid direction.")


def analyze_beam(design: BeamInput) -> AnalysisResult:
    """Compute reactions and elastic response using singularity functions."""
    validate_design(design)
    section = SECTIONS_BY_NAME[design.section_name]
    length_in = design.span_ft * 12.0
    point_loads = tuple(
        (load.magnitude_kip * (1 if load.direction == "down" else -1), load.position_ft * 12.0)
        for load in design.point_loads
    )
    uniform_loads = tuple(
        (
            load.magnitude_kip_per_ft * (1 if load.direction == "down" else -1) / 12.0,
            load.start_ft * 12.0,
            load.end_ft * 12.0,
        )
        for load in design.uniform_loads
    )

    total_point_load = sum(load for load, _ in point_loads)
    total_uniform_load = sum(load * (end - start) for load, start, end in uniform_loads)
    total_load = total_point_load + total_uniform_load
    applied_moment_at_a = sum(load * position for load, position in point_loads) + sum(
        load * (end - start) * (start + end) / 2.0
        for load, start, end in uniform_loads
    )

    if design.support == "simple":
        reaction_b = applied_moment_at_a / length_in
        reaction_a = total_load - reaction_b
        fixed_moment = 0.0
    else:
        reaction_a = total_load
        reaction_b = 0.0
        fixed_moment = -applied_moment_at_a

    def positive_part(x: float, start: float) -> float:
        return max(0.0, x - start)

    def shear(x: float, side: str = "right") -> float:
        value = reaction_a
        for load, position in point_loads:
            if x > position or (side == "right" and math.isclose(x, position, abs_tol=1e-10)):
                value -= load
        for load, start, end in uniform_loads:
            value -= load * max(0.0, min(x, end) - start)
        return value

    def moment(x: float) -> float:
        value = fixed_moment + reaction_a * x
        for load, position in point_loads:
            value -= load * positive_part(x, position)
        for load, start, end in uniform_loads:
            value -= load / 2.0 * (
                positive_part(x, start) ** 2 - positive_part(x, end) ** 2
            )
        return value

    def moment_integral(x: float) -> float:
        value = fixed_moment * x + reaction_a * x**2 / 2.0
        for load, position in point_loads:
            value -= load * positive_part(x, position) ** 2 / 2.0
        for load, start, end in uniform_loads:
            value -= load / 6.0 * (
                positive_part(x, start) ** 3 - positive_part(x, end) ** 3
            )
        return value

    def moment_double_integral(x: float) -> float:
        value = fixed_moment * x**2 / 2.0 + reaction_a * x**3 / 6.0
        for load, position in point_loads:
            value -= load * positive_part(x, position) ** 3 / 6.0
        for load, start, end in uniform_loads:
            value -= load / 24.0 * (
                positive_part(x, start) ** 4 - positive_part(x, end) ** 4
            )
        return value

    elastic_rigidity = STEEL_E_KSI * section.ix_in4
    slope_constant = (
        moment_double_integral(length_in) / (elastic_rigidity * length_in)
        if design.support == "simple"
        else 0.0
    )

    def rotation(x: float) -> float:
        return -moment_integral(x) / elastic_rigidity + slope_constant

    def deflection(x: float) -> float:
        return -moment_double_integral(x) / elastic_rigidity + slope_constant * x

    breaks = sorted(
        {
            0.0,
            length_in,
            *(position for _, position in point_loads),
            *(position for _, start, end in uniform_loads for position in (start, end)),
        }
    )

    moment_candidates = list(breaks)
    shear_candidates = [reaction_a]
    for x in breaks:
        shear_candidates.append(shear(x, "left"))
        shear_candidates.append(shear(x, "right"))
    for start, end in zip(breaks, breaks[1:]):
        if end - start <= 1e-12:
            continue
        left = start + (end - start) * 1e-9
        right = end - (end - start) * 1e-9
        v_left = shear(left, "right")
        v_right = shear(right, "left")
        if abs(v_left) <= 1e-12:
            moment_candidates.append(left)
        if v_left * v_right < 0:
            moment_candidates.append(
                left + (right - left) * abs(v_left) / (abs(v_left) + abs(v_right))
            )

    max_shear = max(shear_candidates, key=abs, default=0.0)
    max_moment = max((moment(x) for x in moment_candidates), key=abs, default=0.0)

    def rotation_roots(start: float, end: float) -> list[float]:
        roots: list[float] = []
        grid = np.linspace(start, end, 33)
        previous_x = float(grid[0])
        previous_value = rotation(previous_x)
        for current in grid[1:]:
            current_x = float(current)
            current_value = rotation(current_x)
            if abs(previous_value) <= 1e-12:
                roots.append(previous_x)
            if previous_value * current_value < 0:
                low, high = previous_x, current_x
                low_value = previous_value
                for _ in range(60):
                    middle = (low + high) / 2.0
                    middle_value = rotation(middle)
                    if low_value * middle_value <= 0:
                        high = middle
                    else:
                        low, low_value = middle, middle_value
                roots.append((low + high) / 2.0)
            previous_x = current_x
            previous_value = current_value
        if abs(previous_value) <= 1e-12:
            roots.append(previous_x)
        return roots

    deflection_candidates = [0.0, length_in]
    for start, end in zip(breaks, breaks[1:]):
        deflection_candidates.extend(rotation_roots(start, end))
    max_deflection = max(
        (deflection(x) for x in deflection_candidates), key=abs, default=0.0
    )

    sample_xs = set(float(x) for x in np.linspace(0.0, length_in, CSV_SAMPLE_INTERVALS + 1))
    sample_xs.update(breaks)
    rows: list[tuple[float, float, float, float]] = []
    point_positions = {position for _, position in point_loads}
    for x in sorted(sample_xs):
        if x in point_positions and 0.0 < x < length_in:
            rows.append((x / 12.0, shear(x, "left"), moment(x), deflection(x)))
            rows.append((x / 12.0, shear(x, "right"), moment(x), deflection(x)))
        else:
            side = "left" if math.isclose(x, length_in, abs_tol=1e-10) else "right"
            rows.append((x / 12.0, shear(x, side), moment(x), deflection(x)))

    result_values = (
        reaction_a,
        reaction_b,
        fixed_moment,
        max_shear,
        max_moment,
        max_deflection,
        length_in / 360.0,
        abs(max_moment) / section.sx_in3,
        *(value for row in rows for value in row),
    )
    if any(not math.isfinite(value) for value in result_values):
        raise ValueError("These inputs exceed the supported numerical range.")

    return AnalysisResult(
        reaction_a_kip=reaction_a,
        reaction_b_kip=reaction_b,
        fixed_end_moment_kip_in=fixed_moment,
        max_shear_kip=max_shear,
        max_moment_kip_in=max_moment,
        max_deflection_in=max_deflection,
        deflection_limit_in=length_in / 360.0,
        max_bending_stress_ksi=abs(max_moment) / section.sx_in3,
        samples=tuple(rows),
    )


def format_sig(value: float) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    return f"{value:.3g}"


def design_to_dict(design: BeamInput) -> dict[str, Any]:
    validate_design(design)
    return {
        "format": FILE_FORMAT,
        "version": FILE_VERSION,
        "support": design.support,
        "span_ft": design.span_ft,
        "section": design.section_name,
        "allowable_bending_stress_ksi": design.allowable_bending_stress_ksi,
        "point_loads": [
            {
                "magnitude_kip": load.magnitude_kip,
                "position_ft": load.position_ft,
                "direction": load.direction,
            }
            for load in design.point_loads
        ],
        "uniform_loads": [
            {
                "magnitude_kip_per_ft": load.magnitude_kip_per_ft,
                "start_ft": load.start_ft,
                "end_ft": load.end_ft,
                "direction": load.direction,
            }
            for load in design.uniform_loads
        ],
    }


def design_from_dict(data: object) -> BeamInput:
    if not isinstance(data, dict):
        raise ValueError("The design file must contain a JSON object.")
    version = data.get("version")
    if (
        data.get("format") != FILE_FORMAT
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != FILE_VERSION
    ):
        raise ValueError("This design file uses an unsupported format or version.")
    for field in ("support", "span_ft", "section", "point_loads", "uniform_loads"):
        if field not in data:
            raise ValueError(f"The design file is missing '{field}'.")
    if not isinstance(data["support"], str) or not isinstance(data["section"], str):
        raise ValueError("The support condition and section must be text values.")
    if not isinstance(data["point_loads"], list) or not isinstance(data["uniform_loads"], list):
        raise ValueError("The load lists must be JSON arrays.")

    allowable_value = data.get("allowable_bending_stress_ksi")
    allowable = (
        None
        if allowable_value is None
        else _finite_number(allowable_value, "Allowable bending stress")
    )
    point_loads: list[PointLoad] = []
    for index, item in enumerate(data["point_loads"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Point load {index} must be a JSON object.")
        point_loads.append(
            PointLoad(
                magnitude_kip=_finite_number(item.get("magnitude_kip"), f"Point load {index} magnitude"),
                position_ft=_finite_number(item.get("position_ft"), f"Point load {index} position"),
                direction=item.get("direction"),
            )
        )
    uniform_loads: list[UniformLoad] = []
    for index, item in enumerate(data["uniform_loads"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Uniform load {index} must be a JSON object.")
        uniform_loads.append(
            UniformLoad(
                magnitude_kip_per_ft=_finite_number(
                    item.get("magnitude_kip_per_ft"), f"Uniform load {index} magnitude"
                ),
                start_ft=_finite_number(item.get("start_ft"), f"Uniform load {index} start"),
                end_ft=_finite_number(item.get("end_ft"), f"Uniform load {index} end"),
                direction=item.get("direction"),
            )
        )

    design = BeamInput(
        support=data["support"],
        span_ft=_finite_number(data["span_ft"], "Span"),
        section_name=data["section"],
        allowable_bending_stress_ksi=allowable,
        point_loads=tuple(point_loads),
        uniform_loads=tuple(uniform_loads),
    )
    validate_design(design)
    return design


def save_design(path: str | Path, design: BeamInput) -> None:
    content = json.dumps(design_to_dict(design), indent=2, allow_nan=False) + "\n"
    Path(path).write_text(content, encoding="utf-8")


def open_design(path: str | Path) -> BeamInput:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"The design file is not valid JSON: {error.msg}.") from error
    return design_from_dict(data)


def export_results_csv(path: str | Path, design: BeamInput, result: AnalysisResult) -> None:
    with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(("beam_length_ft", "x_ft", "V_kip", "M_kip_ft", "deflection_in"))
        for x_ft, shear_kip, moment_kip_in, deflection_in in result.samples:
            writer.writerow(
                (
                    design.span_ft,
                    x_ft,
                    shear_kip,
                    moment_kip_in / 12.0,
                    deflection_in,
                )
            )


def _load_description(design: BeamInput) -> str:
    loads: list[str] = []
    for load in design.point_loads:
        direction = "down" if load.direction == "down" else "up"
        loads.append(
            f"{format_sig(load.magnitude_kip)} kip {direction} at {format_sig(load.position_ft)} ft"
        )
    for load in design.uniform_loads:
        direction = "down" if load.direction == "down" else "up"
        loads.append(
            f"{format_sig(load.magnitude_kip_per_ft)} kip/ft {direction} "
            f"from {format_sig(load.start_ft)} to {format_sig(load.end_ft)} ft"
        )
    return "; ".join(loads) if loads else "No applied loads"


def draw_analysis_plots(
    figure: Figure,
    design: BeamInput,
    result: AnalysisResult,
    *,
    pdf_layout: bool = False,
) -> None:
    figure.clear()
    if pdf_layout:
        axes = figure.subplots(4, 1)
        figure.subplots_adjust(left=0.09, right=0.97, top=0.67, bottom=0.06, hspace=0.75)
    else:
        axes = figure.subplots(4, 1, sharex=True)
        figure.subplots_adjust(left=0.10, right=0.98, top=0.98, bottom=0.07, hspace=0.68)
    beam_ax, shear_ax, moment_ax, deflection_ax = axes

    length = design.span_ft
    beam_ax.set_xlim(-length * 0.08, length * 1.08)
    beam_ax.set_ylim(-1.35, 1.65)
    beam_ax.axhline(0, xmin=0.08, xmax=0.92, color="#183c55", linewidth=5, zorder=2)
    beam_ax.axis("off")
    if design.support == "simple":
        for x in (0.0, length):
            beam_ax.add_patch(
                Polygon(
                    ((x, -0.07), (x - length * 0.025, -0.65), (x + length * 0.025, -0.65)),
                    closed=True,
                    facecolor="#e8eff3",
                    edgecolor="#183c55",
                    linewidth=1.2,
                )
            )
            beam_ax.plot((x - length * 0.035, x + length * 0.035), (-0.68, -0.68), color="#8398a7", lw=1)
    else:
        beam_ax.add_patch(
            Polygon(
                ((-length * 0.018, -0.55), (0, -0.55), (0, 0.55), (-length * 0.018, 0.55)),
                closed=True,
                facecolor="#e8eff3",
                edgecolor="#183c55",
                linewidth=1.2,
            )
        )
        for y in np.linspace(-0.5, 0.5, 6):
            beam_ax.plot((-length * 0.05, -length * 0.018), (y - 0.12, y), color="#8398a7", lw=0.8)
    beam_ax.annotate(
        f"L = {format_sig(length)} ft",
        xy=(length / 2, -0.78),
        ha="center",
        va="top",
        fontsize=8,
        color="#40566a",
    )

    for index, load in enumerate(design.point_loads, start=1):
        x = load.position_ft
        positive_down = load.direction == "down"
        start_y, end_y = (1.15, 0.12) if positive_down else (-1.12, -0.12)
        beam_ax.annotate(
            "",
            xy=(x, end_y),
            xytext=(x, start_y),
            arrowprops={"arrowstyle": "-|>", "color": "#c4573c", "lw": 1.3},
        )
        label_y = 1.22 if positive_down else -1.27
        beam_ax.text(
            x,
            label_y,
            f"P{index} {format_sig(load.magnitude_kip)} kip",
            ha="center",
            va="bottom" if positive_down else "top",
            fontsize=7,
            color="#8f402d",
        )

    for index, load in enumerate(design.uniform_loads, start=1):
        y = 0.95 if load.direction == "down" else -0.92
        arrow_end = 0.10 if load.direction == "down" else -0.10
        beam_ax.plot((load.start_ft, load.end_ft), (y, y), color="#c4573c", lw=1.1)
        arrow_count = max(2, min(12, round((load.end_ft - load.start_ft) / max(length / 12.0, 1e-9))))
        for x in np.linspace(load.start_ft, load.end_ft, arrow_count + 1):
            beam_ax.annotate(
                "",
                xy=(x, arrow_end),
                xytext=(x, y),
                arrowprops={"arrowstyle": "-|>", "color": "#c4573c", "lw": 0.8},
            )
        beam_ax.text(
            (load.start_ft + load.end_ft) / 2,
            y + (0.06 if load.direction == "down" else -0.06),
            f"w{index} {format_sig(load.magnitude_kip_per_ft)} kip/ft",
            ha="center",
            va="bottom" if load.direction == "down" else "top",
            fontsize=7,
            color="#8f402d",
        )
    beam_ax.set_title("Beam and applied loads", loc="left", fontsize=9, color="#173c55", pad=4)

    x_values = [sample[0] for sample in result.samples]
    shear_values = [sample[1] for sample in result.samples]
    moment_values = [sample[2] / 12.0 for sample in result.samples]
    deflection_values = [sample[3] for sample in result.samples]
    charts = (
        (shear_ax, shear_values, "Shear V (kip)", "#287a91"),
        (moment_ax, moment_values, "Moment M (kip-ft)", "#a3652d"),
        (deflection_ax, deflection_values, "Deflection (in; positive downward)", "#6556a3"),
    )
    for ax, values, label, color in charts:
        ax.plot(x_values, values, color=color, linewidth=1.6)
        ax.axhline(0, color="#8398a7", linewidth=0.8)
        ax.grid(axis="x", color="#e8edf1", linewidth=0.6)
        ax.grid(axis="y", color="#eef1f4", linewidth=0.5)
        ax.set_ylabel(label, fontsize=8)
        ax.tick_params(labelsize=7, length=2)
        max_abs = max((abs(value) for value in values), default=0.0)
        bound = max_abs * 1.12 if max_abs > 1e-12 else 1.0
        if ax is deflection_ax:
            ax.set_ylim(bound, -bound)
        else:
            ax.set_ylim(-bound, bound)
        ax.margins(x=0)
    deflection_ax.set_xlabel("Position x (ft)", fontsize=8)
    for ax in (shear_ax, moment_ax, deflection_ax):
        ax.set_xlim(0, length)


def save_calculation_sheet(path: str | Path, design: BeamInput, result: AnalysisResult) -> None:
    section = SECTIONS_BY_NAME[design.section_name]
    figure = Figure(figsize=(11.0, 8.5), dpi=150)
    draw_analysis_plots(figure, design, result, pdf_layout=True)
    support_name = "Simply supported" if design.support == "simple" else "Cantilever"
    allowable = (
        "not supplied"
        if design.allowable_bending_stress_ksi is None
        else f"{format_sig(design.allowable_bending_stress_ksi)} ksi"
    )
    bending_status = (
        "Not evaluated"
        if design.allowable_bending_stress_ksi is None
        else (
            "Pass"
            if result.max_bending_stress_ksi <= design.allowable_bending_stress_ksi
            else "Fail"
        )
    )
    deflection_status = (
        "Pass"
        if abs(result.max_deflection_in) <= result.deflection_limit_in + 1e-10
        else "Fail"
    )
    figure.text(0.07, 0.96, "Beam Designer - Calculation Sheet", fontsize=16, weight="bold", color="#173c55")
    figure.text(
        0.07,
        0.925,
        "Educational screening only; not a code-compliant design or engineering review. "
        "Section properties are a limited, rounded AISC Shapes Database subset; verify independently.",
        fontsize=8,
        color="#7a5a12",
    )
    figure.text(
        0.07,
        0.885,
        f"Support: {support_name}    Span: {format_sig(design.span_ft)} ft    "
        f"Section: {section.name}    Ix: {format_sig(section.ix_in4)} in^4    "
        f"Sx: {format_sig(section.sx_in3)} in^3    E: {format_sig(STEEL_E_KSI)} ksi",
        fontsize=8,
    )
    load_lines = textwrap.fill(
        f"Allowable bending stress: {allowable}    Loads: {_load_description(design)}",
        width=145,
    )
    figure.text(0.07, 0.85, load_lines, fontsize=8, va="top")
    figure.text(
        0.07,
        0.79,
        f"Reactions: RA {format_sig(result.reaction_a_kip)} kip"
        + (
            f", RB {format_sig(result.reaction_b_kip)} kip"
            if design.support == "simple"
            else f", fixed moment {format_sig(result.fixed_end_moment_kip_in / 12.0)} kip-ft"
        )
        + f"    |V|max {format_sig(abs(result.max_shear_kip))} kip"
        f"    |M|max {format_sig(abs(result.max_moment_kip_in) / 12.0)} kip-ft",
        fontsize=8,
    )
    figure.text(
        0.07,
        0.755,
        f"Deflection: {format_sig(abs(result.max_deflection_in))} in / "
        f"{format_sig(result.deflection_limit_in)} in (L/360): {deflection_status}    "
        f"Bending stress: {format_sig(result.max_bending_stress_ksi)} ksi / "
        f"{allowable}: {bending_status}",
        fontsize=8,
    )
    with PdfPages(path) as pdf:
        pdf.savefig(figure)
    figure.clear()


class BeamDesignerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Beam Designer")
        self.root.geometry("1440x920")
        self.root.minsize(1080, 720)
        self.current_path: Path | None = None
        self.current_design: BeamInput | None = None
        self.current_result: AnalysisResult | None = None
        self.point_rows: list[dict[str, Any]] = []
        self.uniform_rows: list[dict[str, Any]] = []

        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Header.TLabel", font=("TkDefaultFont", 18, "bold"), foreground="#173c55")
        style.configure("MetricValue.TLabel", font=("TkDefaultFont", 13, "bold"), foreground="#173c55")
        style.configure("MetricTitle.TLabel", font=("TkDefaultFont", 9, "bold"), foreground="#647789")

        self._create_menu()
        self._create_layout()
        self.load_example()

    def _create_menu(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Open...", command=self.open_file)
        file_menu.add_command(label="Save", command=self.save_file)
        file_menu.add_separator()
        file_menu.add_command(label="Export results to CSV...", command=self.export_csv)
        file_menu.add_command(label="Calculation sheet to PDF...", command=self.export_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menu_bar)

    def _create_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, padding=(18, 12))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Beam Designer", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Single-span analysis | US customary units | service-level loads | self-weight excluded",
        ).pack(anchor="w", pady=(2, 0))

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        input_outer = ttk.Frame(main, width=390)
        input_outer.columnconfigure(0, weight=1)
        input_outer.rowconfigure(0, weight=1)
        main.add(input_outer, weight=0)
        self.input_canvas = tk.Canvas(input_outer, highlightthickness=0, width=390)
        scrollbar = ttk.Scrollbar(input_outer, orient=tk.VERTICAL, command=self.input_canvas.yview)
        self.input_canvas.configure(yscrollcommand=scrollbar.set)
        self.input_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.input_form = ttk.Frame(self.input_canvas, padding=(4, 4, 12, 12))
        self.input_window = self.input_canvas.create_window(
            (0, 0), window=self.input_form, anchor="nw"
        )
        self.input_form.bind(
            "<Configure>",
            lambda _event: self.input_canvas.configure(
                scrollregion=self.input_canvas.bbox("all")
            ),
        )
        self.input_canvas.bind(
            "<Configure>",
            lambda event: self.input_canvas.itemconfigure(
                self.input_window, width=event.width
            ),
        )
        self._build_input_form()

        results = ttk.Frame(main, padding=(8, 4, 4, 4))
        results.columnconfigure(0, weight=1)
        results.rowconfigure(2, weight=1)
        main.add(results, weight=1)
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(
            results, textvariable=self.status_var, wraplength=900, justify=tk.LEFT
        )
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.metrics_frame = ttk.Frame(results)
        self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            self.metrics_frame.columnconfigure(column, weight=1)
        self.figure = Figure(figsize=(9.0, 7.2), dpi=100)
        self.figure_canvas = FigureCanvasTkAgg(self.figure, master=results)
        self.figure_canvas.get_tk_widget().grid(row=2, column=0, sticky="nsew")
        ttk.Label(
            results,
            text=(
                "Positive applied loads and deflection are downward; upward reactions are positive; "
                "positive moment is sagging. Section properties are a limited rounded subset of the "
                "AISC Shapes Database; verify them independently."
            ),
            wraplength=900,
        ).grid(row=3, column=0, sticky="ew", pady=(7, 0))

    def _build_input_form(self) -> None:
        form = self.input_form
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Beam and loading", style="MetricValue.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(2, 8)
        )
        self.support_var = tk.StringVar(value="Simply supported")
        self.span_var = tk.StringVar(value="20")
        self.section_var = tk.StringVar(value="W12x26")
        self.allowable_var = tk.StringVar()
        ttk.Label(form, text="Support condition").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(
            form,
            textvariable=self.support_var,
            values=("Simply supported", "Cantilever"),
            state="readonly",
            width=18,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="Span (ft)").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.span_var).grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="Steel W-shape").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Combobox(
            form,
            textvariable=self.section_var,
            values=tuple(SECTIONS_BY_NAME),
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Label(form, text="Allowable bending stress (ksi)").grid(
            row=4, column=0, sticky="w", pady=3
        )
        ttk.Entry(form, textvariable=self.allowable_var).grid(
            row=4, column=1, sticky="ew", pady=3
        )
        self.section_summary = ttk.Label(form, wraplength=350)
        self.section_summary.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        self.point_section = ttk.LabelFrame(form, text="Point loads", padding=6)
        self.point_section.grid(row=6, column=0, columnspan=2, sticky="ew", pady=5)
        self.point_section.columnconfigure(0, weight=1)
        ttk.Button(
            self.point_section, text="+ Add point load", command=self.add_point_load
        ).grid(row=0, column=0, sticky="w")
        self.point_list = ttk.Frame(self.point_section)
        self.point_list.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.point_list.columnconfigure(0, weight=1)

        self.uniform_section = ttk.LabelFrame(form, text="Uniform loads", padding=6)
        self.uniform_section.grid(row=7, column=0, columnspan=2, sticky="ew", pady=5)
        self.uniform_section.columnconfigure(0, weight=1)
        ttk.Button(
            self.uniform_section, text="+ Add uniform load", command=self.add_uniform_load
        ).grid(row=0, column=0, sticky="w")
        self.uniform_list = ttk.Frame(self.uniform_section)
        self.uniform_list.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.uniform_list.columnconfigure(0, weight=1)

        actions = ttk.Frame(form)
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 4))
        ttk.Button(actions, text="Load validation example", command=self.load_example).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(actions, text="Update analysis", command=self.update_analysis).pack(
            side=tk.LEFT
        )
        ttk.Separator(form).grid(row=9, column=0, columnspan=2, sticky="ew", pady=9)
        ttk.Label(
            form,
            text=(
                "Educational screening only. No buckling, code checks, load combinations, "
                "or self-weight. Verify all inputs and section properties independently."
            ),
            wraplength=355,
            foreground="#745817",
            justify=tk.LEFT,
        ).grid(row=10, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        export_actions = ttk.Frame(form)
        export_actions.grid(row=11, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(export_actions, text="Export results to CSV...", command=self.export_csv).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(
            export_actions, text="Calculation sheet to PDF...", command=self.export_pdf
        ).pack(side=tk.LEFT)
        self.section_var.trace_add("write", lambda *_args: self._update_section_summary())
        self._update_section_summary()

    def _update_section_summary(self) -> None:
        section = SECTIONS_BY_NAME.get(self.section_var.get())
        if section:
            self.section_summary.configure(
                text=(
                    f"{section.name}: Ix {format_sig(section.ix_in4)} in^4 | "
                    f"Sx {format_sig(section.sx_in3)} in^3 | E {format_sig(STEEL_E_KSI)} ksi"
                )
            )

    def _add_load_row(self, kind: str, values: dict[str, Any] | None = None) -> None:
        values = values or {}
        is_point = kind == "point"
        rows = self.point_rows if is_point else self.uniform_rows
        container = self.point_list if is_point else self.uniform_list
        labels = (
            (("Magnitude (kip)", "magnitude"), ("Position (ft)", "position"))
            if is_point
            else (
                ("Magnitude (kip/ft)", "magnitude"),
                ("Start (ft)", "start"),
                ("End (ft)", "end"),
            )
        )
        row_frame = ttk.LabelFrame(
            container, text=f"{'Point' if is_point else 'Uniform'} load {len(rows) + 1}", padding=5
        )
        row_frame.pack(fill=tk.X, expand=True, pady=3)
        row_frame.columnconfigure(1, weight=1)
        vars_for_row: dict[str, Any] = {}
        for row_index, (label, key) in enumerate(labels):
            variable = tk.StringVar(value=str(values.get(key, 0)))
            vars_for_row[key] = variable
            ttk.Label(row_frame, text=label).grid(
                row=row_index, column=0, sticky="w", padx=(0, 5), pady=2
            )
            ttk.Entry(row_frame, textvariable=variable, width=12).grid(
                row=row_index, column=1, sticky="ew", pady=2
            )
        direction_var = tk.StringVar(value=values.get("direction", "down"))
        direction_row = len(labels)
        ttk.Label(row_frame, text="Direction").grid(
            row=direction_row, column=0, sticky="w", padx=(0, 5), pady=2
        )
        ttk.Combobox(
            row_frame,
            textvariable=direction_var,
            values=("down", "up"),
            state="readonly",
            width=10,
        ).grid(row=direction_row, column=1, sticky="ew", pady=2)
        rows.append({"frame": row_frame, "vars": vars_for_row, "direction": direction_var})
        ttk.Button(
            row_frame,
            text="Remove",
            command=lambda row=rows[-1], load_rows=rows: self._remove_load_row(row, load_rows),
        ).grid(row=direction_row + 1, column=0, columnspan=2, sticky="e", pady=(3, 0))

    def _remove_load_row(self, row: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        row["frame"].destroy()
        rows.remove(row)
        self._renumber_rows(rows, "Point" if rows is self.point_rows else "Uniform")
        self.update_analysis()

    @staticmethod
    def _renumber_rows(rows: list[dict[str, Any]], label: str) -> None:
        for index, row in enumerate(rows, start=1):
            row["frame"].configure(text=f"{label} load {index}")

    def add_point_load(self, values: dict[str, Any] | None = None) -> None:
        if values is None:
            try:
                span = float(self.span_var.get())
                position = span / 2 if math.isfinite(span) and span > 0 else 0
            except ValueError:
                position = 0
            values = {"magnitude": 1, "position": position, "direction": "down"}
        self._add_load_row("point", values)
        self.update_analysis()

    def add_uniform_load(self, values: dict[str, Any] | None = None) -> None:
        if values is None:
            try:
                span = float(self.span_var.get())
                end = span if math.isfinite(span) and span > 0 else 0
            except ValueError:
                end = 0
            values = {"magnitude": 1, "start": 0, "end": end, "direction": "down"}
        self._add_load_row("uniform", values)
        self.update_analysis()

    @staticmethod
    def _entry_number(raw: str, label: str, *, optional: bool = False) -> float | None:
        raw = raw.strip()
        if optional and not raw:
            return None
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(f"{label} must be a valid number.") from error
        if not math.isfinite(value):
            raise ValueError(f"{label} must be finite.")
        return value

    @classmethod
    def _required_entry_number(cls, raw: str, label: str) -> float:
        value = cls._entry_number(raw, label)
        if value is None:
            raise ValueError(f"{label} is required.")
        return value

    def _collect_design(self) -> BeamInput:
        span = self._required_entry_number(self.span_var.get(), "Span")
        allowable = self._entry_number(
            self.allowable_var.get(), "Allowable bending stress", optional=True
        )
        point_loads = tuple(
            PointLoad(
                magnitude_kip=self._required_entry_number(
                    row["vars"]["magnitude"].get(), f"Point load {index} magnitude"
                ),
                position_ft=self._required_entry_number(
                    row["vars"]["position"].get(), f"Point load {index} position"
                ),
                direction=row["direction"].get(),
            )
            for index, row in enumerate(self.point_rows, start=1)
        )
        uniform_loads = tuple(
            UniformLoad(
                magnitude_kip_per_ft=self._required_entry_number(
                    row["vars"]["magnitude"].get(), f"Uniform load {index} magnitude"
                ),
                start_ft=self._required_entry_number(
                    row["vars"]["start"].get(), f"Uniform load {index} start"
                ),
                end_ft=self._required_entry_number(
                    row["vars"]["end"].get(), f"Uniform load {index} end"
                ),
                direction=row["direction"].get(),
            )
            for index, row in enumerate(self.uniform_rows, start=1)
        )
        design = BeamInput(
            support={
                "Simply supported": "simple",
                "Cantilever": "cantilever",
            }.get(self.support_var.get(), self.support_var.get()),
            span_ft=span,
            section_name=self.section_var.get(),
            allowable_bending_stress_ksi=allowable,
            point_loads=point_loads,
            uniform_loads=uniform_loads,
        )
        validate_design(design)
        return design

    def _set_metric(self, column: int, row: int, title: str, value: str, detail: str) -> None:
        card = ttk.Frame(self.metrics_frame, padding=(8, 4))
        card.grid(row=row, column=column, sticky="nsew", padx=2, pady=2)
        ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text=value, style="MetricValue.TLabel").pack(anchor="w")
        ttk.Label(card, text=detail, wraplength=240).pack(anchor="w")

    def _render_metrics(self, design: BeamInput, result: AnalysisResult) -> None:
        for child in self.metrics_frame.winfo_children():
            child.destroy()
        if design.support == "simple":
            reaction_value = "Simply supported"
            reaction_detail = (
                f"RA {format_sig(result.reaction_a_kip)} kip | "
                f"RB {format_sig(result.reaction_b_kip)} kip"
            )
        else:
            reaction_value = "Cantilever"
            reaction_detail = (
                f"Fixed reaction {format_sig(result.reaction_a_kip)} kip | "
                f"fixed moment {format_sig(result.fixed_end_moment_kip_in / 12)} kip-ft"
            )
        bending_status = (
            "Not evaluated"
            if design.allowable_bending_stress_ksi is None
            else (
                "Pass"
                if result.max_bending_stress_ksi <= design.allowable_bending_stress_ksi
                else "Fail"
            )
        )
        deflection_status = (
            "Pass"
            if abs(result.max_deflection_in) <= result.deflection_limit_in + 1e-10
            else "Fail"
        )
        metrics = (
            ("Support reactions", reaction_value, reaction_detail),
            ("Maximum shear", f"{format_sig(abs(result.max_shear_kip))} kip", "Absolute peak"),
            (
                "Maximum moment",
                f"{format_sig(abs(result.max_moment_kip_in) / 12)} kip-ft",
                "Absolute peak",
            ),
            (
                "Maximum deflection",
                f"{format_sig(abs(result.max_deflection_in))} in",
                f"Limit {format_sig(result.deflection_limit_in)} in | {deflection_status}",
            ),
            (
                "Bending stress",
                f"{format_sig(result.max_bending_stress_ksi)} ksi",
                (
                    f"{bending_status} | allowable "
                    f"{format_sig(design.allowable_bending_stress_ksi)} ksi"
                    if design.allowable_bending_stress_ksi is not None
                    else "Not evaluated | no allowable supplied"
                ),
            ),
            (
                "Section properties",
                design.section_name,
                (
                    f"Ix {format_sig(SECTIONS_BY_NAME[design.section_name].ix_in4)} in^4 | "
                    f"Sx {format_sig(SECTIONS_BY_NAME[design.section_name].sx_in3)} in^3"
                ),
            ),
        )
        for index, (title, value, detail) in enumerate(metrics):
            self._set_metric(index % 3, index // 3, title, value, detail)

    def update_analysis(self) -> bool:
        try:
            design = self._collect_design()
            result = analyze_beam(design)
        except ValueError as error:
            self.status_label.configure(foreground="#9b332c")
            self.status_var.set(f"Input error: {error}  Last valid analysis remains displayed.")
            return False
        self.current_design = design
        self.current_result = result
        self.status_label.configure(foreground="#294d60")
        stress_status = (
            "Bending check not evaluated; enter an allowable stress."
            if design.allowable_bending_stress_ksi is None
            else (
                f"Bending {('passes' if result.max_bending_stress_ksi <= design.allowable_bending_stress_ksi else 'fails')} "
                f"at {format_sig(result.max_bending_stress_ksi)} ksi."
            )
        )
        deflection_status = (
            "Deflection passes L/360."
            if abs(result.max_deflection_in) <= result.deflection_limit_in + 1e-10
            else "Deflection exceeds L/360."
        )
        self.status_var.set(f"Analysis updated. {stress_status} {deflection_status}")
        self._render_metrics(design, result)
        draw_analysis_plots(self.figure, design, result)
        self.figure_canvas.draw_idle()
        return True

    def load_example(self) -> None:
        self.support_var.set("Simply supported")
        self.span_var.set("20")
        self.section_var.set("W12x26")
        self.allowable_var.set("")
        for row in self.point_rows:
            row["frame"].destroy()
        for row in self.uniform_rows:
            row["frame"].destroy()
        self.point_rows.clear()
        self.uniform_rows.clear()
        self._add_load_row(
            "uniform",
            {"magnitude": 1, "start": 0, "end": 20, "direction": "down"},
        )
        self.update_analysis()

    def _apply_design(self, design: BeamInput) -> None:
        self.support_var.set(
            "Simply supported" if design.support == "simple" else "Cantilever"
        )
        self.span_var.set(format(design.span_ft, ".15g"))
        self.section_var.set(design.section_name)
        self.allowable_var.set(
            ""
            if design.allowable_bending_stress_ksi is None
            else format(design.allowable_bending_stress_ksi, ".15g")
        )
        for row in self.point_rows:
            row["frame"].destroy()
        for row in self.uniform_rows:
            row["frame"].destroy()
        self.point_rows.clear()
        self.uniform_rows.clear()
        for load in design.point_loads:
            self._add_load_row(
                "point",
                {
                    "magnitude": load.magnitude_kip,
                    "position": load.position_ft,
                    "direction": load.direction,
                },
            )
        for load in design.uniform_loads:
            self._add_load_row(
                "uniform",
                {
                    "magnitude": load.magnitude_kip_per_ft,
                    "start": load.start_ft,
                    "end": load.end_ft,
                    "direction": load.direction,
                },
            )

    def _validated_snapshot(self) -> tuple[BeamInput, AnalysisResult] | None:
        if not self.update_analysis():
            return None
        assert self.current_design is not None and self.current_result is not None
        return self.current_design, self.current_result

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open beam design",
            filetypes=(("Beam design", "*.beam.json"), ("JSON files", "*.json"), ("All files", "*")),
        )
        if not path:
            return
        try:
            design = open_design(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not open design", str(error), parent=self.root)
            return
        self._apply_design(design)
        self.current_path = Path(path)
        self.update_analysis()

    def save_file(self) -> None:
        snapshot = self._validated_snapshot()
        if snapshot is None:
            return
        design, _result = snapshot
        path = self.current_path
        if path is None:
            selected = filedialog.asksaveasfilename(
                title="Save beam design",
                defaultextension=".beam.json",
                filetypes=(("Beam design", "*.beam.json"), ("JSON files", "*.json")),
            )
            if not selected:
                return
            path = Path(selected)
        try:
            save_design(path, design)
        except OSError as error:
            messagebox.showerror("Could not save design", str(error), parent=self.root)
            return
        self.current_path = path
        self.status_var.set(f"Design saved to {path}.")

    def export_csv(self) -> None:
        snapshot = self._validated_snapshot()
        if snapshot is None:
            return
        design, result = snapshot
        path = filedialog.asksaveasfilename(
            title="Export beam results",
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*")),
        )
        if not path:
            return
        try:
            export_results_csv(path, design, result)
        except OSError as error:
            messagebox.showerror("Could not export CSV", str(error), parent=self.root)
            return
        self.status_var.set(f"Results exported to {path}.")

    def export_pdf(self) -> None:
        snapshot = self._validated_snapshot()
        if snapshot is None:
            return
        design, result = snapshot
        path = filedialog.asksaveasfilename(
            title="Save calculation sheet",
            defaultextension=".pdf",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*")),
        )
        if not path:
            return
        try:
            save_calculation_sheet(path, design, result)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not save calculation sheet", str(error), parent=self.root)
            return
        self.status_var.set(f"Calculation sheet saved to {path}.")


def main() -> None:
    root = tk.Tk()
    BeamDesignerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
