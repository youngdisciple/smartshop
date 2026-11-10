from flask import Blueprint, current_app, redirect, render_template, request, url_for
from smartshop.presentation.gauges import get_fridges

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
def save_threshold(fridge_id):
    threshold = float(request.form["threshold"])
    if -10 <= threshold <= 50:
        current_app.extensions["smartshop"].monitor.set_threshold(fridge_id, threshold)
    return redirect(url_for("dashboard.index"))
