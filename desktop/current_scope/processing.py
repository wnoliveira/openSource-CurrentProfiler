"""Select an oscilloscope window from acquired samples, independent of the GUI."""

import numpy as np


def scope_frame(
    times,
    values,
    span,
    mode="Auto",
    threshold=0.0,
    edge="Rising",
    pretrigger=0.3,
):
    """Return (relative times, values, window start, triggered), or None.

    The trigger runs on the PC after acquisition. Linear interpolation locates
    the crossing for display alignment only; returned values remain original
    samples. A NaN gap cannot create a crossing.

    Canonical mode/edge names are English. Portuguese aliases are accepted for
    compatibility with earlier scripts and saved UI choices. The GUI handles
    arming and freezing a Single capture; this function selects its Normal
    trigger window.
    """
    mode = {"Livre": "Free", "Único": "Single"}.get(mode, mode)
    edge = {"Subida": "Rising", "Descida": "Falling"}.get(edge, edge)
    sample_times = np.asarray(times, dtype=float)
    sample_values = np.asarray(values, dtype=float)
    if len(sample_times) < 2:
        return None

    if mode == "Free":
        window_start = max(sample_times[0], sample_times[-1] - span)
        window_end = window_start + span
        in_window = (sample_times >= window_start) & (sample_times <= window_end)
        return (
            sample_times[in_window] - window_start,
            sample_values[in_window],
            window_start,
            False,
        )

    before = sample_values[:-1]
    after = sample_values[1:]
    finite_pair = np.isfinite(before) & np.isfinite(after)
    if edge == "Rising":
        crosses_threshold = (before < threshold) & (after >= threshold)
    else:
        crosses_threshold = (before > threshold) & (after <= threshold)
    crossing_indices = np.flatnonzero(crosses_threshold & finite_pair) + 1

    # Prefer the newest crossing for which both the pre-trigger and the
    # post-trigger part of the requested window have already been acquired.
    for index in reversed(crossing_indices):
        fraction = (threshold - sample_values[index - 1]) / (
            sample_values[index] - sample_values[index - 1]
        )
        crossing_time = sample_times[index - 1] + fraction * (
            sample_times[index] - sample_times[index - 1]
        )
        window_start = crossing_time - pretrigger * span
        window_end = window_start + span
        complete_window = (
            window_start >= sample_times[0] and window_end <= sample_times[-1]
        )
        if complete_window:
            in_window = (sample_times >= window_start) & (sample_times <= window_end)
            return (
                sample_times[in_window] - window_start,
                sample_values[in_window],
                window_start,
                True,
            )

    if mode == "Auto":
        # Auto keeps the trace moving when no complete triggered frame exists.
        window_start = max(sample_times[0], sample_times[-1] - span)
        in_window = sample_times >= window_start
        return (
            sample_times[in_window] - window_start,
            sample_values[in_window],
            window_start,
            False,
        )
    return None
