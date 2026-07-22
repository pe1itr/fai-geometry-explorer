"""English graphical user interface for FAI Geometry Explorer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import queue
import threading
import webbrowser

from .coordinates import maidenhead_to_wgs84
from .dual_station import DualSearchConfig, search_dual_station
from .geomagnetic import PpigrfModel
from .map_export import write_scatter_map
from .png_export import write_dual_station_png, write_single_station_png
from .single_map_export import write_single_station_map
from .single_station import SingleSearchConfig, geometry_rating, search_single_station

GITHUB_URL = "https://github.com/pe1itr/fai-geometry-explorer"
Q65_GUIDE_URL = "https://wsjt.sourceforge.io/Q65_Quick_Start.pdf"
MODE_SKED = "sked"
MODE_EXPLORER = "explorer"
ABOUT_TEXT = (
    "A geometry research tool for mid-latitude Field Aligned Irregularity "
    "propagation at 144 MHz. The geometry score is not a propagation forecast.\n\n"
    "Historical references\n\n"
    "• DUBUS 3/86 — Ludovico Scaroni, I3LDS: “Recent Acquisitions on "
    "Midlatitude F.A.I. Propagation at 144 MHz”.\n\n"
    "• DUBUS 1/87 and 2/87 — Günter Köllner, DL4MEA: “FAI Informationen”.\n\n"
    "Weak-signal digital modes\n\n"
    "Historical FAI contacts were made using CW or SSB. Analysis of the available "
    "recordings found strong CW tone cores approximately 22–32 Hz wide. FT8 uses "
    "6.25 Hz tone spacing and is therefore not considered a reliable mode for these "
    "recorded FAI conditions.\n\n"
    "Practical FAI advice: start with Q65-15B. It combines a short 15-second T/R "
    "period (approximately 12.8 seconds of transmission) with 13.33 Hz tone spacing. "
    "If a signal is visible but too broad or rough to decode reliably, switch to "
    "Q65-15C with 26.67 Hz spacing. For openings that remain stable for longer, "
    "Q65-30C provides 13.33 Hz spacing and Q65-30D provides 26.67 Hz spacing with a "
    "longer integration period. Actual decoding remains dependent on signal strength, "
    "fading and instantaneous Doppler spread.\n\n"
    "Developed by Rob Hardenberg, PE1ITR.\n\n"
)


@dataclass(frozen=True, slots=True)
class GuiSettings:
    """Validated settings for a GUI calculation."""

    mode: str
    locator_1: str
    locator_2: str | None
    antenna_azimuth_deg: float | None
    antenna_tolerance_deg: float
    height_km: float
    grid_step_km: float
    model_date: date
    output_path: Path


@dataclass(frozen=True, slots=True)
class CalculationResult:
    """Text and antenna directions presented after a calculation."""

    station_1_direction: str
    station_2_direction: str
    details: str
    output_path: Path


def validate_settings(
    *,
    mode: str,
    locator_1: str,
    locator_2: str,
    antenna_azimuth: str,
    antenna_tolerance: str,
    height_km: str,
    grid_step_km: str,
    model_date: str,
    output_path: str,
) -> GuiSettings:
    """Validate all GUI fields and return English, user-facing errors."""

    if mode not in {MODE_SKED, MODE_EXPLORER}:
        raise ValueError("Select Sked Mode or Explorer Mode.")
    first = _validate_locator(locator_1, "Location 1")
    second = _validate_locator(locator_2, "Location 2") if mode == MODE_SKED else None
    azimuth = (
        _required_float(antenna_azimuth, "Antenna direction")
        if mode == MODE_EXPLORER
        else None
    )
    tolerance = _positive_float(antenna_tolerance, "Direction tolerance")
    height = _positive_float(height_km, "Scatter height")
    grid = _positive_float(grid_step_km, "Grid spacing")
    if azimuth is not None and not 0.0 <= azimuth < 360.0:
        raise ValueError("Antenna direction must be between 0 and 360 degrees.")
    if tolerance > 180.0:
        raise ValueError("Direction tolerance cannot exceed 180 degrees.")
    try:
        selected_date = date.fromisoformat(model_date.strip())
    except ValueError as exc:
        raise ValueError("Model date must use the YYYY-MM-DD format.") from exc
    if not output_path.strip():
        raise ValueError("Choose an output file for the map.")
    path = Path(output_path.strip()).expanduser()
    if path.suffix.lower() not in {".png", ".html"}:
        raise ValueError("The map filename must end in .png or .html.")
    return GuiSettings(
        mode=mode,
        locator_1=first,
        locator_2=second,
        antenna_azimuth_deg=azimuth,
        antenna_tolerance_deg=tolerance,
        height_km=height,
        grid_step_km=grid,
        model_date=selected_date,
        output_path=path.resolve(),
    )


def calculate(settings: GuiSettings) -> CalculationResult:
    """Run the selected mode and create its map and direction summary."""

    if settings.mode == MODE_SKED:
        return _calculate_sked(settings)
    return _calculate_explorer(settings)


def _calculate_sked(settings: GuiSettings) -> CalculationResult:
    assert settings.locator_2 is not None
    station_1 = maidenhead_to_wgs84(settings.locator_1)
    station_2 = maidenhead_to_wgs84(settings.locator_2)
    result = search_dual_station(
        station_1,
        station_2,
        config=DualSearchConfig(
            heights_km=(settings.height_km,),
            grid_step_km=settings.grid_step_km,
        ),
        geomagnetic_model=PpigrfModel(),
        model_date=settings.model_date,
    )
    if settings.output_path.suffix.lower() == ".png":
        write_dual_station_png(
            result, settings.locator_1, settings.locator_2, settings.output_path
        )
    else:
        write_scatter_map(
            result, settings.locator_1, settings.locator_2, settings.output_path
        )
    best = result.best
    if best is None:
        return CalculationResult(
            station_1_direction="No suitable direction found.",
            station_2_direction="No suitable direction found.",
            details=(
                "No scatter point was found within the configured geometric limits.\n"
                f"Visible grid points: {result.visible_candidate_count}\n"
                f"Map: {settings.output_path}"
            ),
            output_path=settings.output_path,
        )
    return CalculationResult(
        station_1_direction=(
            f"{settings.locator_1}: azimuth {best.azimuth_1_deg:.2f}°, "
            f"elevation {best.elevation_1_deg:.2f}°"
        ),
        station_2_direction=(
            f"{settings.locator_2}: azimuth {best.azimuth_2_deg:.2f}°, "
            f"elevation {best.elevation_2_deg:.2f}°"
        ),
        details=(
            f"Best bistatic geometry match: {best.score_total:.6f}\n"
            f"Scatter point: {best.latitude_deg:.4f}°, {best.longitude_deg:.4f}° "
            f"at {best.height_km:.1f} km\n"
            f"Bistatic aspect error: {best.bistatic_aspect_error_deg:.2f}°\n"
            f"Propagation deflection: {best.scatter_angle_deg:.2f}°\n"
            f"Visible grid points: {result.visible_candidate_count}; "
            f"within limits: {result.accepted_candidate_count}\n"
            f"Map: {settings.output_path}"
        ),
        output_path=settings.output_path,
    )


def _calculate_explorer(settings: GuiSettings) -> CalculationResult:
    assert settings.antenna_azimuth_deg is not None
    station = maidenhead_to_wgs84(settings.locator_1)
    result = search_single_station(
        station,
        config=SingleSearchConfig(
            heights_km=(settings.height_km,),
            grid_step_km=settings.grid_step_km,
            antenna_azimuth_deg=settings.antenna_azimuth_deg,
            azimuth_tolerance_deg=settings.antenna_tolerance_deg,
        ),
        geomagnetic_model=PpigrfModel(),
        model_date=settings.model_date,
    )
    if settings.output_path.suffix.lower() == ".png":
        write_single_station_png(result, settings.locator_1, settings.output_path)
    else:
        write_single_station_map(result, settings.locator_1, settings.output_path)
    best = result.best
    validation = result.sked_validation
    if best is None:
        return CalculationResult(
            station_1_direction="No suitable direction found in the selected sector.",
            station_2_direction="No potential remote location found.",
            details=(
                f"Antenna sector: {settings.antenna_azimuth_deg:.1f}° ± "
                f"{settings.antenna_tolerance_deg:.1f}°\n"
                f"Map: {settings.output_path}"
            ),
            output_path=settings.output_path,
        )
    if validation is not None:
        station_1_direction = (
            f"{settings.locator_1}: azimuth {validation.azimuth_1_deg:.2f}°, "
            f"elevation {validation.elevation_1_deg:.2f}°"
        )
        remote_direction = (
            f"Suggested remote station ({best.latitude_deg:.4f}°, {best.longitude_deg:.4f}°): "
            f"azimuth {validation.azimuth_2_deg:.2f}°, "
            f"elevation {validation.elevation_2_deg:.2f}°"
        )
        match = validation.score_total
        scatter_position = (
            f"{validation.latitude_deg:.4f}°, {validation.longitude_deg:.4f}°"
        )
    else:
        station_1_direction = (
            f"{settings.locator_1}: azimuth {best.azimuth_1_deg:.2f}°, "
            f"elevation {best.elevation_1_deg:.2f}°"
        )
        remote_direction = (
            f"Potential remote station ({best.latitude_deg:.4f}°, {best.longitude_deg:.4f}°): "
            f"azimuth {best.counterstation_azimuth_deg:.2f}°, "
            f"elevation {best.counterstation_elevation_deg:.2f}°"
        )
        match = best.score_total
        scatter_position = (
            f"{best.scatter_latitude_deg:.4f}°, {best.scatter_longitude_deg:.4f}°"
        )
    return CalculationResult(
        station_1_direction=station_1_direction,
        station_2_direction=remote_direction,
        details=(
            f"Best geometry match: {match:.6f} ({geometry_rating(match)})\n"
            f"Suggested remote location: {best.latitude_deg:.4f}°, "
            f"{best.longitude_deg:.4f}°\n"
            f"Scatter point: {scatter_position}\n"
            f"Reachable ground cells: {len(result.reachable_points)}\n"
            f"Map: {settings.output_path}"
        ),
        output_path=settings.output_path,
    )


def _validate_locator(value: str, label: str) -> str:
    locator = value.strip().upper()
    if len(locator) not in (4, 6, 8):
        raise ValueError(f"{label} must be a 4, 6 or 8 character Maidenhead locator.")
    try:
        maidenhead_to_wgs84(locator)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid Maidenhead locator.") from exc
    return locator


def _positive_float(value: str, label: str) -> float:
    number = _required_float(value, label)
    if number <= 0.0:
        raise ValueError(f"{label} must be greater than zero.")
    return number


def _required_float(value: str, label: str) -> float:
    if not value.strip():
        raise ValueError(f"Enter a value for {label.lower()}.")
    try:
        return float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc


class FaiExplorerApp:
    """Tk application with mode-specific inputs and a configuration dialog."""

    def __init__(self, root: object) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.root.title("FAI Geometry Explorer")
        self.root.geometry("790x680")
        self.root.minsize(700, 620)
        self.root.option_add("*Font", ("Segoe UI", 10))
        self._result_queue: queue.Queue[tuple[bool, CalculationResult | str]] = queue.Queue()
        self._last_output: Path | None = None

        documents = Path.home() / "Documents"
        output_directory = documents if documents.is_dir() else Path.home()
        self.mode = tk.StringVar(value=MODE_SKED)
        self.locator_1 = tk.StringVar()
        self.locator_2 = tk.StringVar()
        self.azimuth = tk.StringVar(value="140")
        self.tolerance = tk.StringVar(value="20")
        self.height = tk.StringVar(value="110")
        self.grid = tk.StringVar(value="10")
        self.model_date = tk.StringVar(value=date.today().isoformat())
        self.output = tk.StringVar(value=str(output_directory / "fai_scatter_map.png"))
        self.direction_1 = tk.StringVar(value="Run a calculation to obtain an antenna direction.")
        self.direction_2 = tk.StringVar(value="")

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", foreground="#475569")
        style.configure("Direction.TLabel", font=("Segoe UI", 11, "bold"), foreground="#0f4c81")
        style.configure("Run.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 9))
        self._create_menu()

        outer = ttk.Frame(root, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="FAI Geometry Explorer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Explore geometrically suitable mid-latitude FAI scatter regions.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        modes = ttk.LabelFrame(outer, text="Calculation mode", padding=12)
        modes.pack(fill="x")
        ttk.Radiobutton(
            modes,
            text="Sked Mode — calculate between two known locations",
            variable=self.mode,
            value=MODE_SKED,
            command=self._show_mode,
        ).pack(anchor="w", pady=2)
        ttk.Radiobutton(
            modes,
            text="Explorer Mode — explore possibilities from my location",
            variable=self.mode,
            value=MODE_EXPLORER,
            command=self._show_mode,
        ).pack(anchor="w", pady=2)

        self.inputs = ttk.LabelFrame(outer, text="Sked Mode locations", padding=14)
        self.inputs.pack(fill="x", pady=(12, 0))
        self.inputs.columnconfigure(1, weight=1)
        self._show_mode()

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 10))
        self.run_button = ttk.Button(
            actions, text="Calculate map", style="Run.TButton", command=self._start
        )
        self.run_button.pack(side="left")
        self.open_button = ttk.Button(
            actions, text="Open map", command=self._open_result, state="disabled"
        )
        self.open_button.pack(side="left", padx=10)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=170)
        self.progress.pack(side="right")

        directions = ttk.LabelFrame(outer, text="Antenna directions", padding=12)
        directions.pack(fill="x")
        ttk.Label(
            directions, textvariable=self.direction_1, style="Direction.TLabel", wraplength=710
        ).pack(anchor="w")
        ttk.Label(
            directions, textvariable=self.direction_2, style="Direction.TLabel", wraplength=710
        ).pack(anchor="w", pady=(5, 0))

        ttk.Label(outer, text="Calculation details").pack(anchor="w", pady=(10, 0))
        self.log = tk.Text(
            outer,
            height=8,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            background="#f8fafc",
        )
        self.log.pack(fill="both", expand=True, pady=(5, 0))

    def _create_menu(self) -> None:
        import tkinter as tk

        menu = tk.Menu(self.root)
        menu.add_command(label="Config", command=self._open_config)
        menu.add_command(label="Info", command=self._open_info)
        self.root.configure(menu=menu)

    def _show_mode(self) -> None:
        from tkinter import ttk

        for child in self.inputs.winfo_children():
            child.destroy()
        if self.mode.get() == MODE_SKED:
            self.inputs.configure(text="Sked Mode locations")
            fields = (
                ("Location 1 locator", self.locator_1, "e.g. JO21QK"),
                ("Location 2 locator", self.locator_2, "e.g. JN47FD"),
            )
        else:
            self.inputs.configure(text="Explorer Mode inputs")
            fields = (
                ("My location locator", self.locator_1, "e.g. JO21QK"),
                ("Antenna direction", self.azimuth, "degrees from north"),
                ("Direction tolerance", self.tolerance, "± degrees"),
            )
        for row, (label, variable, hint) in enumerate(fields):
            ttk.Label(self.inputs, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(self.inputs, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=(14, 10), pady=6)
            ttk.Label(self.inputs, text=hint, style="Subtitle.TLabel").grid(
                row=row, column=2, sticky="w"
            )
            if row == 0:
                entry.focus_set()

    def _open_config(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        dialog = tk.Toplevel(self.root)
        dialog.title("Configuration")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        height_value = tk.StringVar(value=self.height.get())
        grid_value = tk.StringVar(value=self.grid.get())
        date_value = tk.StringVar(value=self.model_date.get())
        output_value = tk.StringVar(value=self.output.get())
        fields = (
            ("Scatter height", height_value, "km"),
            ("Grid spacing", grid_value, "km"),
            ("Model date", date_value, "YYYY-MM-DD"),
        )
        for row, (label, variable, unit) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=variable, width=28).grid(
                row=row, column=1, sticky="ew", padx=12, pady=7
            )
            ttk.Label(frame, text=unit).grid(row=row, column=2, sticky="w")
        ttk.Label(frame, text="Map output file").grid(row=3, column=0, sticky="w", pady=7)
        ttk.Entry(frame, textvariable=output_value, width=48).grid(
            row=3, column=1, sticky="ew", padx=12, pady=7
        )

        def browse() -> None:
            current = Path(output_value.get()).expanduser()
            chosen = filedialog.asksaveasfilename(
                parent=dialog,
                title="Save map",
                initialdir=str(current.parent),
                initialfile=current.name,
                defaultextension=".png",
                filetypes=(
                    ("PNG image", "*.png"),
                    ("Interactive HTML map", "*.html"),
                ),
            )
            if chosen:
                output_value.set(chosen)

        ttk.Button(frame, text="Browse…", command=browse).grid(row=3, column=2)

        def close_if_valid() -> None:
            try:
                _positive_float(height_value.get(), "Scatter height")
                _positive_float(grid_value.get(), "Grid spacing")
                try:
                    date.fromisoformat(date_value.get().strip())
                except ValueError as exc:
                    raise ValueError("Model date must use the YYYY-MM-DD format.") from exc
                if Path(output_value.get().strip()).suffix.lower() not in {".png", ".html"}:
                    raise ValueError("The map filename must end in .png or .html.")
            except ValueError as exc:
                messagebox.showerror("Check configuration", str(exc), parent=dialog)
                return
            self.height.set(height_value.get())
            self.grid.set(grid_value.get())
            self.model_date.set(date_value.get())
            self.output.set(output_value.get())
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=close_if_valid).pack(side="right", padx=8)
        dialog.grab_set()
        dialog.wait_visibility()
        dialog.focus_set()

    def _open_info(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        dialog = tk.Toplevel(self.root)
        dialog.title("About FAI Geometry Explorer")
        dialog.transient(self.root)
        dialog.geometry("650x500")
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="FAI Geometry Explorer", style="Title.TLabel").pack(anchor="w")
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True, pady=(12, 8))
        text = tk.Text(
            text_frame, wrap="word", borderwidth=0, background=dialog.cget("background")
        )
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("end", ABOUT_TEXT)
        text.insert("end", "Q65 specification: ")
        text.insert("end", Q65_GUIDE_URL, "q65_link")
        text.insert("end", "\n\nSource code: ")
        text.insert("end", GITHUB_URL, "github_link")
        for tag, url in (("q65_link", Q65_GUIDE_URL), ("github_link", GITHUB_URL)):
            text.tag_configure(tag, foreground="#0563c1", underline=True)
            text.tag_bind(tag, "<Button-1>", lambda _event, link=url: webbrowser.open(link))
            text.tag_bind(tag, "<Enter>", lambda _event: text.configure(cursor="hand2"))
            text.tag_bind(tag, "<Leave>", lambda _event: text.configure(cursor=""))
        text.configure(state="disabled")
        ttk.Button(frame, text="Close", command=dialog.destroy).pack(anchor="e")
        dialog.grab_set()

    def _start(self) -> None:
        from tkinter import messagebox

        try:
            settings = validate_settings(
                mode=self.mode.get(),
                locator_1=self.locator_1.get(),
                locator_2=self.locator_2.get(),
                antenna_azimuth=self.azimuth.get(),
                antenna_tolerance=self.tolerance.get(),
                height_km=self.height.get(),
                grid_step_km=self.grid.get(),
                model_date=self.model_date.get(),
                output_path=self.output.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Check the input", str(exc), parent=self.root)
            return
        self.direction_1.set("Calculating…")
        self.direction_2.set("")
        self._set_log("The calculation is running. A 10 km grid can take a while.")
        self.run_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.start(12)
        threading.Thread(target=self._calculate_worker, args=(settings,), daemon=True).start()
        self.root.after(100, self._poll_result)

    def _calculate_worker(self, settings: GuiSettings) -> None:
        try:
            result = calculate(settings)
        except BaseException as exc:
            self._result_queue.put((False, str(exc)))
        else:
            self._result_queue.put((True, result))

    def _poll_result(self) -> None:
        try:
            succeeded, payload = self._result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_result)
            return
        self.progress.stop()
        self.run_button.configure(state="normal")
        if succeeded:
            assert isinstance(payload, CalculationResult)
            self.direction_1.set(payload.station_1_direction)
            self.direction_2.set(payload.station_2_direction)
            self._set_log(payload.details)
            self._last_output = payload.output_path
            self.open_button.configure(state="normal")
        else:
            from tkinter import messagebox

            self.direction_1.set("Calculation failed.")
            self.direction_2.set("")
            self._set_log(str(payload))
            messagebox.showerror("Calculation failed", str(payload), parent=self.root)

    def _set_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", message)
        self.log.configure(state="disabled")

    def _open_result(self) -> None:
        if self._last_output is not None:
            webbrowser.open(self._last_output.as_uri())


def main() -> int:
    """Start the graphical application."""

    import tkinter as tk

    root = tk.Tk()
    FaiExplorerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
