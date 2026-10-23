
import math
import os
import threading
import time
import fan_controller
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from website.emailHandler import send_alert_email

load_dotenv()

BROKER_HOST = os.getenv("MQTT_BROKER_HOST") #device IP address
BROKER_PORT = 1883
TOPIC = "smartshop/fridge/+/+" #example topic: smartshop/fridge/1/temperature, smartshop/fridge/2/humidity, etc.
ERROR_VALUE = 999

latest_readings = {
    1: {"temperature": ERROR_VALUE, "humidity": ERROR_VALUE},
    2: {"temperature": ERROR_VALUE, "humidity": ERROR_VALUE},
}

thresholds = {1: 5.0, 2: 4.0}
alert_sent = {1: False, 2: False}
COOLDOWN_SECONDS = 5
below_threshold_since = None
cooldown_thread_started = False

def set_threshold(fridge_id, value):
    thresholds[fridge_id] = float(value)
    alert_sent[fridge_id] = False


def notify(fridge_id, temperature, threshold):
    if not send_alert_email(fridge_id, temperature, threshold):
        alert_sent[fridge_id] = False


def check_alert(fridge_id):
    temperature = latest_readings[fridge_id]["temperature"]
    threshold = thresholds[fridge_id]

    if threshold is None or temperature == ERROR_VALUE:
        return

    if temperature > threshold and not alert_sent[fridge_id]:
        alert_sent[fridge_id] = True
        threading.Thread(
            target=notify, args=(fridge_id, temperature, threshold)
        ).start()
    elif temperature <= threshold:
        alert_sent[fridge_id] = False


def check_fan_cooldown():
    global below_threshold_since

    while True:
        if not fan_controller.fan_is_on:
            below_threshold_since = None

        elif any(
            latest_readings[i]["temperature"] == ERROR_VALUE
            or thresholds[i] is None
            for i in (1, 2)
        ):
            below_threshold_since = None

        elif all(
            latest_readings[i]["temperature"] <= thresholds[i]
            for i in (1, 2)
        ):
            if below_threshold_since is None:
                below_threshold_since = time.monotonic()

            elif time.monotonic() - below_threshold_since >= COOLDOWN_SECONDS:
                fan_controller.fan_off()
                below_threshold_since = None
                print("Fan OFF: both fridges stayed below their thresholds for 5 seconds.")

        else:
            below_threshold_since = None

        time.sleep(0.2)

def on_message(client, userdata, msg):
    try:
        fridge, kind = msg.topic.split("/")
        fridge_id = int(fridge.replace("Frig", ""))

        if fridge_id not in latest_readings:
            return

        if kind not in ("temperature", "humidity"):
            return

        latest_readings[fridge_id][kind] = float(msg.payload)

        if kind == "temperature":
            check_alert(fridge_id)
    except (ValueError, KeyError):
        pass


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe("Frig1/#")
    client.subscribe("Frig2/#")


def start():
    global cooldown_thread_started

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(BROKER_HOST, BROKER_PORT)
    client.loop_start()

    if not cooldown_thread_started:
        threading.Thread(
            target=check_fan_cooldown,
            daemon=True
        ).start()
        cooldown_thread_started = True


def gauge(value, lo, hi, unit):
    error = value == ERROR_VALUE
    ratio = 0 if error else max(0, min(1, (value - lo) / (hi - lo)))
    return {
        "error": error,
        "dash": ratio * math.pi * 90,
        "angle": -90 + ratio * 180,
        "label": str(ERROR_VALUE) if error else f"{value:.1f} {unit}",
    }


def get_fridges():
    return {
        fridge_id: {
            "temperature": gauge(r["temperature"], -10, 50, "°C"),
            "humidity": gauge(r["humidity"], 0, 100, "%"),
        }
        for fridge_id, r in latest_readings.items()
    }
