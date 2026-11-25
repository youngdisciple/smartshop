"""Administrator-owned Minew sensor discovery and monitoring."""
import json
from functools import wraps
from types import SimpleNamespace
from time import monotonic, sleep
from flask import Blueprint, Response, current_app, flash, g, redirect, render_template, request, stream_with_context, url_for
from smartshop.extensions import db
from smartshop.presentation.i18n import tr
from smartshop.presentation.ble import sensor_view
from smartshop.security import admin_required
from smartshop.services.ble import normalize_address


ble = Blueprint('ble', __name__, url_prefix='/admin/ble')


def device_view(sensor, devices):
    device = devices.get(sensor['address'], {})
    # Build a transient display object; never attach readings to an ORM row.
    view = sensor_view(SimpleNamespace(
        address=sensor['address'], name=sensor['name'],
        measurements=device.get('measurements', {}), last_seen=device.get('last_seen'),
        rssi=device.get('rssi'),
    ))
    view.update(motion_enabled=sensor.get('motion_enabled', False),
                alert_recipient=sensor.get('alert_recipient'), alert_status=sensor.get('alert_status', 'off'),
                last_alert_at=sensor.get('last_alert_at'))
    view['alert_status_label'] = tr({
        'off': 'Email alerts off', 'armed': 'Waiting for motion', 'sending': 'Sending email…',
        'sent': 'Email sent', 'failed': 'Email could not be sent',
    }[view['alert_status']])
    view['motion_action_label'] = tr('Disable motion monitoring' if view['motion_enabled'] else 'Enable motion monitoring')
    if not view['motion_enabled']:
        view['readings'][3].update(value=None, display=tr('Monitoring off'), receipt={
            'iso': '', 'absolute': '', 'relative': tr('Monitoring off'), 'state': 'missing',
        })
    view['missing'] = any(reading['value'] is None for reading in view['readings']
                          if reading['key'] != 'motion' or view['motion_enabled'])
    return view


def live_payload(service):
    # Connections and telemetry both come exclusively from runtime memory.
    with service.data_lock:
        snapshot = service.live_snapshot()
        sensors = sorted(service.connected().values(), key=lambda sensor: (sensor['name'], sensor['address']))
        views = [device_view(sensor, snapshot['devices']) for sensor in sensors]
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
    if not service.connected():
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
                flash(tr('BLE scan complete') if devices else tr('No Minew sensors found. Check power and advertising settings.'), 'success' if devices else 'error')
            elif action == 'connect':
                address = normalize_address(request.form.get('address', ''))
                service.connect(address)
                flash(tr('BLE sensor connected'), 'success')
                anchor = 'sensor-' + address.replace(':', '')
            elif action == 'disconnect':
                service.disconnect(request.form.get('address', ''))
                flash(tr('BLE sensor disconnected'), 'success')
            elif action == 'motion':
                mode = request.form.get('enabled')
                if mode not in ('on', 'off'):
                    raise ValueError('Invalid operation')
                address = normalize_address(request.form.get('address', ''))
                service.set_motion_monitoring(address, mode == 'on', g.customer.email)
                flash(tr('Motion monitoring enabled' if mode == 'on' else 'Motion monitoring disabled'), 'success')
                anchor = 'sensor-' + address.replace(':', '')
            else:
                raise ValueError('Invalid operation')
        except ValueError as error:
            flash(tr(str(error)), 'error')
        return redirect(url_for('ble.index', _anchor=anchor))
    sensors = sorted(service.connected().values(), key=lambda sensor: (sensor['name'], sensor['address']))
    saved = {sensor['address'] for sensor in sensors}
    candidates = [device for address, device in service.discovered().items() if address not in saved]
    devices = service.live_snapshot()['devices']
    return render_template('admin/ble.html', sensors=[device_view(sensor, devices) for sensor in sensors],
                           candidates=candidates, scan_seconds=service.seconds,
                           motion_email_ready=service.email_configured, alert_cooldown=service.alert_cooldown)
