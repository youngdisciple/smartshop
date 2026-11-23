"""Administrator-owned Minew sensor discovery and monitoring."""
import json
from functools import wraps
from time import monotonic, sleep
from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, stream_with_context, url_for
from sqlalchemy.exc import IntegrityError
from smartshop.extensions import db
from smartshop.models import BLESensor
from smartshop.presentation.i18n import tr
from smartshop.presentation.ble import sensor_view
from smartshop.security import admin_required
from smartshop.services.ble import normalize_address


ble = Blueprint('ble', __name__, url_prefix='/admin/ble')


def update_readings(sensor, device):
    # Each sensor frame advertises independently; never erase another frame's
    # reading just because it wasn't received in this scan window.
    measurements = dict(sensor.measurements or {})
    for key, reading in device['measurements'].items():
        if (reading.get('received_at') or '') >= (measurements.get(key, {}).get('received_at') or ''):
            measurements[key] = reading
    sensor.measurements = measurements
    if device['last_seen'] >= (sensor.last_seen or ''):
        sensor.last_seen = device['last_seen']
        sensor.rssi = device['rssi']


def live_payload(service):
    # Streams share the radio and serialize DB merges to preserve independent
    # packets when several administrator tabs are open.
    with service.data_lock:
        snapshot = service.live_snapshot()
        sensors = db.session.execute(db.select(BLESensor).order_by(BLESensor.name, BLESensor.address)).scalars().all()
        for sensor in sensors:
            if sensor.address in snapshot['devices']:
                update_readings(sensor, snapshot['devices'][sensor.address])
        db.session.commit()
        views = [sensor_view(sensor) for sensor in sensors]
        for view in views:
            for reading in view['readings']:
                reading['label'] = tr(reading['label'])
        db.session.remove()
    return {'state': snapshot['state'], 'message': tr(snapshot['error']) if snapshot['error'] else '',
            'sensors': views}, snapshot['version']


@ble.get('/events')
@admin_required
def events():
    service = current_app.extensions['smartshop'].ble
    if not db.session.execute(db.select(BLESensor.address).limit(1)).first():
        return '', 204

    @stream_with_context
    def updates():
        subscription = None
        try:
            subscription = service.subscribe()
            # Reconnect periodically so authorization is checked again.
            deadline, previous = monotonic() + 55, None
            yield 'retry: 5000\n\n'
            while monotonic() < deadline:
                snapshot = service.live_snapshot()
                if snapshot['version'] != previous:
                    payload, previous = live_payload(service)
                    yield 'data: ' + json.dumps(payload) + '\n\n'
                    if payload['state'] == 'error' or not payload['sensors']:
                        return
                else:
                    # A heartbeat also detects closed/hidden tabs promptly.
                    yield ': heartbeat\n\n'
                sleep(1)
            yield 'event: renew\ndata: {}\n\n'
        except ValueError as error:
            yield 'data: ' + json.dumps({'state': 'error', 'message': tr(str(error))}) + '\n\n'
        finally:
            db.session.remove()
            if subscription:
                service.unsubscribe(subscription)

    return Response(updates(), mimetype='text/event-stream', headers={'X-Accel-Buffering': 'no'})


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with current_app.extensions['smartshop'].ble.data_lock:
            return function(*args, **kwargs)
    return wrapped


@ble.route('', methods=['GET', 'POST'])
@admin_required
@serialized
def index():
    service = current_app.extensions['smartshop'].ble
    if request.method == 'POST':
        action = request.form.get('action')
        anchor = None
        try:
            if action in ('scan', 'refresh'):
                devices = service.scan()
                for sensor in db.session.execute(db.select(BLESensor)).scalars():
                    if sensor.address in devices:
                        update_readings(sensor, devices[sensor.address])
                db.session.commit()
                flash(tr('BLE scan complete') if devices else tr('No Minew sensors found. Check power and advertising settings.'), 'success' if devices else 'error')
            elif action == 'connect':
                address = normalize_address(request.form.get('address', ''))
                device = service.discovered().get(address)
                if device is None:
                    raise ValueError('Scan again before connecting this sensor')
                sensor = db.session.get(BLESensor, address)
                if sensor is None:
                    sensor = BLESensor(address=address, name=device['name'])
                    db.session.add(sensor)
                update_readings(sensor, device)
                db.session.commit()
                flash(tr('BLE sensor saved'), 'success')
                anchor = 'sensor-' + address.replace(':', '')
            elif action == 'disconnect':
                sensor = db.get_or_404(BLESensor, normalize_address(request.form.get('address', '')))
                db.session.delete(sensor)
                db.session.commit()
                flash(tr('BLE sensor disconnected'), 'success')
            else:
                raise ValueError('Invalid operation')
        except ValueError as error:
            db.session.rollback()
            flash(tr(str(error)), 'error')
        except IntegrityError:
            db.session.rollback()
            flash(tr('Sensor already saved. Refresh this page.'), 'error')
        return redirect(url_for('ble.index', _anchor=anchor))
    sensors = db.session.execute(db.select(BLESensor).order_by(BLESensor.name, BLESensor.address)).scalars().all()
    saved = {sensor.address for sensor in sensors}
    candidates = [device for address, device in service.discovered().items() if address not in saved]
    return render_template('admin/ble.html', sensors=[sensor_view(sensor) for sensor in sensors],
                           candidates=candidates, scan_seconds=service.seconds)
