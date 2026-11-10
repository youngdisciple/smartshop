import math
from smartshop.services.fridge_monitor import ERROR_VALUE


def gauge(value, lo, hi, unit):
    error = value == ERROR_VALUE
    ratio = 0 if error else max(0, min(1, (value - lo) / (hi - lo)))
    return {
        "error": error,
        "dash": ratio * math.pi * 90,
        "angle": -90 + ratio * 180,
        "label": str(ERROR_VALUE) if error else f"{value:.1f} {unit}",
    }


def get_fridges(readings):
    return {
        fridge_id: {
            "temperature": gauge(reading["temperature"], -10, 50, "°C"),
            "humidity": gauge(reading["humidity"], 0, 100, "%"),
        }
        for fridge_id, reading in readings.items()
    }
