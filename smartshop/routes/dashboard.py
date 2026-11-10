from flask import Blueprint, current_app, redirect, render_template, request, url_for
from smartshop.presentation.gauges import get_fridges
from smartshop.security import admin_required

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/")
def home():
    return redirect(url_for("dashboard.index"))


@dashboard.route("/dashboard")
def index():
    runtime = current_app.extensions["smartshop"]
    readings, thresholds = runtime.monitor.snapshot()
    return render_template(
        "dashboard/dashboard.html",
        fridges=get_fridges(readings),
        thresholds=thresholds,
        motor_on=runtime.fan.fan_is_on,
        mqtt_connected=runtime.mqtt.connected,
    )


@dashboard.route("/thresholds/<int:fridge_id>", methods=["POST"])
@admin_required
def save_threshold(fridge_id):
    try:
        threshold = float(request.form.get("threshold", ""))
    except ValueError:
        from flask import abort
        abort(400)
    if fridge_id in (1, 2) and -10 <= threshold <= 50:
        current_app.extensions["smartshop"].monitor.set_threshold(fridge_id, threshold)
    return redirect(url_for("dashboard.index"))
