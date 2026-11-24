"""Static diagnostics and a Matplotlib viewer with Apply-based parameter tuning."""

from pathlib import Path

import numpy as np
from manifold3d import CrossSection, FillRule
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.colors import LightSource
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

from .config import ANGLE_RANGE, OFFSET_RANGE, GeometryError
from .mesh import from_solid, to_solid


BLUE = "#1976c9"
YELLOW = "#af7b00"
RED = "#c43131"
TEAL = "#16766c"


def _closed(points):
    return np.vstack([points, points[0]])


def _outline(generator):
    projected = generator._input_solid.project()
    return CrossSection(projected.to_polygons(), FillRule.Positive).to_polygons()


def _draw_profile(ax, result, outline):
    params = result.parameters
    ax.clear()
    for i, contour in enumerate(outline):
        ax.plot(*_closed(contour).T, color="#566578", lw=1.2, label="STL XY projection" if i == 0 else None)
    x, y = result.keep_polygon.exterior.xy
    ax.fill(x, y, color=TEAL, alpha=0.10)
    ax.plot(x, y, color=TEAL, lw=1.0, linestyle=":", label="Keep profile")
    for key, color, label in (
        ("blue_y_mm", BLUE, "Blue reference"),
        ("yellow_y_mm", YELLOW, "Yellow reference"),
        ("red_y_mm", RED, "Red section plane"),
    ):
        ax.axhline(params[key], linestyle="--", color=color, lw=1.0, label=label)
    ax.plot(*_closed(result.trapezoid_vertices_2d).T, color=RED, lw=1.8)
    geometry = result.geometry_parameters
    for name, dx, dy in (("A", -10, 5), ("B", 6, 5), ("C", -10, 7), ("D", 6, 7)):
        x, y = getattr(geometry, name)
        ax.scatter(x, y, color=RED, s=20, zorder=5)
        ax.annotate(name, (x, y), xytext=(dx, dy), textcoords="offset points", weight="bold", color=RED)
    ax.set(
        title=f"XY projection   |   Offset {params['offset_mm']:g} mm   |   Angle {params['angle_deg']:g}°",
        xlabel="Local X (mm)", ylabel="Local Y (mm)", aspect="equal",
    )
    ax.grid(alpha=0.15)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), ncol=2, frameon=False, fontsize=8)


def _draw_section(ax, result):
    segments = result.section.segments[:, :, [0, 2]]
    ax.add_collection(LineCollection(segments, colors="#566578", linewidths=1))
    section = result.section
    ax.plot(*_closed(section.points[:, [0, 2]]).T, color=RED, lw=1.4, label="Selected outer contour")
    ax.autoscale()
    ax.set(
        title=f"Actual XZ section at Y = {section.y_mm:g} mm",
        xlabel="Local X (mm)", ylabel="Local Z (mm)", aspect="equal",
    )
    ax.grid(alpha=0.15)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), frameon=False, fontsize=8)


def save_profile(generator, result, path):
    figure = Figure(figsize=(11, 6.5), layout="constrained")
    FigureCanvasAgg(figure)
    left, right = figure.subplots(1, 2)
    _draw_profile(left, result, _outline(generator))
    _draw_section(right, result)
    figure.savefig(path, dpi=155, facecolor="white")


def _display_mesh(solid, span):
    # Visualization only. Display tessellation never enters the cutting or export path.
    return from_solid(solid.simplify(span / 500.0))


def _axes_xyz(points):
    # Right-handed screen coordinate frame, with mesh Y as the up axis.
    return np.asarray(points)[..., [0, 2, 1]] * [1, -1, 1]


def _add_mesh(ax, mesh, color, alpha, *, shade=False):
    ax.add_collection3d(Poly3DCollection(
        _axes_xyz(mesh.triangles),
        facecolors=color,
        alpha=alpha,
        linewidths=0,
        antialiased=False,
        shade=shade,
        lightsource=LightSource(azdeg=315, altdeg=45) if shade else None,
    ))


def _configure_3d(ax, bounds, *, angles):
    # Relabel the reversed depth axis in local Z coordinates.
    ax.set(
        xlim=bounds[:, 0], ylim=-bounds[::-1, 2], zlim=bounds[:, 1],
        xlabel="X (mm)", ylabel="Z (mm)", zlabel="Y (mm)",
    )
    ax.yaxis.set_major_formatter(lambda value, _: f"{-value:g}")
    ax.set_box_aspect(np.diff(bounds[:, [0, 2, 1]], axis=0)[0])
    ax.set_proj_type("ortho")
    ax.view_init(elev=angles[0], azim=angles[1])


def _draw_3d(ax, bounds, original, result_mesh, result, *, angles, layers=False):
    ax.clear()
    _configure_3d(ax, bounds, angles=angles)
    if not layers:
        _add_mesh(ax, result_mesh, "#d9b383", 1, shade=True)
        return

    _add_mesh(ax, original, "#aeb9c5", 0.16)
    _add_mesh(ax, result.keep_mesh, TEAL, 0.10)
    _add_mesh(ax, result.trapezoid_mesh, BLUE, 0.21)
    if result.assembly_region_mesh is not None:
        _add_mesh(ax, result.assembly_region_mesh, "#e3a451", 0.48)
    xlo, xhi = bounds[:, 0]
    zlo, zhi = bounds[:, 2]
    red = result.section.y_mm
    ax.add_collection3d(Poly3DCollection(
        _axes_xyz([[(xlo, red, zlo), (xhi, red, zlo), (xhi, red, zhi), (xlo, red, zhi)]]),
        facecolors=RED, alpha=0.10, linewidths=0,
    ))
    ax.add_collection3d(Line3DCollection(_axes_xyz(result.section.segments), colors=RED, linewidths=1.1))
    for name, color in (("yellow", YELLOW), ("blue", BLUE)):
        points = result.parameters.get("blue_reference_points_local_mm") if name == "blue" else None
        if points is None:
            y = result.parameters[f"{name}_y_mm"]
            points = [[xlo, y, zhi], [xhi, y, zhi]]
        ax.plot(*_axes_xyz(points).T, color=color, linewidth=2.0)


