# Licensing information
"""
Huawei modem manager
Copyright (C) 2021 François Cami

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

# pylint: disable=line-too-long
# pylint: disable=empty-docstring
# pylint: disable=missing-module-docstring

from datetime import datetime, timedelta
import time
import sys

import xml.etree.ElementTree as ET

import huawei_lte.router as lte
import huawei_lte.xmlobjects as xmlobjects
from huawei_lte.errors import RouterError

router_name = "default"
router_ip = ""
router_login = "admin"
router_password = ""

upload_bands = ["B28", ]
download_bands = ["B28", "B3", "B7"]
connection_timeout = 20

log_name = "log/router.log"


def pprint(xml_str, filename, pretty=True):
    """
    Write xml_str to file.
    Make it human-readable by default.
    """
    element = ET.XML(xml_str)
    ET.indent(element)
    with open(filename, mode="w") as file:
        if pretty:
            file.write("%s\n" % ET.tostring(element, encoding='unicode'))
        else:
            file.write("%s\n" % xml_str)


def toggle_data_off_on(router):
    """
    Toggles data off/on.
    Does not wait for a signal to be up.
    """
    logger("%s: switching data off." % router_name)
    router.dataswitch.set_dataswitch_off()
    logger("%s: switching data on." % router_name)
    router.dataswitch.set_dataswitch_on()


def force_4g(router):
    """
    Forces the router in 4G mode.
    """
    logger("%s: setting mode to 4G" % router_name)
    router.net.set_network_mode({'mode': '4G'})


def get_upload_band(router, numerical=False):
    """
    Returns the upload band currently used, or none.
    The text returned by the router is numerical (e.g. 28).
    This methods prepends "B" e.g. "B28" by default.
    """
    signal_root = ET.fromstring(router.device.signal)
    for child in signal_root:
        if child.tag == "band":
            # "band None", "band 28" ...
            if child.text is not None:
                if numerical:
                    return child.text
                return "B%s" % child.text
            return None
    raise RuntimeError("No band entry in device signal.")


def get_download_bands(router, numerical=False):
    """
    """
    raise NotImplementedError


def wait_for_connection(router, timeout=connection_timeout):
    """
    * timeout in seconds, max 120 (>120: RunTimeError)
    * returns True if connected, False otherwise
    """
    if timeout > 120:
        raise RuntimeError("Timeout value %s is too large." % timeout)
    start = datetime.now()
    end = start + timedelta(seconds=timeout)
    while True:
        # timeout
        if datetime.now() > end:
            logger("%s was unable to connect to an antenna." % router_name)
            break
        # connected!
        ul_band = get_upload_band(router)
        if ul_band is not None:
            break
        time.sleep(1)
    return ul_band is not None


def set_upload_bands(router, bands):
    """
    bands: list of bands.
    On the B715, this method can configure both upload and download bands:
    * first use a single band (the desired band for upload) ["B28",]
    * then use a set of bands ["B28", "B3", "B7"]

    Use the lowest frequency in heavy fog or rainy weather.
    """
    router.net.set_lte_band({'bands': bands})


def force_band_setting(router, ul_bands, dl_bands):
    """
    Goal: force the router band setting to ul_bands, dl_bands.
    Limitations:
    * does not handle more than one upload band.
    * as get_download_bands is not implemented yet, this method only forces
      download bands if the upload band is incorrect.
    """
    if len(ul_bands) > 1:
        # B715 only uses a single upload band.
        raise NotImplementedError
    if not wait_for_connection(router):
        logger("Router {0} is not connected yet. Forcing 4G and toggling antennas off/on.".format(router_name))
        force_4g(router)
        toggle_data_off_on(router)
    if not wait_for_connection(router):
        raise RuntimeError("Could not acquire any antenna #1.")

    # FixMe: no way yet to check download band correctness.
    # for band in get_download_bands(router):
    #     if band not in download_bands:
    #         FixMe

    if get_upload_band(router) in ul_bands:
        return True
    set_upload_bands(router, ul_bands)
    set_upload_bands(router, dl_bands)
    if not wait_for_connection(router):
        raise RuntimeError("Could not acquire any antenna #2.")
    return get_upload_band(router) in ul_bands


def logger(msg):
    """
    Logs msg to log_name.
    """
    with open(log_name, mode="a") as file:
        file.write("{0}: {1}\n".format(datetime.now(), msg))


def main():
    """
    Experimental implementation to properly set upload and download bands.
    What works:
    * The B715s (or at least my sample) does not take into account the SnR (sinr) of the band
      to choose the upload band. As a result, in my case it uses the B3/1800MHz which is noisier than the B28/700MHz.
      This tool will detect this situation and force the right setting.
      NB: It sometimes takes multiple API calls to do so. Other tools behave similarly.
    FixMe:
    * get_download_bands() is not implemented so only the upload band is checked for correctness.
    * if the bands are set to an invalid frequency (2100MHz / B1 for instance), the only way out for now is to use the WebUI to switch the LTE band list to Auto.
      See https://github.com/fcami/HuaweiB525Router/blob/mine/README.md on how to implement this.
    TODO:
    * daemon mode
    * client/server communication using JSON
    """

    logger("Router {0}: Starting monitoring.".format(router_name))

    router = lte.B525Router(router_ip)
    router.login(username=router_login, password=router_password)

    # We've just started. Let's see if we have a signal:
    if not wait_for_connection(router, timeout=1):
        logger("Router {0} is not connected yet".format(router_name))

    # did we acquire the right upload band?
    if get_upload_band(router) == upload_bands[0]:
        logger("Router {0} is properly set up, exiting.".format(router_name))
        router.logout()
        sys.exit()

    # pprint(router.device.signal, "log/signal-bad.xml", pretty=False)

    # this tracebacks if the router has not acquired an antenna yet
    # print(router.device.signal_strength)

    # print(router.device.status)
    # print(router.device.signal)
    # pprint(router.features, "log/features.xml")
    # pprint(router.device.info, "log/device_info.xml")

    # This works perfectly but sometimes requires multiple attempts.
    # force_4g(router)
    # set_upload_bands(router, upload_bands)
    # set_upload_bands(router, download_bands)

    # pprint(router.device.signal, "log/signal-lost.xml", pretty=False)
    # import time ; time.sleep(10)
    # pprint(router.device.signal, "log/signal.xml", pretty=False)

    while get_upload_band(router) != upload_bands[0]:
        logger("Router {0} is using {1} as upload band. Forcing {2} instead.".format(router_name, get_upload_band(router), upload_bands[0]))
        try:
            if not force_band_setting(router, upload_bands, download_bands):
                raise Exception("Router {0}: Forcing bands failed.".format(router_name))
        except RuntimeError:
            logger("Router {0}: Attempt to force bands failed: no antenna signal. Consider setting LTE bands to auto in the web interface".format(router_name))
        except Exception as e:
            logger("%s, retrying..." % e)

    logger("Router %s is properly set up." % router_name)
    router.logout()
    logger("Stopping at %s" % datetime.now())


if __name__ == "__main__":
    main()
