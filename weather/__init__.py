# TODO: grey when it's not received within the list 5-10 minutes
# turn into something we can systemd correctly. (actual poetry project)
#

import sys
import os
import pkgutil
import importlib
from asyncio import Lock
import aiomqtt
import aiohttp
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
import draw


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
    "dhw_energy_consumption": 0,
    "heat_energy_consumption": 0,
}


async def every_second():
    if 'DO_NOT_SEND' in os.environ:
        f = Path(__file__).parent / "draw.py"
        h = f.read_text()
        while True:
            n = f.read_text()
            if n != h:
                h = n
                print("reload")
                try:
                    importlib.reload(draw)
                except:
                    print("syntax error")
                await draw.draw_status(status, resource_path)
            await asyncio.sleep(1)



async def every_minute():
    global status
    while True:
        async with status_lock:
            new_status = status.copy()
            new_status["hour"] = int(time.strftime("%H"))
            new_status["minute"] = int(time.strftime("%M"))
            if new_status != status:
                status = new_status
                await draw.draw_status(status, resource_path)
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
                            await draw.draw_status(status, resource_path)
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
        elif msg.topic.matches("panasonic_heat_pump/main/Heat_Energy_Consumption"):
            new_status["heat_energy_consumption"] = float(msg.payload)
        elif msg.topic.matches("panasonic_heat_pump/main/DHW_Energy_Consumption"):
            new_status["dhw_energy_consumption"] = float(msg.payload)

        if new_status != status:
            status = new_status
            await draw.draw_status(new_status, resource_path)


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
            await client.subscribe("panasonic_heat_pump/main/DHW_Energy_Consumption")
            await client.subscribe("panasonic_heat_pump/main/Heat_Energy_Consumption")
            async for message in messages:
                await handle_message(client, message)


async def main():
    task1 = asyncio.create_task(every_second())
    task1 = asyncio.create_task(every_minute())
    task1 = asyncio.create_task(every_hour())
    task2 = mqtt_setup()
    await asyncio.gather(task1, task2)  # which never returns..


asyncio.run(main())
