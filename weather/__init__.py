# TODO: grey when it's not received within the list 5-10 minutes
# turn into something we can systemd correctly. (actual poetry project)
#

from PIL import Image, ImageDraw, ImageFont
import sys
import os
import aiohttp
import pkgutil
from asyncio import Lock
import aiomqtt
import pprint
import traceback
import asyncio
import time
from pathlib import Path
import subprocess
import http.client
import json
import paho.mqtt.client as mqtt

from rich.console import Console
import rich.traceback

console = Console()
rich.traceback.install(show_locals=True)

prefix = "zigbee/tele/tasmota_609AD0/"

topic_power_leistung = "stromzaehler/sensor/1/obis/1-0:16.7.0/255/value"

if "weather" in sys.modules:
    resource_path = Path(sys.modules["weather"].__file__).parent
else:
    resource_path = Path(__file__).parent


# The callback for when the client receives a CONNACK response from the server.
def handle_temp_sensor(payload, id, name, new_status):
    if id in payload["ZbReceived"]:  # indoor temp
        if "Humidity" in payload["ZbReceived"][id]:
            new_status[f"humidity_{name}"] = payload["ZbReceived"][id]["Humidity"]
        if "Temperature" in payload["ZbReceived"][id]:
            new_status[f"temp_{name}"] = payload["ZbReceived"][id]["Temperature"]


# The callback for when a PUBLISH message is received from the server.

status_lock = Lock()
status = {
    "temp_indoor": None,
    "humidity_indoor": None,
    "temp_outdoor1": None,
    "humidity_outdoor1": None,
    "temp_outdoor2": None,
    "humidity_outdoor2": None,
    "power_solar": None,
    "garage_offen": None,
    "min_temp": None,
    "max_temp": None,
    "hour": None,
    "minute": None,
}


def format_temp(temp):
    if temp is None:
        return "??°"
    else:
        return "{:.1f}°".format(temp)


def format_humidity(humidity):
    if humidity is None:
        return "??%"
    return "{:.0f}%".format(humidity)


def format_power(power):
    if power is None:
        return "?"
    else:
        return ("+" if power > 0 else "") + "{:.2f}kW".format(power / 1000)


background = Image.open(resource_path / "back.png")


async def draw_status(status):
    # Create a 480x800 pixel image with a white background
    image = Image.new("RGB", (480, 800), "white")

    draw = ImageDraw.Draw(image)

    # load back.png and draw it on the image
    image.paste(background, (0, 0))

    # Set font and size
    font = ImageFont.truetype(
        resource_path / "font" / "fonts/Piscolabis-Regular.ttf", 85
    )

    # Draw indoor temperature and humidity
    start_y = 15
    x1 = 280
    x2 = 480
    spacing = 100

    if status["garage_offen"]:
        y = 600

        draw.rectangle([(0, 0), (480, 800)], fill="red")
        draw.text((480 / 2, y), "Garage", font=font, fill="black", anchor="mt")
        draw.text((480 / 2, y + 80), "offen!", font=font, fill="black", anchor="mt")

    y = start_y
    draw.text(
        (x1, y), format_temp(status["min_temp"]), font=font, fill="black", anchor="rt"
    )
    draw.text((x1 + 30, y + spacing / 4), "-", font=font, fill="black", anchor="rt")
    draw.text(
        (x2, y), format_temp(status["max_temp"]), font=font, fill="black", anchor="rt"
    )

    y = start_y + spacing * 2
    if status.get("uv") is not None:
        y = start_y + spacing * 1
        draw.text(
            (x1, y), f"{status['rain']:.1f}L", font=font, fill="black", anchor="rt"
        )
        draw.text(
            (x2, y),
            f"{status['rain_probability']:.0f}%",
            font=font,
            fill="black",
            anchor="rt",
        )

        y = start_y + spacing * 2
        draw.text((x1, y), f"{status['uv']:.1f}", font=font, fill="black", anchor="rt")

    y = start_y + spacing * 3
    draw.text(
        (x1, y),
        format_temp(status["temp_outdoor1"]),
        font=font,
        fill="black",
        anchor="rt",
    )
    draw.text(
        (x2, y),
        format_humidity(status["humidity_outdoor1"]),
        font=font,
        fill="black",
        anchor="rt",
    )

    y = start_y + spacing * 4
    draw.text(
        (x1, y),
        format_temp(status["temp_outdoor2"]),
        font=font,
        fill="black",
        anchor="rt",
    )
    draw.text(
        (x2, y),
        format_humidity(status["humidity_outdoor2"]),
        font=font,
        fill="black",
        anchor="rt",
    )

    y = start_y + spacing * 5
    draw.text(
        (x1, y),
        format_temp(status["temp_indoor"]),
        font=font,
        fill="black",
        anchor="rt",
    )
    draw.text(
        (x2, y),
        format_humidity(status["humidity_indoor"]),
        font=font,
        fill="black",
        anchor="rt",
    )

    if status["hour"] is not None:
        y = start_y + spacing * 7
        draw.text(
            (160, y),
            f"{status['hour']}:{status['minute']:02}",
            font=font,
            fill="black",
            anchor="lt",
        )

    y = start_y + spacing * 6
    power_solar = status["power_solar"]
    if power_solar is not None:
        if power_solar > 0:
            color = "darkgreen"
        else:
            color = "black"
        draw.text(
            (x2, y), format_power(power_solar), font=font, fill=color, anchor="rt"
        )
    # I need to rotate the image 90 degrees
    image = image.transpose(Image.ROTATE_90)
    image.save("/tmp/weather_data.png")
    subprocess.check_call(["qoiconv", "/tmp/weather_data.png", "/tmp/weather_data.qoi"])
    payload = Path("/tmp/weather_data.qoi")
    try:
        async with aiohttp.ClientSession() as session:
            print("sending")
            async with session.put(
                "http://192.168.178.106/img", data=open(payload, "rb")
            ) as rep:
                await rep.text()
            # conn = http.client.HTTPConnection("192.168.178.106")
            # conn.request("PUT", "/img", payload)
            # response = conn.getresponse()
            # print(response.status, response.reason)
            # print(response.read().decode())
            # conn.close()
    except Exception as e:
        print("error", e)
        console.print_exception(show_locals=True)


