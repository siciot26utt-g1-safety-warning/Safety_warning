import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
TOPIC = "smart-safety/test"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

client.connect(BROKER, PORT, 60)

client.publish(TOPIC, "Hello from Python!")

print("MQTT message sent successfully!")

client.disconnect()