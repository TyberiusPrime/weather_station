from PIL import Image, ImageDraw, ImageFont
import aiohttp
import os
from pathlib import Path
import subprocess
from rich.console import Console
import rich.traceback

console = Console()
rich.traceback.install(show_locals=True)


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
    if power is None or power == -1:
        return "?"
    else:
        return ("+" if power > 0 else "") + "{:.2f}kW".format(power / 1000)


images = {}
resource_path = None


def get_img(name):
    if name not in images:
        images[name] = Image.open(resource_path / f"{name}.png")
    return images[name]


async def draw_status(status, resource_path_):
    global resource_path
    resource_path = resource_path_
    # Create a 480x800 pixel image with a white background
    image = Image.new("RGB", (480, 800), "white")

    draw = ImageDraw.Draw(image)

    # load back.png and draw it on the image
    image.paste(get_img("back"), (0, 0))

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

    # time
    print("draw")
    if status["hour"] is not None:
        y = start_y
        draw.text(
            (160, y),
            f"{status['hour']}:{status['minute']:02}",
            font=font,
            fill="black",
            anchor="lt",
        )
        print("clock")
        image.paste(get_img("clock"), (10, y - 15))

    # outside temp
    y = start_y + spacing * 1
    image.paste(get_img("terasse"), (10, y - 15))
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
    # prediction
    y = start_y + spacing * 2
    image.paste(get_img("prediction"), (10, y - 15))
    draw.text(
        (x1, y),
        format_temp(status["min_temp"]),
        font=font,
        fill="black",
        anchor="rt",
    )
    draw.text((x1 + 30, y + spacing / 4), "-", font=font, fill="black", anchor="rt")
    draw.text(
        (x2, y),
        format_temp(status["max_temp"]),
        font=font,
        fill="black",
        anchor="rt",
    )
    # hinten...
    y = start_y + spacing * 3
    image.paste(get_img("hinten"), (10, y - 15))
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

    y = start_y + spacing * 4
    image.paste(get_img("haus"), (10, y - 15))
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
    uv = status.get("uv", 0)
    uvx = 400
    uvy = 0
    if uv >= 11:
        image.paste(get_img("uv_violet"), (uvx, uvy))
    elif uv > 8:
        image.paste(get_img("uv_red"), (uvx, uvy))
    elif uv > 6:
        image.paste(get_img("uv_orange"), (uvx, uvy))
    elif uv > 3:
        image.paste(get_img("uv_yellow"), (uvx, uvy))
    else:
        image.paste(get_img("uv_green"), (uvx, uvy))

        # draw.text(
        #     (x2, y), f"{status['uv']:.1f}", font=font, fill="black", anchor="rt"
        # )

    if status.get('rain',0) > 0:
        y = start_y + spacing * 5
        image.paste(get_img("rain"), (10, y - 15))
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



    y = start_y + spacing * 6
    power_solar = status.get("power_solar",-1)
    if power_solar is not None:
        if power_solar > 0:
            color = "darkgreen"
        else:
            color = "black"
        draw.text(
            (x2, y), format_power(power_solar), font=font, fill=color, anchor="rt"
        )
    if (
        status["dhw_energy_consumption"] > 0
        or status["heat_energy_consumption"] > 0
    ):
        image.paste(get_img('heat'), (0, y - 15))
    else:

        image.paste(get_img('power'), (0, y - 15))

    # I need to rotate the image 90 degrees
    image.save("/tmp/weather_data_org.png")
    image = image.transpose(Image.ROTATE_90)
    image.save("/tmp/weather_data.png")
    subprocess.check_call(["qoiconv", "/tmp/weather_data.png", "/tmp/weather_data.qoi"])
    payload = Path("/tmp/weather_data.qoi")
    try:
        async with aiohttp.ClientSession() as session:
            if not "DO_NOT_SEND" in os.environ:
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
