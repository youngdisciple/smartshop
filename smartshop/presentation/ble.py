"""Readable, explicitly historical BLE measurements for the admin overview."""
from datetime import datetime, timezone
from flask import current_app, has_app_context
from smartshop.presentation.i18n import tr
from smartshop.presentation.gauges import gauge


def receipt(timestamp, now):
    try:
        received = datetime.fromisoformat(timestamp)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {'iso': '', 'absolute': '', 'relative': tr('No reading yet'), 'state': 'missing'}
    seconds = max(0, int((now - received).total_seconds()))
    if seconds < 10:
        relative = tr('Just now')
    else:
        for divisor, limit, message, singular in (
            (1, 60, '{count} seconds ago', '1 second ago'), (60, 3600, '{count} minutes ago', '1 minute ago'),
            (3600, 86400, '{count} hours ago', '1 hour ago'), (86400, float('inf'), '{count} days ago', '1 day ago'),
        ):
            if seconds < limit:
                count = seconds // divisor
                relative = tr(singular) if count == 1 else tr(message).format(count=count)
                break
    return {'iso': received.isoformat(), 'absolute': received.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'relative': relative, 'state': 'recent' if seconds <= 120 else 'older'}


def sensor_view(sensor, now=None):
    now = now or datetime.now(timezone.utc)
    measurements = sensor.measurements or {}

    def reading(key, label, unit=''):
        stored = measurements.get(key) or {}
        value = stored.get('value')
        display = '—' if value is None else (f'{value:g}' if type(value) in (float, int) else value)
        if key == 'humidity' and value is not None:
            display = f'{value:.2f}'
        if key == 'motion' and value is not None:
            display = tr('Motion detected') if value else tr('No motion detected')
        result = {'key': key, 'label': label, 'unit': unit, 'value': value, 'display': display,
                  'receipt': receipt(stored.get('received_at'), now)}
        if key in ('temperature', 'humidity'):
            lo, hi = (-10, 50) if key == 'temperature' else (0, 100)
            result['gauge'] = gauge(value, lo, hi, unit, precision=2) if value is not None else {
                'error': True, 'dash': 0, 'angle': -90, 'label': tr('No reading yet'),
            }
        if key in ('light', 'illuminance'):
            setting = 'BLE_LIGHT_BRIGHT_PS' if key == 'light' else 'BLE_LIGHT_BRIGHT_LUX'
            threshold = max(1, float(current_app.config.get(setting, 300))) if has_app_context() else 300
            maximum = threshold * 2
            state = 'unknown' if value is None else 'bright' if value >= threshold else 'dim'
            result['light_meter'] = {
                'state': state, 'label': tr('No reading yet') if value is None else tr('Bright' if state == 'bright' else 'Dim'),
                'percent': 0 if value is None else max(0, min(100, value / maximum * 100)),
                'maximum': maximum, 'maximum_label': f'{maximum:g} {unit or "PS"}',
                'bounded_value': 0 if value is None else max(0, min(maximum, value)),
                'threshold_label': tr('Bright from {value} {unit}').format(value=f'{threshold:g}', unit=unit or 'PS'),
            }
        return result

    has_lux = (measurements.get('illuminance') or {}).get('value') is not None
    light = reading('illuminance', 'Light intensity', 'lux') if has_lux else reading('light', 'Light level', 'PS')
    readings = [reading('temperature', 'Temperature', '°C'), reading('humidity', 'Humidity', '%'),
                light, reading('motion', 'Motion')]
    return {'address': sensor.address, 'anchor': 'sensor-' + sensor.address.replace(':', ''),
            'name': sensor.name, 'rssi': sensor.rssi, 'receipt': receipt(sensor.last_seen, now),
            'readings': readings, 'battery': reading('battery', 'Battery', '%'),
            'secondary_light': reading('light', 'Light level (PS)') if has_lux and measurements.get('light') else None,
            'missing': any(item['value'] is None for item in readings)}
