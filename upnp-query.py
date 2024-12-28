#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import socket
import struct
import platform
import subprocess
import requests

def get_default_gateway():
    try:
        if platform.system() == "Linux":
            with open('/proc/net/route') as f:
                for line in f.readlines():
                    fields = line.strip().split()
                    if fields[1] != '00000000' or not int(fields[3], 16) & 2:
                        continue
                    return socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))
        elif platform.system() == "Darwin":  # macOS
            result = subprocess.run(["netstat", "-rn"], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if line.startswith("default"):
                    parts = line.split()
                    if len(parts) > 1:
                        return parts[1]
    except Exception as e:
        print(f"Error fetching default gateway: {e}")
        return None

def send_udp_request(ip, port, message):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(5)
        sock.sendto(message.encode('utf-8'), (ip, port))
        response, _ = sock.recvfrom(65507)
        return response.decode('utf-8')
    except socket.timeout:
        print("No response from the gateway.")
    except Exception as e:
        print(f"Error sending UDP request: {e}")
    finally:
        sock.close()
    return None

def get_upnp_description(gateway_ip, port=1900):
    message = """M-SEARCH * HTTP/1.1\r\nST: upnp:rootdevice\r\nMX: 2\r\nMAN: "ssdp:discover"\r\nHOST: {}:{}\r\n\r\n""".format(gateway_ip, port)
    return send_udp_request(gateway_ip, port, message)

def perform_soap_request(control_url, service_type, action_name, arguments):
    soap_body = f"""<?xml version="1.0"?>
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
        <s:Body>
            <u:{action_name} xmlns:u="{service_type}">
                {arguments}
            </u:{action_name}>
        </s:Body>
    </s:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f'"{service_type}#{action_name}"'
    }

    try:
        response = requests.post(control_url, data=soap_body, headers=headers, timeout=5)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error during SOAP request: {e}")
        return None

def get_upnp_actions():
    gateway_ip = get_default_gateway()
    if not gateway_ip:
        print("Could not determine the default gateway.")
        return

    port = 1900  # Default UPnP port, can vary

    try:
        # Discover the gateway device's UPnP description
        response = get_upnp_description(gateway_ip, port)
        if not response:
            return

        # Extract the location of the device description XML from the response
        for line in response.split("\r\n"):
            if line.lower().startswith("location:"):
                location = line.split(" ", 1)[1].strip()
                break
        else:
            print("No location header found in the response.")
            return

        # Debugging output for the location
        print(f"Device description XML location: {location}")

        # Fetch the device description XML using HTTP
        xml_response = requests.get(location, timeout=5)
        print(f"Request to {location} returned status code: {xml_response.status_code}")
        print(f"Response headers: {xml_response.headers}")
        xml_response.raise_for_status()

        # Parse the XML to find the service list
        root = ET.fromstring(xml_response.content)
        namespaces = {'': 'urn:schemas-upnp-org:device-1-0'}  # Adjust as needed

        # Locate the services in the device description
        services = root.findall(".//serviceList/service", namespaces)

        for service in services:
            service_type = service.find("serviceType", namespaces).text
            control_path = service.find("controlURL", namespaces).text
            scpd_path = service.find("SCPDURL", namespaces).text
            print(f"Service Type: {service_type}")
            print(f"Control URL: {scpd_path}")
            print(f"Control URL: {control_path}")

            # Request the service's SCPD (Service Control Protocol Description) using HTTP
            scpd_url = f"{location.rsplit('/', 1)[0]}{scpd_path}"
            control_url = f"{location.rsplit('/', 1)[0]}{control_path}"
            scpd_response = requests.get(scpd_url, timeout=5)
            scpd_response.raise_for_status()

            # Parse the SCPD XML to find actions
            scpd_root = ET.fromstring(scpd_response.content)
            namespaces_scpd = {'': 'urn:schemas-upnp-org:service-1-0'}  # SCPD namespace
            actions = scpd_root.findall(".//action", namespaces_scpd)

            print("Available Actions:")
            for action in actions:
                action_name = action.find("name", namespaces_scpd).text
                print(f"  - {action_name}")
                arguments = action.findall(".//argument", namespaces_scpd)
                arguments_in = []
                arguments_out = []
                for action_argument in arguments:
                    action_argument_name = action_argument.find("name", namespaces_scpd).text
                    action_argument_direction = action_argument.find("direction", namespaces_scpd).text
                    print(f"    - {action_argument_name} ({action_argument_direction})")
                    if action_argument_direction == 'out':
                        arguments_out.append(action_argument_name)
                    else:
                        arguments_in.append(action_argument_name)

                if action_name.startswith("Get") and (len(arguments_in) == 0):
                    # print(f"!!!Executing action: {action_name}")
                    soap_response = perform_soap_request(control_url, service_type, action_name, "")
                    if soap_response:
                        print(f"SOAP Response for {action_name}: {soap_response}")

    except requests.exceptions.RequestException as e:
        print(f"Error while connecting to gateway: {e}")
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}")

get_upnp_actions()
