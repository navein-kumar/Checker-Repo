import ipaddress
import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

client = MongoClient(os.getenv('MONGO_DB'))
db = client["checker"]
collection = db["ip_addresses"]
domain_collection = db["domains"]
url_collection = db["urls"]
meta_collection = db["metadata"]
ip_url_collection = db["ip_urls"]
domain_url_collection = db["domain_urls"]
url_url_collection = db["url_urls"]
settings_collection = db["settings"]

def get_url_dict():
    url_dict = {}
    for entry in ip_url_collection.find():
        if entry["source"] != "trigger":
            url_dict[entry["source"]] = entry["url"]
    return url_dict

def get_domain_url_dict():
    url_dict = {}
    for entry in domain_url_collection.find():
        url_dict[entry["source"]] = entry["url"]
    return url_dict

def get_url_url_dict():
    url_dict = {}
    for entry in url_url_collection.find():
        url_dict[entry["source"]] = entry["url"]
    return url_dict

def read_local_file(file_path):
    try:
        with open(file_path, 'r') as file:
            return file.read().splitlines()
    except Exception as e:
        logging.error(f"Failed to read local file {file_path}: {e}")
        return []

def extract_ips_from_text(text):
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
    ips = re.findall(ip_pattern, text)
    return ips

def fetch_and_store_ips():
    last_updated = datetime.utcnow()
    new_ips = []
    seen_ips = set()
    url_dict = get_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace(
                    'http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                ip_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                ip_list = response.text.splitlines()

            for line in ip_list:
                ips_in_line = extract_ips_from_text(line)

                for ip in ips_in_line:
                    try:
                        ip_obj = ipaddress.ip_address(ip)
                        if ip_obj.is_global and ip not in seen_ips:
                            new_ips.append({"ip": ip, "source": label})
                            seen_ips.add(ip)
                        elif ip in seen_ips:
                            logging.info(f"Duplicate IP {ip} removed from {url}")
                    except ValueError:
                        logging.warning(f"Invalid IP address {ip} extracted from {url}")
        except requests.RequestException as e:
            logging.error(f"Failed to fetch IPs from {url}: {e}")

    if new_ips:
        collection.delete_many({})
        collection.insert_many(new_ips)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"IP addresses updated at {last_updated}")
        cleanup_duplicates()


def extract_domains_from_text(text):
    domain_pattern = r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b'
    domains = re.findall(domain_pattern, text)
    return domains

def fetch_and_store_domains():
    last_updated = datetime.utcnow()
    new_domains = []
    seen_domains = set()
    url_dict = get_domain_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace(
                    'http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                domain_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                domain_list = response.text.splitlines()

            for line in domain_list:
                domains_in_line = extract_domains_from_text(line)

                for domain in domains_in_line:
                    if domain not in seen_domains:
                        new_domains.append({"domain": domain, "source": label})
                        seen_domains.add(domain)
                    elif domain in seen_domains:
                        logging.info(f"Duplicate domain {domain} removed from {url}")
        except requests.RequestException as e:
            logging.error(f"Failed to fetch domains from {url}: {e}")

    if new_domains:
        domain_collection.delete_many({})
        domain_collection.insert_many(new_domains)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"Domains updated at {last_updated}")
        cleanup_duplicate_domains()

def extract_urls_from_text(text):
    url_pattern = r'\b(?:https?|ftp):\/\/[-A-Z0-9+&@#\/%?=~_|!:,.;]*[-A-Z0-9+&@#\/%=~_|]'
    urls = re.findall(url_pattern, text, re.IGNORECASE)
    return urls

def fetch_and_store_urls():
    last_updated = datetime.utcnow()
    new_urls = []
    seen_urls = set()
    url_dict = get_url_url_dict()

    for label, url in url_dict.items():
        try:
            if 'localhost' in url or '127.0.0.1' in url or '156.67.80.79' in url:
                file_path = url.replace('http://localhost:8000', '').replace('http://127.0.0.1:8000', '').replace(
                    'http://156.67.80.79:8000', '')
                if file_path.startswith('/'):
                    file_path = file_path[1:]
                url_list = read_local_file(file_path)
            else:
                response = requests.get(url)
                response.raise_for_status()
                url_list = response.text.splitlines()

            for line in url_list:
                urls_in_line = extract_urls_from_text(line)

                for url1 in urls_in_line:
                    try:
                        parsed_url = urlparse(url1)
                        # Check if scheme and netloc are present
                        if parsed_url.scheme and parsed_url.netloc and url1 not in seen_urls:
                            new_urls.append({"url": url1, "source": label})
                            seen_urls.add(url1)
                        elif url1 not in seen_urls:
                            logging.info(f"Duplicate url {url1} removed from {url}")
                    except Exception as e:
                        logging.warning(f"Invalid URL {url1} extracted from {url}: {e}")
        except requests.RequestException as e:
            logging.error(f"Failed to fetch URLs from {url}: {e}")

    if new_urls:
        url_collection.delete_many({})
        url_collection.insert_many(new_urls)
        meta_collection.update_one(
            {"_id": "last_updated"},
            {"$set": {"timestamp": last_updated}},
            upsert=True
        )
        logging.info(f"URLs updated at {last_updated}")
        cleanup_duplicate_urls()

def cleanup_duplicates():
    pipeline = [
        {"$group": {
            "_id": "$ip",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for IP {duplicate['_id']}")


def cleanup_duplicate_domains():
    pipeline = [
        {"$group": {
            "_id": "$domain",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(domain_collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        domain_collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for domain {duplicate['_id']}")

def cleanup_duplicate_urls():
    pipeline = [
        {"$group": {
            "_id": "$url",
            "count": {"$sum": 1},
            "docs": {"$push": "$$ROOT"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = list(url_collection.aggregate(pipeline))

    for duplicate in duplicates:
        docs_to_remove = duplicate["docs"][1:]
        ids_to_remove = [doc["_id"] for doc in docs_to_remove]
        url_collection.delete_many({"_id": {"$in": ids_to_remove}})
        logging.info(f"Removed {len(ids_to_remove)} duplicate(s) for URL {duplicate['_id']}")