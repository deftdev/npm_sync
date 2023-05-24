import requests
import yaml
import sys
import json
import logging
import time

first_run=True

logging.basicConfig(filename='/log/app.log', level=logging.INFO)


try:
    # Read configuration from config.yaml
    with open('/config/config.yaml') as f:
        config = yaml.safe_load(f)
    source_username = config['source']['username']
    source_password = config['source']['password']
    source_address = config['source']['address']
    destinations = config['destinations']
    interval = config['interval']
    if interval <= 1:
        interval = 3600;
except FileNotFoundError:
    # Handle the case when the config file is not found
    print("Error: Configuration file not found. Please make sure /config/config.yaml exists and is readable")
    logging.error("Error: Configuration file not found. Please make sure /config/config.yaml exists and is readable")
    sys.exit()

# Get API key from source server
url = f"{source_address}/api/tokens"
data = {"identity": source_username, "secret": source_password}
response = requests.post(url, json=data, allow_redirects=False)
if response.status_code != 200:
    print(f"Error: failed to log in to {source_address} using provided details - Please check config.yaml")
    logging.error(f"Error: failed to log in to {source_address} using provided details - Please check config.yaml")
    logging.error(response)
    sys.exit(1)
else:
    print(f"Login Successful to source server {source_address}")
    api_key = response.json()['token']
    print(f"retreived Source API key")

sites_added = 0
sites_deleted = 0
sites_updated = 0
sites_errored = 0

# Prepare to copy from source to destination servers
for dest in destinations:
    dest_username = dest['username']
    dest_password = dest['password']
    dest_address = dest['address']
    dest_api_key = None

    url = f"{dest_address}/api/tokens"
    data = {"identity": dest_username, "secret": dest_password}
    response = requests.post(url, json=data, allow_redirects=False)
    if response.status_code != 200:
       print(f"Error: failed to log in to {dest_address} using provided details - Please check config.yaml")
       logging.error(f"Error: failed to log in to {dest_address} using provided details - Please check config.yaml")
       logging.error(response)
       continue
    else:
       print(f"Login Successful to destination server: {dest_address}")
       dest_api_key = response.json()['token']
       print(f"retreived Destination API key")


    # Get list of hosts from source
    url = f"{source_address}/api/nginx/proxy-hosts"
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
       print(f"Error: failed to get proxy hosts from {source_address}")
       logging.error(f"Error: failed to get proxy hosts from {source_address}")
       logging.error(response)
       break
    else:
        source_proxy_hosts = response.json()
        unique_count = len({tuple(host['domain_names']) for host in source_proxy_hosts})

        print(f"Retreived {unique_count} proxy hosts for copy")



    # Delete all proxy hosts on destination server in preperation
    url = f"{dest_address}/api/nginx/proxy-hosts"
    headers = {"Authorization": f"Bearer {dest_api_key}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Error: failed to get proxy hosts from {dest_address}")
        logging.error(f"Error: failed to get proxy hosts from %d", dest_address)
        continue
    else:
        dest_proxy_hosts = response.json()
        for dest_proxy_host in dest_proxy_hosts:
            dest_host_match = False
            for source_proxy_host in source_proxy_hosts:
                if (
                    dest_proxy_host["domain_names"] == source_proxy_host["domain_names"]
                ):
                    dest_host_match = True
                    logging.info(f"{dest_proxy_host['domain_names']} on source, no need to delete from destination")
                    break
            if not dest_host_match:
                url = f"{dest_address}/api/nginx/proxy-hosts/{dest_proxy_host['id']}"
                response = requests.delete(url, headers=headers)
                print(f"{dest_proxy_host['domain_names']} deleted from destination server as no longer on source")
                logging.info(f"{dest_proxy_host['domain_names']} deleted from destination server as no longer on source")
                sites_deleted += 1



        # Add all proxy hosts from source server to destination server
        for proxy_host in source_proxy_hosts:
            dest_host_missing = True
            needs_updating = False

            for dest_proxy_host in dest_proxy_hosts:
                dest_host_missing = True
                needs_updating = False

                if (dest_proxy_host["domain_names"] == proxy_host["domain_names"]):
                    logging.info(f"{proxy_host['domain_names']} on destination, checking to see if details are same")

                    excluded_keys = {"id","meta", "created_on", "modified_on"}

                    for key in proxy_host:
                        if key in excluded_keys:
                            continue  # Skip the comparison for excluded keys
                        if proxy_host[key] != dest_proxy_host[key]:
                            logging.info(f"{key} mismatch")
                            print(f"{key} mismatch")
                            needs_updating = True
                            break

                    if needs_updating:
                        logging.info(f"Details dont match, updating {proxy_host['domain_names']}")
                        url = f"{dest_address}/api/nginx/proxy-hosts/{dest_proxy_host['id']}"
                        response = requests.delete(url, headers=headers)
                        logging.info(f"{dest_proxy_host['domain_names']} deleted from destination server for updating")
                        sites_updated += 1
                        dest_host_missing = True
                        break
                    dest_host_missing = False
                    break
                else:
                    logging.info(f"{dest_proxy_host['domain_names']} is missing from destination")
                    continue


            if dest_host_missing == True:
                logging.info(f"Attempting to add {proxy_host['domain_names']}")
                logging.info(json.dumps(proxy_host))
                url = f"{dest_address}/api/nginx/proxy-hosts"
                headers = {"Content-Type": "application/json","Authorization": f"Bearer {dest_api_key}"}
                domain = ','.join(proxy_host['domain_names']) if proxy_host['domain_names'] else ""
                print(f"adding or updating {domain}")
                payload = {
                "domain_names": proxy_host['domain_names'],
                "forward_host": proxy_host['forward_host'],
                "forward_port":  proxy_host['forward_port'],
                "forward_scheme": proxy_host['forward_scheme'],
                "caching_enabled": proxy_host['caching_enabled'],
                "ssl_forced": proxy_host['ssl_forced'],
                "allow_websocket_upgrade": proxy_host['allow_websocket_upgrade'],
                "block_exploits": proxy_host['block_exploits'],
                "certificate_id": proxy_host['certificate_id'],
                "advanced_config": proxy_host['advanced_config'],
                "access_list_id": proxy_host['access_list_id'],
                "http2_support": proxy_host['http2_support'],
                "enabled": proxy_host['enabled'],
                "locations": proxy_host['locations'],
                "hsts_enabled": proxy_host['hsts_enabled'],
                "hsts_subdomains": proxy_host['hsts_subdomains'],
                }
                response = requests.post(url, headers=headers, data=json.dumps(payload))
                if response.status_code != 201:
                    print(response)
                    print(f"Error: failed to add proxy host {proxy_host['domain_names']} [ {proxy_host['forward_scheme']}://{proxy_host['forward_host']}:{proxy_host['forward_port']} ] to {dest_address}")
                    sites_errored += 1
                else:
                    print(f"Successfully added {domain}")
                    sites_added += 1

print(f"Sites added: {sites_added-sites_updated}")
print(f"Sites deleted: {sites_deleted}")
print(f"Sites updated: {sites_updated}")
print(f"Sites with Errors: {sites_errored}")

first_run = False
print(f"Sleeping for {interval}")
if not first_run:
    time.sleep(interval)
