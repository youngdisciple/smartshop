"""Print live readings: python -m scripts.monitor_mqtt."""
from smartshop.config import load_config


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Connected to MQTT broker!")
        client.subscribe("Frig1/#")
        client.subscribe("Frig2/#")
    else:
        print("MQTT connection failed:", reason_code)


def on_message(client, userdata, message):
    print(f"{message.topic}: {message.payload.decode()}")


def main():
    import paho.mqtt.client as mqtt

    config = load_config()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(config["MQTT_BROKER_HOST"], config["MQTT_BROKER_PORT"], 60)
        client.loop_forever()
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
