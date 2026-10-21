
import paho.mqtt.client as mqtt

# Raspberry Pi MQTT broker address
mqtt_server = ""

# Called when Python connects to Mosquitto
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Connected to MQTT broker!")

        # Listen to both fridges
        client.subscribe("Frig1/#")
        client.subscribe("Frig2/#")
    else:
        print("MQTT connection failed:", reason_code)

# Called whenever a reading arrives
def on_message(client, userdata, msg):
    value = msg.payload.decode()
    print(f"{msg.topic}: {value}")

# Create the MQTT client
client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
)

client.on_connect = on_connect
client.on_message = on_message

# Connect to Mosquitto
client.connect(mqtt_server, 1883, 60)

# Keep receiving readings
client.loop_forever()