def _view_bounds(generator, result):
    bounds = result.keep_mesh.bounds.copy()
    bounds[0] = np.minimum(bounds[0], generator.bounds[0])
    bounds[1] = np.maximum(bounds[1], generator.bounds[1])
    return bounds


def save_3d_preview(generator, result, path):
    fig = Figure(figsize=(13, 5.0), layout="constrained")
    FigureCanvasAgg(fig)
    span = float(np.ptp(generator.bounds, axis=0).max())
    source = _display_mesh(generator._input_solid, span)
    final = _display_mesh(to_solid(result.result_mesh, "Preview"), span)
    specs = [
        ("Cutting geometry", (17, -68), True),
        ("Final STL · front", (0, -90), False),
        ("Final STL · side", (0, 0), False),
    ]
    for i, (title, angles, layers) in enumerate(specs, 1):
        ax = fig.add_subplot(1, 3, i, projection="3d")
        _draw_3d(ax, _view_bounds(generator, result), source, final, result, angles=angles, layers=layers)
        ax.set_title(title)
        if not layers:
            ax.set_axis_off()
        else:
            ax.legend(
                handles=[
                    Patch(color="#aeb9c5", label="Source"),
                    Patch(color=TEAL, label="Keep volume", alpha=0.45),
                    Patch(color=BLUE, label="Trapezoid prism", alpha=0.50),
                    Patch(color="#e3a451", label="Assembly region"),
                ],
                loc="lower center", bbox_to_anchor=(0.5, -0.11),
                ncol=2, fontsize=8, frameon=False,
            )
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight", pad_inches=0.13)


def build_debug_figure(figure, generator, result, *, output_dir=None,
                       export_intermediate=True, preview_path=None):
    from matplotlib.widgets import Button, Slider

    figure.subplots_adjust(left=0.05, right=0.98, top=0.90, bottom=0.23, wspace=0.22)
    profile_ax = figure.add_subplot(131)
    overlay_ax = figure.add_subplot(132, projection="3d")
    final_ax = figure.add_subplot(133, projection="3d")
    status = figure.text(0.05, 0.04, "")
    outline = _outline(generator)
    span = float(np.ptp(generator.bounds, axis=0).max())
    source = _display_mesh(generator._input_solid, span)
    offset = Slider(figure.add_axes([0.15, 0.12, 0.50, 0.025]), "Offset (mm)", *OFFSET_RANGE,
                    valinit=result.parameters["offset_mm"], valstep=0.1)
    angle = Slider(figure.add_axes([0.15, 0.08, 0.50, 0.025]), "Angle (°)", *ANGLE_RANGE,
                   valinit=result.parameters["angle_deg"], valstep=0.1)
    apply_button = Button(figure.add_axes([0.77, 0.092, 0.12, 0.042]), "Apply")
    front_button = Button(figure.add_axes([0.74, 0.18, 0.09, 0.036]), "Front")
    side_button = Button(figure.add_axes([0.85, 0.18, 0.09, 0.036]), "Side")

    def redraw(current, overlay_angles, final_angles):
        _draw_profile(profile_ax, current, outline)
        mesh = _display_mesh(to_solid(current.result_mesh, "Viewer result"), span)
        bounds = _view_bounds(generator, current)
        _draw_3d(overlay_ax, bounds, source, mesh, current, angles=overlay_angles, layers=True)
        _draw_3d(final_ax, bounds, source, mesh, current, angles=final_angles)
        overlay_ax.set_axis_off()
        final_ax.set_axis_off()
        overlay_ax.set_title("Geometry and references")
        final_ax.set_title("Clipped STL")
        figure.canvas.draw_idle()

    def change_view(azimuth):
        for ax in (overlay_ax, final_ax):
            ax.view_init(elev=0, azim=azimuth)
        figure.canvas.draw_idle()

    def apply(_):
        status.set_text("Computing…")
        figure.canvas.draw_idle()
        figure.canvas.flush_events()
        try:
            updated = generator.generate(
                output_dir, offset_mm=offset.val, angle_deg=angle.val,
                margin_mm=result.parameters["margin_mm"], export_intermediate=export_intermediate,
                compute_assembly=result.assembly_region_mesh is not None,
            )
            if preview_path is not None:
                save_3d_preview(generator, updated, preview_path)
            redraw(updated, (overlay_ax.elev, overlay_ax.azim), (final_ax.elev, final_ax.azim))
            status.set_text("Updated" if output_dir is None else f"Updated · {Path(output_dir)}")
        except (GeometryError, OSError) as exc:
            status.set_text(str(exc))
        figure.canvas.draw_idle()

    apply_button.on_clicked(apply)
    front_button.on_clicked(lambda _: change_view(-90))
    side_button.on_clicked(lambda _: change_view(0))
    redraw(result, (17, -68), (0, -90))
    return offset, angle, apply_button, front_button, side_button


def show_debug(generator, result, *, output_dir=None, export_intermediate=True, preview_path=None):
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(14, 6.5))
    if figure.canvas.required_interactive_framework is None:
        plt.close(figure)
        raise GeometryError("An interactive Matplotlib backend is required. Use --preview-3d for a headless PNG.")
    widgets = build_debug_figure(
        figure, generator, result, output_dir=output_dir,
        export_intermediate=export_intermediate, preview_path=preview_path,
    )
    plt.show()
    return widgets
