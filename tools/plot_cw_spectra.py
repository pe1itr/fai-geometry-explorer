#!/usr/bin/env python3
"""Generate normalized CW spectrum plots for the historical FAI recordings."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np


SAMPLE_RATE_HZ = 12_000
FFT_SIZE = 32_768
FT8_TONE_SPACING_HZ = 6.25
FT8_OCCUPIED_BANDWIDTH_HZ = 50.0


@dataclass(frozen=True, slots=True)
class Recording:
    filename: str
    label: str
    band_hz: tuple[float, float]
    analysis_end_s: float | None = None
    confidence: str = "good"


RECORDINGS = (
    Recording("CT1WW.mp3", "CT1WW", (250.0, 750.0), confidence="low"),
    Recording("G4LOH.mp3", "G4LOH", (500.0, 1_150.0)),
    Recording("I5JUX.mp3", "I5JUX", (350.0, 900.0), confidence="moderate"),
    Recording("SV1DH.mp3", "SV1DH", (600.0, 1_100.0)),
    Recording(
        "SV1DH_CW&SSB.mp3",
        "SV1DH CW section",
        (500.0, 1_050.0),
        analysis_end_s=48.5,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot normalized CW-tone spectra from the historical FAI MP3 files."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("mp3"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("mp3") / "spectra"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for recording in RECORDINGS:
        input_path = args.input_dir / recording.filename
        if not input_path.is_file():
            raise FileNotFoundError(input_path)
        output_name = recording.filename.replace(".mp3", "_cw_spectrum.png")
        output_path = args.output_dir / output_name
        metrics = plot_recording(input_path, output_path, recording)
        print(
            f"{recording.label}: peak L/R {metrics['peak_l']:.1f}/"
            f"{metrics['peak_r']:.1f} Hz; -3 dB {metrics['width_3']:.1f} Hz; "
            f"-10 dB {metrics['width_10']:.1f} Hz -> {output_path.resolve()}"
        )
    return 0


def plot_recording(
    input_path: Path, output_path: Path, recording: Recording
) -> dict[str, float]:
    samples = decode_stereo(input_path)
    if recording.analysis_end_s is not None:
        samples = samples[: int(recording.analysis_end_s * SAMPLE_RATE_HZ)]

    frequency_hz, left_power = welch_power(samples[:, 0])
    _, right_power = welch_power(samples[:, 1])
    left_db = smooth_db(frequency_hz, left_power)
    right_db = smooth_db(frequency_hz, right_power)

    relative_hz = np.arange(-300.0, 300.001, frequency_hz[1] - frequency_hz[0])
    left_relative, peak_l = align_to_peak(
        frequency_hz, left_db, recording.band_hz, relative_hz
    )
    right_relative, peak_r = align_to_peak(
        frequency_hz, right_db, recording.band_hz, relative_hz
    )
    combined_db = combine_db(left_relative, right_relative)
    width_3 = contiguous_width(relative_hz, combined_db, -3.0)
    width_10 = contiguous_width(relative_hz, combined_db, -10.0)

    cache = Path(tempfile.gettempdir()) / "fai-explorer-matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axis = plt.subplots(figsize=(12, 7.5), constrained_layout=True)
    axis.axvspan(
        -FT8_OCCUPIED_BANDWIDTH_HZ / 2.0,
        FT8_OCCUPIED_BANDWIDTH_HZ / 2.0,
        color="#f59e0b",
        alpha=0.10,
        label="FT8 occupied bandwidth (50 Hz)",
    )
    for offset in (-FT8_TONE_SPACING_HZ, 0.0, FT8_TONE_SPACING_HZ):
        axis.axvline(offset, color="#d97706", linewidth=1.0, linestyle=":")
    axis.axhline(-3.0, color="#64748b", linewidth=1.0, linestyle="--")
    axis.axhline(-10.0, color="#94a3b8", linewidth=1.0, linestyle="--")
    axis.plot(
        relative_hz,
        left_relative,
        color="#2563eb",
        linewidth=1.0,
        alpha=0.55,
        label=f"Left channel (peak {peak_l:.1f} Hz)",
    )
    axis.plot(
        relative_hz,
        right_relative,
        color="#7c3aed",
        linewidth=1.0,
        alpha=0.55,
        label=f"Right channel (peak {peak_r:.1f} Hz)",
    )
    axis.plot(
        relative_hz,
        combined_db,
        color="#111827",
        linewidth=2.1,
        label="Mean normalized distribution",
    )
    axis.set_xlim(-300.0, 300.0)
    axis.set_ylim(-50.0, 3.0)
    axis.set_xlabel("Frequency offset from CW peak (Hz)")
    axis.set_ylabel("Normalized spectral power (dB)")
    axis.grid(True, color="#cbd5e1", linewidth=0.6, alpha=0.7)
    axis.set_title(f"FAI CW tone spreading — {recording.label}", weight="bold")
    interval = (
        f"first {recording.analysis_end_s:.1f} s (CW only)"
        if recording.analysis_end_s is not None
        else "complete recording"
    )
    axis.text(
        0.01,
        0.98,
        (
            f"Analysis: {interval}\n"
            f"Core width: {width_3:.1f} Hz at -3 dB\n"
            f"Width at -10 dB: {width_10:.1f} Hz\n"
            f"Measurement confidence: {recording.confidence}\n"
            "Orange dotted lines: adjacent FT8 tone centres (6.25 Hz spacing)"
        ),
        transform=axis.transAxes,
        va="top",
        ha="left",
        fontsize=9.5,
        bbox={"facecolor": "white", "edgecolor": "#cbd5e1", "alpha": 0.92},
    )
    axis.legend(loc="upper right", fontsize=9)
    figure.savefig(
        output_path,
        dpi=160,
        facecolor="white",
        metadata={"Software": "FAI Geometry Explorer"},
    )
    plt.close(figure)
    return {
        "peak_l": peak_l,
        "peak_r": peak_r,
        "width_3": width_3,
        "width_10": width_10,
    }


def decode_stereo(path: Path) -> np.ndarray:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "2",
        "-ar",
        str(SAMPLE_RATE_HZ),
        "pipe:1",
    ]
    completed = subprocess.run(command, check=True, stdout=subprocess.PIPE)
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    if samples.size % 2:
        samples = samples[:-1]
    return samples.reshape(-1, 2)


def welch_power(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    samples = samples.astype(np.float64, copy=False)
    samples = samples - np.mean(samples)
    window = np.hanning(FFT_SIZE)
    step = FFT_SIZE // 2
    accumulated = np.zeros(FFT_SIZE // 2 + 1, dtype=np.float64)
    segment_count = 0
    for start in range(0, len(samples) - FFT_SIZE + 1, step):
        spectrum = np.fft.rfft(samples[start : start + FFT_SIZE] * window)
        accumulated += np.abs(spectrum) ** 2
        segment_count += 1
    if segment_count == 0:
        raise ValueError("recording is too short for spectrum analysis")
    frequency_hz = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE_HZ)
    return frequency_hz, accumulated / segment_count


def smooth_db(frequency_hz: np.ndarray, power: np.ndarray) -> np.ndarray:
    power_db = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
    bin_width = frequency_hz[1] - frequency_hz[0]
    sigma_bins = 2.0 / bin_width
    radius = max(1, math.ceil(4.0 * sigma_bins))
    positions = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (positions / sigma_bins) ** 2)
    kernel /= np.sum(kernel)
    return np.convolve(power_db, kernel, mode="same")


def align_to_peak(
    frequency_hz: np.ndarray,
    power_db: np.ndarray,
    band_hz: tuple[float, float],
    relative_hz: np.ndarray,
) -> tuple[np.ndarray, float]:
    band = (frequency_hz >= band_hz[0]) & (frequency_hz <= band_hz[1])
    band_frequency = frequency_hz[band]
    band_power_db = power_db[band]
    peak_index = int(np.argmax(band_power_db))
    peak_hz = float(band_frequency[peak_index])
    normalized_db = band_power_db - band_power_db[peak_index]
    aligned_db = np.interp(
        relative_hz,
        band_frequency - peak_hz,
        normalized_db,
        left=np.nan,
        right=np.nan,
    )
    return aligned_db, peak_hz


def combine_db(left_db: np.ndarray, right_db: np.ndarray) -> np.ndarray:
    stacked_power = np.vstack((10.0 ** (left_db / 10.0), 10.0 ** (right_db / 10.0)))
    valid_count = np.sum(np.isfinite(stacked_power), axis=0)
    summed = np.nansum(stacked_power, axis=0)
    mean_power = np.divide(
        summed,
        valid_count,
        out=np.full_like(summed, np.nan),
        where=valid_count > 0,
    )
    combined_db = 10.0 * np.log10(mean_power)
    return combined_db - np.nanmax(combined_db)


def contiguous_width(
    relative_hz: np.ndarray, normalized_db: np.ndarray, threshold_db: float
) -> float:
    peak_index = int(np.nanargmax(normalized_db))
    above = np.isfinite(normalized_db) & (normalized_db >= threshold_db)
    lower = peak_index
    upper = peak_index
    while lower > 0 and above[lower - 1]:
        lower -= 1
    while upper + 1 < len(above) and above[upper + 1]:
        upper += 1
    return float(relative_hz[upper] - relative_hz[lower])


if __name__ == "__main__":
    raise SystemExit(main())