async def every_minute():
    global status
    while True:
        async with status_lock:
            new_status = status.copy()
            new_status["hour"] = int(time.strftime("%H"))
            new_status["minute"] = int(time.strftime("%M"))
            if new_status != status:
                status = new_status
                await draw_status(status)
        await asyncio.sleep(60)


async def get_forecast():
    global status
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&daily=temperature_2m_max,temperature_2m_min,uv_index_max,rain_sum,precipitation_probability_max&timezone=Europe%2FBerlin&forecast_days=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as rep:
                response = await rep.json()
                if "daily" in response:
                    async with status_lock:
                        new_status = status.copy()
                        new_status["min_temp"] = response["daily"][
                            "temperature_2m_min"
                        ][0]
                        new_status["max_temp"] = response["daily"][
                            "temperature_2m_max"
                        ][0]
                        new_status["uv"] = response["daily"]["uv_index_max"][0]
                        new_status["rain"] = response["daily"]["rain_sum"][0]
                        new_status["rain_probability"] = response["daily"][
                            "precipitation_probability_max"
                        ][0]
                        if new_status != status:
                            status = new_status
                            await draw_status(status)
    except:
        print("Could not connect weather forcast")
        console.print_exception(show_locals=True)
        return


async def every_hour():
    while True:
        await get_forecast()
        await asyncio.sleep(60 * 60)


async def handle_message(client, msg):
    global status
    async with status_lock:
        print("mqtt", msg.topic, str(msg.payload))
        new_status = status.copy()
        if msg.topic.matches(topic_power_leistung):
            new_status["power_solar"] = -1 * float(msg.payload)

        elif msg.topic.matches(prefix + "SENSOR"):
            payload = json.loads(msg.payload)
            if "ZbReceived" in payload:
                if "0x3B34" in payload["ZbReceived"]:  # garagen sensor
                    if "Contact" in payload["ZbReceived"]["0x3B34"]:
                        open = payload["ZbReceived"]["0x3B34"]["Contact"] != 0
                        new_status["garage_offen"] = open
                handle_temp_sensor(payload, "0xF2E2", "indoor", new_status)
                handle_temp_sensor(payload, "0x7554", "outdoor1", new_status)

        if new_status != status:
            status = new_status
            await draw_status(new_status)


async def mqtt_setup():
    async with aiomqtt.Client(
        os.environ["MQTT_HOST"],
        port=1883,
        keepalive=60,
        password=os.environ["MQTT_PASSWORD"],
        username=os.environ["MQTT_USERNAME"],
    ) as client:
        async with client.messages() as messages:
            await client.subscribe(prefix + "SENSOR")
            await client.subscribe(topic_power_leistung)
            async for message in messages:
                await handle_message(client, message)


async def main():
    task1 = asyncio.create_task(every_minute())
    task1 = asyncio.create_task(every_hour())
    task2 = mqtt_setup()
    await asyncio.gather(task1, task2)  # which never returns..


asyncio.run(main())
